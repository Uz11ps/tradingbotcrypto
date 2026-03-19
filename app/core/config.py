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
    feed_universe_size: int = 500
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
    bingx_futures_klines_url: str = "https://open-api.bingx.com/openApi/swap/v2/quote/klines"
    bingx_futures_ticker_url: str = "https://open-api.bingx.com/openApi/swap/v2/quote/ticker"
    signal_dedup_window_seconds: int = 900
    signal_min_abs_change_pct: float = 1.5
    signal_volume_spike_multiplier: float = 2.0
    signal_volume_avg_window: int = 20
    signal_price_change_5m_trigger_pct: float = 1.5
    signal_price_change_15m_trigger_pct: float = 3.0
    signal_trigger_mode: str = "candle"  # candle | live_spike | both
    signal_live_spike_5m_trigger_pct: float = 2.5
    signal_live_spike_15m_trigger_pct: float = 4.0
    signal_volume_multiplier_base: float = 1.35
    signal_volume_multiplier_strong: float = 1.2
    signal_strong_move_pct: float = 5.0
    signal_followup_move_pct: float = 1.5
    signal_repeat_guard_min_move_pct: float = 0.4
    signal_repeat_guard_min_rsi_delta: float = 2.0
    signal_soft_flip_window_seconds: int = 300
    signal_soft_flip_min_move_pct: float = 1.0
    signal_soft_flip_log_only: bool = True
    signal_filter_redis_prefix: str = "signal_filter"
    signal_filter_memory_state_ttl_seconds: int = 7200
    signal_filter_memory_state_max_keys: int = 200_000
    signal_filter_memory_gc_interval_seconds: int = 60
    signal_retention_days: int = 3
    signal_retention_prune_interval_seconds: int = 1800
    signal_stats_short_window_hours: int = 72
    signal_stats_short_max_rows: int = 200
    signal_chat_symbol_budget_per_cycle: int = 120
    signal_debug_full_enabled: bool = False
    signal_debug_reject_sample_rate: float = 0.2
    signal_debug_log_limit_per_cycle: int = 500
    signal_disable_double_min_move_filter: bool = True
    signal_enable_futures_adapter: bool = False
    signal_market_route_trace_enabled: bool = True
    signal_live_price_enabled: bool = True
    signal_live_price_cache_ttl_seconds: float = 1.5
    signal_live_detector_enabled: bool = False
    signal_shadow_mode_enabled: bool = True
    signal_send_enabled: bool = True
    signal_contract_version: str = "v2"
    signal_live_ws_url: str = "wss://open-api-ws.bingx.com/market"
    signal_live_shadow_symbols: str = "BTC/USDT,ETH/USDT,SOL/USDT"
    signal_live_ws_reconnect_seconds: float = 3.0
    signal_live_ws_reconnect_max_seconds: float = 20.0
    signal_live_ws_reconnect_jitter_seconds: float = 0.75
    signal_live_shadow_log_interval_cycles: int = 3
    signal_live_ingest_owner_lock_ttl_seconds: int = 90
    worker_shard_slot_lock_ttl_seconds: int = 120
    worker_shard_slot_retry_interval_seconds: float = 3.0
    worker_shard_fail_open_enabled: bool = True
    worker_shard_fail_open_after_retries: int = 20

    log_level: str = "INFO"


settings = Settings()
