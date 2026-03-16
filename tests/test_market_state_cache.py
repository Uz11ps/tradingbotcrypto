from __future__ import annotations

from app.services.market_state_cache import MarketStateCache


def test_prefers_mid_price_over_last_trade() -> None:
    cache = MarketStateCache(ttl_seconds=120, max_points_per_symbol=10, max_symbols=10)
    cache.upsert(
        symbol="BTC/USDT",
        exchange_event_ts_ms=1000,
        received_ts_ms=1010,
        last_trade=101.0,
        best_bid=100.0,
        best_ask=102.0,
    )
    latest = cache.get_latest(symbol="BTC/USDT", now_ms=1020)
    assert latest is not None
    assert latest.source == "live_mid"
    assert latest.point.current_price == 101.0


def test_fallbacks_to_last_trade_when_bbo_missing() -> None:
    cache = MarketStateCache(ttl_seconds=120, max_points_per_symbol=10, max_symbols=10)
    cache.upsert(
        symbol="ETH/USDT",
        exchange_event_ts_ms=1000,
        received_ts_ms=1010,
        last_trade=2500.0,
    )
    latest = cache.get_latest(symbol="ETH/USDT", now_ms=1020)
    assert latest is not None
    assert latest.source == "live_trade"
    assert latest.point.current_price == 2500.0


def test_cleanup_respects_ttl() -> None:
    cache = MarketStateCache(ttl_seconds=2, max_points_per_symbol=10, max_symbols=10)
    cache.upsert(
        symbol="SOL/USDT",
        exchange_event_ts_ms=1_000,
        received_ts_ms=1_000,
        last_trade=100.0,
    )
    cache.upsert(
        symbol="SOL/USDT",
        exchange_event_ts_ms=3_500,
        received_ts_ms=3_500,
        last_trade=110.0,
    )
    cache.cleanup(now_ms=3_500)
    baseline_old = cache.get_baseline_price(symbol="SOL/USDT", window_seconds=3, now_ms=3_500)
    assert baseline_old == 110.0


def test_evicts_oldest_symbol_when_symbol_cap_reached() -> None:
    cache = MarketStateCache(ttl_seconds=120, max_points_per_symbol=10, max_symbols=1)
    cache.upsert(
        symbol="BTC/USDT",
        exchange_event_ts_ms=1000,
        received_ts_ms=1000,
        last_trade=100.0,
    )
    cache.upsert(
        symbol="ETH/USDT",
        exchange_event_ts_ms=2000,
        received_ts_ms=2000,
        last_trade=200.0,
    )
    assert cache.get_latest(symbol="BTC/USDT") is None
    assert cache.get_latest(symbol="ETH/USDT") is not None
