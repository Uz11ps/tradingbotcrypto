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
        chat_id: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"universe": universe, "limit": limit, "min_change_pct": min_change_pct}
        if chat_id is not None:
            params["chat_id"] = chat_id
        r = await self._client.get(
            "/feed/movers",
            params=params,
        )
        r.raise_for_status()
        return r.json()

    async def get_user_settings(self, *, chat_id: int) -> dict[str, Any]:
        r = await self._client.get("/user-settings", params={"chat_id": chat_id})
        r.raise_for_status()
        return r.json()

    async def update_user_settings(
        self,
        *,
        chat_id: int,
        lower_rsi: float | None = None,
        upper_rsi: float | None = None,
        active_timeframes: list[str] | None = None,
        min_price_move_pct: float | None = None,
        min_quote_volume: float | None = None,
        signal_side_mode: str | None = None,
        market_type: str | None = None,
        feed_mode_enabled: bool | None = None,
        strategy_mode_enabled: bool | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if lower_rsi is not None:
            payload["lower_rsi"] = lower_rsi
        if upper_rsi is not None:
            payload["upper_rsi"] = upper_rsi
        if active_timeframes is not None:
            payload["active_timeframes"] = active_timeframes
        if min_price_move_pct is not None:
            payload["min_price_move_pct"] = min_price_move_pct
        if min_quote_volume is not None:
            payload["min_quote_volume"] = min_quote_volume
        if signal_side_mode is not None:
            payload["signal_side_mode"] = signal_side_mode
        if market_type is not None:
            payload["market_type"] = market_type
        if feed_mode_enabled is not None:
            payload["feed_mode_enabled"] = feed_mode_enabled
        if strategy_mode_enabled is not None:
            payload["strategy_mode_enabled"] = strategy_mode_enabled
        r = await self._client.post("/user-settings", params={"chat_id": chat_id}, json=payload)
        r.raise_for_status()
        return r.json()

    async def post_raw_candidate(
        self,
        *,
        chat_id: int | None,
        symbol: str,
        timeframe: str,
        market_type: str,
        mode: str,
        decision: str,
        reject_reason: str | None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        r = await self._client.post(
            "/telemetry/raw-candidates",
            json={
                "chat_id": chat_id,
                "symbol": symbol,
                "timeframe": timeframe,
                "market_type": market_type,
                "mode": mode,
                "decision": decision,
                "reject_reason": reject_reason,
                "payload": payload,
            },
        )
        r.raise_for_status()

    async def post_scan_log(
        self,
        *,
        chat_id: int | None,
        symbol: str,
        timeframe: str,
        market_type: str,
        mode: str,
        event: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        r = await self._client.post(
            "/telemetry/scan-logs",
            json={
                "chat_id": chat_id,
                "symbol": symbol,
                "timeframe": timeframe,
                "market_type": market_type,
                "mode": mode,
                "event": event,
                "details": details,
            },
        )
        r.raise_for_status()

