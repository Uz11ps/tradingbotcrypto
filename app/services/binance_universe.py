from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings

BINGX_SYMBOLS_URL = "https://open-api.bingx.com/openApi/spot/v1/common/symbols"
BINGX_TICKER_24H_URL = "https://open-api.bingx.com/openApi/spot/v1/ticker/24hr"
LEVERAGED_SUFFIXES = ("UP-USDT", "DOWN-USDT", "BULL-USDT", "BEAR-USDT")

log = logging.getLogger(__name__)


class BinanceUniverseError(RuntimeError):
    pass


def _resolve_ticker_url(market_type: str) -> str:
    normalized = (market_type or "spot").strip().lower()
    if normalized == "futures":
        return settings.bingx_futures_ticker_url
    return BINGX_TICKER_24H_URL


@dataclass(slots=True)
class UniverseSnapshot:
    symbols: list[str]
    volume_map: dict[str, float]


def _is_leveraged(symbol: str) -> bool:
    return symbol.endswith(LEVERAGED_SUFFIXES)


def _to_human_symbol(raw: str) -> str:
    if raw.endswith("-USDT"):
        return f"{raw[:-5]}/USDT"
    return raw


async def fetch_spot_symbols(*, quote_asset: str = "USDT") -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.get(
                BINGX_SYMBOLS_URL,
                params={"timestamp": int(time.time() * 1000)},
            )
            response.raise_for_status()
    except Exception as e:
        raise BinanceUniverseError(f"Failed to load BingX symbols: {e}") from e

    payload: dict[str, Any] = response.json()
    if int(payload.get("code", -1)) != 0:
        raise BinanceUniverseError(f"BingX symbols error: {payload}")
    symbols = (payload.get("data") or {}).get("symbols", [])
    if not isinstance(symbols, list):
        raise BinanceUniverseError("Invalid BingX symbols payload: symbols is not a list")

    result: list[str] = []
    for row in symbols:
        if not isinstance(row, dict):
            continue
        if int(row.get("status", 0)) != 0:
            continue
        if not bool(row.get("apiStateBuy", True)) and not bool(row.get("apiStateSell", True)):
            continue
        raw_symbol = str(row.get("symbol", ""))
        if not raw_symbol:
            continue
        if not raw_symbol.endswith(f"-{quote_asset.upper()}"):
            continue
        if _is_leveraged(raw_symbol):
            continue
        result.append(_to_human_symbol(raw_symbol))

    if not result:
        raise BinanceUniverseError("No tradable symbols found in BingX universe")
    return sorted(set(result))


async def fetch_top_symbols_by_volume(
    *,
    quote_asset: str = "USDT",
    top_n: int = 300,
    min_quote_volume_24h: float = 500_000.0,
    market_type: str = "spot",
) -> UniverseSnapshot:
    """One ticker call -> top-N pairs by 24h quoteVolume.

    Returns both the ranked symbol list and volume map (reusable by workers).
    """
    try:
        ticker_url = _resolve_ticker_url(market_type)
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                ticker_url,
                params={"timestamp": int(time.time() * 1000)},
            )
            response.raise_for_status()
    except Exception as e:
        raise BinanceUniverseError(f"Failed to fetch BingX ticker/24hr: {e}") from e

    payload: dict[str, Any] = response.json()
    if int(payload.get("code", -1)) != 0:
        raise BinanceUniverseError(f"BingX ticker/24hr error: {payload}")
    tickers: list[dict[str, Any]] = payload.get("data") or []

    suffix = f"-{quote_asset.upper()}"
    ranked: list[tuple[str, float]] = []
    for t in tickers:
        raw = str(t.get("symbol", ""))
        if not raw.endswith(suffix):
            continue
        if _is_leveraged(raw):
            continue
        vol = float(t.get("quoteVolume", 0.0) or 0.0)
        if vol < min_quote_volume_24h:
            continue
        ranked.append((_to_human_symbol(raw), vol))

    ranked.sort(key=lambda x: x[1], reverse=True)
    selected = ranked[:top_n]

    symbols = [s for s, _ in selected]
    volume_map = {s: v for s, v in selected}
    log.info(
        "Universe (%s): %d pairs above $%.0f vol, selected top %d",
        market_type,
        len(ranked),
        min_quote_volume_24h,
        len(symbols),
    )
    return UniverseSnapshot(symbols=symbols, volume_map=volume_map)

