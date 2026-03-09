from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from redis.asyncio import Redis

from app.services.rsi_engine import RsiSignalCandidate


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
        redis_url: str = "",
        redis_prefix: str = "signal_filter",
    ) -> None:
        self.cooldown_seconds = max(0, cooldown_seconds)
        self.dedup_window_seconds = max(0, dedup_window_seconds)
        self.followup_move_pct = max(0.0, followup_move_pct)
        self.redis_prefix = redis_prefix.strip() or "signal_filter"
        self._redis: Redis | None = Redis.from_url(redis_url, decode_responses=True) if redis_url else None
        self._last_sent_at: dict[tuple[str, str, str, str], float] = {}
        self._last_fingerprint_at: dict[str, float] = {}
        self._last_sent_price: dict[tuple[str, str, str, str], float] = {}
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
        key = self._cooldown_key(candidate, scope)
        last_sent = self._last_sent_at.get(key, 0.0)
        last_price = self._last_sent_price.get(key, 0.0)
        moved_after_last_signal = self._pct_change(last_price, candidate.current_price)

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

        self._last_fingerprint_at[fingerprint] = now

        self._last_sent_at[key] = now
        self._last_sent_price[key] = candidate.current_price
        return True, None

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

        existing_fp_ts = await self._redis.get(fingerprint_key)
        if existing_fp_ts:
            return False, RejectReason(
                reason="duplicate",
                details="identical signal already sent (fingerprint exists)",
            )
        state_raw = await self._redis.get(cooldown_key)

        if state_raw:
            try:
                prev_ts_s, prev_price_s = state_raw.split("|", maxsplit=1)
                prev_ts = float(prev_ts_s)
                prev_price = float(prev_price_s)
            except ValueError:
                prev_ts = 0.0
                prev_price = 0.0
            moved_after_last_signal = self._pct_change(prev_price, candidate.current_price)
            if self.cooldown_seconds and (now - prev_ts < self.cooldown_seconds) and (
                moved_after_last_signal < self.followup_move_pct
            ):
                return False, RejectReason(
                    reason="cooldown",
                    details=(
                        f"key={key} wait_left={int(self.cooldown_seconds - (now - prev_ts))}s"
                    ),
                )

        ttl = max(self.cooldown_seconds, self.dedup_window_seconds, 3600)
        await self._redis.set(cooldown_key, f"{now}|{candidate.current_price}", ex=ttl)

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

