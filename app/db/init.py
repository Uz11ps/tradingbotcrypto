from __future__ import annotations

from app.db.base import Base
from app.db.session import engine


async def init_db() -> None:
    # Для dev-запуска создаем таблицы автоматически.
    # В проде это заменяется миграциями Alembic.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

