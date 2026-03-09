from __future__ import annotations

import time
from dataclasses import dataclass

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
    ) -> None:
        self.cooldown_seconds = max(0, cooldown_seconds)
        self.dedup_window_seconds = max(0, dedup_window_seconds)
        self.followup_move_pct = max(0.0, followup_move_pct)
        self._last_sent_at: dict[tuple[str, str, str, str], float] = {}
        self._last_fingerprint_at: dict[str, float] = {}
        self._last_sent_price: dict[tuple[str, str, str, str], float] = {}

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

    def accept(self, candidate: RsiSignalCandidate, *, scope: str = "global") -> tuple[bool, RejectReason | None]:
        now = time.time()
        key = self._cooldown_key(candidate, scope)
        last_sent = self._last_sent_at.get(key, 0.0)
        last_price = self._last_sent_price.get(key, 0.0)
        moved_after_last_signal = self._pct_change(last_price, candidate.current_price)

        # Cooldown can be bypassed when movement continues strongly.
        if self.cooldown_seconds and (now - last_sent < self.cooldown_seconds) and (
            moved_after_last_signal < self.followup_move_pct
        ):
            return False, RejectReason(
                reason="cooldown",
                details=f"key={key} wait_left={int(self.cooldown_seconds - (now - last_sent))}s",
            )

        fingerprint = self._fingerprint(candidate, scope)
        self._last_fingerprint_at[fingerprint] = now

        self._last_sent_at[key] = now
        self._last_sent_price[key] = candidate.current_price
        return True, None

