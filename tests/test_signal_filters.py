from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.services.rsi_engine import evaluate_rsi_signal
from app.services.signal_filters import SignalFilterEngine


def _candidate(*, current_price: float) -> object:
    ts = datetime.now(tz=UTC)
    candidate = evaluate_rsi_signal(
        symbol="BTC/USDT",
        timeframe="5m",
        rsi_value=62.0,
        price_change_5m=2.7,
        price_change_15m=4.6,
        price_change_5m_trigger_pct=2.5,
        price_change_15m_trigger_pct=4.5,
        window_open_price=100.0,
        current_price=current_price,
        pct_change=2.7,
        current_volume=200.0,
        avg_volume_20=100.0,
        quote_volume_24h=1_000_000.0,
        generated_at=ts,
    )
    assert candidate is not None
    return candidate


@pytest.mark.asyncio
async def test_duplicate_is_not_blocked() -> None:
    engine = SignalFilterEngine(cooldown_seconds=0, dedup_window_seconds=600, followup_move_pct=1.5)
    first = _candidate(current_price=102.0)
    second = _candidate(current_price=102.0)

    ok1, reject1 = await engine.accept(first, scope="chat")
    ok2, reject2 = await engine.accept(second, scope="chat")

    assert ok1 is True
    assert reject1 is None
    assert ok2 is False
    assert reject2 is not None
    assert reject2.reason == "duplicate"


@pytest.mark.asyncio
async def test_cooldown_bypassed_when_move_continues() -> None:
    engine = SignalFilterEngine(cooldown_seconds=600, dedup_window_seconds=600, followup_move_pct=1.5)
    first = _candidate(current_price=100.0)
    followup = _candidate(current_price=102.0)  # +2% from previous signal price

    ok1, reject1 = await engine.accept(first, scope="chat")
    ok2, reject2 = await engine.accept(followup, scope="chat")

    assert ok1 is True
    assert reject1 is None
    assert ok2 is True
    assert reject2 is None


@pytest.mark.asyncio
async def test_stale_repeat_blocked_even_after_cooldown() -> None:
    engine = SignalFilterEngine(
        cooldown_seconds=1,
        dedup_window_seconds=1,
        followup_move_pct=1.5,
        repeat_guard_min_move_pct=0.4,
        repeat_guard_min_rsi_delta=2.0,
    )
    first = _candidate(current_price=100.0)
    second = _candidate(current_price=100.2)  # +0.2% and same RSI path

    ok1, reject1 = await engine.accept(first, scope="chat")
    assert ok1 is True
    assert reject1 is None

    await asyncio.sleep(1.1)

    ok2, reject2 = await engine.accept(second, scope="chat")
    assert ok2 is False
    assert reject2 is not None
    assert reject2.reason == "stale_repeat"


@pytest.mark.asyncio
async def test_soft_flip_log_only_allows_signal() -> None:
    engine = SignalFilterEngine(
        cooldown_seconds=0,
        dedup_window_seconds=0,
        soft_flip_window_seconds=600,
        soft_flip_min_move_pct=1.0,
        soft_flip_log_only=True,
    )
    first = _candidate(current_price=100.0)
    flip = replace(first, signal_type="dump", current_price=100.2)

    ok1, reject1 = await engine.accept(first, scope="chat")
    ok2, reject2 = await engine.accept(flip, scope="chat")

    assert ok1 is True
    assert reject1 is None
    assert ok2 is True
    assert reject2 is None


@pytest.mark.asyncio
async def test_soft_flip_strict_rejects_signal() -> None:
    engine = SignalFilterEngine(
        cooldown_seconds=0,
        dedup_window_seconds=0,
        soft_flip_window_seconds=600,
        soft_flip_min_move_pct=1.0,
        soft_flip_log_only=False,
    )
    first = _candidate(current_price=100.0)
    flip = replace(first, signal_type="dump", current_price=100.2)

    ok1, reject1 = await engine.accept(first, scope="chat")
    ok2, reject2 = await engine.accept(flip, scope="chat")

    assert ok1 is True
    assert reject1 is None
    assert ok2 is False
    assert reject2 is not None
    assert reject2.reason == "soft_flip_guard"
