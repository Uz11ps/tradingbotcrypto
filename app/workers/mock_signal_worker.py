from __future__ import annotations

import asyncio
import logging
import os
import random
import re
from dataclasses import dataclass

import httpx
from aiogram import Bot

from app.core.config import settings
from app.core.logging import setup_logging
from app.services.binance_candles import (
    BinanceCandlesError,
    build_snapshot,
    fetch_live_price,
    fetch_recent_bars,
)
from app.services.binance_universe import BinanceUniverseError, fetch_top_symbols_by_volume
from app.services.feed_formatter import format_signal_card, format_strategy_signal_card
from app.services.rsi_engine import compute_rsi, evaluate_rsi_signal, validate_candidate_filters
from app.services.signal_filters import SignalFilterEngine
from app.services.signal_presentation import matches_signal_side_mode
from app.services.strategy_engine import detect_pinbar_strategy_signal

log = logging.getLogger("workers.mock_signal_worker")

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
TIMEFRAMES = ["15m", "1h", "4h", "1d"]


@dataclass(slots=True)
class _FilterProxy:
    symbol: str
    timeframe: str
    signal_type: str
    current_price: float
    rsi_value: float = 0.0


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
            "market_type": mover.get("market_type", "spot"),
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


async def _prune_old_signals(client: httpx.AsyncClient) -> int:
    r = await client.post(
        "/maintenance/prune-signals",
        params={"days": settings.signal_retention_days},
    )
    r.raise_for_status()
    payload = r.json()
    return int(payload.get("deleted_total", 0) or 0)


def _resolve_market_types(mode: str) -> list[str]:
    normalized = (mode or "both").strip().lower()
    if normalized == "spot":
        return ["spot"]
    if normalized == "futures":
        return ["futures"]
    return ["spot", "futures"]


def _resolve_shard_index(shard_count: int) -> int:
    if settings.worker_shard_index >= 0:
        return settings.worker_shard_index % shard_count
    hostname = os.getenv("HOSTNAME", "")
    match = re.search(r"-(\d+)$", hostname)
    if not match:
        return 0
    # Docker compose replica names end with 1..N
    return (int(match.group(1)) - 1) % shard_count


