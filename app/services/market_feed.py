from __future__ import annotations

from datetime import UTC, datetime
from math import log10
from typing import Any

import httpx

BINANCE_TICKER_24H_URL = "https://api.binance.com/api/v3/ticker/24hr"
LEVERAGED_SUFFIXES = ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")


class MarketFeedError(RuntimeError):
    pass


def _to_human_symbol(raw: str) -> str:
    if raw.endswith("USDT"):
        return f"{raw[:-4]}/USDT"
    return raw


def _is_spot_usdt_symbol(raw: str) -> bool:
    return raw.endswith("USDT") and not raw.endswith(LEVERAGED_SUFFIXES)


def _strength(price_change_pct: float, quote_volume: float) -> float:
    # Даем приоритет резкому движению и подкрепляем ликвидностью.
    price_score = min(1.0, abs(price_change_pct) / 12.0)
    volume_score = min(1.0, max(0.0, log10(max(1.0, quote_volume)) / 8.0))
    return round((price_score * 0.75) + (volume_score * 0.25), 4)


async def fetch_top_movers(
    *,
    universe_size: int = 100,
    movers_limit: int = 15,
    min_abs_change_pct: float = 2.5,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=12.0) as client:
        response = await client.get(BINANCE_TICKER_24H_URL)
        response.raise_for_status()
        payload: list[dict[str, Any]] = response.json()

    if not payload:
        raise MarketFeedError("Ticker data is empty")

    filtered = [item for item in payload if _is_spot_usdt_symbol(str(item.get("symbol", "")))]
    ranked_by_liquidity = sorted(
        filtered,
        key=lambda item: float(item.get("quoteVolume", 0.0) or 0.0),
        reverse=True,
    )
    universe = ranked_by_liquidity[: max(10, min(universe_size, 250))]

    movers: list[dict[str, Any]] = []
    for item in universe:
        change_pct = float(item.get("priceChangePercent", 0.0) or 0.0)
        if abs(change_pct) < min_abs_change_pct:
            continue
        quote_volume = float(item.get("quoteVolume", 0.0) or 0.0)
        strength = _strength(change_pct, quote_volume)
        action = "entry" if strength >= 0.72 else "watch"
        movers.append(
            {
                "symbol": _to_human_symbol(str(item.get("symbol", ""))),
                "direction": "up" if change_pct >= 0 else "down",
                "change_24h_pct": change_pct,
                "last_price": float(item.get("lastPrice", 0.0) or 0.0),
                "quote_volume": quote_volume,
                "trades_count": int(item.get("count", 0) or 0),
                "strength": strength,
                "action": action,
            }
        )

    movers.sort(key=lambda row: (row["strength"], abs(row["change_24h_pct"])), reverse=True)
    top_movers = movers[: max(1, min(movers_limit, 50))]

    return {
        "generated_at": datetime.now(tz=UTC),
        "universe_size": len(universe),
        "movers": top_movers,
    }

