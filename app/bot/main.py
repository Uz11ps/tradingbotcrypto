from __future__ import annotations

import asyncio
import logging

from aiogram import Dispatcher
from aiogram.exceptions import TelegramNetworkError
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
from app.core.telegram import build_telegram_bot

log = logging.getLogger("bot.main")


def _build_storage():
    if _HAS_REDIS_STORAGE and settings.redis_url:
        return RedisStorage.from_url(settings.redis_url)
    return MemoryStorage()


async def main() -> None:
    setup_logging(settings.log_level)
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is empty. Fill .env (see .env.example).")

    bot = build_telegram_bot()
    dp = Dispatcher(storage=_build_storage())

    api = ApiClient()
    dp["api"] = api  # dependency injection into handlers via parameter name

    dp.include_router(router)

    try:
        while True:
            try:
                await dp.start_polling(bot)
                break
            except TelegramNetworkError:
                log.exception("Telegram API is unreachable, retrying polling startup")
                await asyncio.sleep(max(1.0, settings.telegram_polling_start_retry_seconds))
    finally:
        await api.aclose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

