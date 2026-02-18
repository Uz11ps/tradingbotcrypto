from __future__ import annotations

import asyncio
import logging
import random
import time

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


async def _fetch_feed_movers(client: httpx.AsyncClient) -> list[dict[str, object]]:
    r = await client.get(
        "/feed/movers",
        params={
            "universe": settings.feed_universe_size,
            "limit": settings.feed_movers_limit,
            "min_change_pct": settings.feed_min_change_pct,
        },
    )
    r.raise_for_status()
    payload = r.json()
    return payload.get("movers", [])


async def _save_feed_signal(client: httpx.AsyncClient, mover: dict[str, object]) -> None:
    r = await client.post(
        "/signals",
        json={
            "symbol": mover["symbol"],
            "timeframe": "1h",
            "direction": mover["direction"],
            "strength": mover["strength"],
            "action": mover["action"],
            "source": "cex",
            "price": mover["last_price"],
            "volume": mover["quote_volume"],
            "reason": f"Feed mover: 24h change {mover['change_24h_pct']:+.2f}%",
        },
    )
    r.raise_for_status()


def _fmt_feed_msg(mover: dict[str, object]) -> str:
    arrow = "🟢" if mover["direction"] == "up" else "🔴"
    return (
        f"FEED ALERT {arrow}\n"
        f"{mover['symbol']} | change 24h: {mover['change_24h_pct']:+.2f}%\n"
        f"Price: {mover['last_price']:.6f}\n"
        f"Quote volume: {mover['quote_volume']:.2f}\n"
        f"Strength: {mover['strength']:.2f}\n"
        f"Action: {mover['action']}"
    )


async def main() -> None:
    setup_logging(settings.log_level)
    if not settings.api_public_base_url:
        raise RuntimeError("API_PUBLIC_BASE_URL is empty")

    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is empty")

    bot = Bot(token=settings.telegram_bot_token)
    client = httpx.AsyncClient(base_url=settings.api_public_base_url, timeout=15.0)
    feed_sent_at: dict[str, float] = {}

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

            # Лента: скан широкого пула монет и отправка только свежих сильных движений.
            try:
                movers = await _fetch_feed_movers(client)
            except Exception:
                log.exception("Feed movers fetch failed")
                movers = []

            now = time.time()
            for mover in movers[:5]:
                symbol = str(mover["symbol"])
                strength = float(mover.get("strength", 0.0) or 0.0)
                if strength < 0.58:
                    continue
                last_sent = feed_sent_at.get(symbol, 0.0)
                if now - last_sent < settings.worker_feed_cooldown_seconds:
                    continue
                feed_sent_at[symbol] = now

                try:
                    await _save_feed_signal(client, mover)
                except Exception:
                    log.exception("Failed to save feed signal for %s", symbol)

                if settings.telegram_signals_chat_id:
                    try:
                        await bot.send_message(settings.telegram_signals_chat_id, _fmt_feed_msg(mover))
                    except Exception:
                        log.exception("Failed to send feed alert for %s", symbol)

            await _tune_ai(client)

            await asyncio.sleep(settings.worker_interval_seconds)
    finally:
        await client.aclose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

