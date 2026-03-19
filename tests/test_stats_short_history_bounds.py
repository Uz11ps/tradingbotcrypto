from __future__ import annotations

from app.api.router import _bounded_positive_int


def test_bounded_positive_int_uses_default_when_missing() -> None:
    assert _bounded_positive_int(None, default=72, upper=72) == 72


def test_bounded_positive_int_clamps_to_range() -> None:
    assert _bounded_positive_int(0, default=72, upper=72) == 1
    assert _bounded_positive_int(999, default=72, upper=72) == 72

