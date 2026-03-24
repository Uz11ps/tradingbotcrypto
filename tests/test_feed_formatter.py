from __future__ import annotations

from datetime import UTC, datetime

from app.services.feed_formatter import format_signal_card
from app.services.rsi_engine import RsiSignalCandidate


def _candidate() -> RsiSignalCandidate:
    return RsiSignalCandidate(
        symbol="TEST/USDT",
        timeframe="15m",
        signal_type="pump",
        prev_price=95.0,
        pct_change=5.1,
        price_change_5m=2.1,
        price_change_15m=5.1,
        current_price=100.0,
        current_volume=1000.0,
        avg_volume_20=800.0,
        quote_volume_24h=1_000_000.0,
        rsi_value=80.0,
        exchange="bingx",
        trigger_source="price_move",
        context_tag=None,
        rsi_divergence_type=None,
        rsi_divergence_pct=None,
        rsi_divergence_note=None,
        generated_at=datetime.now(tz=UTC),
    )


def test_feed_card_uses_live_price_when_available() -> None:
    text = format_signal_card(_candidate(), live_price=101.25)
    assert "Цена (close)" not in text
    assert "Live:" not in text
    assert "Цена: 101" in text


def test_feed_card_falls_back_to_snapshot_price() -> None:
    text = format_signal_card(_candidate(), live_price=None)
    assert "Цена (close)" not in text
    assert "Live:" not in text
    assert "Цена: 100" in text
