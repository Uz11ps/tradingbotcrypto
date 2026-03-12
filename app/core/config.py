from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    telegram_bot_token: str = ""
    telegram_signals_chat_id: int = 0

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_public_base_url: str = "http://127.0.0.1:8000"

    database_url: str = (
        "postgresql+asyncpg://cryptoarbi:cryptoarbi@127.0.0.1:5432/cryptoarbi"
    )
    redis_url: str = "redis://127.0.0.1:6379/0"
    worker_interval_seconds: int = 20
    signal_worker_replicas: int = 5
    worker_shard_index: int = 0
    worker_shard_count: int = 1
    feed_universe_size: int = 300
    feed_movers_limit: int = 20
    feed_min_change_pct: float = 2.5
    worker_feed_cooldown_seconds: int = 1800
    signal_engine_mode: str = "legacy"  # legacy | rsi

    rsi_default_lower: float = 40.0
    rsi_default_upper: float = 60.0
    rsi_default_timeframes: str = "15m"
    rsi_period: int = 14

    bingx_quote_asset: str = "USDT"
    bingx_min_quote_volume: float = 1000000.0
    signal_dedup_window_seconds: int = 900
    signal_min_abs_change_pct: float = 1.5
    signal_volume_spike_multiplier: float = 2.0
    signal_volume_avg_window: int = 20
    signal_price_change_5m_trigger_pct: float = 1.5
    signal_price_change_15m_trigger_pct: float = 3.0
    signal_volume_multiplier_base: float = 1.35
    signal_volume_multiplier_strong: float = 1.2
    signal_strong_move_pct: float = 5.0
    signal_followup_move_pct: float = 1.5
    signal_repeat_guard_min_move_pct: float = 0.4
    signal_repeat_guard_min_rsi_delta: float = 2.0
    signal_filter_redis_prefix: str = "signal_filter"
    signal_retention_days: int = 14
    signal_retention_prune_interval_seconds: int = 3600
    signal_debug_full_enabled: bool = False
    signal_debug_log_limit_per_cycle: int = 500

    log_level: str = "INFO"


settings = Settings()
