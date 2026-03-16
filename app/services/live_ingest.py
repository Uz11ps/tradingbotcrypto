from __future__ import annotations

import asyncio
import gzip
import json
import logging
import random
from dataclasses import dataclass
from time import time
from typing import Any

import httpx
from httpx_ws import WebSocketDisconnect, aconnect_ws
from wsproto.events import BytesMessage, TextMessage

from app.services.market_state_cache import MarketStateCache

log = logging.getLogger(__name__)


def _to_bingx_symbol(symbol: str) -> str:
    return symbol.replace("/", "-").replace("_", "-").upper()


@dataclass(slots=True)
class LiveIngestStats:
    connected: bool = False
    attempts_total: int = 0
    reconnects: int = 0
    disconnects_total: int = 0
    timeouts_total: int = 0
    messages_total: int = 0
    updates_total: int = 0
    errors_total: int = 0
    decode_failures_total: int = 0
    pongs_sent_total: int = 0
    subscriptions_sent_total: int = 0
    last_event_ts_ms: int = 0
    last_receive_ts_ms: int = 0
    cache_age_ms: int = -1


class LiveShadowIngestor:
    def __init__(
        self,
        *,
        cache: MarketStateCache,
        symbols: list[str],
        ws_url: str,
        reconnect_delay_seconds: float = 3.0,
        reconnect_max_delay_seconds: float = 20.0,
        reconnect_jitter_seconds: float = 0.75,
    ) -> None:
        self.cache = cache
        self.symbols = [s for s in symbols if s]
        self.ws_url = ws_url.strip()
        self.reconnect_delay_seconds = max(0.5, reconnect_delay_seconds)
        self.reconnect_max_delay_seconds = max(
            self.reconnect_delay_seconds,
            reconnect_max_delay_seconds,
        )
        self.reconnect_jitter_seconds = max(0.0, reconnect_jitter_seconds)
        self.stats = LiveIngestStats()

    async def run(self, *, stop_event: Any) -> None:
        if not self.ws_url or not self.symbols:
            log.info("Live shadow ingest disabled: ws_url or symbols are empty")
            return
        attempt_streak = 0
        async with httpx.AsyncClient(timeout=20.0) as client:
            while not stop_event.is_set():
                try:
                    self.stats.attempts_total += 1
                    self.stats.reconnects += 1
                    async with aconnect_ws(
                        self.ws_url,
                        client,
                        keepalive_ping_interval_seconds=20.0,
                        keepalive_ping_timeout_seconds=20.0,
                    ) as ws:
                        attempt_streak = 0
                        self.stats.connected = True
                        await self._subscribe(ws)
                        while not stop_event.is_set():
                            event = await ws.receive(timeout=5.0)
                            self.stats.messages_total += 1
                            payload = self._decode_event(event)
                            if payload is None:
                                self.stats.decode_failures_total += 1
                                continue
                            self.stats.last_receive_ts_ms = int(time() * 1000)
                            maybe_pong = self._extract_pong(payload)
                            if maybe_pong is not None:
                                await ws.send_json(maybe_pong)
                                self.stats.pongs_sent_total += 1
                                continue
                            if self._apply_payload(payload, receive_ts_ms=self.stats.last_receive_ts_ms):
                                self.stats.updates_total += 1
                                self.stats.cache_age_ms = max(
                                    0,
                                    self.stats.last_receive_ts_ms - self.stats.last_event_ts_ms,
                                )
                except TimeoutError:
                    # Normal idle wait branch.
                    self.stats.timeouts_total += 1
                    continue
                except WebSocketDisconnect:
                    self.stats.connected = False
                    self.stats.disconnects_total += 1
                    attempt_streak += 1
                    wait_s = self._next_reconnect_delay(attempt_streak)
                    await self._sleep(stop_event, wait_s)
                except Exception:
                    self.stats.connected = False
                    self.stats.errors_total += 1
                    attempt_streak += 1
                    log.exception("Live shadow ingest loop error")
                    wait_s = self._next_reconnect_delay(attempt_streak)
                    await self._sleep(stop_event, wait_s)

    async def _subscribe(self, ws: Any) -> None:
        for symbol in self.symbols:
            pair = _to_bingx_symbol(symbol)
            # BingX market channels are dataType based.
            await ws.send_json(
                {
                    "id": f"trade-{pair}",
                    "reqType": "sub",
                    "dataType": f"{pair}@trade",
                }
            )
            self.stats.subscriptions_sent_total += 1
            await ws.send_json(
                {
                    "id": f"depth-{pair}",
                    "reqType": "sub",
                    "dataType": f"{pair}@depth5",
                }
            )
            self.stats.subscriptions_sent_total += 1

    @staticmethod
    async def _sleep(stop_event: Any, seconds: float) -> None:
        started = time()
        while not stop_event.is_set() and (time() - started) < seconds:
            await asyncio.sleep(0.2)

    def _next_reconnect_delay(self, attempt_streak: int) -> float:
        base = self.reconnect_delay_seconds * (2 ** max(0, attempt_streak - 1))
        capped = min(base, self.reconnect_max_delay_seconds)
        jitter = random.uniform(0.0, self.reconnect_jitter_seconds)
        return capped + jitter

    @staticmethod
    def _decode_event(event: Any) -> dict[str, Any] | None:
        raw: bytes | str | None = None
        if isinstance(event, TextMessage):
            raw = event.data
        elif isinstance(event, BytesMessage):
            raw = event.data
        if raw is None:
            return None
        if isinstance(raw, bytes):
            try:
                raw = gzip.decompress(raw).decode("utf-8")
            except Exception:
                try:
                    raw = raw.decode("utf-8")
                except Exception:
                    return None
        try:
            payload = json.loads(raw)
        except Exception:
            return None
        if isinstance(payload, dict):
            return payload
        return None

    @staticmethod
    def _extract_pong(payload: dict[str, Any]) -> dict[str, Any] | None:
        if "ping" in payload:
            return {"pong": payload.get("ping")}
        if str(payload.get("op", "")).lower() == "ping":
            return {"op": "pong", "ts": payload.get("ts")}
        return None

    def _apply_payload(self, payload: dict[str, Any], *, receive_ts_ms: int) -> bool:
        data = payload.get("data")
        row: dict[str, Any] | None = None
        if isinstance(data, dict):
            row = data
        elif isinstance(data, list) and data and isinstance(data[0], dict):
            row = data[0]
        elif isinstance(payload, dict):
            row = payload
        if not row:
            return False
        symbol = str(row.get("symbol") or row.get("s") or row.get("S") or "")
        if not symbol:
            channel = str(payload.get("dataType", ""))
            if "@" in channel:
                symbol = channel.split("@", 1)[0]
        if not symbol:
            return False
        symbol = symbol.replace("-", "/").upper()
        event_ts_ms = int(
            row.get("E")
            or row.get("T")
            or row.get("ts")
            or row.get("t")
            or payload.get("ts")
            or receive_ts_ms
        )
        last_trade = _to_float(
            row.get("lastPrice")
            or row.get("last")
            or row.get("p")
            or row.get("price")
            or row.get("c")
        )
        best_bid = _to_float(row.get("bestBid") or row.get("bidPrice") or row.get("b") or row.get("bid"))
        best_ask = _to_float(row.get("bestAsk") or row.get("askPrice") or row.get("a") or row.get("ask"))
        self.cache.upsert(
            symbol=symbol,
            exchange_event_ts_ms=event_ts_ms,
            received_ts_ms=receive_ts_ms,
            last_trade=last_trade,
            best_bid=best_bid,
            best_ask=best_ask,
        )
        self.stats.last_event_ts_ms = event_ts_ms
        return True


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out <= 0:
        return None
    return out
