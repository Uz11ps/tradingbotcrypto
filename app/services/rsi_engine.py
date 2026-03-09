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
    current_volume: float
    avg_volume_20: float
    exchange: str
    trigger_source: str
    generated_at: datetime


def evaluate_rsi_signal(
    *,
    symbol: str,
    timeframe: str,
    rsi_value: float,
    lower: float,
    upper: float,
    prev_price: float,
    current_price: float,
    pct_change: float,
    current_volume: float,
    avg_volume_20: float,
    generated_at: datetime,
) -> RsiSignalCandidate | None:
    if rsi_value >= upper:
        signal_type: SignalType = "pump"
    elif rsi_value <= lower:
        signal_type = "dump"
    else:
        return None

    return RsiSignalCandidate(
        symbol=symbol,
        timeframe=timeframe,
        signal_type=signal_type,
        rsi_value=round(rsi_value, 2),
        prev_price=prev_price,
        current_price=current_price,
        pct_change=round(pct_change, 4),
        current_volume=current_volume,
        avg_volume_20=avg_volume_20,
        exchange="Binance",
        trigger_source="rsi",
        generated_at=generated_at,
    )


def validate_candidate_filters(
    candidate: RsiSignalCandidate,
    *,
    min_abs_change_pct: float,
    volume_spike_multiplier: float,
) -> tuple[bool, str | None]:
    if abs(candidate.pct_change) < min_abs_change_pct:
        return False, "reject_min_move"

    if candidate.signal_type == "pump" and candidate.pct_change <= 0:
        return False, "reject_direction"
    if candidate.signal_type == "dump" and candidate.pct_change >= 0:
        return False, "reject_direction"

    required_volume = candidate.avg_volume_20 * volume_spike_multiplier
    if candidate.current_volume < required_volume:
        return False, "reject_volume"

    return True, None

