from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.services.binance_candles import KlineBar

StrategyDirection = Literal["long", "short"]
StrategySignalType = Literal["post_dump_bounce_long", "post_pump_pullback_short"]


@dataclass(slots=True)
class StrategySignalCandidate:
    symbol: str
    timeframe: str
    direction: StrategyDirection
    signal_type: StrategySignalType
    current_price: float
    baseline_price: float
    deviation_pct: float
    pinbar_strength: float
    generated_at: datetime
    market_type: str


def _pinbar_strength(bar: KlineBar) -> tuple[float, float, float]:
    body = abs(bar.close - bar.open)
    full_range = max(1e-12, bar.high - bar.low)
    upper_wick = max(0.0, bar.high - max(bar.open, bar.close))
    lower_wick = max(0.0, min(bar.open, bar.close) - bar.low)
    body_ratio = body / full_range
    return upper_wick, lower_wick, body_ratio


def detect_pinbar_strategy_signal(
    *,
    symbol: str,
    timeframe: str,
    bars: list[KlineBar],
    generated_at: datetime,
    market_type: str,
    impulse_window: int = 12,
    deviation_threshold_pct: float = 4.0,
    min_pinbar_strength: float = 2.0,
) -> StrategySignalCandidate | None:
    if len(bars) < max(impulse_window + 1, 20):
        return None

    recent = bars[-impulse_window:]
    baseline = recent[0].close
    current = recent[-1].close
    if baseline == 0:
        return None
    deviation_pct = ((current - baseline) / baseline) * 100.0
    pin_bar = bars[-2]
    upper_wick, lower_wick, body_ratio = _pinbar_strength(pin_bar)
    body = max(1e-12, abs(pin_bar.close - pin_bar.open))

    # Short setup: strong upward impulse + bearish pin bar.
    if deviation_pct >= deviation_threshold_pct:
        strength = upper_wick / body
        is_bearish_pin = strength >= min_pinbar_strength and pin_bar.close < pin_bar.open and body_ratio <= 0.35
        if is_bearish_pin:
            return StrategySignalCandidate(
                symbol=symbol,
                timeframe=timeframe,
                direction="short",
                signal_type="post_pump_pullback_short",
                current_price=current,
                baseline_price=baseline,
                deviation_pct=round(deviation_pct, 4),
                pinbar_strength=round(strength, 2),
                generated_at=generated_at,
                market_type=market_type,
            )

    # Long setup: strong downward impulse + bullish pin bar.
    if deviation_pct <= -deviation_threshold_pct:
        strength = lower_wick / body
        is_bullish_pin = strength >= min_pinbar_strength and pin_bar.close > pin_bar.open and body_ratio <= 0.35
        if is_bullish_pin:
            return StrategySignalCandidate(
                symbol=symbol,
                timeframe=timeframe,
                direction="long",
                signal_type="post_dump_bounce_long",
                current_price=current,
                baseline_price=baseline,
                deviation_pct=round(deviation_pct, 4),
                pinbar_strength=round(strength, 2),
                generated_at=generated_at,
                market_type=market_type,
            )

    return None
