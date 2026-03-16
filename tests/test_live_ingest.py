from __future__ import annotations

import gzip
import json

from wsproto.events import BytesMessage, TextMessage

from app.services.live_ingest import LiveShadowIngestor
from app.services.market_state_cache import MarketStateCache


def _ingestor(cache: MarketStateCache) -> LiveShadowIngestor:
    return LiveShadowIngestor(
        cache=cache,
        symbols=["BTC/USDT"],
        ws_url="wss://open-api-ws.bingx.com/market",
    )


def test_decode_text_payload() -> None:
    cache = MarketStateCache()
    ingest = _ingestor(cache)
    event = TextMessage(data='{"data":{"symbol":"BTC-USDT","lastPrice":"100"}}')
    payload = ingest._decode_event(event)
    assert payload is not None
    assert payload["data"]["symbol"] == "BTC-USDT"


def test_decode_gzip_binary_payload() -> None:
    cache = MarketStateCache()
    ingest = _ingestor(cache)
    raw = json.dumps({"data": {"symbol": "BTC-USDT", "lastPrice": "100"}}).encode("utf-8")
    event = BytesMessage(data=gzip.compress(raw))
    payload = ingest._decode_event(event)
    assert payload is not None
    assert payload["data"]["lastPrice"] == "100"


def test_apply_payload_updates_cache_with_mid() -> None:
    cache = MarketStateCache()
    ingest = _ingestor(cache)
    ok = ingest._apply_payload(
        {
            "data": {
                "symbol": "BTC-USDT",
                "lastPrice": "101.0",
                "bestBid": "100.0",
                "bestAsk": "102.0",
                "ts": 123456,
            }
        },
        receive_ts_ms=123500,
    )
    assert ok is True
    latest = cache.get_latest(symbol="BTC/USDT", now_ms=123500)
    assert latest is not None
    assert latest.source == "live_mid"
    assert latest.point.current_price == 101.0


def test_extract_pong_variants() -> None:
    cache = MarketStateCache()
    ingest = _ingestor(cache)
    assert ingest._extract_pong({"ping": 1}) == {"pong": 1}
    assert ingest._extract_pong({"op": "ping", "ts": 2}) == {"op": "pong", "ts": 2}
    assert ingest._extract_pong({"hello": "world"}) is None


def test_reconnect_backoff_delay_bounds() -> None:
    cache = MarketStateCache()
    ingest = LiveShadowIngestor(
        cache=cache,
        symbols=["BTC/USDT"],
        ws_url="wss://open-api-ws.bingx.com/market",
        reconnect_delay_seconds=2.0,
        reconnect_max_delay_seconds=10.0,
        reconnect_jitter_seconds=0.5,
    )
    delay1 = ingest._next_reconnect_delay(1)
    delay3 = ingest._next_reconnect_delay(3)
    delay10 = ingest._next_reconnect_delay(10)
    assert 2.0 <= delay1 <= 2.5
    assert 8.0 <= delay3 <= 8.5
    assert 10.0 <= delay10 <= 10.5
