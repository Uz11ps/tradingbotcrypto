from __future__ import annotations

from datetime import UTC, datetime

from app.services.rsi_engine import compute_rsi, evaluate_rsi_signal


def test_compute_rsi_in_extreme_uptrend() -> None:
    closes = [float(i) for i in range(1, 40)]
    rsi = compute_rsi(closes, period=14)
    assert rsi > 90


def test_evaluate_rsi_signal_pump_and_dump() -> None:
    ts = datetime.now(tz=UTC)
    pump = evaluate_rsi_signal(
        symbol="BTC/USDT",
        timeframe="15m",
        rsi_value=77.0,
        lower=25.0,
        upper=75.0,
        prev_price=100.0,
        current_price=103.0,
        pct_change=3.0,
        generated_at=ts,
    )
    dump = evaluate_rsi_signal(
        symbol="BTC/USDT",
        timeframe="15m",
        rsi_value=23.0,
        lower=25.0,
        upper=75.0,
        prev_price=100.0,
        current_price=97.0,
        pct_change=-3.0,
        generated_at=ts,
    )

    assert pump is not None
    assert dump is not None
    assert pump.signal_type == "pump"
    assert dump.signal_type == "dump"

