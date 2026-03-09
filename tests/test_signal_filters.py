from __future__ import annotations

from datetime import UTC, datetime

from app.services.rsi_engine import evaluate_rsi_signal
from app.services.signal_filters import SignalFilterEngine


def _candidate(*, current_price: float) -> object:
    ts = datetime.now(tz=UTC)
    candidate = evaluate_rsi_signal(
        symbol="BTC/USDT",
        timeframe="5m",
        rsi_value=62.0,
        price_change_5m=2.7,
        price_change_15m=4.6,
        price_change_5m_trigger_pct=2.5,
        price_change_15m_trigger_pct=4.5,
        prev_price=100.0,
        current_price=current_price,
        pct_change=2.7,
        current_volume=200.0,
        avg_volume_20=100.0,
        generated_at=ts,
    )
    assert candidate is not None
    return candidate


def test_duplicate_is_not_blocked() -> None:
    engine = SignalFilterEngine(cooldown_seconds=0, dedup_window_seconds=600, followup_move_pct=1.5)
    first = _candidate(current_price=102.0)
    second = _candidate(current_price=102.0)

    ok1, reject1 = engine.accept(first, scope="chat")
    ok2, reject2 = engine.accept(second, scope="chat")

    assert ok1 is True
    assert reject1 is None
    assert ok2 is True
    assert reject2 is None


def test_cooldown_bypassed_when_move_continues() -> None:
    engine = SignalFilterEngine(cooldown_seconds=600, dedup_window_seconds=600, followup_move_pct=1.5)
    first = _candidate(current_price=100.0)
    followup = _candidate(current_price=102.0)  # +2% from previous signal price

    ok1, reject1 = engine.accept(first, scope="chat")
    ok2, reject2 = engine.accept(followup, scope="chat")

    assert ok1 is True
    assert reject1 is None
    assert ok2 is True
    assert reject2 is None
