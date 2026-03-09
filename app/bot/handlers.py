from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.api_client import ApiClient
from app.bot.keyboards import (
    feed_kb,
    main_menu_kb,
    panel_actions_kb,
    settings_main_kb,
    timeframes_kb,
)
from app.bot.states import UserFlow

router = Router()


def _status_line(cfg: dict[str, object], *, universe: int, min_vol: float) -> str:
    tfs = " ".join(cfg.get("active_timeframes", [])) or "15m"
    rsi = f"{float(cfg.get('upper_rsi', 60)):.0f}/{float(cfg.get('lower_rsi', 40)):.0f}"
    trigger = (
        f"{float(cfg.get('min_price_move_pct', 1.5)):.1f}% / "
        f"{settings.signal_price_change_15m_trigger_pct:.1f}%"
    )
    feed_status = "Вкл"
    return (
        f"ТФ: {tfs} | Триггер: {trigger} | RSI: {rsi} | "
        f"Пары: {universe} (≥${min_vol/1_000_000:.1f}M) | Лента: {feed_status}"
    )


def _home_text(cfg: dict[str, object], *, universe: int, min_vol: float) -> str:
    return (
        "Сигнальный бот\n\n"
        "Сканируем Binance и отправляем Pump/Dump сигналы.\n\n"
        f"{_status_line(cfg, universe=universe, min_vol=min_vol)}"
    )


def _settings_text(cfg: dict[str, object]) -> str:
    active = " ".join(cfg.get("active_timeframes", [])) or "15m"
    lower_rsi = float(cfg.get("lower_rsi", 40))
    upper_rsi = float(cfg.get("upper_rsi", 60))
    min_vol = float(cfg.get("min_quote_volume", settings.binance_min_quote_volume))
    trigger_5m = float(cfg.get("min_price_move_pct", settings.signal_price_change_5m_trigger_pct))
    trigger_15m = settings.signal_price_change_15m_trigger_pct
    return (
        "⚙️ Настройки сигналов\n\n"
        f"Таймфреймы: {active}\n"
        "Триггер цены:\n"
        f" 5m ≥ {trigger_5m:.1f}%\n"
        f" 15m ≥ {trigger_15m:.1f}%\n\n"
        f"RSI:\n pump ≥ {upper_rsi:.0f}\n dump ≤ {lower_rsi:.0f}\n\n"
        f"Мин. объём 24h:\n ≥ ${min_vol:,.0f}"
    )


async def _render_home(target: Message | CallbackQuery, api: ApiClient) -> None:
    chat_id = target.chat.id if isinstance(target, Message) else target.message.chat.id
    cfg = await api.get_user_settings(chat_id=chat_id)
    text = _home_text(cfg, universe=settings.feed_universe_size, min_vol=float(cfg.get("min_quote_volume", settings.binance_min_quote_volume)))
    if isinstance(target, Message):
        await target.answer(text, reply_markup=main_menu_kb())
    else:
        await target.message.edit_text(text, reply_markup=main_menu_kb())


async def _render_settings(c: CallbackQuery, api: ApiClient) -> None:
    cfg = await api.get_user_settings(chat_id=c.message.chat.id)
    text = _settings_text(cfg)
    await c.message.edit_text(text, reply_markup=settings_main_kb())


@router.message(CommandStart())
async def start(m: Message, state: FSMContext, api: ApiClient) -> None:
    await state.set_state(UserFlow.main)
    # Register this chat for push stream delivery.
    await api.update_user_settings(chat_id=m.chat.id)
    await _render_home(m, api)


