from __future__ import annotations

from typing import Any

import httpx

BINANCE_EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"
LEVERAGED_SUFFIXES = ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")


class BinanceUniverseError(RuntimeError):
    pass


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

