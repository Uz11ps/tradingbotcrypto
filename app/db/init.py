from __future__ import annotations

from sqlalchemy import text

from app.core.config import settings
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
        await conn.execute(text("ALTER TABLE user_signal_settings ADD COLUMN IF NOT EXISTS strategy_impulse_window INTEGER"))
        await conn.execute(
            text(
                "ALTER TABLE user_signal_settings "
                "ADD COLUMN IF NOT EXISTS strategy_deviation_threshold_pct DOUBLE PRECISION"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE user_signal_settings "
                "ADD COLUMN IF NOT EXISTS strategy_min_pinbar_strength DOUBLE PRECISION"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE user_signal_settings "
                "ADD COLUMN IF NOT EXISTS strategy_max_body_ratio DOUBLE PRECISION"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE user_signal_settings "
                "ADD COLUMN IF NOT EXISTS strategy_max_signals_per_cycle INTEGER"
            )
        )
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
        await conn.execute(
            text(
                "UPDATE user_signal_settings SET strategy_impulse_window = :default_value "
                "WHERE strategy_impulse_window IS NULL"
            ),
            {"default_value": int(settings.signal_strategy_impulse_window)},
        )
        await conn.execute(
            text(
                "UPDATE user_signal_settings SET strategy_deviation_threshold_pct = :default_value "
                "WHERE strategy_deviation_threshold_pct IS NULL"
            ),
            {"default_value": float(settings.signal_strategy_deviation_threshold_pct)},
        )
        await conn.execute(
            text(
                "UPDATE user_signal_settings SET strategy_min_pinbar_strength = :default_value "
                "WHERE strategy_min_pinbar_strength IS NULL"
            ),
            {"default_value": float(settings.signal_strategy_min_pinbar_strength)},
        )
        await conn.execute(
            text(
                "UPDATE user_signal_settings SET strategy_max_body_ratio = :default_value "
                "WHERE strategy_max_body_ratio IS NULL"
            ),
            {"default_value": float(settings.signal_strategy_max_body_ratio)},
        )
        await conn.execute(
            text(
                "UPDATE user_signal_settings SET strategy_max_signals_per_cycle = :default_value "
                "WHERE strategy_max_signals_per_cycle IS NULL"
            ),
            {"default_value": int(settings.signal_strategy_max_signals_per_cycle)},
        )
        await conn.execute(text("ALTER TABLE user_signal_settings ADD COLUMN IF NOT EXISTS rsi_enabled BOOLEAN DEFAULT TRUE"))
        await conn.execute(
            text(
                "UPDATE user_signal_settings SET rsi_enabled = TRUE "
                "WHERE rsi_enabled IS NULL"
            )
        )

