from __future__ import annotations

from datetime import UTC, datetime

from app.services.binance_candles import KlineBar
from app.services.strategy_engine import detect_pinbar_strategy_signal


def _bar(*, i: int, open_: float, high: float, low: float, close: float) -> KlineBar:
    return KlineBar(
        open_time_ms=i * 60_000,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1_000.0,
    )


def test_strategy_respects_max_body_ratio() -> None:
    bars: list[KlineBar] = []
    for i in range(18):
        base = 100.0 + i
        bars.append(_bar(i=i, open_=base, high=base + 1.0, low=base - 1.0, close=base + 1.0))

    # Pin-like bearish bar with body_ratio=0.25 and strength=2.0.
    # It should pass at 0.35 and fail at 0.20 max_body_ratio.
    bars.append(_bar(i=18, open_=119.0, high=121.0, low=117.0, close=118.0))
    # Confirmation bar for short: closes below pin close and does not break pin high.
    bars.append(_bar(i=19, open_=118.0, high=120.0, low=116.0, close=117.0))

    loose = detect_pinbar_strategy_signal(
        symbol="TEST/USDT",
        timeframe="15m",
        bars=bars,
        generated_at=datetime.now(tz=UTC),
        market_type="spot",
        impulse_window=12,
        deviation_threshold_pct=4.0,
        min_pinbar_strength=2.0,
        max_body_ratio=0.35,
    )
    strict = detect_pinbar_strategy_signal(
        symbol="TEST/USDT",
        timeframe="15m",
        bars=bars,
        generated_at=datetime.now(tz=UTC),
        market_type="spot",
        impulse_window=12,
        deviation_threshold_pct=4.0,
        min_pinbar_strength=2.0,
        max_body_ratio=0.20,
    )

    assert loose is not None
    assert strict is None


def test_strategy_confirmation_toggle() -> None:
    bars: list[KlineBar] = []
    for i in range(18):
        base = 100.0 + i
        bars.append(_bar(i=i, open_=base, high=base + 1.0, low=base - 1.0, close=base + 1.0))

    # Bearish pin bar.
    bars.append(_bar(i=18, open_=119.0, high=121.0, low=117.0, close=118.0))
    # Non-confirming bar for short: closes above pin close.
    bars.append(_bar(i=19, open_=118.0, high=120.0, low=117.0, close=119.0))

    with_confirmation = detect_pinbar_strategy_signal(
        symbol="TEST/USDT",
        timeframe="15m",
        bars=bars,
        generated_at=datetime.now(tz=UTC),
        market_type="spot",
        require_confirmation=True,
    )
    without_confirmation = detect_pinbar_strategy_signal(
        symbol="TEST/USDT",
        timeframe="15m",
        bars=bars,
        generated_at=datetime.now(tz=UTC),
        market_type="spot",
        require_confirmation=False,
    )

    assert with_confirmation is None
    assert without_confirmation is not None
