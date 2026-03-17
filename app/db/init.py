from __future__ import annotations

from sqlalchemy import text

from app.db.base import Base
from app.db.session import engine


async def init_db() -> None:
    # Для dev-запуска создаем таблицы автоматически.
    # В проде это заменяется миграциями Alembic.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Backward-compatible additive schema updates for existing databases.
        await conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS signal_type VARCHAR(16)"))
        await conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS market_type VARCHAR(16)"))
        await conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS trigger_source VARCHAR(32)"))
        await conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS rsi_value DOUBLE PRECISION"))
        await conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS prev_price DOUBLE PRECISION"))
        # Widen legacy columns to support verbose live/strategy labels.
        await conn.execute(text("ALTER TABLE signals ALTER COLUMN signal_type TYPE VARCHAR(32)"))
        await conn.execute(text("ALTER TABLE scan_logs ALTER COLUMN event TYPE VARCHAR(64)"))
        await conn.execute(text("ALTER TABLE user_signal_settings ADD COLUMN IF NOT EXISTS min_price_move_pct DOUBLE PRECISION"))
        await conn.execute(text("ALTER TABLE user_signal_settings ADD COLUMN IF NOT EXISTS signal_side_mode VARCHAR(16)"))
        await conn.execute(text("ALTER TABLE user_signal_settings ADD COLUMN IF NOT EXISTS market_type VARCHAR(16)"))
        await conn.execute(text("ALTER TABLE user_signal_settings ADD COLUMN IF NOT EXISTS feed_mode_enabled BOOLEAN"))
        await conn.execute(text("ALTER TABLE user_signal_settings ADD COLUMN IF NOT EXISTS strategy_mode_enabled BOOLEAN"))
        await conn.execute(
            text(
                "UPDATE user_signal_settings SET feed_mode_enabled = TRUE "
                "WHERE feed_mode_enabled IS NULL"
            )
        )
        await conn.execute(
            text(
                "UPDATE user_signal_settings SET strategy_mode_enabled = TRUE "
                "WHERE strategy_mode_enabled IS NULL"
            )
        )
        await conn.execute(text("ALTER TABLE user_signal_settings ADD COLUMN IF NOT EXISTS rsi_enabled BOOLEAN DEFAULT TRUE"))
        await conn.execute(
            text(
                "UPDATE user_signal_settings SET rsi_enabled = TRUE "
                "WHERE rsi_enabled IS NULL"
            )
        )

