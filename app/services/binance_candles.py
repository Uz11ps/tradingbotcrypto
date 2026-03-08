from __future__ import annotations

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
    quote_volume_24h: float
    generated_at: datetime


def _pct_change(prev_value: float, current_value: float) -> float:
    if prev_value == 0:
        return 0.0
    return ((current_value - prev_value) / prev_value) * 100


async def fetch_closes(*, symbol: str, timeframe: str, limit: int = 100) -> list[float]:
    interval = TIMEFRAME_MAP.get(timeframe)
    if not interval:
        raise BinanceCandlesError(f"Unsupported timeframe '{timeframe}'")

    pair = _to_binance_symbol(symbol)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                BINANCE_KLINES_URL,
                params={"symbol": pair, "interval": interval, "limit": max(30, min(limit, 500))},
            )
            response.raise_for_status()
    except Exception as e:
        raise BinanceCandlesError(f"Failed to fetch klines for {symbol} {timeframe}: {e}") from e

    payload: list[list[Any]] = response.json()
    closes = [float(row[4]) for row in payload if len(row) > 4]
    if len(closes) < 30:
        raise BinanceCandlesError(f"Not enough closes for {symbol} {timeframe}")
    return closes


async def fetch_quote_volume_24h(*, symbol: str) -> float:
    pair = _to_binance_symbol(symbol)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(BINANCE_TICKER_24H_URL, params={"symbol": pair})
            response.raise_for_status()
    except Exception as e:
        raise BinanceCandlesError(f"Failed to fetch 24h ticker for {symbol}: {e}") from e
    payload: dict[str, Any] = response.json()
    return float(payload.get("quoteVolume", 0.0) or 0.0)


async def build_snapshot(*, symbol: str, timeframe: str) -> CandleSnapshot:
    closes = await fetch_closes(symbol=symbol, timeframe=timeframe, limit=100)
    quote_volume_24h = await fetch_quote_volume_24h(symbol=symbol)
    prev_close = closes[-2]
    current_close = closes[-1]
    return CandleSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        prev_close=prev_close,
        current_close=current_close,
        pct_change=_pct_change(prev_close, current_close),
        quote_volume_24h=quote_volume_24h,
        generated_at=datetime.now(tz=UTC),
    )

