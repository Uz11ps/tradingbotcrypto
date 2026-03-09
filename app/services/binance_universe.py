from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

BINANCE_EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"
BINANCE_TICKER_24H_URL = "https://api.binance.com/api/v3/ticker/24hr"
LEVERAGED_SUFFIXES = ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")

log = logging.getLogger(__name__)


class BinanceUniverseError(RuntimeError):
    pass


@dataclass(slots=True)
class UniverseSnapshot:
    symbols: list[str]
    volume_map: dict[str, float]


def _is_leveraged(symbol: str) -> bool:
    return symbol.endswith(LEVERAGED_SUFFIXES)


def _to_human_symbol(raw: str) -> str:
    if raw.endswith("USDT"):
        return f"{raw[:-4]}/USDT"
    return raw


async def fetch_spot_symbols(*, quote_asset: str = "USDT") -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.get(BINANCE_EXCHANGE_INFO_URL)
            response.raise_for_status()
    except Exception as e:
        raise BinanceUniverseError(f"Failed to load exchangeInfo: {e}") from e

    payload: dict[str, Any] = response.json()
    symbols = payload.get("symbols", [])
    if not isinstance(symbols, list):
        raise BinanceUniverseError("Invalid exchangeInfo payload: symbols is not a list")

    result: list[str] = []
    for row in symbols:
        if not isinstance(row, dict):
            continue
        if row.get("status") != "TRADING":
            continue
        if row.get("isSpotTradingAllowed") is False:
            continue
        raw_symbol = str(row.get("symbol", ""))
        if not raw_symbol:
            continue
        if str(row.get("quoteAsset", "")).upper() != quote_asset.upper():
            continue
        if _is_leveraged(raw_symbol):
            continue
        result.append(_to_human_symbol(raw_symbol))

    if not result:
        raise BinanceUniverseError("No tradable symbols found in Binance universe")
    return sorted(set(result))


async def fetch_top_symbols_by_volume(
    *,
    quote_asset: str = "USDT",
    top_n: int = 300,
    min_quote_volume_24h: float = 500_000.0,
) -> UniverseSnapshot:
    """One /ticker/24hr call → top-N USDT pairs by 24h quoteVolume.

    Returns both the ranked symbol list and volume map (reusable by workers).
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(BINANCE_TICKER_24H_URL)
            response.raise_for_status()
    except Exception as e:
        raise BinanceUniverseError(f"Failed to fetch ticker/24hr: {e}") from e

    tickers: list[dict[str, Any]] = response.json()

    suffix = quote_asset.upper()
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
        "Universe: %d pairs above $%.0f vol, selected top %d",
        len(ranked),
        min_quote_volume_24h,
        len(symbols),
    )
    return UniverseSnapshot(symbols=symbols, volume_map=volume_map)

