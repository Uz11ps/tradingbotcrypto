from __future__ import annotations

import time
from dataclasses import dataclass

from app.services.rsi_engine import RsiSignalCandidate


@dataclass(slots=True)
class RejectReason:
    reason: str
    details: str


class SignalFilterEngine:
    def __init__(self, *, cooldown_seconds: int, dedup_window_seconds: int) -> None:
        self.cooldown_seconds = max(0, cooldown_seconds)
        self.dedup_window_seconds = max(0, dedup_window_seconds)
        self._last_sent_at: dict[tuple[str, str, str], float] = {}
        self._last_fingerprint_at: dict[str, float] = {}

    @staticmethod
    def _cooldown_key(candidate: RsiSignalCandidate) -> tuple[str, str, str]:
        return (candidate.symbol, candidate.timeframe, candidate.signal_type)

    @staticmethod
    def _fingerprint(candidate: RsiSignalCandidate) -> str:
        # Fingerprint keeps message-level uniqueness while preserving signal key cooldown.
        return (
            f"{candidate.symbol}|{candidate.timeframe}|{candidate.signal_type}|"
            f"{candidate.rsi_value:.2f}|{candidate.current_price:.8f}"
        )

    def accept(self, candidate: RsiSignalCandidate) -> tuple[bool, RejectReason | None]:
        now = time.time()
        key = self._cooldown_key(candidate)
        last_sent = self._last_sent_at.get(key, 0.0)
        if self.cooldown_seconds and (now - last_sent < self.cooldown_seconds):
            return False, RejectReason(
                reason="cooldown",
                details=f"key={key} wait_left={int(self.cooldown_seconds - (now - last_sent))}s",
            )

        fingerprint = self._fingerprint(candidate)
        last_dup = self._last_fingerprint_at.get(fingerprint, 0.0)
        if self.dedup_window_seconds and (now - last_dup < self.dedup_window_seconds):
            return False, RejectReason(
                reason="duplicate",
                details=f"fingerprint={fingerprint}",
            )

        self._last_sent_at[key] = now
        self._last_fingerprint_at[fingerprint] = now
        return True, None

