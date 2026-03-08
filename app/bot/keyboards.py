from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

DEFAULT_TIMEFRAMES: list[str] = ["5m", "15m", "1h", "4h"]


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Лента", callback_data="menu:feed")],
            [InlineKeyboardButton(text="Настройки", callback_data="menu:settings")],
            [InlineKeyboardButton(text="Информация", callback_data="menu:info")],
        ]
    )


def settings_kb(
    *,
    active_timeframes: list[str],
) -> InlineKeyboardMarkup:
    def mark(tf: str) -> str:
        return ("✅ " if tf in active_timeframes else "⬜ ") + tf

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=mark("5m"), callback_data="settings:tf:5m"),
                InlineKeyboardButton(text=mark("15m"), callback_data="settings:tf:15m"),
            ],
            [
                InlineKeyboardButton(text=mark("1h"), callback_data="settings:tf:1h"),
                InlineKeyboardButton(text=mark("4h"), callback_data="settings:tf:4h"),
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

