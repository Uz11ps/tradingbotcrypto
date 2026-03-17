from __future__ import annotations

from app.workers.mock_signal_worker import _resolve_evaluation_window


def test_live_spike_fallbacks_high_timeframes_to_15m_window() -> None:
    evaluation_tf, window_seconds, fallback_applied, fallback_reason = _resolve_evaluation_window(
        selected_tf="1h",
        trigger_mode="live_spike",
    )
    assert evaluation_tf == "15m"
    assert window_seconds == 900
    assert fallback_applied is True
    assert fallback_reason == "live_trigger_window_fallback_to_15m"


def test_live_spike_keeps_5m_without_fallback() -> None:
    evaluation_tf, window_seconds, fallback_applied, fallback_reason = _resolve_evaluation_window(
        selected_tf="5m",
        trigger_mode="live_spike",
    )
    assert evaluation_tf == "5m"
    assert window_seconds == 300
    assert fallback_applied is False
    assert fallback_reason is None


def test_candle_mode_keeps_selected_timeframe() -> None:
    evaluation_tf, window_seconds, fallback_applied, fallback_reason = _resolve_evaluation_window(
        selected_tf="4h",
        trigger_mode="candle",
    )
    assert evaluation_tf == "4h"
    assert window_seconds == 14400
    assert fallback_applied is False
    assert fallback_reason is None

