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
    subscriptions_kb,
    symbols_kb,
    timeframes_kb,
)
from app.bot.states import UserFlow

router = Router()


def _fmt_selection(symbol: str | None, timeframe: str | None) -> str:
    s = symbol or "не выбрана"
    tf = timeframe or "не выбран"
    return f"Монета: {s}\nТаймфрейм: {tf}"


def _home_text(symbol: str | None, timeframe: str | None) -> str:
    return (
        "Крипто аналитика\n\n"
        "Выбери действие в меню ниже.\n\n"
        f"{_fmt_selection(symbol, timeframe)}"
    )


def _settings_text(symbol: str | None, timeframe: str | None) -> str:
    return (
        "Настройки фильтра\n\n"
        "1) Выбери монету\n"
        "2) Выбери таймфрейм\n\n"
        f"{_fmt_selection(symbol, timeframe)}"
    )


async def _render_home(target: Message | CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    text = _home_text(data.get("symbol"), data.get("timeframe"))
    if isinstance(target, Message):
        await target.answer(text, reply_markup=main_menu_kb())
    else:
        await target.message.edit_text(text, reply_markup=main_menu_kb())


async def _render_settings(c: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    text = _settings_text(data.get("symbol"), data.get("timeframe"))
    await c.message.edit_text(text, reply_markup=settings_kb())


@router.message(CommandStart())
async def start(m: Message, state: FSMContext) -> None:
    await state.set_state(UserFlow.main)
    current = await state.get_data()
    if "symbol" not in current:
        await state.update_data(symbol="BTC/USDT")
    if "timeframe" not in current:
        await state.update_data(timeframe="15m")
    await _render_home(m, state)


@router.callback_query(F.data == "menu:home")
async def menu_home(c: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(UserFlow.main)
    await _render_home(c, state)
    await c.answer()


@router.callback_query(F.data == "menu:settings")
async def menu_settings(c: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(UserFlow.main)
    await _render_settings(c, state)
    await c.answer()


@router.callback_query(F.data == "menu:overview")
async def menu_overview(c: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    data = await state.get_data()
    symbol = data.get("symbol")
    timeframe = data.get("timeframe")
    if not symbol or not timeframe:
        await c.answer("Сначала выберите монету и таймфрейм", show_alert=True)
        return
    try:
        overview = await api.get_market_overview(symbol=symbol, timeframe=timeframe)
    except Exception as e:
        await c.message.edit_text(f"Ошибка обзора: {e}", reply_markup=panel_actions_kb())
        await c.answer()
        return
    text = (
        f"Обзор {overview['symbol']} {overview['timeframe']}\n\n"
        f"CEX price: {overview['cex_price']:.4f} ({overview['cex_price_change_pct']:+.2f}%)\n"
        f"CEX volume: {overview['cex_volume']:.2f}\n"
        f"DEX price: {overview['dex_price'] if overview['dex_price'] is not None else 'n/a'}\n"
        f"DEX liquidity: {overview['dex_liquidity_usd'] if overview['dex_liquidity_usd'] is not None else 'n/a'}\n"
        f"News sentiment: {overview['avg_news_sentiment']:+.2f}\n"
        f"AI: {overview['ai_action']} ({overview['ai_score']:.2f})\n\n"
        f"{overview['ai_explanation']}"
    )
    await c.message.edit_text(text, reply_markup=panel_actions_kb())
    await c.answer()


@router.callback_query(F.data == "settings:symbol")
async def settings_symbol(c: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(UserFlow.choosing_symbol)
    await c.message.edit_text("Выберите монету:", reply_markup=symbols_kb())
    await c.answer()


@router.callback_query(F.data == "settings:tf")
async def settings_timeframe(c: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(UserFlow.choosing_timeframe)
    await c.message.edit_text("Выберите таймфрейм:", reply_markup=timeframes_kb())
    await c.answer()


@router.callback_query(F.data.startswith("pick:sym:"))
async def choose_symbol(c: CallbackQuery, state: FSMContext) -> None:
    sym = c.data.split(":", 2)[2]
    await state.update_data(symbol=sym)
    await _render_settings(c, state)
    await c.answer("Монета обновлена")


@router.callback_query(F.data.startswith("pick:tf:"))
async def choose_timeframe(c: CallbackQuery, state: FSMContext) -> None:
    tf = c.data.split(":", 2)[2]
    await state.update_data(timeframe=tf)
    await _render_settings(c, state)
    await c.answer("Таймфрейм обновлен")


@router.callback_query(F.data == "menu:signals")
async def show_signals(c: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    data = await state.get_data()
    symbol = data.get("symbol")
    timeframe = data.get("timeframe")
    if not symbol or not timeframe:
        await c.answer("Сначала выберите настройки", show_alert=True)
        return

    try:
        live = await api.get_live_signal(symbol=symbol, timeframe=timeframe)
        rows = await api.get_signals(symbol=symbol, timeframe=timeframe, limit=5)
    except Exception as e:
        await c.message.edit_text(f"Ошибка загрузки сигналов: {e}", reply_markup=panel_actions_kb())
        await c.answer()
        return

    lines = [
        "Живой сигнал (CEX + DEX + News + AI):",
        f"{live['symbol']} {live['timeframe']} | {live['direction'].upper()} | {live['action']}",
        f"Сила: {live['strength']:.2f}",
        f"Цена: {live['price']:.4f} ({live['price_change_pct']:+.2f}%)",
        f"Объем: {live['volume']:.2f} ({live['volume_change_pct']:+.2f}%)",
        f"Ликвидность: {live['liquidity'] if live['liquidity'] is not None else 'n/a'}",
        f"Тренд: {live['trend']}",
        f"AI score: {live['ai_score']:.2f}",
        f"AI: {live['ai_explanation']}",
    ]
    if rows:
        lines.append("\nПоследние сигналы:")
        for item in rows[:5]:
            lines.append(
                f"- {item['symbol']} {item['timeframe']} {item['direction']} "
                f"| strength={item['strength']:.2f} | {item['action']}"
            )

    await c.message.edit_text("\n".join(lines), reply_markup=panel_actions_kb())
    await c.answer()


@router.callback_query(F.data == "menu:refresh")
async def refresh_panel(c: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    data = await state.get_data()
    symbol = data.get("symbol")
    timeframe = data.get("timeframe")
    if not symbol or not timeframe:
        await _render_home(c, state)
        await c.answer()
        return

    lines = ["Последние сигналы и ключевые показатели:"]
    rows = await api.get_signals(symbol=symbol, timeframe=timeframe, limit=5)
    overview = await api.get_market_overview(symbol=symbol, timeframe=timeframe)
    lines.append(
        f"CEX: {overview['cex_price']:.4f} ({overview['cex_price_change_pct']:+.2f}%) | "
        f"Sentiment: {overview['avg_news_sentiment']:+.2f} | AI: {overview['ai_action']}"
    )
    for s in rows or []:
        lines.append(
            f"- {s['symbol']} {s['timeframe']} {s['direction']} "
            f"strength={s['strength']:.2f} action={s['action']}"
        )
    if len(lines) == 1:
        lines.append("Пока нет сохраненных сигналов.")
    lines.append("")
    lines.append(_fmt_selection(symbol, timeframe))
    await c.message.edit_text("\n".join(lines), reply_markup=panel_actions_kb())
    await c.answer()


@router.callback_query(F.data == "menu:analytics")
async def show_analytics(c: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    data = await state.get_data()
    symbol = data.get("symbol")
    timeframe = data.get("timeframe")
    if not symbol or not timeframe:
        await c.answer("Сначала выберите монету и таймфрейм", show_alert=True)
        return

    try:
        a = await api.get_analytics(symbol=symbol, timeframe=timeframe)
        n = await api.get_news_sentiment(symbol=symbol)
    except Exception as e:
        await c.message.edit_text(f"Ошибка аналитики: {e}", reply_markup=panel_actions_kb())
        await c.answer()
        return

    lines = [
        f"Аналитика: {a['symbol']} {a['timeframe']}",
        "",
        a["summary"],
        "",
        f"AI: {a['ai_explanation']}",
        f"News sentiment: {a['avg_news_sentiment']:+.2f}",
        "",
        "Новости:",
    ]
    for item in n["headlines"][:4]:
        lines.append(f"- {item['title']} ({item['sentiment']:+.2f})")
    text = "\n".join(lines)
    await c.message.edit_text(text, reply_markup=panel_actions_kb())
    await c.answer()


@router.callback_query(F.data == "menu:stats")
async def show_stats(c: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    data = await state.get_data()
    symbol = data.get("symbol")
    timeframe = data.get("timeframe")
    try:
        s = await api.get_stats_overview()
        p = await api.get_performance(symbol=symbol, timeframe=timeframe)
    except Exception as e:
        await c.message.edit_text(f"Ошибка статистики: {e}", reply_markup=panel_actions_kb())
        await c.answer()
        return

    total = int(s["total_signals"])
    up = int(s["up_signals"])
    down = int(s["down_signals"])
    up_share = (up / total * 100) if total else 0
    down_share = (down / total * 100) if total else 0
    text = (
        "Статистика сигналов\n\n"
        f"Всего: {total}\n"
        f"UP: {up} ({up_share:.1f}%)\n"
        f"DOWN: {down} ({down_share:.1f}%)\n\n"
        f"Эффективность ({symbol} {timeframe})\n"
        f"Evaluated: {p['evaluated_signals']}\n"
        f"Winrate: {p['winrate_pct']:.2f}%\n"
        f"Hit ratio: {p['hit_ratio_pct']:.2f}%\n"
        f"Avg PnL: {p['avg_pnl_pct']:+.3f}%\n"
        f"Total PnL: {p['total_pnl_pct']:+.3f}%\n"
        f"Max drawdown: {p['max_drawdown_pct']:.3f}%\n"
        f"Profit factor: {p['profit_factor']:.3f}"
    )
    await c.message.edit_text(text, reply_markup=panel_actions_kb())
    await c.answer()


@router.callback_query(F.data == "menu:subs")
async def menu_subs(c: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    data = await state.get_data()
    symbol = data.get("symbol")
    timeframe = data.get("timeframe")
    if not symbol or not timeframe:
        await c.answer("Сначала выберите монету и таймфрейм", show_alert=True)
        return
    subs = await api.list_subscriptions(chat_id=c.message.chat.id)
    has_current = any(s["symbol"] == symbol and s["timeframe"] == timeframe for s in subs)
    lines = [f"Подписки ({len(subs)})", "", "Текущая выборка:", f"{symbol} {timeframe}", ""]
    if subs:
        lines.append("Активные:")
        for s in subs[:10]:
            lines.append(f"- {s['symbol']} {s['timeframe']}")
    else:
        lines.append("Подписок пока нет")
    await c.message.edit_text("\n".join(lines), reply_markup=subscriptions_kb(has_current))
    await c.answer()


@router.callback_query(F.data == "subs:add")
async def add_sub(c: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    data = await state.get_data()
    symbol = data.get("symbol")
    timeframe = data.get("timeframe")
    if not symbol or not timeframe:
        await c.answer("Сначала выберите монету и таймфрейм", show_alert=True)
        return
    await api.add_subscription(chat_id=c.message.chat.id, symbol=symbol, timeframe=timeframe)
    await c.answer("Подписка добавлена")
    await menu_subs(c, state, api)


@router.callback_query(F.data == "subs:remove")
async def remove_sub(c: CallbackQuery, state: FSMContext, api: ApiClient) -> None:
    data = await state.get_data()
    symbol = data.get("symbol")
    timeframe = data.get("timeframe")
    if not symbol or not timeframe:
        await c.answer("Сначала выберите монету и таймфрейм", show_alert=True)
        return
    await api.remove_subscription(chat_id=c.message.chat.id, symbol=symbol, timeframe=timeframe)
    await c.answer("Подписка удалена")
    await menu_subs(c, state, api)

