from __future__ import annotations

from app.workers.mock_signal_worker import (
    _chat_symbol_window,
    _mark_strategy_symbol_sent,
    _rotate_chat_ids,
    _strategy_symbol_cooldown_allows,
    _strategy_symbol_cooldown_reset_for_tests,
)


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


def test_strategy_symbol_hard_cooldown_blocks_repeats() -> None:
    _strategy_symbol_cooldown_reset_for_tests()
    allowed, wait = _strategy_symbol_cooldown_allows(
        chat_id=1,
        symbol="CRK/USDT",
        cooldown_seconds=300,
        now_ts=1000.0,
    )
    assert allowed is True
    assert wait == 0
    _mark_strategy_symbol_sent(chat_id=1, symbol="CRK/USDT", now_ts=1000.0)
    allowed2, wait2 = _strategy_symbol_cooldown_allows(
        chat_id=1,
        symbol="CRK/USDT",
        cooldown_seconds=300,
        now_ts=1100.0,
    )
    assert allowed2 is False
    assert wait2 > 0


def test_strategy_symbol_hard_cooldown_expires() -> None:
    _strategy_symbol_cooldown_reset_for_tests()
    _mark_strategy_symbol_sent(chat_id=1, symbol="CRK/USDT", now_ts=1000.0)
    allowed, wait = _strategy_symbol_cooldown_allows(
        chat_id=1,
        symbol="CRK/USDT",
        cooldown_seconds=300,
        now_ts=1305.0,
    )
    assert allowed is True
    assert wait == 0

