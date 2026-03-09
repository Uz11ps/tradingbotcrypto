from __future__ import annotations

import asyncio
import logging
import random

import httpx
from aiogram import Bot

from app.core.config import settings
from app.core.logging import setup_logging
from app.services.binance_candles import (
    BinanceCandlesError,
    build_snapshot,
    fetch_quote_volume_24h_map,
)
from app.services.binance_universe import BinanceUniverseError, fetch_spot_symbols
from app.services.feed_formatter import format_signal_card
from app.services.rsi_engine import compute_rsi, evaluate_rsi_signal, validate_candidate_filters
from app.services.signal_filters import SignalFilterEngine

log = logging.getLogger("workers.mock_signal_worker")

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
TIMEFRAMES = ["15m", "1h", "4h", "1d"]


def _select_shard_symbols(symbols: list[str], *, shard_index: int, shard_count: int) -> list[str]:
    ordered = sorted(symbols)
    return [symbol for i, symbol in enumerate(ordered) if i % shard_count == shard_index]


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
            "timeframe": mover.get("timeframe", "1h"),
            "direction": mover["direction"],
            "strength": float(mover.get("strength", 0.0) or 0.0),
            "action": mover.get("action", "watch"),
            "source": str(mover.get("source", "cex")),
            "signal_type": mover.get("signal_type"),
            "trigger_source": mover.get("trigger_source"),
            "rsi_value": mover.get("rsi_value"),
            "prev_price": mover.get("prev_price"),
            "price": mover["last_price"],
            "volume": mover.get("quote_volume"),
            "reason": str(mover.get("reason", "feed mover")),
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


async def _load_effective_settings(client: httpx.AsyncClient, *, chat_id: int) -> dict[str, object]:
    r = await client.get("/user-settings", params={"chat_id": chat_id})
    r.raise_for_status()
    return r.json()


async def _list_signal_chats(client: httpx.AsyncClient) -> list[int]:
    r = await client.get("/user-settings/chats")
    r.raise_for_status()
    raw = r.json()
    return [int(x) for x in raw if int(x)]


async def _run_legacy_mode(
    client: httpx.AsyncClient,
    bot: Bot,
) -> None:
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

    try:
        movers = await _fetch_feed_movers(client)
    except Exception:
        log.exception("Feed movers fetch failed")
        movers = []

    for mover in movers[:5]:
        symbol = str(mover.get("symbol", ""))
        signal_type = str(mover.get("signal_type", "pump"))
        direction = "up" if signal_type == "pump" else "down"
        current_price = float(mover.get("current_price", mover.get("last_price", 0.0)) or 0.0)
        prev_price = float(mover.get("prev_price", current_price) or current_price)
        change_pct = float(mover.get("change_pct", mover.get("change_24h_pct", 0.0)) or 0.0)
        try:
            await _save_feed_signal(
                client,
                {
                    "symbol": symbol,
                    "timeframe": "1h",
                    "direction": direction,
                    "strength": 0.7,
                    "action": "watch",
                    "source": "cex",
                    "signal_type": signal_type,
                    "trigger_source": "legacy_feed",
                    "prev_price": prev_price,
                    "last_price": current_price,
                    "quote_volume": None,
                    "reason": f"Legacy feed change {change_pct:+.2f}%",
                    "change_24h_pct": change_pct,
                },
            )
        except Exception:
            log.exception("Failed to save feed signal for %s", symbol)

        if settings.telegram_signals_chat_id:
            try:
                await bot.send_message(
                    settings.telegram_signals_chat_id,
                    _fmt_feed_msg(
                        {
                            "symbol": symbol,
                            "direction": direction,
                            "change_24h_pct": change_pct,
                            "last_price": current_price,
                            "quote_volume": 0.0,
                            "strength": 0.7,
                            "action": "watch",
                        }
                    ),
                )
            except Exception:
                log.exception("Failed to send feed alert for %s", symbol)


