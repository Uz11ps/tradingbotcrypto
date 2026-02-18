from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

DEFAULT_TIMEFRAMES: list[str] = ["15m", "1h", "4h", "1d"]
DEFAULT_SYMBOLS: list[str] = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Настройки", callback_data="menu:settings"),
                InlineKeyboardButton(text="Обзор", callback_data="menu:overview"),
            ],
            [InlineKeyboardButton(text="Лента топ-движений", callback_data="menu:feed")],
            [
                InlineKeyboardButton(text="Живой сигнал", callback_data="menu:signals"),
                InlineKeyboardButton(text="Аналитика", callback_data="menu:analytics"),
            ],
            [
                InlineKeyboardButton(text="Статистика", callback_data="menu:stats"),
                InlineKeyboardButton(text="Подписки", callback_data="menu:subs"),
            ],
        ]
    )


def settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Монета", callback_data="settings:symbol"),
                InlineKeyboardButton(text="Таймфрейм", callback_data="settings:tf"),
            ],
            [InlineKeyboardButton(text="Подписать текущую пару", callback_data="subs:add")],
            [InlineKeyboardButton(text="Обновить меню", callback_data="menu:home")],
        ]
    )


def timeframes_kb(timeframes: list[str] | None = None) -> InlineKeyboardMarkup:
    tfs = timeframes or DEFAULT_TIMEFRAMES
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for tf in tfs:
        row.append(InlineKeyboardButton(text=tf, callback_data=f"pick:tf:{tf}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="Назад к настройкам", callback_data="menu:settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def symbols_kb(symbols: list[str] | None = None) -> InlineKeyboardMarkup:
    syms = symbols or DEFAULT_SYMBOLS
    rows: list[list[InlineKeyboardButton]] = []
    for sym in syms:
        rows.append([InlineKeyboardButton(text=sym, callback_data=f"pick:sym:{sym}")])
    rows.append([InlineKeyboardButton(text="Назад к настройкам", callback_data="menu:settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def panel_actions_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Обновить", callback_data="menu:refresh"),
                InlineKeyboardButton(text="Главное меню", callback_data="menu:home"),
            ],
            [InlineKeyboardButton(text="Подписать текущую пару", callback_data="subs:add")],
        ]
    )


def subscriptions_kb(has_current: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="Добавить текущую", callback_data="subs:add")]
    ]
    if has_current:
        rows.append([InlineKeyboardButton(text="Удалить текущую", callback_data="subs:remove")])
    rows.append([InlineKeyboardButton(text="Главное меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

