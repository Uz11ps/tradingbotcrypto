from __future__ import annotations

VALID_SIGNAL_SIDE_MODES = {"all", "pump", "dump"}
VALID_MARKET_TYPES = {"spot", "futures", "both"}


def _normalize_direction(
    direction: str | None = None,
    signal_type: str | None = None,
) -> str | None:
    raw_direction = (direction or "").strip().lower()
    raw_signal_type = (signal_type or "").strip().lower()
    if raw_direction in {"up", "pump"} or raw_signal_type == "pump":
        return "up"
    if raw_direction in {"down", "dump"} or raw_signal_type == "dump":
        return "down"
    return None


def normalize_signal_side_mode(mode: str | None) -> str:
    value = (mode or "all").strip().lower()
    return value if value in VALID_SIGNAL_SIDE_MODES else "all"


def normalize_market_type(value: str | None) -> str:
    normalized = (value or "both").strip().lower()
    return normalized if normalized in VALID_MARKET_TYPES else "both"


def build_recommendation(
    direction: str | None = None,
    signal_type: str | None = None,
    action: str | None = None,
) -> str:
    normalized_action = (action or "").strip().lower()
    normalized_direction = _normalize_direction(direction=direction, signal_type=signal_type)
    if normalized_action == "entry" and normalized_direction == "up":
        return "Лонг"
    if normalized_action == "entry" and normalized_direction == "down":
        return "Шорт"
    return "Наблюдать"


def matches_signal_side_mode(
    mode: str,
    direction: str | None = None,
    signal_type: str | None = None,
) -> bool:
    normalized_mode = normalize_signal_side_mode(mode)
    if normalized_mode == "all":
        return True
    normalized_direction = _normalize_direction(direction=direction, signal_type=signal_type)
    if normalized_mode == "pump":
        return normalized_direction == "up"
    return normalized_direction == "down"
