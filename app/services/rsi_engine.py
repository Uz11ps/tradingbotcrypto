from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

SignalType = Literal["pump", "dump"]
DivergenceType = Literal["bullish", "bearish", "hidden_bullish", "hidden_bearish"]


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
    rsi_divergence_type: DivergenceType | None
    rsi_divergence_pct: float | None
    rsi_divergence_note: str | None
    generated_at: datetime


def compute_rsi_series(closes: list[float], *, period: int = 14) -> dict[int, float]:
    """Return RSI values keyed by close index."""
    if period < 2:
        raise ValueError("RSI period must be >= 2")
    if len(closes) <= period:
        raise ValueError("Not enough data to compute RSI series")

    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(0.0, delta))
        losses.append(abs(min(0.0, delta)))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def _to_rsi(gain: float, loss: float) -> float:
        if loss == 0:
            return 100.0
        rs = gain / loss
        return 100.0 - (100.0 / (1.0 + rs))

    out: dict[int, float] = {period: _to_rsi(avg_gain, avg_loss)}
    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period
        out[i + 1] = _to_rsi(avg_gain, avg_loss)
    return out


def _pct_change(prev_value: float, current_value: float) -> float:
    if prev_value == 0:
        return 0.0
    return ((current_value - prev_value) / prev_value) * 100.0


def _pivot_indices(values: list[float], *, kind: Literal["low", "high"], window: int = 3) -> list[int]:
    if len(values) < (window * 2) + 1:
        return []
    pivots: list[int] = []
    for i in range(window, len(values) - window):
        chunk = values[i - window : i + window + 1]
        center = values[i]
        if kind == "low" and center == min(chunk):
            pivots.append(i)
        if kind == "high" and center == max(chunk):
            pivots.append(i)
    return pivots


def _build_divergence(
    *,
    div_type: DivergenceType,
    idx_a: int,
    idx_b: int,
    closes: list[float],
    rsi_map: dict[int, float],
) -> tuple[DivergenceType, float, str]:
    price_a = closes[idx_a]
    price_b = closes[idx_b]
    rsi_a = rsi_map[idx_a]
    rsi_b = rsi_map[idx_b]
    strength = abs(_pct_change(price_a, price_b)) + abs(_pct_change(rsi_a, rsi_b))
    note = (
        f"price: {price_a:.8f}->{price_b:.8f}, "
        f"rsi: {rsi_a:.2f}->{rsi_b:.2f}"
    )
    return div_type, round(strength, 2), note


def detect_rsi_divergence(
    *,
    closes: list[float],
    period: int,
    signal_type: SignalType,
) -> tuple[DivergenceType | None, float | None, str | None]:
    try:
        rsi_map = compute_rsi_series(closes, period=period)
    except ValueError:
        return None, None, None

    if signal_type == "pump":
        lows = [idx for idx in _pivot_indices(closes, kind="low", window=3) if idx in rsi_map]
        if len(lows) < 2:
            return None, None, None
        idx_a, idx_b = lows[-2], lows[-1]
        price_a, price_b = closes[idx_a], closes[idx_b]
        rsi_a, rsi_b = rsi_map[idx_a], rsi_map[idx_b]
        if price_b < price_a and rsi_b > rsi_a:
            return _build_divergence(
                div_type="bullish",
                idx_a=idx_a,
                idx_b=idx_b,
                closes=closes,
                rsi_map=rsi_map,
            )
        if price_b > price_a and rsi_b < rsi_a:
            return _build_divergence(
                div_type="hidden_bullish",
                idx_a=idx_a,
                idx_b=idx_b,
                closes=closes,
                rsi_map=rsi_map,
            )
        return None, None, None

    highs = [idx for idx in _pivot_indices(closes, kind="high", window=3) if idx in rsi_map]
    if len(highs) < 2:
        return None, None, None
    idx_a, idx_b = highs[-2], highs[-1]
    price_a, price_b = closes[idx_a], closes[idx_b]
    rsi_a, rsi_b = rsi_map[idx_a], rsi_map[idx_b]
    if price_b > price_a and rsi_b < rsi_a:
        return _build_divergence(
            div_type="bearish",
            idx_a=idx_a,
            idx_b=idx_b,
            closes=closes,
            rsi_map=rsi_map,
        )
    if price_b < price_a and rsi_b > rsi_a:
        return _build_divergence(
            div_type="hidden_bearish",
            idx_a=idx_a,
            idx_b=idx_b,
            closes=closes,
            rsi_map=rsi_map,
        )
    return None, None, None


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
    closes: list[float] | None = None,
    rsi_period: int = 14,
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
    divergence_type: DivergenceType | None = None
    divergence_pct: float | None = None
    divergence_note: str | None = None
    if closes:
        divergence_type, divergence_pct, divergence_note = detect_rsi_divergence(
            closes=closes,
            period=rsi_period,
            signal_type=signal_type,
        )

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
        exchange="BingX",
        trigger_source="price_window",
        context_tag=None,
        rsi_divergence_type=divergence_type,
        rsi_divergence_pct=divergence_pct,
        rsi_divergence_note=divergence_note,
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
