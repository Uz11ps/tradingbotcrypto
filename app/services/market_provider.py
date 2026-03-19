from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.services.binance_candles import CandleSnapshot, KlineBar
from app.services.binance_candles import build_snapshot as fetch_candle_snapshot
from app.services.binance_candles import fetch_live_price as fetch_candle_live_price
from app.services.binance_candles import fetch_recent_bars as fetch_candle_recent_bars
from app.services.binance_universe import UniverseSnapshot
from app.services.binance_universe import fetch_top_symbols_by_volume as fetch_universe_snapshot
from app.services.signal_presentation import normalize_market_type


@dataclass(frozen=True, slots=True)
class ResolvedMarketRoute:
    requested_market_type: str
    market_type: str
    provider_name: str
    enabled: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class MarketPolicyResolution:
    requested_market_type: str
    normalized_market_type: str
    enabled_routes: tuple[ResolvedMarketRoute, ...]
    skipped_routes: tuple[ResolvedMarketRoute, ...]


class MarketDataProvider(Protocol):
    name: str
    market_type: str

    async def fetch_universe(
        self,
        *,
        quote_asset: str,
        top_n: int,
        min_quote_volume_24h: float,
    ) -> UniverseSnapshot: ...

    async def build_snapshot(
        self,
        *,
        symbol: str,
        timeframe: str,
        volume_avg_window: int,
        quote_volume_24h: float | None = None,
    ) -> CandleSnapshot: ...

    async def fetch_recent_bars(
        self,
        *,
        symbol: str,
        timeframe: str,
        limit: int = 120,
    ) -> list[KlineBar]: ...

    async def fetch_live_price(
        self,
        *,
        symbol: str,
        cache_ttl_seconds: float,
    ) -> float: ...


class SpotMarketProvider:
    name = "bingx_spot"
    market_type = "spot"

    async def fetch_universe(
        self,
        *,
        quote_asset: str,
        top_n: int,
        min_quote_volume_24h: float,
    ) -> UniverseSnapshot:
        return await fetch_universe_snapshot(
            quote_asset=quote_asset,
            top_n=top_n,
            min_quote_volume_24h=min_quote_volume_24h,
            market_type=self.market_type,
        )

    async def build_snapshot(
        self,
        *,
        symbol: str,
        timeframe: str,
        volume_avg_window: int,
        quote_volume_24h: float | None = None,
    ) -> CandleSnapshot:
        return await fetch_candle_snapshot(
            symbol=symbol,
            timeframe=timeframe,
            volume_avg_window=volume_avg_window,
            quote_volume_24h=quote_volume_24h,
            market_type=self.market_type,
        )

    async def fetch_recent_bars(
        self,
        *,
        symbol: str,
        timeframe: str,
        limit: int = 120,
    ) -> list[KlineBar]:
        return await fetch_candle_recent_bars(
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
            market_type=self.market_type,
        )

    async def fetch_live_price(
        self,
        *,
        symbol: str,
        cache_ttl_seconds: float,
    ) -> float:
        return await fetch_candle_live_price(
            symbol=symbol,
            cache_ttl_seconds=cache_ttl_seconds,
            market_type=self.market_type,
        )


class SpotBackedFuturesMarketProvider(SpotMarketProvider):
    name = "bingx_futures"
    market_type = "futures"


class MarketProviderRouter:
    """Resolves market policy into concrete provider routes."""

    def __init__(self, *, futures_adapter_enabled: bool) -> None:
        self._futures_adapter_enabled = bool(futures_adapter_enabled)
        self._spot = SpotMarketProvider()
        self._futures_adapter = SpotBackedFuturesMarketProvider()

    @property
    def futures_adapter_enabled(self) -> bool:
        return self._futures_adapter_enabled

    def primary_provider(self) -> MarketDataProvider:
        # Universe source remains spot-backed in current rollout.
        return self._spot

    def resolve(self, requested_market_type: str | None) -> MarketPolicyResolution:
        normalized = normalize_market_type(requested_market_type)
        requested = (requested_market_type or "both").strip().lower() or "both"
        requested_types: tuple[str, ...]
        if normalized == "spot":
            requested_types = ("spot",)
        elif normalized == "futures":
            requested_types = ("futures",)
        else:
            requested_types = ("spot", "futures")

        enabled_routes: list[ResolvedMarketRoute] = []
        skipped_routes: list[ResolvedMarketRoute] = []
        for market_type in requested_types:
            if market_type == "spot":
                enabled_routes.append(
                    ResolvedMarketRoute(
                        requested_market_type=requested,
                        market_type="spot",
                        provider_name=self._spot.name,
                        enabled=True,
                        reason=None,
                    )
                )
                continue
            if self._futures_adapter_enabled:
                enabled_routes.append(
                    ResolvedMarketRoute(
                        requested_market_type=requested,
                        market_type="futures",
                        provider_name=self._futures_adapter.name,
                        enabled=True,
                        reason="futures_route_live_source",
                    )
                )
            else:
                skipped_routes.append(
                    ResolvedMarketRoute(
                        requested_market_type=requested,
                        market_type="futures",
                        provider_name=self._futures_adapter.name,
                        enabled=False,
                        reason="futures_adapter_disabled",
                    )
                )

        return MarketPolicyResolution(
            requested_market_type=requested,
            normalized_market_type=normalized,
            enabled_routes=tuple(enabled_routes),
            skipped_routes=tuple(skipped_routes),
        )

    def get_provider(self, route: ResolvedMarketRoute) -> MarketDataProvider:
        if route.market_type == "spot":
            return self._spot
        return self._futures_adapter

