from __future__ import annotations

import asyncio
import logging
import random

import httpx
from aiogram import Bot

from app.core.config import settings
from app.core.logging import setup_logging

log = logging.getLogger("workers.mock_signal_worker")

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
TIMEFRAMES = ["15m", "1h", "4h", "1d"]


def _fmt_signal_msg(s: dict[str, object]) -> str:
    return (
        "SIGNAL\n"
        f"Asset: {s['symbol']} ({s['timeframe']})\n"
        f"Dir: {s['direction']} | Trend: {s['trend']}\n"
        f"Strength: {s['strength']}\n"
        f"Action: {s['action']}\n"
        f"Price: {s['price']:.4f} ({s['price_change_pct']:+.2f}%)\n"
        f"Volume: {s['volume']:.2f} ({s['volume_change_pct']:+.2f}%)\n"
        f"Summary: {s['summary']}"
    )


async def _list_subscriptions(client: httpx.AsyncClient) -> list[dict[str, object]]:
    r = await client.get("/subscriptions")
    r.raise_for_status()
    return r.json()


async def _tune_ai(client: httpx.AsyncClient) -> None:
    try:
        await client.post("/ai/tune")
    except Exception:
        log.exception("AI tune failed")


async def _update_performance(client: httpx.AsyncClient, symbol: str, timeframe: str) -> None:
    try:
        await client.get("/stats/performance", params={"symbol": symbol, "timeframe": timeframe})
    except Exception:
        log.exception("Performance refresh failed")


def _fmt_log_msg(s: dict[str, object]) -> str:
    return (
        f"{s['symbol']} {s['timeframe']} {s['direction']} "
        f"strength={s['strength']} action={s['action']}"
    )


async def _generate_live_signal_for_pair(
    client: httpx.AsyncClient,
    symbol: str,
    timeframe: str,
) -> dict[str, object]:
    r = await client.get(
        "/signals/live",
        params={
            "symbol": symbol,
            "timeframe": timeframe,
            "persist": "true",
            "source": "hybrid",
        },
    )
    r.raise_for_status()
    return r.json()


async def main() -> None:
    setup_logging(settings.log_level)
    if not settings.api_public_base_url:
        raise RuntimeError("API_PUBLIC_BASE_URL is empty")

    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is empty")

    bot = Bot(token=settings.telegram_bot_token)
    client = httpx.AsyncClient(base_url=settings.api_public_base_url, timeout=15.0)

    try:
        while True:
            subscriptions = await _list_subscriptions(client)
            pairs = {(str(s["symbol"]), str(s["timeframe"])) for s in subscriptions}
            if not pairs:
                pairs = {(random.choice(SYMBOLS), random.choice(TIMEFRAMES))}

            for symbol, timeframe in pairs:
                try:
                    signal = await _generate_live_signal_for_pair(client, symbol, timeframe)
                except Exception:
                    log.exception("Signal generation failed for %s %s", symbol, timeframe)
                    continue

                if subscriptions:
                    targets = [
                        int(s["chat_id"])
                        for s in subscriptions
                        if s["symbol"] == symbol and s["timeframe"] == timeframe and s["is_active"]
                    ]
                else:
                    targets = [settings.telegram_signals_chat_id] if settings.telegram_signals_chat_id else []

                sent = 0
                for chat_id in targets:
                    if not chat_id:
                        continue
                    try:
                        await bot.send_message(chat_id, _fmt_signal_msg(signal))
                        sent += 1
                    except Exception:
                        log.exception("Failed to send signal to chat_id=%s", chat_id)

                await _update_performance(client, symbol, timeframe)
                log.info("Signal generated (%s), delivered=%s", _fmt_log_msg(signal), sent)

            await _tune_ai(client)

            await asyncio.sleep(settings.worker_interval_seconds)
    finally:
        await client.aclose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

