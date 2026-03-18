from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from redis.asyncio import Redis

from app.services.rsi_engine import RsiSignalCandidate

log = logging.getLogger(__name__)


@dataclass(slots=True)
class RejectReason:
    reason: str
    details: str


class SignalFilterEngine:
    def __init__(
        self,
        *,
        cooldown_seconds: int,
        dedup_window_seconds: int,
        followup_move_pct: float = 1.5,
        repeat_guard_min_move_pct: float = 0.4,
        repeat_guard_min_rsi_delta: float = 2.0,
        soft_flip_window_seconds: int = 0,
        soft_flip_min_move_pct: float = 1.0,
        soft_flip_log_only: bool = True,
        redis_url: str = "",
        redis_prefix: str = "signal_filter",
        memory_state_ttl_seconds: int = 7200,
        memory_state_max_keys: int = 200000,
        memory_gc_interval_seconds: int = 60,
    ) -> None:
        self.cooldown_seconds = max(0, cooldown_seconds)
        self.dedup_window_seconds = max(0, dedup_window_seconds)
        self.followup_move_pct = max(0.0, followup_move_pct)
        self.repeat_guard_min_move_pct = max(0.0, repeat_guard_min_move_pct)
        self.repeat_guard_min_rsi_delta = max(0.0, repeat_guard_min_rsi_delta)
        self.soft_flip_window_seconds = max(0, int(soft_flip_window_seconds))
        self.soft_flip_min_move_pct = max(0.0, soft_flip_min_move_pct)
        self.soft_flip_log_only = bool(soft_flip_log_only)
        self.redis_prefix = redis_prefix.strip() or "signal_filter"
        self.memory_state_ttl_seconds = max(300, int(memory_state_ttl_seconds))
        self.memory_state_max_keys = max(1000, int(memory_state_max_keys))
        self.memory_gc_interval_seconds = max(10, int(memory_gc_interval_seconds))
        self._redis: Redis | None = Redis.from_url(redis_url, decode_responses=True) if redis_url else None
        self._last_sent_at: dict[tuple[str, str, str, str], float] = {}
        self._last_fingerprint_at: dict[str, float] = {}
        self._last_sent_price: dict[tuple[str, str, str, str], float] = {}
        self._last_sent_rsi: dict[tuple[str, str, str, str], float] = {}
        self._last_side_state: dict[tuple[str, str, str], tuple[float, float, str]] = {}
        self._last_gc_ts = 0.0
        self._lock = asyncio.Lock()

    @staticmethod
    def _cooldown_key(candidate: RsiSignalCandidate, scope: str) -> tuple[str, str, str, str]:
        return (scope, candidate.symbol, candidate.timeframe, candidate.signal_type)

    @staticmethod
    def _fingerprint(candidate: RsiSignalCandidate, scope: str) -> str:
        # Fingerprint keeps message-level uniqueness while preserving signal key cooldown.
        return (
            f"{scope}|{candidate.symbol}|{candidate.timeframe}|{candidate.signal_type}|"
            f"{candidate.rsi_value:.2f}|{candidate.current_price:.8f}"
        )

    @staticmethod
    def _side_key(candidate: RsiSignalCandidate, scope: str) -> tuple[str, str, str]:
        return (scope, candidate.symbol, candidate.timeframe)

    @staticmethod
    def _pct_change(prev_value: float, current_value: float) -> float:
        if prev_value == 0:
            return 0.0
        return abs((current_value - prev_value) / prev_value) * 100.0

    async def _accept_in_memory(
        self,
        candidate: RsiSignalCandidate,
        *,
        scope: str,
    ) -> tuple[bool, RejectReason | None]:
        now = time.time()
        self._gc_in_memory_state(now)
        key = self._cooldown_key(candidate, scope)
        last_sent = self._last_sent_at.get(key, 0.0)
        last_price = self._last_sent_price.get(key, 0.0)
        last_rsi = self._last_sent_rsi.get(key, candidate.rsi_value)
        moved_after_last_signal = self._pct_change(last_price, candidate.current_price)
        rsi_delta = abs(candidate.rsi_value - last_rsi)
        side_key = self._side_key(candidate, scope)
        side_state = self._last_side_state.get(side_key)

        fingerprint = self._fingerprint(candidate, scope)
        last_fp_ts = self._last_fingerprint_at.get(fingerprint, 0.0)
        if self.dedup_window_seconds and (now - last_fp_ts < self.dedup_window_seconds):
            return False, RejectReason(
                reason="duplicate",
                details=f"fingerprint duplicate ts={last_fp_ts}",
            )

        # Cooldown can be bypassed when movement continues strongly.
        if self.cooldown_seconds and (now - last_sent < self.cooldown_seconds) and (
            moved_after_last_signal < self.followup_move_pct
        ):
            return False, RejectReason(
                reason="cooldown",
                details=f"key={key} wait_left={int(self.cooldown_seconds - (now - last_sent))}s",
            )

        # Even after cooldown, reject stale repeats with nearly unchanged price and RSI.
        if (
            last_sent > 0
            and moved_after_last_signal < self.repeat_guard_min_move_pct
            and rsi_delta < self.repeat_guard_min_rsi_delta
        ):
            return False, RejectReason(
                reason="stale_repeat",
                details=(
                    f"key={key} move={moved_after_last_signal:.4f}% "
                    f"rsi_delta={rsi_delta:.2f}"
                ),
            )

        if self.soft_flip_window_seconds > 0 and side_state is not None:
            prev_ts, prev_price, prev_signal_type = side_state
            flip_move = self._pct_change(prev_price, candidate.current_price)
            if (
                prev_signal_type != candidate.signal_type
                and (now - prev_ts) < self.soft_flip_window_seconds
                and flip_move < self.soft_flip_min_move_pct
            ):
                details = (
                    f"key={side_key} prev={prev_signal_type} new={candidate.signal_type} "
                    f"move={flip_move:.4f}% window={self.soft_flip_window_seconds}s"
                )
                if self.soft_flip_log_only:
                    log.info("soft_flip_trace allow details=%s", details)
                else:
                    return False, RejectReason(reason="soft_flip_guard", details=details)

        self._last_fingerprint_at[fingerprint] = now

        self._last_sent_at[key] = now
        self._last_sent_price[key] = candidate.current_price
        self._last_sent_rsi[key] = candidate.rsi_value
        self._last_side_state[side_key] = (now, candidate.current_price, candidate.signal_type)
        return True, None

    def _gc_in_memory_state(self, now: float) -> None:
        if (now - self._last_gc_ts) < self.memory_gc_interval_seconds:
            return
        self._last_gc_ts = now
        cutoff = now - self.memory_state_ttl_seconds

        stale_cooldown_keys = [key for key, ts in self._last_sent_at.items() if ts < cutoff]
        for key in stale_cooldown_keys:
            self._last_sent_at.pop(key, None)
            self._last_sent_price.pop(key, None)
            self._last_sent_rsi.pop(key, None)

        stale_fp_keys = [key for key, ts in self._last_fingerprint_at.items() if ts < cutoff]
        for key in stale_fp_keys:
            self._last_fingerprint_at.pop(key, None)

        stale_side_keys = [key for key, state in self._last_side_state.items() if state[0] < cutoff]
        for key in stale_side_keys:
            self._last_side_state.pop(key, None)

        # Soft cap protection if process lives very long without Redis state.
        if len(self._last_fingerprint_at) > self.memory_state_max_keys:
            overflow = len(self._last_fingerprint_at) - int(self.memory_state_max_keys * 0.8)
            if overflow > 0:
                oldest = sorted(self._last_fingerprint_at.items(), key=lambda item: item[1])[:overflow]
                for key, _ in oldest:
                    self._last_fingerprint_at.pop(key, None)

    async def _accept_redis(
        self,
        candidate: RsiSignalCandidate,
        *,
        scope: str,
    ) -> tuple[bool, RejectReason | None]:
        assert self._redis is not None
        now = time.time()
        key = self._cooldown_key(candidate, scope)
        cooldown_key = f"{self.redis_prefix}:cooldown:{'|'.join(key)}"
        fingerprint = self._fingerprint(candidate, scope)
        fingerprint_key = f"{self.redis_prefix}:fingerprint:{fingerprint}"
        side_key = self._side_key(candidate, scope)
        side_state_key = f"{self.redis_prefix}:side:{'|'.join(side_key)}"

        existing_fp_ts = await self._redis.get(fingerprint_key)
        if existing_fp_ts:
            return False, RejectReason(
                reason="duplicate",
                details="identical signal already sent (fingerprint exists)",
            )
        state_raw = await self._redis.get(cooldown_key)
        side_raw = await self._redis.get(side_state_key)

        prev_rsi = candidate.rsi_value
        if state_raw:
            try:
                parts = state_raw.split("|")
                prev_ts_s = parts[0]
                prev_price_s = parts[1] if len(parts) > 1 else "0"
                prev_rsi_s = parts[2] if len(parts) > 2 else str(candidate.rsi_value)
                prev_ts = float(prev_ts_s)
                prev_price = float(prev_price_s)
                prev_rsi = float(prev_rsi_s)
            except ValueError:
                prev_ts = 0.0
                prev_price = 0.0
                prev_rsi = candidate.rsi_value
            moved_after_last_signal = self._pct_change(prev_price, candidate.current_price)
            rsi_delta = abs(candidate.rsi_value - prev_rsi)
            if self.cooldown_seconds and (now - prev_ts < self.cooldown_seconds) and (
                moved_after_last_signal < self.followup_move_pct
            ):
                return False, RejectReason(
                    reason="cooldown",
                    details=(
                        f"key={key} wait_left={int(self.cooldown_seconds - (now - prev_ts))}s"
                    ),
                )
            if (
                prev_ts > 0
                and moved_after_last_signal < self.repeat_guard_min_move_pct
                and rsi_delta < self.repeat_guard_min_rsi_delta
            ):
                return False, RejectReason(
                    reason="stale_repeat",
                    details=(
                        f"key={key} move={moved_after_last_signal:.4f}% "
                        f"rsi_delta={rsi_delta:.2f}"
                    ),
                )

        if self.soft_flip_window_seconds > 0 and side_raw:
            try:
                side_parts = side_raw.split("|")
                prev_side_ts = float(side_parts[0])
                prev_side_price = float(side_parts[1])
                prev_signal_type = side_parts[2] if len(side_parts) > 2 else ""
            except ValueError:
                prev_side_ts = 0.0
                prev_side_price = 0.0
                prev_signal_type = ""
            flip_move = self._pct_change(prev_side_price, candidate.current_price)
            if (
                prev_side_ts > 0
                and prev_signal_type != candidate.signal_type
                and (now - prev_side_ts) < self.soft_flip_window_seconds
                and flip_move < self.soft_flip_min_move_pct
            ):
                details = (
                    f"key={side_key} prev={prev_signal_type} new={candidate.signal_type} "
                    f"move={flip_move:.4f}% window={self.soft_flip_window_seconds}s"
                )
                if self.soft_flip_log_only:
                    log.info("soft_flip_trace allow details=%s", details)
                else:
                    return False, RejectReason(reason="soft_flip_guard", details=details)

        ttl = max(self.cooldown_seconds, self.dedup_window_seconds, 3600)
        await self._redis.set(cooldown_key, f"{now}|{candidate.current_price}|{candidate.rsi_value}", ex=ttl)
        await self._redis.set(
            side_state_key,
            f"{now}|{candidate.current_price}|{candidate.signal_type}",
            ex=max(self.soft_flip_window_seconds, 300),
        )

        # Keep fingerprint globally visible across workers.
        await self._redis.set(fingerprint_key, str(now), ex=max(self.dedup_window_seconds, 300))
        return True, None

    async def accept(
        self,
        candidate: RsiSignalCandidate,
        *,
        scope: str = "global",
    ) -> tuple[bool, RejectReason | None]:
        if self._redis is None:
            async with self._lock:
                return await self._accept_in_memory(candidate, scope=scope)
        return await self._accept_redis(candidate, scope=scope)

    async def aclose(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()

