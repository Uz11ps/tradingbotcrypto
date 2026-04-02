from __future__ import annotations

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

from app.core.config import settings


def build_telegram_bot(*, token: str | None = None) -> Bot:
    api_base = settings.telegram_api_base.strip()
    proxy = settings.telegram_http_proxy.strip() or None
    session_kwargs: dict[str, object] = {}
    if proxy is not None:
        session_kwargs["proxy"] = proxy
    if api_base and api_base != "https://api.telegram.org":
        session_kwargs["api"] = TelegramAPIServer.from_base(api_base)
    session = AiohttpSession(**session_kwargs)
    return Bot(token=token or settings.telegram_bot_token, session=session)
