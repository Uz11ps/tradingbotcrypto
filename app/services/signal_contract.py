from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal

TriggerSource = Literal["live_trade", "live_mid", "live_mark"]
SignalDirection = Literal["pump", "dump"]


@dataclass(slots=True)
class SignalTimestamps:
    exchange_event_ts_ms: int
    received_ts_ms: int
    processed_ts_ms: int
    sent_ts_ms: int | None = None

    def validate(self) -> None:
        if self.exchange_event_ts_ms <= 0:
            raise ValueError("exchange_event_ts_ms must be > 0")
        if self.received_ts_ms < self.exchange_event_ts_ms:
            raise ValueError("received_ts_ms must be >= exchange_event_ts_ms")
        if self.processed_ts_ms < self.received_ts_ms:
            raise ValueError("processed_ts_ms must be >= received_ts_ms")
        if self.sent_ts_ms is not None and self.sent_ts_ms < self.processed_ts_ms:
            raise ValueError("sent_ts_ms must be >= processed_ts_ms")


@dataclass(slots=True)
class LiveSignalContract:
    symbol: str
    market_type: str
    timeframe: str
    direction: SignalDirection
    trigger_source: TriggerSource
    window_seconds: int
    baseline_price: float
    current_price: float
    change_pct: float
    timestamps: SignalTimestamps
    signal_version: str = "v2"
    created_at: datetime = datetime.now(tz=UTC)
    reason: str | None = None

    def validate(self) -> None:
        if not self.symbol:
            raise ValueError("symbol is required")
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        if self.baseline_price <= 0:
            raise ValueError("baseline_price must be > 0")
        if self.current_price <= 0:
            raise ValueError("current_price must be > 0")
        if self.trigger_source not in {"live_trade", "live_mid", "live_mark"}:
            raise ValueError("trigger_source must be one of live_trade/live_mid/live_mark")
        self.timestamps.validate()

    def to_payload(self) -> dict[str, object]:
        self.validate()
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        return payload
