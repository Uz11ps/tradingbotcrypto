from __future__ import annotations

from datetime import UTC, datetime

from app.services.rsi_engine import compute_rsi, evaluate_rsi_signal, validate_candidate_filters


def test_compute_rsi_in_extreme_uptrend() -> None:
    closes = [float(i) for i in range(1, 40)]
    rsi = compute_rsi(closes, period=14)
    assert rsi > 90


def test_evaluate_rsi_signal_pump_and_dump() -> None:
    ts = datetime.now(tz=UTC)
    pump = evaluate_rsi_signal(
        symbol="BTC/USDT",
        timeframe="15m",
        rsi_value=55.0,
        price_change_5m=2.6,
        price_change_15m=4.6,
        price_change_5m_trigger_pct=2.5,
        price_change_15m_trigger_pct=4.5,
        prev_price=100.0,
        current_price=103.0,
        pct_change=3.0,
        current_volume=250.0,
        avg_volume_20=100.0,
        generated_at=ts,
    )
    dump = evaluate_rsi_signal(
        symbol="BTC/USDT",
        timeframe="15m",
        rsi_value=45.0,
        price_change_5m=-2.7,
        price_change_15m=-4.8,
        price_change_5m_trigger_pct=2.5,
        price_change_15m_trigger_pct=4.5,
        prev_price=100.0,
        current_price=97.0,
        pct_change=-3.0,
        current_volume=250.0,
        avg_volume_20=100.0,
        generated_at=ts,
    )

    assert pump is not None
    assert dump is not None
    assert pump.signal_type == "pump"
    assert dump.signal_type == "dump"


def test_validate_candidate_filters() -> None:
    ts = datetime.now(tz=UTC)
    candidate = evaluate_rsi_signal(
        symbol="BTC/USDT",
        timeframe="15m",
        rsi_value=80.0,
        price_change_5m=2.8,
        price_change_15m=4.7,
        price_change_5m_trigger_pct=2.5,
        price_change_15m_trigger_pct=4.5,
        prev_price=100.0,
        current_price=101.6,
        pct_change=1.6,
        current_volume=250.0,
        avg_volume_20=100.0,
        generated_at=ts,
    )
    assert candidate is not None
    ok, reason = validate_candidate_filters(
        candidate,
        lower_rsi=25.0,
        upper_rsi=75.0,
        volume_multiplier_base=1.35,
        volume_multiplier_strong=1.2,
        strong_move_pct=5.0,
    )
    assert ok is True
    assert reason is None


def test_reject_by_price_trigger() -> None:
    ts = datetime.now(tz=UTC)
    candidate = evaluate_rsi_signal(
        symbol="BTC/USDT",
        timeframe="15m",
        rsi_value=80.0,
        price_change_5m=1.9,
        price_change_15m=3.9,
        price_change_5m_trigger_pct=2.5,
        price_change_15m_trigger_pct=4.5,
        prev_price=100.0,
        current_price=101.0,
        pct_change=1.0,
        current_volume=250.0,
        avg_volume_20=100.0,
        generated_at=ts,
    )
    assert candidate is None

