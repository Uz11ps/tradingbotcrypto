from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

BINGX_KLINES_URL = "https://open-api.bingx.com/openApi/spot/v1/market/kline"
BINGX_TICKER_24H_URL = "https://open-api.bingx.com/openApi/spot/v1/ticker/24hr"
TIMEFRAME_MAP: dict[str, str] = {
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
}

MAX_RETRIES = 2
RETRY_BACKOFF = 1.5

log = logging.getLogger(__name__)


class BinanceCandlesError(RuntimeError):
    pass


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
    closes: list[float]
    generated_at: datetime


@dataclass(slots=True)
class KlineBar:
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def _pct_change(prev_value: float, current_value: float) -> float:
    if prev_value == 0:
        return 0.0
    return ((current_value - prev_value) / prev_value) * 100


def _window_change(closes: list[float], bars_back: int) -> float:
    if len(closes) <= bars_back:
        return 0.0
    return _pct_change(closes[-(bars_back + 1)], closes[-1])


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
) -> tuple[list[float], list[float]]:
    interval = TIMEFRAME_MAP.get(timeframe)
    if not interval:
        raise BinanceCandlesError(f"Unsupported timeframe '{timeframe}'")

    pair = _to_bingx_symbol(symbol)
    response = await _request_with_retry(
        BINGX_KLINES_URL,
        {"symbol": pair, "interval": interval, "limit": max(30, min(limit, 500))},
        label=f"bingx klines {symbol} {timeframe}",
    )

    raw_payload: dict[str, Any] = response.json()
    if int(raw_payload.get("code", -1)) != 0:
        raise BinanceCandlesError(f"bingx klines error: {raw_payload}")
    payload: list[list[Any]] = raw_payload.get("data") or []
    closes = [float(row[4]) for row in payload if len(row) > 5]
    volumes = [float(row[5]) for row in payload if len(row) > 5]
    if len(closes) < 30 or len(volumes) < 30:
        raise BinanceCandlesError(f"Not enough closes for {symbol} {timeframe}")
    return closes, volumes


async def fetch_recent_bars(
    *,
    symbol: str,
    timeframe: str,
    limit: int = 120,
) -> list[KlineBar]:
    interval = TIMEFRAME_MAP.get(timeframe)
    if not interval:
        raise BinanceCandlesError(f"Unsupported timeframe '{timeframe}'")

    pair = _to_bingx_symbol(symbol)
    response = await _request_with_retry(
        BINGX_KLINES_URL,
        {"symbol": pair, "interval": interval, "limit": max(30, min(limit, 500))},
        label=f"bingx bars {symbol} {timeframe}",
    )
    raw_payload: dict[str, Any] = response.json()
    if int(raw_payload.get("code", -1)) != 0:
        raise BinanceCandlesError(f"bingx bars error: {raw_payload}")
    payload: list[list[Any]] = raw_payload.get("data") or []
    bars: list[KlineBar] = []
    for row in payload:
        if len(row) <= 5:
            continue
        bars.append(
            KlineBar(
                open_time_ms=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
        )
    if len(bars) < 30:
        raise BinanceCandlesError(f"Not enough bars for {symbol} {timeframe}")
    return bars


async def fetch_closes(*, symbol: str, timeframe: str, limit: int = 100) -> list[float]:
    closes, _ = await fetch_closes_and_volumes(symbol=symbol, timeframe=timeframe, limit=limit)
    return closes


async def fetch_quote_volume_24h(*, symbol: str) -> float:
    pair = _to_bingx_symbol(symbol)
    response = await _request_with_retry(
        BINGX_TICKER_24H_URL,
        {"symbol": pair, "timestamp": int(datetime.now(tz=UTC).timestamp() * 1000)},
        label=f"bingx 24h ticker {symbol}",
    )
    payload: dict[str, Any] = response.json()
    if int(payload.get("code", -1)) != 0:
        raise BinanceCandlesError(f"bingx 24h ticker error: {payload}")
    rows: list[dict[str, Any]] = payload.get("data") or []
    if not rows:
        return 0.0
    return float(rows[0].get("quoteVolume", 0.0) or 0.0)


async def fetch_quote_volume_24h_map(*, symbols: list[str]) -> dict[str, float]:
    if not symbols:
        return {}
    normalized = {_to_bingx_symbol(symbol): symbol for symbol in symbols}
    response = await _request_with_retry(
        BINGX_TICKER_24H_URL,
        {"timestamp": int(datetime.now(tz=UTC).timestamp() * 1000)},
        timeout=15.0,
        label="bingx 24h ticker map",
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


async def build_snapshot(
    *,
    symbol: str,
    timeframe: str,
    volume_avg_window: int = 20,
    quote_volume_24h: float | None = None,
) -> CandleSnapshot:
    closes, volumes = await fetch_closes_and_volumes(symbol=symbol, timeframe=timeframe, limit=100)
    if quote_volume_24h is None:
        quote_volume_24h = await fetch_quote_volume_24h(symbol=symbol)
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
        closes=closes,
        generated_at=datetime.now(tz=UTC),
    )

