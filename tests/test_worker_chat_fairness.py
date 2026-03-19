from __future__ import annotations

from app.workers.mock_signal_worker import _chat_symbol_window, _rotate_chat_ids


def test_chat_symbol_window_respects_budget() -> None:
    symbols = [f"S{i}" for i in range(10)]
    result = _chat_symbol_window(symbols, chat_id=100, cycle_index=0, budget=4)
    assert len(result) == 4
    assert all(symbol in symbols for symbol in result)


def test_chat_symbol_window_rotates_between_cycles() -> None:
    symbols = [f"S{i}" for i in range(12)]
    first = _chat_symbol_window(symbols, chat_id=42, cycle_index=0, budget=5)
    second = _chat_symbol_window(symbols, chat_id=42, cycle_index=1, budget=5)
    assert first != second
    assert len(first) == 5
    assert len(second) == 5


def test_rotate_chat_ids_round_robin() -> None:
    chat_ids = [111, 222, 333, 444]
    assert _rotate_chat_ids(chat_ids, cycle_index=0) == [111, 222, 333, 444]
    assert _rotate_chat_ids(chat_ids, cycle_index=1) == [222, 333, 444, 111]
    assert _rotate_chat_ids(chat_ids, cycle_index=2) == [333, 444, 111, 222]

