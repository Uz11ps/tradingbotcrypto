from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
BINANCE_TICKER_24H_URL = "https://api.binance.com/api/v3/ticker/24hr"
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


def _to_binance_symbol(symbol: str) -> str:
    return symbol.replace("/", "").replace("-", "").upper()


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
    closes: list[float]
    generated_at: datetime


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

    pair = _to_binance_symbol(symbol)
    response = await _request_with_retry(
        BINANCE_KLINES_URL,
        {"symbol": pair, "interval": interval, "limit": max(30, min(limit, 500))},
        label=f"klines {symbol} {timeframe}",
    )

    payload: list[list[Any]] = response.json()
    closes = [float(row[4]) for row in payload if len(row) > 5]
    volumes = [float(row[5]) for row in payload if len(row) > 5]
    if len(closes) < 30 or len(volumes) < 30:
        raise BinanceCandlesError(f"Not enough closes for {symbol} {timeframe}")
    return closes, volumes


async def fetch_closes(*, symbol: str, timeframe: str, limit: int = 100) -> list[float]:
    closes, _ = await fetch_closes_and_volumes(symbol=symbol, timeframe=timeframe, limit=limit)
    return closes


async def fetch_quote_volume_24h(*, symbol: str) -> float:
    pair = _to_binance_symbol(symbol)
    response = await _request_with_retry(
        BINANCE_TICKER_24H_URL,
        {"symbol": pair},
        label=f"24h ticker {symbol}",
    )
    payload: dict[str, Any] = response.json()
    return float(payload.get("quoteVolume", 0.0) or 0.0)


async def fetch_quote_volume_24h_map(*, symbols: list[str]) -> dict[str, float]:
    if not symbols:
        return {}
    normalized = {_to_binance_symbol(symbol): symbol for symbol in symbols}
    response = await _request_with_retry(
        BINANCE_TICKER_24H_URL,
        {},
        timeout=15.0,
        label="24h ticker map",
    )
    payload: list[dict[str, Any]] = response.json()
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
    elif timeframe == "15m":
        price_change_5m = 0.0
        price_change_15m = _window_change(closes, 1)
    else:
        price_change_5m = 0.0
        price_change_15m = _window_change(closes, 1)
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
        closes=closes,
        generated_at=datetime.now(tz=UTC),
    )

