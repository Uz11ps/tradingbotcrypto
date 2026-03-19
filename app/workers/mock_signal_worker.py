from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import random
import re
from contextlib import suppress
from dataclasses import dataclass

import httpx
from aiogram import Bot
from redis.asyncio import Redis

from app.bot.keyboards import bottom_chat_menu_kb
from app.core.config import settings
from app.core.logging import setup_logging
from app.services.binance_candles import (
    BinanceCandlesError,
)
from app.services.binance_universe import BinanceUniverseError
from app.services.feed_formatter import format_signal_card, format_strategy_signal_card
from app.services.live_ingest import LiveShadowIngestor
from app.services.market_provider import MarketProviderRouter
from app.services.market_state_cache import MarketStateCache
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


def _resolve_evaluation_window(
    *,
    selected_tf: str,
    trigger_mode: str,
) -> tuple[str, int, bool, str | None]:
    tf = (selected_tf or "15m").strip()
    # For live_spike/both we currently have only 5m/15m live trigger windows.
    if trigger_mode in {"live_spike", "both"}:
        if tf == "5m":
            return tf, 300, False, None
        if tf == "15m":
            return tf, 900, False, None
        return "15m", 900, True, "live_trigger_window_fallback_to_15m"
    # Candle mode keeps direct selected timeframe mapping.
    if tf == "5m":
        return tf, 300, False, None
    if tf == "15m":
        return tf, 900, False, None
    if tf == "1h":
        return tf, 3600, False, None
    if tf == "4h":
        return tf, 14400, False, None
    return "15m", 900, True, "unsupported_timeframe_fallback_to_15m"


def _derive_shard_index_from_identity(identity: str, shard_count: int) -> int:
    if shard_count <= 1:
        return 0
    normalized = (identity or "").strip().lower()
    if not normalized:
        return 0
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % shard_count


def _resolve_shard_index(shard_count: int) -> int:
    if settings.worker_shard_index >= 0:
        return settings.worker_shard_index % shard_count
    hostname = os.getenv("HOSTNAME", "")
    match = re.search(r"-(\d+)$", hostname)
    if not match:
        return _derive_shard_index_from_identity(hostname, shard_count)
    # Docker compose replica names end with 1..N
    return (int(match.group(1)) - 1) % shard_count


def _pct_change(prev_value: float, current_value: float) -> float:
    if prev_value == 0:
        return 0.0
    return ((current_value - prev_value) / prev_value) * 100.0


def _parse_shadow_symbols(raw: str) -> list[str]:
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


def _format_market_route_trace(router: MarketProviderRouter, *, chat_id: int, requested_market_type: str) -> str:
    resolution = router.resolve(requested_market_type)
    enabled = ",".join(
        f"{route.market_type}:{route.provider_name}"
        for route in resolution.enabled_routes
    ) or "-"
    skipped = ",".join(
        f"{route.market_type}:{route.reason or '-'}"
        for route in resolution.skipped_routes
    ) or "-"
    policy = "futures_adapter_enabled" if router.futures_adapter_enabled else "futures_adapter_disabled"
    return (
        "market_route_trace "
        f"chat_id={chat_id} "
        f"requested={resolution.requested_market_type} "
        f"normalized={resolution.normalized_market_type} "
        f"policy={policy} "
        f"enabled={enabled} "
        f"skipped={skipped}"
    )


@dataclass(slots=True)
class _LeaseState:
    is_owner: bool = False
    acquired_once: bool = False
    lost_once: bool = False


class _RedisLeaseGuard:
    def __init__(self, *, redis: Redis, key: str, owner: str, ttl_seconds: int) -> None:
        self._redis = redis
        self._key = key
        self._owner = owner
        self._ttl = max(10, int(ttl_seconds))

    async def try_acquire_or_renew(self) -> bool:
        acquired = await self._redis.set(self._key, self._owner, ex=self._ttl, nx=True)
        if acquired:
            return True
        current_owner = await self._redis.get(self._key)
        if current_owner == self._owner:
            await self._redis.expire(self._key, self._ttl)
            return True
        return False

    async def release_if_owner(self) -> None:
        try:
            current_owner = await self._redis.get(self._key)
            if current_owner == self._owner:
                await self._redis.delete(self._key)
        except Exception:
            log.exception("Failed to release redis lease key=%s", self._key)


