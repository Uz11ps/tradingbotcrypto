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
from app.core.config import settings

router = Router()


def _base_symbol(symbol: str) -> str:
    return symbol.split("/")[0]


def _home_text() -> str:
    return (
        "Сигнальный бот (MVP)\n\n"
        "Сценарий: Binance сканер -> Pump/Dump сигналы -> потоковая лента.\n"
        "Выберите раздел:"
    )


def _settings_text(cfg: dict[str, object]) -> str:
    active = ", ".join(cfg.get("active_timeframes", [])) or "-"
    return (
        "Настройки фильтрации\n\n"
        f"Активные таймфреймы: {active}\n"
        f"RSI lower: {float(cfg.get('lower_rsi', 25)):.0f}\n"
        f"RSI upper: {float(cfg.get('upper_rsi', 75)):.0f}\n"
        f"Min quote volume: {float(cfg.get('min_quote_volume', settings.binance_min_quote_volume)):.0f}\n\n"
        "Измени параметры кнопками ниже."
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
            lower_rsi=float(cfg.get("lower_rsi", 25)),
            upper_rsi=float(cfg.get("upper_rsi", 75)),
        ),
    )


@router.message(CommandStart())
async def start(m: Message, state: FSMContext) -> None:
    await state.set_state(UserFlow.main)
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


def _format_feed_row(row: dict[str, object]) -> str:
    signal_type = str(row.get("signal_type", "pump")).lower()
    emoji = "🟢" if signal_type == "pump" else "🔴"
    label = "PUMP" if signal_type == "pump" else "DUMP"
    symbol = _base_symbol(str(row.get("symbol", "")))
    pct = float(row.get("change_pct", 0.0))
    prev_price = float(row.get("prev_price", 0.0))
    current_price = float(row.get("current_price", 0.0))
    generated_at = str(row.get("generated_at", ""))
    hhmm = generated_at[11:16] if len(generated_at) >= 16 else "--:--"
    return (
        f"{emoji} {symbol}\n"
        f"{label}: {pct:+.2f}%\n"
        f"Цена: {prev_price:.6f} -> {current_price:.6f}\n"
        f"Время: {hhmm}"
    )


@router.callback_query(F.data == "menu:feed")
async def menu_feed(c: CallbackQuery, api: ApiClient) -> None:
    try:
        feed = await api.get_feed_movers(
            universe=settings.feed_universe_size,
            limit=settings.feed_movers_limit,
            min_change_pct=settings.feed_min_change_pct,
            chat_id=c.message.chat.id,
        )
    except Exception as e:
        await c.message.edit_text(f"Ошибка ленты: {e}", reply_markup=panel_actions_kb())
        await c.answer()
        return

    movers = feed.get("movers", [])
    lines = [f"Лента сигналов ({feed.get('universe_size', 0)} монет в сканере)", ""]
    if not movers:
        lines.append("Пока нет RSI экстремумов по текущим фильтрам.")
    else:
        for row in movers[: min(len(movers), settings.feed_movers_limit)]:
            lines.append(_format_feed_row(row))
            lines.append("")
    await c.message.edit_text("\n".join(lines), reply_markup=panel_actions_kb())
    await c.answer()


@router.callback_query(F.data.startswith("settings:tf:"))
async def toggle_timeframe(c: CallbackQuery, api: ApiClient) -> None:
    tf = c.data.split(":")[-1]
    cfg = await api.get_user_settings(chat_id=c.message.chat.id)
    active = list(cfg.get("active_timeframes", []))
    if tf in active:
        active = [x for x in active if x != tf]
    else:
        active.append(tf)
    if not active:
        await c.answer("Нужен хотя бы 1 таймфрейм", show_alert=True)
        return
    await api.update_user_settings(chat_id=c.message.chat.id, active_timeframes=active)
    await _render_settings(c, api)
    await c.answer("Таймфреймы обновлены")


@router.callback_query(F.data.startswith("settings:rsi:"))
async def change_rsi(c: CallbackQuery, api: ApiClient) -> None:
    _, _, bound, direction = c.data.split(":")
    cfg = await api.get_user_settings(chat_id=c.message.chat.id)
    lower = float(cfg.get("lower_rsi", 25))
    upper = float(cfg.get("upper_rsi", 75))
    step = 1.0
    delta = step if direction == "up" else -step

    if bound == "lower":
        lower = max(5.0, min(45.0, lower + delta))
        if lower >= upper:
            await c.answer("Lower должен быть меньше Upper", show_alert=True)
            return
    else:
        upper = max(55.0, min(95.0, upper + delta))
        if upper <= lower:
            await c.answer("Upper должен быть больше Lower", show_alert=True)
            return

    await api.update_user_settings(chat_id=c.message.chat.id, lower_rsi=lower, upper_rsi=upper)
    await _render_settings(c, api)
    await c.answer("RSI пороги обновлены")


@router.callback_query(F.data == "settings:reset")
async def reset_settings(c: CallbackQuery, api: ApiClient) -> None:
    await api.update_user_settings(
        chat_id=c.message.chat.id,
        lower_rsi=settings.rsi_default_lower,
        upper_rsi=settings.rsi_default_upper,
        active_timeframes=["5m", "15m", "1h", "4h"],
        min_quote_volume=settings.binance_min_quote_volume,
    )
    await _render_settings(c, api)
    await c.answer("Сброшено на дефолт")


@router.callback_query(F.data == "menu:info")
async def menu_info(c: CallbackQuery) -> None:
    text = (
        "Информация\n\n"
        "Режим: тестовый сигнальный бот.\n"
        "Источник: Binance spot USDT.\n"
        "Логика: RSI экстремумы (Pump/Dump).\n"
        "Режим движка: legacy/rsi через feature flag."
    )
    await c.message.edit_text(text, reply_markup=panel_actions_kb())
    await c.answer()

