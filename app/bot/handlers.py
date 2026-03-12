from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.api_client import ApiClient
from app.bot.keyboards import (
    feed_kb,
    main_menu_kb,
    market_type_kb,
    panel_actions_kb,
    reset_confirm_kb,
    signal_modes_kb,
    settings_main_kb,
    signal_side_kb,
    timeframes_kb,
)
from app.bot.states import UserFlow
from app.core.config import settings

router = Router()


def _status_line(cfg: dict[str, object], *, universe: int, min_vol: float) -> str:
    tfs = " ".join(cfg.get("active_timeframes", [])) or "15m"
    rsi = f"{float(cfg.get('upper_rsi', 60)):.0f}/{float(cfg.get('lower_rsi', 40)):.0f}"
    trigger = f"≥ {float(cfg.get('min_price_move_pct', 5.0)):.1f}%"
    side_map = {"all": "Pump+Dump", "pump": "Только Pump", "dump": "Только Dump"}
    side_mode = side_map.get(str(cfg.get("signal_side_mode", "all")), "Pump+Dump")
    market_map = {"spot": "Spot", "futures": "Futures", "both": "Spot+Futures"}
    market_type = market_map.get(str(cfg.get("market_type", "both")), "Spot+Futures")
    feed_status = "Вкл" if bool(cfg.get("feed_mode_enabled", True)) else "Выкл"
    strategy_status = "Вкл" if bool(cfg.get("strategy_mode_enabled", True)) else "Выкл"
    return (
        f"ТФ: {tfs} | Движение: {trigger} | Режим: {side_mode} | RSI: {rsi} | "
        f"Рынок: {market_type} | Пары: {universe} (≥${min_vol/1_000_000:.1f}M) | "
        f"Лента: {feed_status} | Стратегия: {strategy_status}"
    )


def _home_text(cfg: dict[str, object], *, universe: int, min_vol: float) -> str:
    return (
        "Сигнальный бот\n\n"
        "Сканируем BingX и отправляем сигналы.\n\n"
        f"{_status_line(cfg, universe=universe, min_vol=min_vol)}"
    )


def _settings_text(cfg: dict[str, object]) -> str:
    active = " ".join(cfg.get("active_timeframes", [])) or "15m"
    lower_rsi = float(cfg.get("lower_rsi", 40))
    upper_rsi = float(cfg.get("upper_rsi", 60))
    min_vol = float(cfg.get("min_quote_volume", settings.bingx_min_quote_volume))
    min_move = float(cfg.get("min_price_move_pct", 5.0))
    side_map = {"all": "Все", "pump": "Только pump", "dump": "Только dump"}
    side_mode = side_map.get(str(cfg.get("signal_side_mode", "all")), "Все")
    market_map = {"spot": "Spot", "futures": "Futures", "both": "Spot + Futures"}
    market_type = market_map.get(str(cfg.get("market_type", "both")), "Spot + Futures")
    feed_mode_enabled = bool(cfg.get("feed_mode_enabled", True))
    strategy_mode_enabled = bool(cfg.get("strategy_mode_enabled", True))
    return (
        "⚙️ Настройки сигналов\n\n"
        f"Таймфреймы: {active}\n"
        f"Минимальное движение: ≥ {min_move:.1f}%\n"
        f"Направление: {side_mode}\n"
        f"Тип рынка: {market_type}\n"
        f"Лента pump/dump: {'Вкл' if feed_mode_enabled else 'Выкл'}\n"
        f"Сигналы стратегии: {'Вкл' if strategy_mode_enabled else 'Выкл'}\n\n"
        f"RSI:\n pump ≥ {upper_rsi:.0f}\n dump ≤ {lower_rsi:.0f}\n\n"
        f"Мин. объём 24h:\n ≥ ${min_vol:,.0f}"
    )


async def _render_home(target: Message | CallbackQuery, api: ApiClient) -> None:
    chat_id = target.chat.id if isinstance(target, Message) else target.message.chat.id
    cfg = await api.get_user_settings(chat_id=chat_id)
    text = _home_text(
        cfg,
        universe=settings.feed_universe_size,
        min_vol=float(cfg.get("min_quote_volume", settings.bingx_min_quote_volume)),
    )
    if isinstance(target, Message):
        await target.answer(text, reply_markup=main_menu_kb())
    else:
        await target.message.edit_text(text, reply_markup=main_menu_kb())


async def _render_settings(c: CallbackQuery, api: ApiClient) -> None:
    cfg = await api.get_user_settings(chat_id=c.message.chat.id)
    text = _settings_text(cfg)
    await c.message.edit_text(text, reply_markup=settings_main_kb())


