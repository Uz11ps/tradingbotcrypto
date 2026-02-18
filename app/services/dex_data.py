from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

DEX_SEARCH_URL = "https://api.dexscreener.com/latest/dex/search"
STABLE_QUOTES = {"USDT", "USDC", "DAI", "BUSD"}


class DexDataError(RuntimeError):
    pass


def _normalize_symbol(symbol: str) -> str:
    return symbol.split("/")[0].upper()


def _choose_pair(pairs: list[dict[str, Any]]) -> dict[str, Any] | None:
    filtered = [
        p
        for p in pairs
        if str(p.get("quoteToken", {}).get("symbol", "")).upper() in STABLE_QUOTES
        and p.get("priceUsd")
    ]
    if not filtered:
        filtered = [p for p in pairs if p.get("priceUsd")]
    if not filtered:
        return None
    return max(filtered, key=lambda p: float(p.get("liquidity", {}).get("usd", 0.0) or 0.0))


async def fetch_dex_snapshot(symbol: str) -> dict[str, Any]:
    query = _normalize_symbol(symbol)
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(DEX_SEARCH_URL, params={"q": query})
        response.raise_for_status()
        payload = response.json()

    pairs = payload.get("pairs") or []
    if not pairs:
        raise DexDataError("DEX pairs not found")

    pair = _choose_pair(pairs)
    if not pair:
        raise DexDataError("DEX pair with price not found")

    price = float(pair.get("priceUsd") or 0.0)
    volume_24h = float((pair.get("volume") or {}).get("h24") or 0.0)
    liquidity = float((pair.get("liquidity") or {}).get("usd") or 0.0)
    price_change_1h = float((pair.get("priceChange") or {}).get("h1") or 0.0)

    return {
        "generated_at": datetime.now(tz=UTC),
        "symbol": symbol,
        "price": price,
        "volume_24h": volume_24h,
        "liquidity_usd": liquidity,
        "price_change_1h_pct": price_change_1h,
        "dex_id": pair.get("dexId"),
        "chain_id": pair.get("chainId"),
        "pair_address": pair.get("pairAddress"),
    }

