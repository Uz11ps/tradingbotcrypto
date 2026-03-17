from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Float, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SignalDirection(enum.StrEnum):
    up = "up"
    down = "down"


class SignalType(enum.StrEnum):
    pump = "pump"
    dump = "dump"
    post_dump_bounce_long = "post_dump_bounce_long"
    post_pump_pullback_short = "post_pump_pullback_short"


class MarketType(enum.StrEnum):
    spot = "spot"
    futures = "futures"
    both = "both"


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    symbol: Mapped[str] = mapped_column(String(32), index=True)  # e.g. BTC/USDT
    timeframe: Mapped[str] = mapped_column(String(16), index=True)  # e.g. 15m, 1h, 4h, 1d

    direction: Mapped[SignalDirection] = mapped_column(Enum(SignalDirection))
    strength: Mapped[float] = mapped_column(Float)  # 0..1
    action: Mapped[str] = mapped_column(String(16))  # entry/exit/hold

    signal_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    market_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    trigger_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rsi_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    prev_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class AnalyticsLog(Base):
    __tablename__ = "analytics_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    symbol: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(16), index=True)
    payload: Mapped[str] = mapped_column(Text)  # JSON string


class AISetting(Base):
    __tablename__ = "ai_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text)


class UserSubscription(Base):
    __tablename__ = "user_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(16), index=True)
    is_active: Mapped[bool] = mapped_column(default=True)


class UserSignalSettings(Base):
    __tablename__ = "user_signal_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    lower_rsi: Mapped[float | None] = mapped_column(Float, nullable=True)
    upper_rsi: Mapped[float | None] = mapped_column(Float, nullable=True)
    active_timeframes: Mapped[str | None] = mapped_column(String(64), nullable=True)
    min_price_move_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_quote_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_side_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    market_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    feed_mode_enabled: Mapped[bool] = mapped_column(default=True)
    strategy_mode_enabled: Mapped[bool] = mapped_column(default=True)
    rsi_enabled: Mapped[bool] = mapped_column(default=True)


class RawCandidate(Base):
    __tablename__ = "raw_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    chat_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(16), index=True)
    market_type: Mapped[str] = mapped_column(String(16), index=True)
    mode: Mapped[str] = mapped_column(String(16), index=True)  # feed | strategy
    decision: Mapped[str] = mapped_column(String(16), index=True)  # accept | reject
    reject_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string


class ScanLog(Base):
    __tablename__ = "scan_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    chat_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(16), index=True)
    market_type: Mapped[str] = mapped_column(String(16), index=True)
    mode: Mapped[str] = mapped_column(String(16), index=True)
    event: Mapped[str] = mapped_column(String(64), index=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string


class NewsAndSentiment(Base):
    __tablename__ = "news_and_sentiment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    symbol: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(512))
    url: Mapped[str] = mapped_column(String(1024))
    sentiment: Mapped[float | None] = mapped_column(Float, nullable=True)  # -1..1
    raw: Mapped[str | None] = mapped_column(Text, nullable=True)


class SignalPerformance(Base):
    __tablename__ = "signal_performance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[int] = mapped_column(Integer, index=True, unique=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(16), index=True)
    pnl_pct: Mapped[float] = mapped_column(Float)
    is_win: Mapped[bool] = mapped_column(index=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


Index("ix_signals_symbol_timeframe_created_at", Signal.symbol, Signal.timeframe, Signal.created_at)
Index("ix_signals_symbol_signal_type_created_at", Signal.symbol, Signal.signal_type, Signal.created_at)
Index("ix_news_symbol_created_at", NewsAndSentiment.symbol, NewsAndSentiment.created_at)
Index("ix_subscriptions_chat_symbol_timeframe", UserSubscription.chat_id, UserSubscription.symbol, UserSubscription.timeframe, unique=True)
Index("ix_raw_candidates_symbol_created_at", RawCandidate.symbol, RawCandidate.created_at)
Index("ix_scan_logs_symbol_created_at", ScanLog.symbol, ScanLog.created_at)

