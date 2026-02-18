from __future__ import annotations

from datetime import UTC, datetime
from statistics import fmean, pstdev
from typing import Any

import httpx

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
TIMEFRAME_MAP: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}


class MarketDataError(RuntimeError):
    pass


def _to_binance_symbol(symbol: str) -> str:
    return symbol.replace("/", "").replace("-", "").upper()


def _validate_timeframe(timeframe: str) -> str:
    if timeframe not in TIMEFRAME_MAP:
        allowed = ", ".join(sorted(TIMEFRAME_MAP))
        raise MarketDataError(f"Unsupported timeframe '{timeframe}'. Allowed: {allowed}")
    return TIMEFRAME_MAP[timeframe]


def _pct_change(prev_value: float, current_value: float) -> float:
    if prev_value == 0:
        return 0.0
    return ((current_value - prev_value) / prev_value) * 100


def _signal_strength(
    *,
    price_change_pct: float,
    volume_change_pct: float,
    volatility_pct: float,
) -> float:
    raw = abs(price_change_pct) * 0.06 + abs(volume_change_pct) * 0.02 + volatility_pct * 0.03
    return min(1.0, round(raw, 4))


async def fetch_market_snapshot(
    *,
    symbol: str,
    timeframe: str,
    limit: int = 120,
) -> dict[str, Any]:
    interval = _validate_timeframe(timeframe)
    pair = _to_binance_symbol(symbol)

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            BINANCE_KLINES_URL,
            params={"symbol": pair, "interval": interval, "limit": max(30, min(limit, 500))},
        )
        response.raise_for_status()
        klines: list[list[Any]] = response.json()

    if len(klines) < 30:
        raise MarketDataError("Not enough klines for analytics")

    closes = [float(k[4]) for k in klines]
    volumes = [float(k[5]) for k in klines]
    last_close = closes[-1]
    prev_close = closes[-2]
    price_change_pct = _pct_change(prev_close, last_close)
    volume_change_pct = _pct_change(volumes[-2], volumes[-1])

    returns_pct = [_pct_change(closes[i - 1], closes[i]) for i in range(1, len(closes))]
    volatility_pct = pstdev(returns_pct[-30:])
    sma_fast = fmean(closes[-9:])
    sma_slow = fmean(closes[-21:])
    trend = "bullish" if sma_fast > sma_slow else "bearish"
    direction = "up" if price_change_pct >= 0 else "down"
    strength = _signal_strength(
        price_change_pct=price_change_pct,
        volume_change_pct=volume_change_pct,
        volatility_pct=volatility_pct,
    )

    if strength >= 0.7:
        action = "entry"
    elif strength <= 0.25:
        action = "hold"
    else:
        action = "watch"

    if trend == "bearish" and direction == "up" and action == "entry":
        action = "watch"
    if trend == "bullish" and direction == "down" and action == "entry":
        action = "watch"

    summary = (
        f"{symbol} {timeframe}: price={last_close:.4f}, change={price_change_pct:+.2f}%, "
        f"volume_change={volume_change_pct:+.2f}%, vol(30)={volatility_pct:.2f}%, trend={trend}."
    )

    return {
        "generated_at": datetime.now(tz=UTC),
        "symbol": symbol,
        "timeframe": timeframe,
        "price": last_close,
        "price_change_pct": price_change_pct,
        "volume": volumes[-1],
        "volume_change_pct": volume_change_pct,
        "volatility_pct": volatility_pct,
        "sma_fast": sma_fast,
        "sma_slow": sma_slow,
        "trend": trend,
        "direction": direction,
        "strength": strength,
        "action": action,
        "summary": summary,
    }

