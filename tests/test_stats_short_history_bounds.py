from __future__ import annotations

from app.api.router import _bounded_positive_int, _resolve_short_history_window_hours


def test_bounded_positive_int_uses_default_when_missing() -> None:
    assert _bounded_positive_int(None, default=72, upper=72) == 72


def test_bounded_positive_int_clamps_to_range() -> None:
    assert _bounded_positive_int(0, default=72, upper=72) == 1
    assert _bounded_positive_int(999, default=72, upper=72) == 72


def test_short_history_prefers_window_hours_alias() -> None:
    assert (
        _resolve_short_history_window_hours(
            hours=72,
            window_hours=1,
            default=72,
            upper=72,
        )
        == 1
    )


def test_short_history_uses_hours_when_alias_missing() -> None:
    assert (
        _resolve_short_history_window_hours(
            hours=2,
            window_hours=None,
            default=72,
            upper=72,
        )
        == 2
    )

