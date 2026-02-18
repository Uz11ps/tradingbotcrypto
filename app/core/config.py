from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = ""
    telegram_signals_chat_id: int = 0

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_public_base_url: str = "http://127.0.0.1:8000"

    database_url: str = "postgresql+asyncpg://cryptoarbi:cryptoarbi@127.0.0.1:5432/cryptoarbi"
    redis_url: str = "redis://127.0.0.1:6379/0"
    worker_interval_seconds: int = 20

    log_level: str = "INFO"


settings = Settings()