def _status_popup(cfg: dict[str, object]) -> str:
    min_vol = float(cfg.get("min_quote_volume", settings.bingx_min_quote_volume))
    return _status_line(cfg, universe=settings.feed_universe_size, min_vol=min_vol)


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


@router.callback_query(F.data == "menu:status")
async def menu_status(c: CallbackQuery, api: ApiClient) -> None:
    cfg = await api.get_user_settings(chat_id=c.message.chat.id)
    await c.answer(_status_popup(cfg), show_alert=True)


@router.callback_query(F.data == "menu:feed")
async def menu_feed(c: CallbackQuery, api: ApiClient) -> None:
    cfg = await api.get_user_settings(chat_id=c.message.chat.id)
    mode = str(cfg.get("signal_side_mode", "all"))
    mode_label = {"all": "Pump + Dump", "pump": "Только Pump", "dump": "Только Dump"}.get(mode, "Pump + Dump")
    text = (
        "📡 Лента сигналов\n\n"
        "Новые сигналы приходят в этот чат.\n"
        "Выберите направление внизу.\n\n"
        f"Текущий режим: {mode_label}"
    )
    await c.message.edit_text(text, reply_markup=feed_kb(mode=mode))
    await c.answer()


@router.callback_query(F.data.in_(["feed:toggle:pump", "feed:toggle:dump"]))
async def feed_toggle(c: CallbackQuery, api: ApiClient) -> None:
    cfg = await api.get_user_settings(chat_id=c.message.chat.id)
    current = str(cfg.get("signal_side_mode", "all"))
    selected = c.data.rsplit(":", 1)[-1]

    if selected == "pump":
        next_mode = "all" if current == "dump" else "pump"
    else:
        next_mode = "all" if current == "pump" else "dump"

    await api.update_user_settings(chat_id=c.message.chat.id, signal_side_mode=next_mode)
    label = {"all": "Pump + Dump", "pump": "Только Pump", "dump": "Только Dump"}[next_mode]
    text = (
        "📡 Лента сигналов\n\n"
        "Новые сигналы приходят в этот чат.\n"
        "Выберите направление внизу.\n\n"
        f"Текущий режим: {label}"
    )
    await c.message.edit_text(text, reply_markup=feed_kb(mode=next_mode))
    await c.answer(f"Режим ленты обновлён: {label}", show_alert=True)


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
    await c.answer("Таймфреймы обновлены", show_alert=True)


