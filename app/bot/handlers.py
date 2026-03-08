from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.api_client import ApiClient
from app.bot.keyboards import (
    main_menu_kb,
    panel_actions_kb,
    settings_kb,
)
from app.bot.states import UserFlow

router = Router()


def _home_text() -> str:
    return (
        "Сигнальный бот\n\n"
        "Сканируем Binance и отправляем Pump/Dump сигналы потоком в чат.\n"
        "Выберите раздел:"
    )


def _settings_text(cfg: dict[str, object]) -> str:
    active = ", ".join(cfg.get("active_timeframes", [])) or "15m"
    return (
        "Настройки фильтрации\n\n"
        f"Таймфрейм для сигналов: {active}\n"
        "Выберите один таймфрейм кнопками ниже."
    )


async def _render_home(target: Message | CallbackQuery, state: FSMContext) -> None:
    text = _home_text()
    if isinstance(target, Message):
        await target.answer(text, reply_markup=main_menu_kb())
    else:
        await target.message.edit_text(text, reply_markup=main_menu_kb())


async def _render_settings(c: CallbackQuery, api: ApiClient) -> None:
    cfg = await api.get_user_settings(chat_id=c.message.chat.id)
    text = _settings_text(cfg)
    await c.message.edit_text(
        text,
        reply_markup=settings_kb(
            active_timeframes=list(cfg.get("active_timeframes", [])),
        ),
    )


@router.message(CommandStart())
async def start(m: Message, state: FSMContext, api: ApiClient) -> None:
    await state.set_state(UserFlow.main)
    # Register this chat for push stream delivery.
    await api.update_user_settings(chat_id=m.chat.id)
    await _render_home(m, state)


@router.callback_query(F.data == "menu:home")
async def menu_home(c: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(UserFlow.main)
    await _render_home(c, state)
    await c.answer()


@router.callback_query(F.data == "menu:settings")
async def menu_settings(c: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    await state.set_state(UserFlow.main)
    await _render_settings(c, api)
    await c.answer()


@router.callback_query(F.data == "menu:feed")
async def menu_feed(c: CallbackQuery) -> None:
    text = (
        "Лента сигналов работает в потоковом режиме.\n"
        "Новые Pump/Dump сигналы приходят отдельными сообщениями в этот чат."
    )
    await c.message.edit_text(text, reply_markup=panel_actions_kb())
    await c.answer()


@router.callback_query(F.data.startswith("settings:tf:"))
async def toggle_timeframe(c: CallbackQuery, api: ApiClient) -> None:
    tf = c.data.split(":")[-1]
    await api.update_user_settings(chat_id=c.message.chat.id, active_timeframes=[tf])
    await _render_settings(c, api)
    await c.answer("Таймфрейм обновлен")

@router.callback_query(F.data == "menu:info")
async def menu_info(c: CallbackQuery) -> None:
    text = (
        "Информация\n\n"
        "Бот отслеживает рынок Binance и отправляет поток Pump/Dump сигналов.\n"
        "Чтобы получать сигналы чаще, включите больше таймфреймов в настройках."
    )
    await c.message.edit_text(text, reply_markup=panel_actions_kb())
    await c.answer()

