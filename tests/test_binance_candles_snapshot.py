from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.services import binance_candles
from app.services.binance_candles import KlineBar


def _make_bars(*, descending: bool) -> list[KlineBar]:
    start_open_time = int(datetime(2026, 3, 15, 18, 0, tzinfo=UTC).timestamp() * 1000)
    step_ms = 5 * 60 * 1000
    bars: list[KlineBar] = []
    price = 1.0
    # 30 closed bars.
    for i in range(30):
        open_time = start_open_time + (i * step_ms)
        open_price = price
        close_price = price + 0.01
        bars.append(
            KlineBar(
                open_time_ms=open_time,
                open=open_price,
                high=max(open_price, close_price) + 0.005,
                low=min(open_price, close_price) - 0.005,
                close=close_price,
                volume=1000 + i,
                close_time_ms=open_time + step_ms,
                is_closed=True,
            )
        )
        price = close_price

    # Add one forming bar (must be excluded from closed-candle calculations).
    forming_open_time = start_open_time + (30 * step_ms)
    bars.append(
        KlineBar(
            open_time_ms=forming_open_time,
            open=price,
            high=price + 0.01,
            low=price - 0.02,
            close=price - 0.01,
            volume=1337,
            close_time_ms=forming_open_time + step_ms,
            is_closed=False,
        )
    )
    if descending:
        bars.reverse()
    return bars


@pytest.mark.asyncio
async def test_build_snapshot_same_for_ascending_and_descending(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fetch_bars_asc(
        *,
        symbol: str,
        timeframe: str,
        limit: int = 120,
        market_type: str = "spot",
    ) -> list[KlineBar]:
        return _make_bars(descending=False)

    async def _fetch_bars_desc(
        *,
        symbol: str,
        timeframe: str,
        limit: int = 120,
        market_type: str = "spot",
    ) -> list[KlineBar]:
        return _make_bars(descending=True)

    monkeypatch.setattr(binance_candles, "fetch_recent_bars", _fetch_bars_asc)
    asc_snapshot = await binance_candles.build_snapshot(
        symbol="TEST/USDT",
        timeframe="5m",
        quote_volume_24h=1_000_000.0,
    )

    monkeypatch.setattr(binance_candles, "fetch_recent_bars", _fetch_bars_desc)
    desc_snapshot = await binance_candles.build_snapshot(
        symbol="TEST/USDT",
        timeframe="5m",
        quote_volume_24h=1_000_000.0,
    )

    assert asc_snapshot.prev_close == desc_snapshot.prev_close
    assert asc_snapshot.current_close == desc_snapshot.current_close
    assert asc_snapshot.price_change_5m == desc_snapshot.price_change_5m
    assert asc_snapshot.price_change_15m == desc_snapshot.price_change_15m
    assert asc_snapshot.window_open_price == desc_snapshot.window_open_price
    assert asc_snapshot.live_window_open_price == desc_snapshot.live_window_open_price


def test_parse_kline_bar_supports_dict_rows() -> None:
    row = {
        "openTime": "1710000000000",
        "open": "1.0",
        "high": "1.1",
        "low": "0.9",
        "close": "1.05",
        "volume": "12345.6",
        "closeTime": "1710000300000",
        "isClosed": True,
    }
    bar = binance_candles._parse_kline_bar(row)
    assert bar is not None
    assert bar.open_time_ms == 1710000000000
    assert bar.close == 1.05
    assert bar.is_closed is True


def test_extract_close_and_volume_supports_dict_rows() -> None:
    parsed = binance_candles._extract_close_and_volume({"close": "2.5", "volume": "77"})
    assert parsed == (2.5, 77.0)