async def _run_rsi_mode(
    client: httpx.AsyncClient,
    bot: Bot,
    filters: SignalFilterEngine,
    shard_index: int,
    shard_count: int,
) -> None:
    try:
        symbols = await fetch_spot_symbols(quote_asset=settings.binance_quote_asset)
    except (BinanceUniverseError, Exception):
        log.exception("Failed to load universe/settings in RSI mode")
        return

    try:
        chat_ids = await _list_signal_chats(client)
    except Exception:
        log.exception("Failed to load chat list in RSI mode")
        chat_ids = []
    if not chat_ids and settings.telegram_signals_chat_id:
        chat_ids = [settings.telegram_signals_chat_id]
    if not chat_ids:
        log.info("RSI mode: no target chats registered yet")
        return

    if not symbols:
        log.warning("RSI mode: empty symbols list")
        return

    batch_size = max(20, min(settings.feed_universe_size, len(symbols)))
    selected = sorted(symbols)[:batch_size]
    shard_symbols = _select_shard_symbols(
        selected,
        shard_index=shard_index,
        shard_count=shard_count,
    )
    if not shard_symbols:
        log.info("RSI mode: shard has no symbols (index=%s count=%s)", shard_index, shard_count)
        return
    try:
        volume_map = await fetch_quote_volume_24h_map(symbols=shard_symbols)
    except BinanceCandlesError:
        log.exception("Failed to fetch shared 24h volume map")
        volume_map = {}

    for chat_id in chat_ids:
        try:
            effective = await _load_effective_settings(client, chat_id=chat_id)
        except Exception:
            log.exception("Failed to load settings for chat_id=%s", chat_id)
            continue

        active_timeframes = list(effective.get("active_timeframes") or ["15m"])
        # Keep RSI relaxed regardless of older per-chat strict values.
        lower_rsi = max(float(effective.get("lower_rsi", settings.rsi_default_lower)), 40.0)
        upper_rsi = min(float(effective.get("upper_rsi", settings.rsi_default_upper)), 60.0)
        sent_in_cycle = 0
        max_signals_per_cycle = max(1, settings.feed_movers_limit)
        for timeframe in active_timeframes:
            for symbol in shard_symbols:
                if sent_in_cycle >= max_signals_per_cycle:
                    break
                try:
                    snapshot = await build_snapshot(
                        symbol=symbol,
                        timeframe=timeframe,
                        volume_avg_window=settings.signal_volume_avg_window,
                        quote_volume_24h=volume_map.get(symbol),
                    )
                    rsi_value = compute_rsi(snapshot.closes, period=settings.rsi_period)
                    candidate = evaluate_rsi_signal(
                        symbol=symbol,
                        timeframe=timeframe,
                        rsi_value=rsi_value,
                        price_change_5m=snapshot.price_change_5m,
                        price_change_15m=snapshot.price_change_15m,
                        price_change_5m_trigger_pct=settings.signal_price_change_5m_trigger_pct,
                        price_change_15m_trigger_pct=settings.signal_price_change_15m_trigger_pct,
                        prev_price=snapshot.prev_close,
                        current_price=snapshot.current_close,
                        pct_change=snapshot.pct_change,
                        current_volume=snapshot.current_volume,
                        avg_volume_20=snapshot.avg_volume_20,
                        generated_at=snapshot.generated_at,
                    )
                    if not candidate:
                        log.info(
                            "RSI reject: reject_price_trigger symbol=%s tf=%s chg5m=%.4f chg15m=%.4f",
                            symbol,
                            timeframe,
                            snapshot.price_change_5m,
                            snapshot.price_change_15m,
                        )
                        continue
                except (BinanceCandlesError, ValueError):
                    log.exception("RSI reject: bad_data symbol=%s tf=%s", symbol, timeframe)
                    continue

                is_valid, reject_reason = validate_candidate_filters(
                    candidate,
                    lower_rsi=lower_rsi,
                    upper_rsi=upper_rsi,
                )
                if not is_valid:
                    log.info(
                        "RSI reject: %s symbol=%s tf=%s chg5m=%.4f chg15m=%.4f rsi=%.2f",
                        reject_reason,
                        candidate.symbol,
                        candidate.timeframe,
                        candidate.price_change_5m,
                        candidate.price_change_15m,
                        candidate.rsi_value,
                    )
                    continue

                accepted, reject = await filters.accept(candidate, scope=str(chat_id))
                if not accepted:
                    log.info(
                        "RSI reject: %s symbol=%s tf=%s signal_type=%s details=%s",
                        (
                            "reject_cooldown"
                            if (reject and reject.reason == "cooldown")
                            else "reject_duplicate"
                            if (reject and reject.reason == "duplicate")
                            else "unknown"
                        ),
                        candidate.symbol,
                        candidate.timeframe,
                        candidate.signal_type,
                        reject.details if reject else "-",
                    )
                    continue

                payload = {
                    "symbol": candidate.symbol,
                    "timeframe": candidate.timeframe,
                    "direction": "up" if candidate.signal_type == "pump" else "down",
                    "strength": 1.0,
                    "action": "entry",
                    "source": "cex",
                    "signal_type": candidate.signal_type,
                    "trigger_source": candidate.trigger_source,
                    "rsi_value": candidate.rsi_value,
                    "prev_price": candidate.prev_price,
                    "price": candidate.current_price,
                    "volume": snapshot.quote_volume_24h,
                    "reason": f"RSI {candidate.rsi_value:.2f} ({candidate.timeframe})",
                    "last_price": candidate.current_price,
                    "quote_volume": snapshot.quote_volume_24h,
                }
                try:
                    await _save_feed_signal(client, payload)
                except Exception:
                    log.exception("Failed to save RSI signal for %s %s", candidate.symbol, candidate.timeframe)
                    continue

                try:
                    await bot.send_message(chat_id, format_signal_card(candidate))
                except Exception:
                    log.exception("Failed to send RSI feed alert for %s chat_id=%s", candidate.symbol, chat_id)
                    continue
                sent_in_cycle += 1

    return


async def main() -> None:
    setup_logging(settings.log_level)
    if not settings.api_public_base_url:
        raise RuntimeError("API_PUBLIC_BASE_URL is empty")

    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is empty")

    bot = Bot(token=settings.telegram_bot_token)
    client = httpx.AsyncClient(base_url=settings.api_public_base_url, timeout=15.0)
    filters = SignalFilterEngine(
        cooldown_seconds=settings.worker_feed_cooldown_seconds,
        dedup_window_seconds=settings.signal_dedup_window_seconds,
        followup_move_pct=settings.signal_followup_move_pct,
        redis_url=settings.redis_url,
        redis_prefix=settings.signal_filter_redis_prefix,
    )
    shard_count = max(1, settings.worker_shard_count)
    shard_index = settings.worker_shard_index % shard_count
    log.info("RSI worker shard setup: index=%s count=%s", shard_index, shard_count)

    try:
        while True:
            if settings.signal_engine_mode == "rsi":
                await _run_rsi_mode(client, bot, filters, shard_index, shard_count)
            else:
                await _run_legacy_mode(client, bot)

            await _tune_ai(client)

            await asyncio.sleep(settings.worker_interval_seconds)
    finally:
        await filters.aclose()
        await client.aclose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

