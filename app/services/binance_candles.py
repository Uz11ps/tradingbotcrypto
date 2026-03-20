from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import settings

BINGX_KLINES_URL = "https://open-api.bingx.com/openApi/spot/v1/market/kline"
BINGX_TICKER_24H_URL = "https://open-api.bingx.com/openApi/spot/v1/ticker/24hr"
TIMEFRAME_MAP: dict[str, str] = {
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
}
TIMEFRAME_TO_MS: dict[str, int] = {
    "5m": 5 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
}

MAX_RETRIES = 2
RETRY_BACKOFF = 1.5

log = logging.getLogger(__name__)
_LIVE_PRICE_CACHE: dict[str, tuple[float, float]] = {}
_LIVE_PRICE_CACHE_LOCK = asyncio.Lock()


class BinanceCandlesError(RuntimeError):
    pass


def _resolve_market_urls(market_type: str) -> tuple[str, str]:
    normalized = (market_type or "spot").strip().lower()
    if normalized == "futures":
        return settings.bingx_futures_klines_url, settings.bingx_futures_ticker_url
    return BINGX_KLINES_URL, BINGX_TICKER_24H_URL


def _to_bingx_symbol(symbol: str) -> str:
    return symbol.replace("/", "-").replace("_", "-").upper()


@dataclass(slots=True)
class CandleSnapshot:
    symbol: str
    timeframe: str
    prev_close: float
    current_close: float
    pct_change: float
    price_change_5m: float
    price_change_15m: float
    current_volume: float
    avg_volume_20: float
    quote_volume_24h: float
    window_open_price: float
    live_window_open_price: float
    closes: list[float]
    signal_candle_open_time_ms: int
    signal_candle_close_time_ms: int
    generated_at: datetime


@dataclass(slots=True)
class KlineBar:
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time_ms: int | None = None
    is_closed: bool | None = None


def _pct_change(prev_value: float, current_value: float) -> float:
    if prev_value == 0:
        return 0.0
    return ((current_value - prev_value) / prev_value) * 100


def _window_change(closes: list[float], bars_back: int) -> float:
    if len(closes) <= bars_back:
        return 0.0
    return _pct_change(closes[-(bars_back + 1)], closes[-1])


