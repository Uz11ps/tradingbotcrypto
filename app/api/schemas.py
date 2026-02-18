from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SignalOut(BaseModel):
    id: int
    created_at: datetime
    symbol: str
    timeframe: str
    direction: str
    strength: float = Field(ge=0, le=1)
    action: str
    source: str = "hybrid"
    price: float | None = None
    volume: float | None = None
    liquidity: float | None = None
    reason: str | None = None


class SignalCreate(BaseModel):
    symbol: str
    timeframe: str
    direction: str
    strength: float = Field(ge=0, le=1)
    action: str
    source: str = "hybrid"
    price: float | None = None
    volume: float | None = None
    liquidity: float | None = None
    reason: str | None = None


class AnalyticsOut(BaseModel):
    symbol: str
    timeframe: str
    summary: str
    ai_explanation: str
    avg_news_sentiment: float


class LiveSignalOut(BaseModel):
    symbol: str
    timeframe: str
    generated_at: datetime
    direction: str
    strength: float = Field(ge=0, le=1)
    action: str
    source: str = "hybrid"
    price: float
    price_change_pct: float
    volume: float
    liquidity: float | None = None
    volume_change_pct: float
    volatility_pct: float
    trend: str
    summary: str
    ai_score: float
    ai_explanation: str


class StatsOverviewOut(BaseModel):
    total_signals: int
    up_signals: int
    down_signals: int


class PerformanceStatsOut(BaseModel):
    evaluated_signals: int
    winrate_pct: float
    hit_ratio_pct: float
    avg_pnl_pct: float
    total_pnl_pct: float
    max_drawdown_pct: float
    profit_factor: float


class NewsItemOut(BaseModel):
    source: str
    title: str
    url: str
    sentiment: float


class NewsSentimentOut(BaseModel):
    symbol: str
    avg_sentiment: float
    headlines: list[NewsItemOut]


class MarketOverviewOut(BaseModel):
    symbol: str
    timeframe: str
    cex_price: float
    cex_price_change_pct: float
    cex_volume: float
    dex_price: float | None = None
    dex_price_change_1h_pct: float | None = None
    dex_liquidity_usd: float | None = None
    avg_news_sentiment: float
    ai_score: float
    ai_action: str
    ai_explanation: str
    summary: str


class SubscriptionOut(BaseModel):
    id: int
    chat_id: int
    symbol: str
    timeframe: str
    is_active: bool


class SubscriptionCreate(BaseModel):
    chat_id: int
    symbol: str
    timeframe: str


class SubscriptionDelete(BaseModel):
    chat_id: int
    symbol: str
    timeframe: str

