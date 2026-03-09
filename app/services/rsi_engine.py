from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

SignalType = Literal["pump", "dump"]


def compute_rsi(closes: list[float], *, period: int = 14) -> float:
    if period < 2:
        raise ValueError("RSI period must be >= 2")
    if len(closes) <= period:
        raise ValueError("Not enough data to compute RSI")

    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(0.0, delta))
        losses.append(abs(min(0.0, delta)))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


@dataclass(slots=True)
class RsiSignalCandidate:
    symbol: str
    timeframe: str
    signal_type: SignalType
    rsi_value: float
    prev_price: float
    current_price: float
    pct_change: float
    price_change_5m: float
    price_change_15m: float
    current_volume: float
    avg_volume_20: float
    quote_volume_24h: float
    exchange: str
    trigger_source: str
    context_tag: str | None
    generated_at: datetime


def evaluate_rsi_signal(
    *,
    symbol: str,
    timeframe: str,
    rsi_value: float,
    price_change_5m: float,
    price_change_15m: float,
    price_change_5m_trigger_pct: float,
    price_change_15m_trigger_pct: float,
    window_open_price: float,
    current_price: float,
    pct_change: float,
    current_volume: float,
    avg_volume_20: float,
    quote_volume_24h: float,
    generated_at: datetime,
) -> RsiSignalCandidate | None:
    trigger_5m = abs(price_change_5m) >= price_change_5m_trigger_pct
    trigger_15m = abs(price_change_15m) >= price_change_15m_trigger_pct
    if not (trigger_5m or trigger_15m):
        return None

    dominant_change = (
        price_change_15m
        if abs(price_change_15m) >= abs(price_change_5m)
        else price_change_5m
    )
    if dominant_change == 0:
        return None
    signal_type: SignalType = "pump" if dominant_change > 0 else "dump"

    return RsiSignalCandidate(
        symbol=symbol,
        timeframe=timeframe,
        signal_type=signal_type,
        rsi_value=round(rsi_value, 2),
        prev_price=window_open_price,
        current_price=current_price,
        pct_change=round(dominant_change, 4),
        price_change_5m=round(price_change_5m, 4),
        price_change_15m=round(price_change_15m, 4),
        current_volume=current_volume,
        avg_volume_20=avg_volume_20,
        quote_volume_24h=quote_volume_24h,
        exchange="Binance",
        trigger_source="price_window",
        context_tag=None,
        generated_at=generated_at,
    )


def validate_candidate_filters(
    candidate: RsiSignalCandidate,
    *,
    lower_rsi: float,
    upper_rsi: float,
) -> tuple[bool, str | None]:
    if candidate.signal_type == "pump" and candidate.rsi_value < upper_rsi:
        return False, "reject_rsi_filter"
    if candidate.signal_type == "dump" and candidate.rsi_value > lower_rsi:
        return False, "reject_rsi_filter"

    return True, None