class _RedisShardSlotGuard:
    def __init__(self, *, redis: Redis, prefix: str, owner: str, shard_count: int, ttl_seconds: int) -> None:
        self._redis = redis
        self._prefix = prefix
        self._owner = owner
        self._shard_count = max(1, int(shard_count))
        self._ttl = max(30, int(ttl_seconds))
        self._slot: int | None = None

    @property
    def slot(self) -> int | None:
        return self._slot

    async def acquire_or_renew(self) -> int | None:
        if self._slot is not None:
            key = f"{self._prefix}:{self._slot}"
            owner = await self._redis.get(key)
            if owner == self._owner:
                await self._redis.expire(key, self._ttl)
                return self._slot
            self._slot = None
        for slot in range(self._shard_count):
            key = f"{self._prefix}:{slot}"
            acquired = await self._redis.set(key, self._owner, ex=self._ttl, nx=True)
            if acquired:
                self._slot = slot
                return slot
        return None

    async def release_if_owner(self) -> None:
        if self._slot is None:
            return
        key = f"{self._prefix}:{self._slot}"
        try:
            owner = await self._redis.get(key)
            if owner == self._owner:
                await self._redis.delete(key)
        except Exception:
            log.exception("Failed to release shard slot key=%s", key)


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
    market_router: MarketProviderRouter,
) -> int:
    try:
        chat_ids = await _list_signal_chats(client)
    except Exception:
        log.exception("Failed to load chat list in RSI mode")
        chat_ids = []
    if not chat_ids and settings.telegram_signals_chat_id:
        chat_ids = [settings.telegram_signals_chat_id]
    if not chat_ids:
        log.info("RSI mode: no target chats registered yet")
        return 0

    route_scan_cache: dict[str, tuple[list[str], dict[str, float]]] = {}
    max_assigned_symbols = 0

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
        selected_threshold = float(
            effective.get("min_price_move_pct", settings.signal_price_change_5m_trigger_pct)
        )
        trigger_5m = selected_threshold
        trigger_15m = float(
            effective.get("price_change_15m_trigger_pct", selected_threshold)
        )
        # Protect against hidden lower thresholds in mixed config payloads.
        if trigger_15m < selected_threshold:
            trigger_15m = selected_threshold
        side_mode = str(effective.get("signal_side_mode", "all"))
        trigger_mode = str(settings.signal_trigger_mode).strip().lower() or "candle"
        if trigger_mode not in {"candle", "live_spike", "both"}:
            trigger_mode = "candle"
        log.info(
            (
                "settings_trace chat_id=%s selected_tf=%s effective_tf=%s "
                "selected_threshold=%.4f effective_threshold=%.4f trigger_mode=%s"
            ),
            chat_id,
            ",".join(active_timeframes),
            ",".join(active_timeframes),
            selected_threshold,
            max(trigger_5m, trigger_15m),
            trigger_mode,
        )
        requested_market_type = str(effective.get("market_type", "both"))
        resolution = market_router.resolve(requested_market_type)
        if settings.signal_market_route_trace_enabled:
            log.info(
                _format_market_route_trace(
                    market_router,
                    chat_id=chat_id,
                    requested_market_type=requested_market_type,
                )
            )
        if resolution.skipped_routes:
            for skipped in resolution.skipped_routes:
                await _debug_scan_event(
                    client,
                    chat_id=chat_id,
                    symbol="-",
                    timeframe="-",
                    market_type=skipped.market_type,
                    mode="system",
                    event=f"{skipped.market_type}_route_skipped",
                    details={"reason": skipped.reason or "unknown"},
                )
        if not resolution.enabled_routes:
            continue
        feed_mode_enabled = bool(effective.get("feed_mode_enabled", True))
        strategy_mode_enabled = bool(effective.get("strategy_mode_enabled", True))
        rsi_enabled = bool(effective.get("rsi_enabled", True))
        sent_in_cycle = 0
        max_signals_per_cycle = max(1, settings.feed_movers_limit)
        for route in resolution.enabled_routes:
            market_type = route.market_type
            provider = market_router.get_provider(route)
            if market_type not in route_scan_cache:
                try:
                    route_universe = await provider.fetch_universe(
                        quote_asset=settings.bingx_quote_asset,
                        top_n=settings.feed_universe_size,
                        min_quote_volume_24h=settings.bingx_min_quote_volume,
                    )
                except (BinanceUniverseError, Exception):
                    log.exception(
                        "Failed to load universe in RSI mode route=%s provider=%s",
                        market_type,
                        route.provider_name,
                    )
                    route_scan_cache[market_type] = ([], {})
                else:
                    route_shard_symbols = _select_shard_symbols(
                        route_universe.symbols,
                        shard_index=shard_index,
                        shard_count=shard_count,
                    )
                    route_scan_cache[market_type] = (
                        route_shard_symbols,
                        route_universe.volume_map,
                    )
                    log.info(
                        "RSI shard %d route=%s provider=%s: %d symbols to scan",
                        shard_index,
                        market_type,
                        route.provider_name,
                        len(route_shard_symbols),
                    )
            shard_symbols, volume_map = route_scan_cache.get(market_type, ([], {}))
            if not shard_symbols:
                continue
            max_assigned_symbols = max(max_assigned_symbols, len(shard_symbols))
            for selected_tf in active_timeframes:
                (
                    evaluation_tf,
                    window_seconds,
                    fallback_applied,
                    fallback_reason,
                ) = _resolve_evaluation_window(
                    selected_tf=selected_tf,
                    trigger_mode=trigger_mode,
                )
                if fallback_applied:
                    log.info(
                        (
                            "tf_fallback_trace chat_id=%s selected_tf=%s evaluation_tf=%s "
                            "window_seconds=%s fallback_reason=%s trigger_mode=%s"
                        ),
                        chat_id,
                        selected_tf,
                        evaluation_tf,
                        window_seconds,
                        fallback_reason,
                        trigger_mode,
                    )
                for symbol in shard_symbols:
                    if sent_in_cycle >= max_signals_per_cycle:
                        break
                    try:
                        snapshot = await provider.build_snapshot(
                            symbol=symbol,
                            timeframe=evaluation_tf,
                            volume_avg_window=settings.signal_volume_avg_window,
                            quote_volume_24h=volume_map.get(symbol),
                        )
                    except (BinanceCandlesError, ValueError):
                        log.exception(
                            "RSI reject: bad_data symbol=%s tf=%s eval_tf=%s",
                            symbol,
                            selected_tf,
                            evaluation_tf,
                        )
                        continue
                    finally:
                        await asyncio.sleep(0.08)

                    if feed_mode_enabled:
                        prefetched_live_price: float | None = None
                        live_change_pct: float | None = None
                        try:
                            if trigger_mode in {"live_spike", "both"}:
                                prefetched_live_price = await provider.fetch_live_price(
                                    symbol=symbol,
                                    cache_ttl_seconds=settings.signal_live_price_cache_ttl_seconds,
                                )
                                live_change_pct = _pct_change(
                                    snapshot.live_window_open_price,
                                    prefetched_live_price,
                                )
                            rsi_value = compute_rsi(snapshot.closes, period=settings.rsi_period)
                            candidate = evaluate_rsi_signal(
                                symbol=symbol,
                                timeframe=evaluation_tf,
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
                                trigger_mode=trigger_mode,
                                live_change_pct=live_change_pct,
                                live_window_open_price=snapshot.live_window_open_price,
                                live_spike_5m_trigger_pct=settings.signal_live_spike_5m_trigger_pct,
                                live_spike_15m_trigger_pct=settings.signal_live_spike_15m_trigger_pct,
                            )
                        except ValueError:
                            candidate = None
                            live_change_pct = None
                        except BinanceCandlesError:
                            candidate = None
                            live_change_pct = None

                        if not candidate:
                            await _debug_raw_candidate(
                                client,
                                chat_id=chat_id,
                                symbol=symbol,
                                timeframe=evaluation_tf,
                                market_type=market_type,
                                mode="feed",
                                decision="reject",
                                reject_reason="reject_price_trigger",
                                payload={
                                    "price_change_5m": snapshot.price_change_5m,
                                    "price_change_15m": snapshot.price_change_15m,
                                    "live_change_pct": live_change_pct,
                                    "trigger_mode": trigger_mode,
                                    "selected_tf": active_timeframes,
                                    "effective_tf": evaluation_tf,
                                    "window_seconds": window_seconds,
                                    "fallback_applied": fallback_applied,
                                    "fallback_reason": fallback_reason,
                                    "effective_threshold": (
                                        trigger_5m if evaluation_tf == "5m" else trigger_15m
                                    ),
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
                                and abs(candidate.pct_change)
                                < (trigger_5m if evaluation_tf == "5m" else trigger_15m)
                            )
                            if (not is_valid) or min_move_blocked:
                                effective_threshold = (
                                    trigger_5m if evaluation_tf == "5m" else trigger_15m
                                )
                                if min_move_blocked:
                                    log.info(
                                        (
                                            "decision_trace reject_user_min_move chat_id=%s symbol=%s tf=%s "
                                            "eval_tf=%s window_seconds=%s fallback=%s "
                                            "change=%.4f threshold=%.4f trigger_mode=%s"
                                        ),
                                        chat_id,
                                        candidate.symbol,
                                        selected_tf,
                                        evaluation_tf,
                                        window_seconds,
                                        fallback_applied,
                                        candidate.pct_change,
                                        effective_threshold,
                                        trigger_mode,
                                    )
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
                                        "selected_tf": active_timeframes,
                                        "effective_tf": evaluation_tf,
                                        "window_seconds": window_seconds,
                                        "fallback_applied": fallback_applied,
                                        "fallback_reason": fallback_reason,
                                        "effective_threshold": effective_threshold,
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
                                    live_price: float | None = prefetched_live_price
                                    if settings.signal_live_price_enabled and live_price is None:
                                        try:
                                            live_price = await provider.fetch_live_price(
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
                                        "reason": (
                                            f"trigger={candidate.trigger_source} "
                                            f"move={candidate.pct_change:+.2f}% ({candidate.timeframe})"
                                        ),
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
                                            reply_markup=bottom_chat_menu_kb(),
                                        )
                                        effective_threshold = (
                                            trigger_5m if evaluation_tf == "5m" else trigger_15m
                                        )
                                        log.info(
                                            (
                                                "decision_trace signal_sent chat_id=%s symbol=%s tf=%s "
                                                "eval_tf=%s window_seconds=%s fallback=%s "
                                                "change=%.4f threshold=%.4f trigger_source=%s"
                                            ),
                                            chat_id,
                                            candidate.symbol,
                                            selected_tf,
                                            evaluation_tf,
                                            window_seconds,
                                            fallback_applied,
                                            candidate.pct_change,
                                            effective_threshold,
                                            candidate.trigger_source,
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
                                            payload={
                                                "pct_change": candidate.pct_change,
                                                "selected_tf": active_timeframes,
                                                "effective_tf": evaluation_tf,
                                                "window_seconds": window_seconds,
                                                "fallback_applied": fallback_applied,
                                                "fallback_reason": fallback_reason,
                                            },
                                        )
                                    except Exception:
                                        log.exception(
                                            "Failed to save/send RSI feed alert for %s chat_id=%s",
                                            candidate.symbol,
                                            chat_id,
                                        )

                    if strategy_mode_enabled and sent_in_cycle < max_signals_per_cycle:
                        try:
                            bars = await provider.fetch_recent_bars(
                                symbol=symbol,
                                timeframe=selected_tf,
                                limit=120,
                            )
                            strategy_candidate = detect_pinbar_strategy_signal(
                                symbol=symbol,
                                timeframe=selected_tf,
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
                                timeframe=selected_tf,
                                market_type=market_type,
                                mode="strategy",
                                decision="reject",
                                reject_reason="reject_no_strategy_setup",
                                payload={"timeframe": selected_tf},
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
                            await bot.send_message(
                                chat_id,
                                format_strategy_signal_card(strategy_candidate),
                                reply_markup=bottom_chat_menu_kb(),
                            )
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

    return max_assigned_symbols


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
        soft_flip_window_seconds=settings.signal_soft_flip_window_seconds,
        soft_flip_min_move_pct=settings.signal_soft_flip_min_move_pct,
        soft_flip_log_only=settings.signal_soft_flip_log_only,
        redis_url=settings.redis_url,
        redis_prefix=settings.signal_filter_redis_prefix,
        memory_state_ttl_seconds=settings.signal_filter_memory_state_ttl_seconds,
        memory_state_max_keys=settings.signal_filter_memory_state_max_keys,
        memory_gc_interval_seconds=settings.signal_filter_memory_gc_interval_seconds,
    )
    market_router = MarketProviderRouter(
        futures_adapter_enabled=settings.signal_enable_futures_adapter,
    )
    shard_count = max(1, settings.worker_shard_count)
    shard_index = _resolve_shard_index(shard_count)
    last_prune_ts = 0.0
    loop_cycle = 0
    worker_identity = os.getenv("HOSTNAME", "unknown-worker")
    assigned_symbols_count_last = -1
    redis_lease_client: Redis | None = None
    shard_slot_guard: _RedisShardSlotGuard | None = None
    ingest_lease: _RedisLeaseGuard | None = None
    ingest_lease_state = _LeaseState()
    shadow_cache: MarketStateCache | None = None
    shadow_ingestor: LiveShadowIngestor | None = None
    shadow_stop_event: asyncio.Event | None = None
    shadow_task: asyncio.Task[None] | None = None
    shadow_symbols = _parse_shadow_symbols(settings.signal_live_shadow_symbols)
    strict_shard_mode = settings.worker_shard_index < 0 and bool(settings.redis_url)
    no_slot_streak = 0
    fail_open_active = False
    fail_open_after = max(1, int(settings.worker_shard_fail_open_after_retries))
    if strict_shard_mode:
        shard_index = -1
    if strict_shard_mode:
        try:
            redis_lease_client = Redis.from_url(settings.redis_url, decode_responses=True)
            shard_slot_guard = _RedisShardSlotGuard(
                redis=redis_lease_client,
                prefix="signal:worker_shard_slot",
                owner=worker_identity,
                shard_count=shard_count,
                ttl_seconds=settings.worker_shard_slot_lock_ttl_seconds,
            )
            claimed_slot = await shard_slot_guard.acquire_or_renew()
            if claimed_slot is not None:
                shard_index = claimed_slot
            log.info(
                "RSI worker shard setup: index=%s count=%s identity=%s",
                shard_index,
                shard_count,
                worker_identity,
            )
        except Exception:
            log.exception("Failed to initialize shard slot guard")
            shard_slot_guard = None
            if redis_lease_client is not None:
                await redis_lease_client.aclose()
            redis_lease_client = None
            log.info(
                "RSI worker shard setup: index=%s count=%s identity=%s",
                shard_index,
                shard_count,
                worker_identity,
            )
    else:
        log.info(
            "RSI worker shard setup: index=%s count=%s identity=%s",
            shard_index,
            shard_count,
            worker_identity,
        )

    if settings.signal_shadow_mode_enabled and settings.redis_url:
        try:
            if redis_lease_client is None:
                redis_lease_client = Redis.from_url(settings.redis_url, decode_responses=True)
            ingest_lease = _RedisLeaseGuard(
                redis=redis_lease_client,
                key="signal:shadow_ingest_owner",
                owner=worker_identity,
                ttl_seconds=settings.signal_live_ingest_owner_lock_ttl_seconds,
            )
        except Exception:
            log.exception("Failed to initialize ingest owner redis lease")
            ingest_lease = None
            redis_lease_client = None
    shadow_should_run = settings.signal_shadow_mode_enabled and (
        ingest_lease is None and shard_index == 0
    )
    if shadow_should_run:
        symbols = _parse_shadow_symbols(settings.signal_live_shadow_symbols)
        shadow_cache = MarketStateCache(
            ttl_seconds=max(30, settings.worker_interval_seconds * 12),
            max_points_per_symbol=1200,
            max_symbols=max(100, len(symbols) * 4),
        )
        shadow_ingestor = LiveShadowIngestor(
            cache=shadow_cache,
            symbols=symbols,
            ws_url=settings.signal_live_ws_url,
            reconnect_delay_seconds=settings.signal_live_ws_reconnect_seconds,
            reconnect_max_delay_seconds=settings.signal_live_ws_reconnect_max_seconds,
            reconnect_jitter_seconds=settings.signal_live_ws_reconnect_jitter_seconds,
        )
        shadow_stop_event = asyncio.Event()
        shadow_task = asyncio.create_task(
            shadow_ingestor.run(stop_event=shadow_stop_event),
            name="live-shadow-ingest",
        )
        log.info(
            "Shadow live ingest started: ws_url=%s symbols=%d",
            settings.signal_live_ws_url,
            len(symbols),
        )
    elif settings.signal_shadow_mode_enabled and ingest_lease is None:
        log.info(
            "Shadow live ingest is enabled but skipped on shard_index=%s (runs only on shard 0)",
            shard_index,
        )
    ingest_lease_state.acquired_once = shadow_should_run
    ingest_lease_state.is_owner = shadow_should_run
    log.info(
        (
            "runtime_state worker_shard_index=%s worker_shard_total=%s "
            "assigned_symbols_count=%s shadow_ingest_owner=%s "
            "ingest_owner_acquired=%s ingest_owner_lost=%s "
            "shard_fail_open=%s no_slot_streak=%s"
        ),
        shard_index,
        shard_count,
        assigned_symbols_count_last,
        ingest_lease_state.is_owner,
        ingest_lease_state.acquired_once,
        ingest_lease_state.lost_once,
        fail_open_active,
        no_slot_streak,
    )

    try:
        while True:
            loop_cycle += 1
            if shard_slot_guard is not None:
                refreshed_slot = await shard_slot_guard.acquire_or_renew()
                if refreshed_slot is not None:
                    if fail_open_active:
                        log.info(
                            "RSI shard fail-open recovered: acquired_slot=%s retries=%s identity=%s",
                            refreshed_slot,
                            no_slot_streak,
                            worker_identity,
                        )
                    no_slot_streak = 0
                    fail_open_active = False
                    shard_index = refreshed_slot
                else:
                    no_slot_streak += 1
                    if settings.worker_shard_fail_open_enabled and no_slot_streak >= fail_open_after:
                        fallback_slot = _derive_shard_index_from_identity(worker_identity, shard_count)
                        if (not fail_open_active) or shard_index != fallback_slot:
                            log.warning(
                                (
                                    "RSI shard fail-open activated: fallback_slot=%s retries=%s "
                                    "identity=%s count=%s"
                                ),
                                fallback_slot,
                                no_slot_streak,
                                worker_identity,
                                shard_count,
                            )
                        shard_index = fallback_slot
                        fail_open_active = True
                    else:
                        shard_index = -1
                        fail_open_active = False
            if settings.signal_shadow_mode_enabled and ingest_lease is not None:
                is_owner_now = await ingest_lease.try_acquire_or_renew()
                if is_owner_now and not ingest_lease_state.acquired_once:
                    ingest_lease_state.acquired_once = True
                if is_owner_now and shadow_task is None:
                    shadow_cache = MarketStateCache(
                        ttl_seconds=max(30, settings.worker_interval_seconds * 12),
                        max_points_per_symbol=1200,
                        max_symbols=max(100, len(shadow_symbols) * 4),
                    )
                    shadow_ingestor = LiveShadowIngestor(
                        cache=shadow_cache,
                        symbols=shadow_symbols,
                        ws_url=settings.signal_live_ws_url,
                        reconnect_delay_seconds=settings.signal_live_ws_reconnect_seconds,
                        reconnect_max_delay_seconds=settings.signal_live_ws_reconnect_max_seconds,
                        reconnect_jitter_seconds=settings.signal_live_ws_reconnect_jitter_seconds,
                    )
                    shadow_stop_event = asyncio.Event()
                    shadow_task = asyncio.create_task(
                        shadow_ingestor.run(stop_event=shadow_stop_event),
                        name="live-shadow-ingest",
                    )
                    ingest_lease_state.is_owner = True
                    log.info(
                        "Shadow live ingest started by lease owner: ws_url=%s symbols=%d",
                        settings.signal_live_ws_url,
                        len(shadow_symbols),
                    )
                elif (not is_owner_now) and shadow_task is not None:
                    ingest_lease_state.is_owner = False
                    ingest_lease_state.lost_once = True
                    if shadow_stop_event is not None:
                        shadow_stop_event.set()
                    shadow_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await shadow_task
                    shadow_task = None
                    shadow_ingestor = None
                    shadow_stop_event = None
                    shadow_cache = None
                    log.warning("Shadow ingest ownership lost: stopping local ingest task")
            if settings.signal_engine_mode == "rsi":
                if shard_index >= 0:
                    assigned_symbols_count_last = await _run_rsi_mode(
                        client,
                        bot,
                        filters,
                        shard_index,
                        shard_count,
                        market_router,
                    )
                else:
                    assigned_symbols_count_last = -1
                    log.warning(
                        "RSI worker skipping scan: no shard slot acquired (identity=%s, count=%s)",
                        worker_identity,
                        shard_count,
                    )
                    await asyncio.sleep(max(0.5, settings.worker_shard_slot_retry_interval_seconds))
                    continue
            else:
                await _run_legacy_mode(client, bot)
                assigned_symbols_count_last = -1

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

            if (
                shadow_ingestor is not None
                and shadow_cache is not None
                and loop_cycle % max(1, settings.signal_live_shadow_log_interval_cycles) == 0
            ):
                stats = shadow_ingestor.stats
                log.info(
                    (
                        "Shadow ingest stats: connected=%s attempts=%d reconnects=%d "
                        "disconnects=%d timeouts=%d errors=%d decode_failures=%d "
                        "pongs_sent=%d subscriptions_sent=%d messages=%d updates=%d "
                        "cache_age_ms=%d symbols=%d points=%d last_event_ts_ms=%d"
                    ),
                    stats.connected,
                    stats.attempts_total,
                    stats.reconnects,
                    stats.disconnects_total,
                    stats.timeouts_total,
                    stats.errors_total,
                    stats.decode_failures_total,
                    stats.pongs_sent_total,
                    stats.subscriptions_sent_total,
                    stats.messages_total,
                    stats.updates_total,
                    stats.cache_age_ms,
                    shadow_cache.symbols_count(),
                    shadow_cache.points_count(),
                    stats.last_event_ts_ms,
                )
            if loop_cycle % max(1, settings.signal_live_shadow_log_interval_cycles) == 0:
                log.info(
                    (
                        "runtime_state worker_shard_index=%s worker_shard_total=%s "
                        "assigned_symbols_count=%s shadow_ingest_owner=%s "
                        "ingest_owner_acquired=%s ingest_owner_lost=%s "
                        "shard_fail_open=%s no_slot_streak=%s"
                    ),
                    shard_index,
                    shard_count,
                    assigned_symbols_count_last,
                    ingest_lease_state.is_owner,
                    ingest_lease_state.acquired_once,
                    ingest_lease_state.lost_once,
                    fail_open_active,
                    no_slot_streak,
                )

            await asyncio.sleep(settings.worker_interval_seconds)
    finally:
        if shadow_stop_event is not None:
            shadow_stop_event.set()
        if shadow_task is not None:
            shadow_task.cancel()
            with suppress(asyncio.CancelledError):
                await shadow_task
        if ingest_lease is not None:
            await ingest_lease.release_if_owner()
        if shard_slot_guard is not None:
            await shard_slot_guard.release_if_owner()
        if redis_lease_client is not None:
            await redis_lease_client.aclose()
        await filters.aclose()
        await client.aclose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

