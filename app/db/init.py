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
        await conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS trigger_source VARCHAR(32)"))
        await conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS rsi_value DOUBLE PRECISION"))
        await conn.execute(text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS prev_price DOUBLE PRECISION"))

