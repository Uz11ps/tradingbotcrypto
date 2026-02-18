from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

try:
    from aiogram.fsm.storage.redis import RedisStorage

    _HAS_REDIS_STORAGE = True
except Exception:  # pragma: no cover
    _HAS_REDIS_STORAGE = False

from app.bot.api_client import ApiClient
from app.bot.handlers import router
from app.core.config import settings
from app.core.logging import setup_logging

log = logging.getLogger("bot.main")


def _build_storage():
    if _HAS_REDIS_STORAGE and settings.redis_url:
        return RedisStorage.from_url(settings.redis_url)
    return MemoryStorage()


async def main() -> None:
    setup_logging(settings.log_level)
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is empty. Fill .env (see .env.example).")

    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher(storage=_build_storage())

    api = ApiClient()
    dp["api"] = api  # dependency injection into handlers via parameter name

    dp.include_router(router)

    try:
        await dp.start_polling(bot)
    finally:
        await api.aclose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

