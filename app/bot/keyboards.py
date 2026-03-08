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
    lower_rsi: float,
    upper_rsi: float,
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
            [
                InlineKeyboardButton(text=f"RSI low - ({lower_rsi:.0f})", callback_data="settings:rsi:lower:down"),
                InlineKeyboardButton(text=f"RSI low + ({lower_rsi:.0f})", callback_data="settings:rsi:lower:up"),
            ],
            [
                InlineKeyboardButton(text=f"RSI high - ({upper_rsi:.0f})", callback_data="settings:rsi:upper:down"),
                InlineKeyboardButton(text=f"RSI high + ({upper_rsi:.0f})", callback_data="settings:rsi:upper:up"),
            ],
            [InlineKeyboardButton(text="Сбросить по умолчанию", callback_data="settings:reset")],
            [InlineKeyboardButton(text="Главное меню", callback_data="menu:home")],
        ]
    )


def panel_actions_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Обновить ленту", callback_data="menu:feed"),
                InlineKeyboardButton(text="Главное меню", callback_data="menu:home"),
            ],
        ]
    )

