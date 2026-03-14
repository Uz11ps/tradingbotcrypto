from __future__ import annotations

from app.services.signal_presentation import (
    build_recommendation,
    matches_signal_side_mode,
    normalize_signal_side_mode,
)


def test_build_recommendation_entry_pump_is_long() -> None:
    assert build_recommendation(direction="up", action="entry") == "Лонг"
    assert build_recommendation(signal_type="pump", action="entry") == "Лонг"


def test_build_recommendation_entry_dump_is_short() -> None:
    assert build_recommendation(direction="down", action="entry") == "Шорт"
    assert build_recommendation(signal_type="dump", action="entry") == "Шорт"


def test_build_recommendation_non_entry_is_watch() -> None:
    assert build_recommendation(direction="up", action="watch") == "Наблюдать"
    assert build_recommendation(direction="down", action="hold") == "Наблюдать"


def test_matches_signal_side_mode() -> None:
    assert matches_signal_side_mode("all", direction="up") is True
    assert matches_signal_side_mode("all", direction="down") is True
    assert matches_signal_side_mode("pump", signal_type="pump") is True
    assert matches_signal_side_mode("pump", signal_type="dump") is False
    assert matches_signal_side_mode("dump", direction="down") is True
    assert matches_signal_side_mode("dump", direction="up") is False


def test_normalize_signal_side_mode_fallbacks_to_all() -> None:
    assert normalize_signal_side_mode(None) == "all"
    assert normalize_signal_side_mode("invalid") == "all"
    assert normalize_signal_side_mode("PUMP") == "pump"