def _parse_is_closed(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value in (0, 1):
            return bool(value)
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return None


def _extract_close_and_volume(row: Any) -> tuple[float, float] | None:
    if isinstance(row, (list, tuple)):
        if len(row) <= 5:
            return None
        return float(row[4]), float(row[5])
    if isinstance(row, dict):
        close_raw = row.get("close")
        volume_raw = row.get("volume")
        if close_raw is None or volume_raw is None:
            return None
        return float(close_raw), float(volume_raw)
    return None


def _parse_kline_bar(row: Any) -> KlineBar | None:
    if isinstance(row, (list, tuple)):
        if len(row) <= 5:
            return None
        return KlineBar(
            open_time_ms=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
            close_time_ms=int(row[6]) if len(row) > 6 else None,
            is_closed=_parse_is_closed(row[7]) if len(row) > 7 else None,
        )
    if isinstance(row, dict):
        open_time_raw = row.get("openTime") or row.get("open_time") or row.get("time")
        open_raw = row.get("open")
        high_raw = row.get("high")
        low_raw = row.get("low")
        close_raw = row.get("close")
        volume_raw = row.get("volume")
        if None in (open_time_raw, open_raw, high_raw, low_raw, close_raw, volume_raw):
            return None
        close_time_raw = row.get("closeTime") or row.get("close_time")
        is_closed_raw = row.get("isClosed")
        if is_closed_raw is None:
            is_closed_raw = row.get("closed")
        return KlineBar(
            open_time_ms=int(open_time_raw),
            open=float(open_raw),
            high=float(high_raw),
            low=float(low_raw),
            close=float(close_raw),
            volume=float(volume_raw),
            close_time_ms=int(close_time_raw) if close_time_raw is not None else None,
            is_closed=_parse_is_closed(is_closed_raw),
        )
    return None


def _normalize_bar_order(bars: list[KlineBar], *, symbol: str, timeframe: str) -> list[KlineBar]:
    if len(bars) < 2:
        return bars
    open_times = [bar.open_time_ms for bar in bars]
    is_ascending = all(open_times[i] <= open_times[i + 1] for i in range(len(open_times) - 1))
    is_descending = all(open_times[i] >= open_times[i + 1] for i in range(len(open_times) - 1))
    if not (is_ascending or is_descending):
        log.warning(
            "BingX kline order is non-monotonic for %s %s; sorting by open_time_ms",
            symbol,
            timeframe,
        )
    if not is_ascending:
        bars.sort(key=lambda bar: bar.open_time_ms)
    return bars


async def _request_with_retry(
    url: str,
    params: dict[str, Any],
    *,
    timeout: float = 10.0,
    label: str = "",
) -> httpx.Response:
    last_exc: Exception | None = None
    for attempt in range(1 + MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                return resp
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as e:
            last_exc = e
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF * (attempt + 1)
                log.warning("Retry %d/%d %s: %s (wait %.1fs)", attempt + 1, MAX_RETRIES, label, e, wait)
                await asyncio.sleep(wait)
        except Exception as e:
            raise BinanceCandlesError(f"{label}: {e}") from e
    raise BinanceCandlesError(f"{label}: {last_exc}") from last_exc


async def fetch_closes_and_volumes(
    *,
    symbol: str,
    timeframe: str,
    limit: int = 100,
    market_type: str = "spot",
) -> tuple[list[float], list[float]]:
    interval = TIMEFRAME_MAP.get(timeframe)
    if not interval:
        raise BinanceCandlesError(f"Unsupported timeframe '{timeframe}'")
    klines_url, _ = _resolve_market_urls(market_type)

    pair = _to_bingx_symbol(symbol)
    response = await _request_with_retry(
        klines_url,
        {"symbol": pair, "interval": interval, "limit": max(30, min(limit, 500))},
        label=f"bingx klines {market_type} {symbol} {timeframe}",
    )

    raw_payload: dict[str, Any] = response.json()
    if int(raw_payload.get("code", -1)) != 0:
        raise BinanceCandlesError(f"bingx klines error: {raw_payload}")
    payload: list[Any] = raw_payload.get("data") or []
    closes: list[float] = []
    volumes: list[float] = []
    for row in payload:
        parsed = _extract_close_and_volume(row)
        if parsed is None:
            continue
        close, volume = parsed
        closes.append(close)
        volumes.append(volume)
    if len(closes) < 30 or len(volumes) < 30:
        raise BinanceCandlesError(f"Not enough closes for {symbol} {timeframe}")
    return closes, volumes


async def fetch_recent_bars(
    *,
    symbol: str,
    timeframe: str,
    limit: int = 120,
    market_type: str = "spot",
) -> list[KlineBar]:
    interval = TIMEFRAME_MAP.get(timeframe)
    if not interval:
        raise BinanceCandlesError(f"Unsupported timeframe '{timeframe}'")
    interval_ms = TIMEFRAME_TO_MS.get(timeframe, 0)
    klines_url, _ = _resolve_market_urls(market_type)

    pair = _to_bingx_symbol(symbol)
    response = await _request_with_retry(
        klines_url,
        {"symbol": pair, "interval": interval, "limit": max(30, min(limit, 500))},
        label=f"bingx bars {market_type} {symbol} {timeframe}",
    )
    raw_payload: dict[str, Any] = response.json()
    if int(raw_payload.get("code", -1)) != 0:
        raise BinanceCandlesError(f"bingx bars error: {raw_payload}")
    payload: list[Any] = raw_payload.get("data") or []
    bars: list[KlineBar] = []
    for row in payload:
        bar = _parse_kline_bar(row)
        if bar is not None:
            bars.append(bar)
    if len(bars) < 30:
        raise BinanceCandlesError(f"Not enough bars for {symbol} {timeframe}")
    bars = _normalize_bar_order(bars, symbol=symbol, timeframe=timeframe)

    # Normalize close_time when API does not provide it.
    if interval_ms > 0:
        for bar in bars:
            if bar.close_time_ms is None:
                bar.close_time_ms = bar.open_time_ms + interval_ms
    return bars


async def fetch_closes(
    *,
    symbol: str,
    timeframe: str,
    limit: int = 100,
    market_type: str = "spot",
) -> list[float]:
    closes, _ = await fetch_closes_and_volumes(
        symbol=symbol,
        timeframe=timeframe,
        limit=limit,
        market_type=market_type,
    )
    return closes


async def fetch_quote_volume_24h(*, symbol: str, market_type: str = "spot") -> float:
    pair = _to_bingx_symbol(symbol)
    _, ticker_url = _resolve_market_urls(market_type)
    response = await _request_with_retry(
        ticker_url,
        {"symbol": pair, "timestamp": int(datetime.now(tz=UTC).timestamp() * 1000)},
        label=f"bingx 24h ticker {market_type} {symbol}",
    )
    payload: dict[str, Any] = response.json()
    if int(payload.get("code", -1)) != 0:
        raise BinanceCandlesError(f"bingx 24h ticker error: {payload}")
    rows: list[dict[str, Any]] = payload.get("data") or []
    if not rows:
        return 0.0
    return float(rows[0].get("quoteVolume", 0.0) or 0.0)


async def fetch_quote_volume_24h_map(
    *,
    symbols: list[str],
    market_type: str = "spot",
) -> dict[str, float]:
    if not symbols:
        return {}
    normalized = {_to_bingx_symbol(symbol): symbol for symbol in symbols}
    _, ticker_url = _resolve_market_urls(market_type)
    response = await _request_with_retry(
        ticker_url,
        {"timestamp": int(datetime.now(tz=UTC).timestamp() * 1000)},
        timeout=15.0,
        label=f"bingx 24h ticker map {market_type}",
    )
    raw_payload: dict[str, Any] = response.json()
    if int(raw_payload.get("code", -1)) != 0:
        raise BinanceCandlesError(f"bingx 24h ticker map error: {raw_payload}")
    payload: list[dict[str, Any]] = raw_payload.get("data") or []
    out: dict[str, float] = {}
    for row in payload:
        pair = str(row.get("symbol", ""))
        if pair in normalized:
            out[normalized[pair]] = float(row.get("quoteVolume", 0.0) or 0.0)
    return out


async def fetch_live_price(
    *,
    symbol: str,
    cache_ttl_seconds: float = 1.5,
    market_type: str = "spot",
) -> float:
    pair = _to_bingx_symbol(symbol)
    now_ts = datetime.now(tz=UTC).timestamp()
    ttl = max(0.0, cache_ttl_seconds)
    _, ticker_url = _resolve_market_urls(market_type)
    if ttl > 0:
        cached = _LIVE_PRICE_CACHE.get(pair)
        if cached and (now_ts - cached[0]) <= ttl:
            return cached[1]

    response = await _request_with_retry(
        ticker_url,
        {"symbol": pair, "timestamp": int(now_ts * 1000)},
        label=f"bingx live ticker {market_type} {symbol}",
    )
    payload: dict[str, Any] = response.json()
    if int(payload.get("code", -1)) != 0:
        raise BinanceCandlesError(f"bingx live ticker error: {payload}")
    rows: list[dict[str, Any]] = payload.get("data") or []
    if not rows:
        raise BinanceCandlesError(f"bingx live ticker empty for {symbol}")

    row = rows[0]
    live_price = float(
        row.get("lastPrice")
        or row.get("last")
        or row.get("close")
        or row.get("lastClose")
        or 0.0
    )
    if live_price <= 0:
        raise BinanceCandlesError(f"bingx live ticker has invalid price for {symbol}: {row}")

    if ttl > 0:
        async with _LIVE_PRICE_CACHE_LOCK:
            _LIVE_PRICE_CACHE[pair] = (now_ts, live_price)
    return live_price


async def build_snapshot(
    *,
    symbol: str,
    timeframe: str,
    volume_avg_window: int = 20,
    quote_volume_24h: float | None = None,
    market_type: str = "spot",
) -> CandleSnapshot:
    bars = await fetch_recent_bars(
        symbol=symbol,
        timeframe=timeframe,
        limit=100,
        market_type=market_type,
    )
    bars = _normalize_bar_order(bars, symbol=symbol, timeframe=timeframe)
    interval_ms = TIMEFRAME_TO_MS.get(timeframe, 0)
    now_ms = int(datetime.now(tz=UTC).timestamp() * 1000)
    last_bar = bars[-1]
    # Some exchanges include the currently forming bar, while others can return only closed bars.
    # Prefer explicit is_closed flag if present; otherwise infer by close_time vs current time.
    if last_bar.is_closed is not None:
        is_last_forming = not last_bar.is_closed
    elif last_bar.close_time_ms is not None and interval_ms > 0:
        is_last_forming = now_ms < last_bar.close_time_ms
    elif interval_ms > 0:
        is_last_forming = now_ms < (last_bar.open_time_ms + interval_ms)
    else:
        is_last_forming = False

    # Lock candle calculations to closed bars only.
    closed_bars = bars[:-1] if is_last_forming and len(bars) >= 31 else bars
    closes = [bar.close for bar in closed_bars]
    volumes = [bar.volume for bar in closed_bars]
    if len(closes) < 30 or len(volumes) < 30:
        raise BinanceCandlesError(f"Not enough closed bars for {symbol} {timeframe}")
    if quote_volume_24h is None:
        quote_volume_24h = await fetch_quote_volume_24h(symbol=symbol, market_type=market_type)
    prev_close = closes[-2]
    current_close = closes[-1]
    current_volume = volumes[-1]
    window = max(5, min(volume_avg_window, len(volumes)))
    avg_volume_20 = sum(volumes[-window:]) / window
    if timeframe == "5m":
        price_change_5m = _window_change(closes, 1)
        price_change_15m = _window_change(closes, 3)
        window_open_price = closes[-4] if len(closes) >= 4 else closes[0]
    elif timeframe == "15m":
        price_change_5m = 0.0
        price_change_15m = _window_change(closes, 1)
        window_open_price = closes[-2]
    else:
        price_change_5m = 0.0
        price_change_15m = _window_change(closes, 1)
        window_open_price = closes[-2]
    current_bar = closed_bars[-1]
    if is_last_forming:
        live_window_open_price = bars[-1].open
    else:
        # Fallback: if exchange returns only closed bars, use latest close baseline
        # to avoid overstating intra-window move.
        live_window_open_price = current_close
    return CandleSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        prev_close=prev_close,
        current_close=current_close,
        pct_change=_pct_change(prev_close, current_close),
        price_change_5m=price_change_5m,
        price_change_15m=price_change_15m,
        current_volume=current_volume,
        avg_volume_20=avg_volume_20,
        quote_volume_24h=quote_volume_24h,
        window_open_price=window_open_price,
        live_window_open_price=live_window_open_price,
        closes=closes,
        signal_candle_open_time_ms=current_bar.open_time_ms,
        signal_candle_close_time_ms=current_bar.open_time_ms + interval_ms,
        generated_at=datetime.now(tz=UTC),
    )