@router.callback_query(F.data == "menu:home")
async def menu_home(c: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    await state.set_state(UserFlow.main)
    await _render_home(c, api)
    await c.answer()


@router.callback_query(F.data == "menu:settings")
async def menu_settings(c: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    await state.set_state(UserFlow.main)
    await _render_settings(c, api)
    await c.answer()


@router.callback_query(F.data == "menu:feed")
async def menu_feed(c: CallbackQuery) -> None:
    text = (
        "📡 Лента сигналов\n\n"
        "Если включена — новые Pump/Dump сигналы\n"
        "будут приходить в этот чат.\n\n"
        "Статус: ВКЛЮЧЕНА"
    )
    await c.message.edit_text(text, reply_markup=feed_kb(enabled=True))
    await c.answer()


@router.callback_query(F.data.in_(["feed:on", "feed:off"]))
async def feed_toggle(c: CallbackQuery) -> None:
    enabled = c.data == "feed:on"
    status = "ВКЛЮЧЕНА" if enabled else "ВЫКЛЮЧЕНА"
    text = (
        "📡 Лента сигналов\n\n"
        "Если включена — новые Pump/Dump сигналы\n"
        "будут приходить в этот чат.\n\n"
        f"Статус: {status}"
    )
    await c.message.edit_text(text, reply_markup=feed_kb(enabled=enabled))
    await c.answer("Статус ленты обновлён")


@router.callback_query(F.data == "settings:tfs")
async def settings_tfs(c: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    cfg = await api.get_user_settings(chat_id=c.message.chat.id)
    await state.set_state(UserFlow.choosing_timeframe)
    await c.message.edit_text(
        "Выберите таймфреймы:",
        reply_markup=timeframes_kb(list(cfg.get("active_timeframes", []))),
    )
    await c.answer()


@router.callback_query(F.data.startswith("tfs:toggle:"), UserFlow.choosing_timeframe)
async def toggle_tfs(c: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    tf = c.data.split(":")[-1]
    cfg = await api.get_user_settings(chat_id=c.message.chat.id)
    active = set(cfg.get("active_timeframes", []))
    if tf in active:
        active.remove(tf)
    else:
        active.add(tf)
    if not active:
        active.add("15m")
    updated = sorted(active, key=lambda x: ["5m", "15m", "1h", "4h"].index(x))
    await api.update_user_settings(chat_id=c.message.chat.id, active_timeframes=updated)
    await c.message.edit_reply_markup(reply_markup=timeframes_kb(updated))
    await c.answer()


@router.callback_query(F.data == "tfs:done", UserFlow.choosing_timeframe)
async def tfs_done(c: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    await state.set_state(UserFlow.main)
    await _render_settings(c, api)
    await c.answer("Таймфреймы обновлены")


@router.callback_query(F.data == "settings:trigger")
async def settings_trigger(c: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(UserFlow.entering_price_triggers)
    await c.message.edit_text(
        "Введите два числа через пробел:\n5m 15m (%)\n\nПример:\n2.5 4.5",
        reply_markup=panel_actions_kb(),
    )
    await c.answer()


@router.message(UserFlow.entering_price_triggers)
async def handle_price_triggers(m: Message, state: FSMContext, api: ApiClient) -> None:
    parts = m.text.strip().replace(",", ".").split()
    if len(parts) != 2:
        await m.answer("Нужно два числа через пробел. Пример: 2.5 4.5")
        return
    try:
        pct_5m, pct_15m = float(parts[0]), float(parts[1])
    except ValueError:
        await m.answer("Не смог прочитать числа. Пример: 2.5 4.5")
        return
    await state.set_state(UserFlow.main)
    try:
        await api.update_user_settings(chat_id=m.chat.id, min_price_move_pct=pct_5m)
        saved_5m = True
    except Exception:
        saved_5m = False
    await m.answer(
        f"{'Сохранено' if saved_5m else 'Не удалось сохранить'}: 5m={pct_5m:.2f}%."
        f"\n15m сейчас: {settings.signal_price_change_15m_trigger_pct:.1f}%.",
        reply_markup=main_menu_kb(),
    )


@router.callback_query(F.data == "settings:rsi")
async def settings_rsi(c: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(UserFlow.entering_rsi)
    await c.message.edit_text(
        "Введите RSI pump и dump через пробел\nПример:\n60 40",
        reply_markup=panel_actions_kb(),
    )
    await c.answer()


@router.message(UserFlow.entering_rsi)
async def handle_rsi(m: Message, state: FSMContext, api: ApiClient) -> None:
    parts = m.text.strip().split()
    if len(parts) != 2:
        await m.answer("Нужно два числа через пробел. Пример: 60 40")
        return
    try:
        pump, dump = float(parts[0]), float(parts[1])
    except ValueError:
        await m.answer("Не смог прочитать числа. Пример: 60 40")
        return
    if pump <= dump:
        await m.answer("RSI pump должен быть больше RSI dump")
        return
    await api.update_user_settings(chat_id=m.chat.id, upper_rsi=pump, lower_rsi=dump)
    await state.set_state(UserFlow.main)
    await m.answer(
        f"RSI обновлён: pump ≥ {pump:.0f}, dump ≤ {dump:.0f}",
        reply_markup=main_menu_kb(),
    )


@router.callback_query(F.data == "settings:volume")
async def settings_volume(c: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(UserFlow.entering_min_volume)
    await c.message.edit_text(
        "Введите минимальный объём 24h (можно K/M)\nПримеры:\n500K\n2M\n1000000",
        reply_markup=panel_actions_kb(),
    )
    await c.answer()


def _parse_volume(text: str) -> float | None:
    t = text.strip().upper().replace(",", "")
    mult = 1.0
    if t.endswith("M"):
        mult = 1_000_000
        t = t[:-1]
    elif t.endswith("K"):
        mult = 1_000
        t = t[:-1]
    try:
        return float(t) * mult
    except ValueError:
        return None


@router.message(UserFlow.entering_min_volume)
async def handle_volume(m: Message, state: FSMContext, api: ApiClient) -> None:
    val = _parse_volume(m.text)
    if val is None or val <= 0:
        await m.answer("Не смог прочитать объём. Пример: 500K или 2M или 1000000")
        return
    await api.update_user_settings(chat_id=m.chat.id, min_quote_volume=val)
    await state.set_state(UserFlow.main)
    await m.answer(f"Мин. объём обновлён: ≥ ${val:,.0f}", reply_markup=main_menu_kb())


@router.callback_query(F.data == "settings:reset")
async def settings_reset(c: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(UserFlow.confirming_reset)
    await c.message.edit_text(
        "Сбросить настройки на дефолт?\n2.5% / 4.5%, RSI 60/40, объём $500K, ТФ 15m",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="Да", callback_data="reset:yes"),
                    InlineKeyboardButton(text="Нет", callback_data="reset:no"),
                ]
            ]
        ),
    )
    await c.answer()


@router.callback_query(F.data == "reset:yes", UserFlow.confirming_reset)
async def reset_yes(c: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    await api.update_user_settings(
        chat_id=c.message.chat.id,
        lower_rsi=40.0,
        upper_rsi=60.0,
        active_timeframes=["15m"],
        min_quote_volume=500_000.0,
    )
    await state.set_state(UserFlow.main)
    await _render_settings(c, api)
    await c.answer("Сброшено")


@router.callback_query(F.data == "reset:no", UserFlow.confirming_reset)
async def reset_no(c: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    await state.set_state(UserFlow.main)
    await _render_settings(c, api)
    await c.answer("Отменено")


@router.callback_query(F.data == "menu:info")
async def menu_info(c: CallbackQuery) -> None:
    text = (
        "Информация\n\n"
        "Бот отслеживает рынок Binance и отправляет поток Pump/Dump сигналов.\n"
        "Чтобы получать сигналы чаще, включите больше таймфреймов в настройках."
    )
    await c.message.edit_text(text, reply_markup=panel_actions_kb())
    await c.answer()

@router.callback_query(F.data == "menu:info")
async def menu_info(c: CallbackQuery) -> None:
    text = (
        "Информация\n\n"
        "Бот отслеживает рынок Binance и отправляет поток Pump/Dump сигналов.\n"
        "Чтобы получать сигналы чаще, включите больше таймфреймов в настройках."
    )
    await c.message.edit_text(text, reply_markup=panel_actions_kb())
    await c.answer()

