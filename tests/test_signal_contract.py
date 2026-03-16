from __future__ import annotations

from app.services.signal_contract import LiveSignalContract, SignalTimestamps


def test_live_signal_contract_payload_ok() -> None:
    contract = LiveSignalContract(
        symbol="BTC/USDT",
        market_type="spot",
        timeframe="live",
        direction="pump",
        trigger_source="live_mid",
        window_seconds=30,
        baseline_price=100.0,
        current_price=103.0,
        change_pct=3.0,
        timestamps=SignalTimestamps(
            exchange_event_ts_ms=1000,
            received_ts_ms=1010,
            processed_ts_ms=1020,
            sent_ts_ms=1030,
        ),
    )
    payload = contract.to_payload()
    assert payload["symbol"] == "BTC/USDT"
    assert payload["window_seconds"] == 30
    assert payload["trigger_source"] == "live_mid"


def test_live_signal_contract_rejects_invalid_timestamp_chain() -> None:
    contract = LiveSignalContract(
        symbol="BTC/USDT",
        market_type="spot",
        timeframe="live",
        direction="dump",
        trigger_source="live_trade",
        window_seconds=10,
        baseline_price=100.0,
        current_price=99.0,
        change_pct=-1.0,
        timestamps=SignalTimestamps(
            exchange_event_ts_ms=1000,
            received_ts_ms=990,
            processed_ts_ms=1020,
        ),
    )
    try:
        contract.to_payload()
    except ValueError as exc:
        assert "received_ts_ms" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid timestamp chain")
