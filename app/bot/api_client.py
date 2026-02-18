from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings


class ApiClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(base_url=settings.api_public_base_url, timeout=10.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_signals(
        self, *, symbol: str | None, timeframe: str | None, limit: int = 5
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        if timeframe:
            params["timeframe"] = timeframe
        r = await self._client.get("/signals", params=params)
        r.raise_for_status()
        return r.json()

    async def get_analytics(self, *, symbol: str, timeframe: str) -> dict[str, Any]:
        r = await self._client.get("/analytics", params={"symbol": symbol, "timeframe": timeframe})
        r.raise_for_status()
        return r.json()

    async def get_live_signal(self, *, symbol: str, timeframe: str) -> dict[str, Any]:
        r = await self._client.get(
            "/signals/live",
            params={"symbol": symbol, "timeframe": timeframe, "persist": "true", "source": "hybrid"},
        )
        r.raise_for_status()
        return r.json()

    async def get_stats_overview(self) -> dict[str, Any]:
        r = await self._client.get("/stats/overview")
        r.raise_for_status()
        return r.json()

    async def get_market_overview(self, *, symbol: str, timeframe: str) -> dict[str, Any]:
        r = await self._client.get("/market/overview", params={"symbol": symbol, "timeframe": timeframe})
        r.raise_for_status()
        return r.json()

    async def get_performance(self, *, symbol: str | None, timeframe: str | None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        if timeframe:
            params["timeframe"] = timeframe
        r = await self._client.get("/stats/performance", params=params)
        r.raise_for_status()
        return r.json()

    async def get_news_sentiment(self, *, symbol: str) -> dict[str, Any]:
        r = await self._client.get("/news/sentiment", params={"symbol": symbol})
        r.raise_for_status()
        return r.json()

    async def list_subscriptions(self, *, chat_id: int) -> list[dict[str, Any]]:
        r = await self._client.get("/subscriptions", params={"chat_id": chat_id})
        r.raise_for_status()
        return r.json()

    async def add_subscription(self, *, chat_id: int, symbol: str, timeframe: str) -> dict[str, Any]:
        r = await self._client.post(
            "/subscriptions",
            json={"chat_id": chat_id, "symbol": symbol, "timeframe": timeframe},
        )
        r.raise_for_status()
        return r.json()

    async def remove_subscription(self, *, chat_id: int, symbol: str, timeframe: str) -> dict[str, Any]:
        r = await self._client.request(
            "DELETE",
            "/subscriptions",
            json={"chat_id": chat_id, "symbol": symbol, "timeframe": timeframe},
        )
        r.raise_for_status()
        return r.json()

    async def get_feed_movers(
        self,
        *,
        universe: int = 100,
        limit: int = 20,
        min_change_pct: float = 2.5,
    ) -> dict[str, Any]:
        r = await self._client.get(
            "/feed/movers",
            params={"universe": universe, "limit": limit, "min_change_pct": min_change_pct},
        )
        r.raise_for_status()
        return r.json()