@router.callback_query(F.data == "settings:trigger")
async def settings_trigger(c: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(UserFlow.entering_min_price_move)
    await c.message.edit_text(
        "Введите минимальное движение в %.\n\nПримеры:\n5\n10\n15",
        reply_markup=panel_actions_kb(),
    )
    await c.answer()


@router.message(UserFlow.entering_min_price_move)
async def handle_min_price_move(m: Message, state: FSMContext, api: ApiClient) -> None:
    try:
        min_move = float(m.text.strip().replace(",", "."))
    except ValueError:
        await m.answer("Не смог прочитать число. Пример: 5 или 10")
        return
    if min_move <= 0:
        await m.answer("Значение должно быть больше 0")
        return
    await state.set_state(UserFlow.main)
    await api.update_user_settings(chat_id=m.chat.id, min_price_move_pct=min_move)
    await m.answer(
        f"Триггер цены обновлён: {min_move:.1f}%",
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
        "Сбросить настройки на дефолт?\nДвижение 5.0%, режим Все, рынок Spot+Futures, RSI 60/40, объём $500K, ТФ 15m, лента+стратегия включены",
        reply_markup=reset_confirm_kb(),
    )
    await c.answer()


@router.callback_query(F.data == "reset:yes", UserFlow.confirming_reset)
async def reset_yes(c: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    await api.update_user_settings(
        chat_id=c.message.chat.id,
        lower_rsi=40.0,
        upper_rsi=60.0,
        active_timeframes=["15m"],
        min_price_move_pct=5.0,
        min_quote_volume=500_000.0,
        signal_side_mode="all",
        market_type="both",
        feed_mode_enabled=True,
        strategy_mode_enabled=True,
    )
    await state.set_state(UserFlow.main)
    await _render_settings(c, api)
    await c.answer("Настройки сброшены", show_alert=True)


@router.callback_query(F.data == "reset:no", UserFlow.confirming_reset)
async def reset_no(c: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    await state.set_state(UserFlow.main)
    await _render_settings(c, api)
    await c.answer("Сброс отменён", show_alert=True)



@router.callback_query(F.data == "menu:info")
async def menu_info(c: CallbackQuery) -> None:
    text = (
        "Информация\n\n"
        "Бот отслеживает рынок BingX и отправляет два типа сигналов:\n"
        "1) Лента pump/dump\n"
        "2) Сигналы стратегии (pin bar + отклонение)\n\n"
        "Чтобы получать сигналы чаще, увеличьте число таймфреймов и проверьте тип рынка в настройках."
    )
    await c.message.edit_text(text, reply_markup=panel_actions_kb())
    await c.answer()


@router.callback_query(F.data == "settings:side")
async def settings_side(c: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    cfg = await api.get_user_settings(chat_id=c.message.chat.id)
    mode = str(cfg.get("signal_side_mode", "all"))
    await state.set_state(UserFlow.choosing_signal_side)
    await c.message.edit_text(
        "Выберите направление сигналов:",
        reply_markup=signal_side_kb(mode),
    )
    await c.answer()


@router.callback_query(F.data.startswith("side:set:"), UserFlow.choosing_signal_side)
async def set_side_mode(c: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    mode = c.data.split(":")[-1]
    if mode not in {"all", "pump", "dump"}:
        await c.answer("Неизвестный режим")
        return
    await api.update_user_settings(chat_id=c.message.chat.id, signal_side_mode=mode)
    await state.set_state(UserFlow.main)
    await _render_settings(c, api)
    labels = {"all": "Все", "pump": "Только pump", "dump": "Только dump"}
    await c.answer(f"Направление ленты: {labels[mode]}", show_alert=True)


@router.callback_query(F.data == "settings:market")
async def settings_market(c: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    cfg = await api.get_user_settings(chat_id=c.message.chat.id)
    market_type = str(cfg.get("market_type", "both"))
    await state.set_state(UserFlow.choosing_market_type)
    await c.message.edit_text(
        "Выберите тип рынка:",
        reply_markup=market_type_kb(market_type),
    )
    await c.answer()


@router.callback_query(F.data.startswith("market:set:"), UserFlow.choosing_market_type)
async def set_market_mode(c: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    mode = c.data.split(":")[-1]
    if mode not in {"spot", "futures", "both"}:
        await c.answer("Неизвестный тип рынка")
        return
    await api.update_user_settings(chat_id=c.message.chat.id, market_type=mode)
    await state.set_state(UserFlow.main)
    await _render_settings(c, api)
    labels = {"spot": "Spot", "futures": "Futures", "both": "Spot + Futures"}
    await c.answer(f"Тип рынка обновлён: {labels[mode]}", show_alert=True)


@router.callback_query(F.data == "settings:modes")
async def settings_modes(c: CallbackQuery, api: ApiClient) -> None:
    cfg = await api.get_user_settings(chat_id=c.message.chat.id)
    feed_mode_enabled = bool(cfg.get("feed_mode_enabled", True))
    strategy_mode_enabled = bool(cfg.get("strategy_mode_enabled", True))
    await c.message.edit_text(
        "Выберите активные режимы сигналов:",
        reply_markup=signal_modes_kb(
            feed_mode_enabled=feed_mode_enabled,
            strategy_mode_enabled=strategy_mode_enabled,
        ),
    )
    await c.answer()


@router.callback_query(F.data.in_(["modes:toggle:feed", "modes:toggle:strategy"]))
async def modes_toggle(c: CallbackQuery, api: ApiClient) -> None:
    cfg = await api.get_user_settings(chat_id=c.message.chat.id)
    feed_mode_enabled = bool(cfg.get("feed_mode_enabled", True))
    strategy_mode_enabled = bool(cfg.get("strategy_mode_enabled", True))
    selected = c.data.rsplit(":", 1)[-1]

    if selected == "feed":
        feed_mode_enabled = not feed_mode_enabled
    else:
        strategy_mode_enabled = not strategy_mode_enabled

    await api.update_user_settings(
        chat_id=c.message.chat.id,
        feed_mode_enabled=feed_mode_enabled,
        strategy_mode_enabled=strategy_mode_enabled,
    )
    await c.message.edit_text(
        "Выберите активные режимы сигналов:",
        reply_markup=signal_modes_kb(
            feed_mode_enabled=feed_mode_enabled,
            strategy_mode_enabled=strategy_mode_enabled,
        ),
    )
    await c.answer(
        (
            f"Лента: {'Вкл' if feed_mode_enabled else 'Выкл'}\n"
            f"Стратегия: {'Вкл' if strategy_mode_enabled else 'Выкл'}"
        ),
        show_alert=True,
    )