async def _debug_raw_candidate(
    client: httpx.AsyncClient,
    *,
    chat_id: int,
    symbol: str,
    timeframe: str,
    market_type: str,
    mode: str,
    decision: str,
    reject_reason: str | None,
    payload: dict[str, object],
) -> None:
    if not settings.signal_debug_full_enabled:
        return
    if decision == "reject":
        sample_rate = max(0.0, min(float(settings.signal_debug_reject_sample_rate), 1.0))
        if sample_rate <= 0:
            return
        if sample_rate < 1.0 and random.random() > sample_rate:
            return
    try:
        await client.post(
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
    except Exception:
        log.exception("Failed to write raw candidate telemetry")


async def _debug_scan_event(
    client: httpx.AsyncClient,
    *,
    chat_id: int,
    symbol: str,
    timeframe: str,
    market_type: str,
    mode: str,
    event: str,
    details: dict[str, object] | None = None,
) -> None:
    if not settings.signal_debug_full_enabled:
        return
    try:
        await client.post(
            "/telemetry/scan-logs",
            json={
                "chat_id": chat_id,
                "symbol": symbol,
                "timeframe": timeframe,
                "market_type": market_type,
                "mode": mode,
                "event": event,
                "details": details or {},
            },
        )
    except Exception:
        log.exception("Failed to write scan log telemetry")


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
                    "market_type": "spot",
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
        universe = await fetch_top_symbols_by_volume(
            quote_asset=settings.bingx_quote_asset,
            top_n=settings.feed_universe_size,
            min_quote_volume_24h=settings.bingx_min_quote_volume,
        )
    except (BinanceUniverseError, Exception):
        log.exception("Failed to load universe in RSI mode")
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

    if not universe.symbols:
        log.warning("RSI mode: empty symbols list")
        return

    shard_symbols = _select_shard_symbols(
        universe.symbols,
        shard_index=shard_index,
        shard_count=shard_count,
    )
    if not shard_symbols:
        log.info("RSI mode: shard has no symbols (index=%s count=%s)", shard_index, shard_count)
        return
    volume_map = universe.volume_map
    log.info("RSI shard %d: %d symbols to scan", shard_index, len(shard_symbols))

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
        trigger_5m = float(effective.get("min_price_move_pct", settings.signal_price_change_5m_trigger_pct))
        trigger_15m = float(
            effective.get("price_change_15m_trigger_pct", settings.signal_price_change_15m_trigger_pct)
        )
        side_mode = str(effective.get("signal_side_mode", "all"))
        market_types = _resolve_market_types(str(effective.get("market_type", "both")))
        if not settings.signal_enable_futures_adapter:
            has_futures = "futures" in market_types
            market_types = [m for m in market_types if m != "futures"]
            if has_futures:
                log.info(
                    "RSI mode: futures excluded from scan loop because adapter is disabled, chat_id=%s",
                    chat_id,
                )
                await _debug_scan_event(
                    client,
                    chat_id=chat_id,
                    symbol="-",
                    timeframe="-",
                    market_type="futures",
                    mode="system",
                    event="futures_excluded_adapter_disabled",
                    details={"chat_id": chat_id},
                )
        if not market_types:
            continue
        feed_mode_enabled = bool(effective.get("feed_mode_enabled", True))
        strategy_mode_enabled = bool(effective.get("strategy_mode_enabled", True))
        rsi_enabled = bool(effective.get("rsi_enabled", True))
        sent_in_cycle = 0
        max_signals_per_cycle = max(1, settings.feed_movers_limit)
        for market_type in market_types:
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
                    except (BinanceCandlesError, ValueError):
                        log.exception("RSI reject: bad_data symbol=%s tf=%s", symbol, timeframe)
                        continue
                    finally:
                        await asyncio.sleep(0.08)

                    if feed_mode_enabled:
                        try:
                            rsi_value = compute_rsi(snapshot.closes, period=settings.rsi_period)
                            candidate = evaluate_rsi_signal(
                                symbol=symbol,
                                timeframe=timeframe,
                                rsi_value=rsi_value,
                                price_change_5m=snapshot.price_change_5m,
                                price_change_15m=snapshot.price_change_15m,
                                price_change_5m_trigger_pct=trigger_5m,
                                price_change_15m_trigger_pct=trigger_15m,
                                window_open_price=snapshot.window_open_price,
                                current_price=snapshot.current_close,
                                pct_change=snapshot.pct_change,
                                current_volume=snapshot.current_volume,
                                avg_volume_20=snapshot.avg_volume_20,
                                quote_volume_24h=snapshot.quote_volume_24h,
                                closes=snapshot.closes,
                                rsi_period=settings.rsi_period,
                                generated_at=snapshot.generated_at,
                            )
                        except ValueError:
                            candidate = None

                        if not candidate:
                            await _debug_raw_candidate(
                                client,
                                chat_id=chat_id,
                                symbol=symbol,
                                timeframe=timeframe,
                                market_type=market_type,
                                mode="feed",
                                decision="reject",
                                reject_reason="reject_price_trigger",
                                payload={
                                    "price_change_5m": snapshot.price_change_5m,
                                    "price_change_15m": snapshot.price_change_15m,
                                },
                            )
                        else:
                            # If RSI is disabled, skip RSI validation
                            if rsi_enabled:
                                is_valid, reject_reason = validate_candidate_filters(
                                    candidate,
                                    lower_rsi=lower_rsi,
                                    upper_rsi=upper_rsi,
                                )
                            else:
                                is_valid, reject_reason = True, None
                            
                            min_move_blocked = (
                                (not settings.signal_disable_double_min_move_filter)
                                and abs(candidate.pct_change) < trigger_5m
                            )
                            if (not is_valid) or min_move_blocked:
                                await _debug_raw_candidate(
                                    client,
                                    chat_id=chat_id,
                                    symbol=candidate.symbol,
                                    timeframe=candidate.timeframe,
                                    market_type=market_type,
                                    mode="feed",
                                    decision="reject",
                                    reject_reason=(
                                        "reject_user_min_move"
                                        if min_move_blocked
                                        else (reject_reason or "reject_rsi_filter")
                                    ),
                                    payload={
                                        "pct_change": candidate.pct_change,
                                        "rsi": candidate.rsi_value,
                                    },
                                )
                            elif not matches_signal_side_mode(side_mode, signal_type=candidate.signal_type):
                                await _debug_raw_candidate(
                                    client,
                                    chat_id=chat_id,
                                    symbol=candidate.symbol,
                                    timeframe=candidate.timeframe,
                                    market_type=market_type,
                                    mode="feed",
                                    decision="reject",
                                    reject_reason="reject_side_mode",
                                    payload={"signal_type": candidate.signal_type, "mode": side_mode},
                                )
                            else:
                                accepted, reject = await filters.accept(candidate, scope=str(chat_id))
                                if not accepted:
                                    await _debug_raw_candidate(
                                        client,
                                        chat_id=chat_id,
                                        symbol=candidate.symbol,
                                        timeframe=candidate.timeframe,
                                        market_type=market_type,
                                        mode="feed",
                                        decision="reject",
                                        reject_reason=reject.reason if reject else "reject_unknown",
                                        payload={"details": reject.details if reject else "-"},
                                    )
                                else:
                                    live_price: float | None = None
                                    if settings.signal_live_price_enabled:
                                        try:
                                            live_price = await fetch_live_price(
                                                symbol=candidate.symbol,
                                                cache_ttl_seconds=settings.signal_live_price_cache_ttl_seconds,
                                            )
                                        except Exception:
                                            # Keep candle-based trigger and signal delivery resilient.
                                            live_price = None
                                    payload = {
                                        "symbol": candidate.symbol,
                                        "timeframe": candidate.timeframe,
                                        "direction": "up" if candidate.signal_type == "pump" else "down",
                                        "strength": 1.0,
                                        "action": "entry",
                                        "source": "cex",
                                        "signal_type": candidate.signal_type,
                                        "market_type": market_type,
                                        "trigger_source": candidate.trigger_source,
                                        "rsi_value": candidate.rsi_value,
                                        "prev_price": candidate.prev_price,
                                        "price": candidate.current_price,
                                        "volume": snapshot.quote_volume_24h,
                                        "reason": f"RSI {candidate.rsi_value:.2f} ({candidate.timeframe})",
                                        "last_price": live_price if live_price is not None else candidate.current_price,
                                        "quote_volume": snapshot.quote_volume_24h,
                                    }
                                    if candidate.rsi_divergence_type and candidate.rsi_divergence_pct is not None:
                                        payload["reason"] = (
                                            f"RSI {candidate.rsi_value:.2f} ({candidate.timeframe}) | "
                                            f"div={candidate.rsi_divergence_type} {candidate.rsi_divergence_pct:.2f}%"
                                        )
                                    try:
                                        await _save_feed_signal(client, payload)
                                        await bot.send_message(
                                            chat_id,
                                            format_signal_card(candidate, live_price=live_price),
                                        )
                                        sent_in_cycle += 1
                                        await _debug_scan_event(
                                            client,
                                            chat_id=chat_id,
                                            symbol=candidate.symbol,
                                            timeframe=candidate.timeframe,
                                            market_type=market_type,
                                            mode="feed",
                                            event="signal_sent",
                                            details={"signal_type": candidate.signal_type},
                                        )
                                        await _debug_raw_candidate(
                                            client,
                                            chat_id=chat_id,
                                            symbol=candidate.symbol,
                                            timeframe=candidate.timeframe,
                                            market_type=market_type,
                                            mode="feed",
                                            decision="accept",
                                            reject_reason=None,
                                            payload={"pct_change": candidate.pct_change},
                                        )
                                    except Exception:
                                        log.exception(
                                            "Failed to save/send RSI feed alert for %s chat_id=%s",
                                            candidate.symbol,
                                            chat_id,
                                        )

                    if strategy_mode_enabled and sent_in_cycle < max_signals_per_cycle:
                        try:
                            bars = await fetch_recent_bars(symbol=symbol, timeframe=timeframe, limit=120)
                            strategy_candidate = detect_pinbar_strategy_signal(
                                symbol=symbol,
                                timeframe=timeframe,
                                bars=bars,
                                generated_at=snapshot.generated_at,
                                market_type=market_type,
                            )
                        except BinanceCandlesError:
                            strategy_candidate = None

                        if not strategy_candidate:
                            await _debug_raw_candidate(
                                client,
                                chat_id=chat_id,
                                symbol=symbol,
                                timeframe=timeframe,
                                market_type=market_type,
                                mode="strategy",
                                decision="reject",
                                reject_reason="reject_no_strategy_setup",
                                payload={"timeframe": timeframe},
                            )
                            continue

                        strategy_proxy = _FilterProxy(
                            symbol=strategy_candidate.symbol,
                            timeframe=strategy_candidate.timeframe,
                            signal_type=(
                                "post_pump_pullback_short"
                                if strategy_candidate.direction == "short"
                                else "post_dump_bounce_long"
                            ),
                            current_price=strategy_candidate.current_price,
                        )
                        accepted, reject = await filters.accept(strategy_proxy, scope=f"{chat_id}:strategy")
                        if not accepted:
                            await _debug_raw_candidate(
                                client,
                                chat_id=chat_id,
                                symbol=strategy_candidate.symbol,
                                timeframe=strategy_candidate.timeframe,
                                market_type=market_type,
                                mode="strategy",
                                decision="reject",
                                reject_reason=reject.reason if reject else "reject_unknown",
                                payload={"details": reject.details if reject else "-"},
                            )
                            continue

                        strategy_direction = "down" if strategy_candidate.direction == "short" else "up"
                        strategy_signal_type = (
                            "post_pump_pullback_short"
                            if strategy_candidate.direction == "short"
                            else "post_dump_bounce_long"
                        )
                        try:
                            await _save_feed_signal(
                                client,
                                {
                                    "symbol": strategy_candidate.symbol,
                                    "timeframe": strategy_candidate.timeframe,
                                    "direction": strategy_direction,
                                    "strength": 1.0,
                                    "action": "entry",
                                    "source": "cex",
                                    "signal_type": strategy_signal_type,
                                    "market_type": market_type,
                                    "trigger_source": "pinbar_deviation",
                                    "prev_price": strategy_candidate.baseline_price,
                                    "price": strategy_candidate.current_price,
                                    "last_price": strategy_candidate.current_price,
                                    "quote_volume": snapshot.quote_volume_24h,
                                    "reason": (
                                        f"Стратегия pin bar: отклонение {strategy_candidate.deviation_pct:+.2f}% "
                                        f"силa={strategy_candidate.pinbar_strength:.2f}"
                                    ),
                                },
                            )
                            await bot.send_message(chat_id, format_strategy_signal_card(strategy_candidate))
                            sent_in_cycle += 1
                            await _debug_scan_event(
                                client,
                                chat_id=chat_id,
                                symbol=strategy_candidate.symbol,
                                timeframe=strategy_candidate.timeframe,
                                market_type=market_type,
                                mode="strategy",
                                event="signal_sent",
                                details={"signal_type": strategy_signal_type},
                            )
                            await _debug_raw_candidate(
                                client,
                                chat_id=chat_id,
                                symbol=strategy_candidate.symbol,
                                timeframe=strategy_candidate.timeframe,
                                market_type=market_type,
                                mode="strategy",
                                decision="accept",
                                reject_reason=None,
                                payload={"deviation_pct": strategy_candidate.deviation_pct},
                            )
                        except Exception:
                            log.exception(
                                "Failed to save/send strategy alert for %s chat_id=%s",
                                strategy_candidate.symbol,
                                chat_id,
                            )

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
        repeat_guard_min_move_pct=settings.signal_repeat_guard_min_move_pct,
        repeat_guard_min_rsi_delta=settings.signal_repeat_guard_min_rsi_delta,
        redis_url=settings.redis_url,
        redis_prefix=settings.signal_filter_redis_prefix,
        memory_state_ttl_seconds=settings.signal_filter_memory_state_ttl_seconds,
        memory_state_max_keys=settings.signal_filter_memory_state_max_keys,
        memory_gc_interval_seconds=settings.signal_filter_memory_gc_interval_seconds,
    )
    shard_count = max(1, settings.worker_shard_count)
    shard_index = _resolve_shard_index(shard_count)
    log.info("RSI worker shard setup: index=%s count=%s", shard_index, shard_count)
    last_prune_ts = 0.0

    try:
        while True:
            if settings.signal_engine_mode == "rsi":
                await _run_rsi_mode(client, bot, filters, shard_index, shard_count)
            else:
                await _run_legacy_mode(client, bot)

            await _tune_ai(client)
            # Only shard 0 runs retention cleanup to avoid duplicate work
            if shard_index == 0:
                loop_time = asyncio.get_running_loop().time()
                if (
                    settings.signal_retention_prune_interval_seconds > 0
                    and (loop_time - last_prune_ts) >= settings.signal_retention_prune_interval_seconds
                ):
                    try:
                        deleted = await _prune_old_signals(client)
                        log.info(
                            "Signal retention prune done: days=%s deleted=%s",
                            settings.signal_retention_days,
                            deleted,
                        )
                        last_prune_ts = loop_time
                    except Exception:
                        log.exception("Signal retention prune failed")

            await asyncio.sleep(settings.worker_interval_seconds)
    finally:
        await filters.aclose()
        await client.aclose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

