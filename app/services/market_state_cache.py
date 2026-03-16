from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from time import time


@dataclass(slots=True)
class MarketPricePoint:
    exchange_event_ts_ms: int
    received_ts_ms: int
    last_trade: float | None = None
    best_bid: float | None = None
    best_ask: float | None = None

    @property
    def mid_price(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        if self.best_bid <= 0 or self.best_ask <= 0:
            return None
        return (self.best_bid + self.best_ask) / 2.0

    @property
    def current_price(self) -> float | None:
        mid = self.mid_price
        if mid is not None:
            return mid
        if self.last_trade is not None and self.last_trade > 0:
            return self.last_trade
        return None

    @property
    def price_source(self) -> str | None:
        if self.mid_price is not None:
            return "live_mid"
        if self.last_trade is not None and self.last_trade > 0:
            return "live_trade"
        return None


@dataclass(slots=True)
class MarketStateSnapshot:
    symbol: str
    point: MarketPricePoint
    age_ms: int
    source: str


class MarketStateCache:
    """Bounded in-memory cache for rolling live price windows."""

    def __init__(
        self,
        *,
        ttl_seconds: int = 180,
        max_points_per_symbol: int = 1200,
        max_symbols: int = 2000,
    ) -> None:
        self.ttl_seconds = max(1, int(ttl_seconds))
        self.max_points_per_symbol = max(10, int(max_points_per_symbol))
        self.max_symbols = max(1, int(max_symbols))
        self._points: dict[str, deque[MarketPricePoint]] = {}
        self._last_touch_monotonic: dict[str, float] = {}

    def upsert(
        self,
        *,
        symbol: str,
        exchange_event_ts_ms: int,
        received_ts_ms: int,
        last_trade: float | None = None,
        best_bid: float | None = None,
        best_ask: float | None = None,
    ) -> None:
        if not symbol:
            return
        point = MarketPricePoint(
            exchange_event_ts_ms=exchange_event_ts_ms,
            received_ts_ms=received_ts_ms,
            last_trade=last_trade,
            best_bid=best_bid,
            best_ask=best_ask,
        )
        if point.current_price is None:
            return
        self._evict_symbols_if_needed()
        buf = self._points.get(symbol)
        if buf is None:
            buf = deque(maxlen=self.max_points_per_symbol)
            self._points[symbol] = buf
        buf.append(point)
        self._last_touch_monotonic[symbol] = time()
        self._cleanup_symbol(symbol=symbol, now_ms=received_ts_ms)

    def get_latest(self, *, symbol: str, now_ms: int | None = None) -> MarketStateSnapshot | None:
        buf = self._points.get(symbol)
        if not buf:
            return None
        point = buf[-1]
        ref_ms = now_ms if now_ms is not None else point.received_ts_ms
        age_ms = max(0, ref_ms - point.received_ts_ms)
        source = point.price_source
        if source is None:
            return None
        return MarketStateSnapshot(symbol=symbol, point=point, age_ms=age_ms, source=source)

    def get_baseline_price(
        self,
        *,
        symbol: str,
        window_seconds: int,
        now_ms: int,
    ) -> float | None:
        if window_seconds <= 0:
            return None
        buf = self._points.get(symbol)
        if not buf:
            return None
        min_ts = now_ms - (window_seconds * 1000)
        for point in buf:
            if point.received_ts_ms >= min_ts:
                return point.current_price
        return None

    def cleanup(self, *, now_ms: int) -> None:
        stale_symbols: list[str] = []
        for symbol in list(self._points.keys()):
            self._cleanup_symbol(symbol=symbol, now_ms=now_ms)
            if not self._points.get(symbol):
                stale_symbols.append(symbol)
        for symbol in stale_symbols:
            self._points.pop(symbol, None)
            self._last_touch_monotonic.pop(symbol, None)

    def symbols_count(self) -> int:
        return len(self._points)

    def points_count(self) -> int:
        return sum(len(buf) for buf in self._points.values())

    def _cleanup_symbol(self, *, symbol: str, now_ms: int) -> None:
        buf = self._points.get(symbol)
        if not buf:
            return
        min_ts = now_ms - (self.ttl_seconds * 1000)
        while buf and buf[0].received_ts_ms < min_ts:
            buf.popleft()

    def _evict_symbols_if_needed(self) -> None:
        if len(self._points) < self.max_symbols:
            return
        # Remove least recently touched symbol.
        oldest_symbol = min(
            self._last_touch_monotonic.items(),
            key=lambda kv: kv[1],
        )[0]
        self._points.pop(oldest_symbol, None)
        self._last_touch_monotonic.pop(oldest_symbol, None)
