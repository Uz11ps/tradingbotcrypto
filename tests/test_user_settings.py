from __future__ import annotations

from app.services.user_settings import get_global_defaults


def test_global_defaults_keep_15m_trigger_aligned_with_min_move() -> None:
    defaults = get_global_defaults()
    assert defaults.min_price_move_pct > 0
    assert defaults.price_change_15m_trigger_pct == defaults.min_price_move_pct
    assert defaults.strategy_impulse_window >= 2
    assert defaults.strategy_deviation_threshold_pct > 0
    assert defaults.strategy_min_pinbar_strength > 0
    assert 0 < defaults.strategy_max_body_ratio <= 1
    assert defaults.strategy_max_signals_per_cycle >= 1

