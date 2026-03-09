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
    min_price_move = float(cfg.get("min_price_move_pct", 1.5))
    lower_rsi = float(cfg.get("lower_rsi", 40))
    upper_rsi = float(cfg.get("upper_rsi", 60))
    return (
        "Настройки фильтрации\n\n"
        f"Таймфрейм для сигналов: {active}\n"
        f"Процент отклонения: {min_price_move:.1f}%\n"
        f"RSI: {lower_rsi:.0f}/{upper_rsi:.0f}\n"
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
            lower_rsi=float(cfg.get("lower_rsi", 40)),
            upper_rsi=float(cfg.get("upper_rsi", 60)),
            min_price_move_pct=float(cfg.get("min_price_move_pct", 1.5)),
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


@router.callback_query(F.data.startswith("settings:move:"))
async def change_min_price_move(c: CallbackQuery, api: ApiClient) -> None:
    direction = c.data.split(":")[-1]
    cfg = await api.get_user_settings(chat_id=c.message.chat.id)
    current = float(cfg.get("min_price_move_pct", 1.5))
    step = 0.5
    updated = current + step if direction == "up" else current - step
    updated = max(0.5, min(5.0, updated))
    await api.update_user_settings(chat_id=c.message.chat.id, min_price_move_pct=updated)
    await _render_settings(c, api)
    await c.answer("Отклонение обновлено")


@router.callback_query(F.data.startswith("settings:rsi:"))
async def change_rsi(c: CallbackQuery, api: ApiClient) -> None:
    _, _, bound, direction = c.data.split(":")
    cfg = await api.get_user_settings(chat_id=c.message.chat.id)
    lower = float(cfg.get("lower_rsi", 40))
    upper = float(cfg.get("upper_rsi", 60))
    delta = 1.0 if direction == "up" else -1.0

    if bound == "lower":
        lower = max(5.0, min(45.0, lower + delta))
        if lower >= upper:
            await c.answer("Нижний RSI должен быть меньше верхнего", show_alert=True)
            return
    else:
        upper = max(55.0, min(95.0, upper + delta))
        if upper <= lower:
            await c.answer("Верхний RSI должен быть больше нижнего", show_alert=True)
            return

    await api.update_user_settings(chat_id=c.message.chat.id, lower_rsi=lower, upper_rsi=upper)
    await _render_settings(c, api)
    await c.answer("RSI обновлен")

@router.callback_query(F.data == "menu:info")
async def menu_info(c: CallbackQuery) -> None:
    text = (
        "Информация\n\n"
        "Бот отслеживает рынок Binance и отправляет поток Pump/Dump сигналов.\n"
        "Чтобы получать сигналы чаще, включите больше таймфреймов в настройках."
    )
    await c.message.edit_text(text, reply_markup=panel_actions_kb())
    await c.answer()

