from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

DEFAULT_TIMEFRAMES: list[str] = ["5m", "15m", "1h", "4h"]


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu:settings"),
                InlineKeyboardButton(text="⏱ ТФ", callback_data="menu:settings"),  # alias to settings
            ],
            [
                InlineKeyboardButton(text="📡 Лента", callback_data="menu:feed"),
                InlineKeyboardButton(text="ℹ️ Инфо", callback_data="menu:info"),
            ],
        ]
    )


def settings_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Таймфреймы", callback_data="settings:tfs")],
            [InlineKeyboardButton(text="Триггер цены", callback_data="settings:trigger")],
            [
                InlineKeyboardButton(text="RSI", callback_data="settings:rsi"),
            ],
            [InlineKeyboardButton(text="Мин. объём", callback_data="settings:volume")],
            [InlineKeyboardButton(text="Сброс", callback_data="settings:reset")],
            [InlineKeyboardButton(text="Главное меню", callback_data="menu:home")],
        ]
    )


def timeframes_kb(active: list[str]) -> InlineKeyboardMarkup:
    def mark(tf: str) -> str:
        return ("✅ " if tf in active else "⬜ ") + tf

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=mark("5m"), callback_data="tfs:toggle:5m"),
                InlineKeyboardButton(text=mark("15m"), callback_data="tfs:toggle:15m"),
            ],
            [
                InlineKeyboardButton(text=mark("1h"), callback_data="tfs:toggle:1h"),
                InlineKeyboardButton(text=mark("4h"), callback_data="tfs:toggle:4h"),
            ],
            [
                InlineKeyboardButton(text="Готово", callback_data="tfs:done"),
                InlineKeyboardButton(text="Отмена", callback_data="menu:settings"),
            ],
        ]
    )


def feed_kb(enabled: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Вкл", callback_data="feed:on"),
                InlineKeyboardButton(text="Выкл", callback_data="feed:off"),
            ],
            [InlineKeyboardButton(text="Главное меню", callback_data="menu:home")],
        ]
    )


def panel_actions_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Лента", callback_data="menu:feed"),
                InlineKeyboardButton(text="Главное меню", callback_data="menu:home"),
            ],
        ]
    )
