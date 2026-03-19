from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

DEFAULT_TIMEFRAMES: list[str] = ["5m", "15m", "1h", "4h"]


def _persistent_bottom_rows() -> list[list[InlineKeyboardButton]]:
    return [
        [InlineKeyboardButton(text="ℹ️ Текущие настройки", callback_data="menu:status")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:home")],
    ]


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu:settings")],
            [
                InlineKeyboardButton(text="📡 Лента", callback_data="menu:feed"),
                InlineKeyboardButton(text="ℹ️ Инфо", callback_data="menu:info"),
            ],
            *_persistent_bottom_rows(),
        ]
    )


def settings_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Триггер цены, %", callback_data="settings:trigger")],
            [InlineKeyboardButton(text="Таймфреймы", callback_data="settings:tfs")],
            [InlineKeyboardButton(text="Направление ленты", callback_data="settings:side")],
            [InlineKeyboardButton(text="Тип рынка", callback_data="settings:market")],
            [InlineKeyboardButton(text="Режимы сигналов", callback_data="settings:modes")],
            [InlineKeyboardButton(text="RSI", callback_data="settings:rsi")],
            [InlineKeyboardButton(text="Мин. объём", callback_data="settings:volume")],
            [InlineKeyboardButton(text="Сброс", callback_data="settings:reset")],
            *_persistent_bottom_rows(),
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
            *_persistent_bottom_rows(),
        ]
    )


def feed_kb(mode: str) -> InlineKeyboardMarkup:
    normalized = (mode or "all").lower()
    pump_text = "✅ Pump" if normalized in {"all", "pump"} else "Pump"
    dump_text = "✅ Dump" if normalized in {"all", "dump"} else "Dump"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=pump_text, callback_data="feed:toggle:pump"),
                InlineKeyboardButton(text=dump_text, callback_data="feed:toggle:dump"),
            ],
            *_persistent_bottom_rows(),
        ]
    )


def panel_actions_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=_persistent_bottom_rows())


def bottom_chat_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬅️ Главное меню")]],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Нажмите «Главное меню»",
    )


def signal_side_kb(current_mode: str) -> InlineKeyboardMarkup:
    mode = (current_mode or "all").lower()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Все" if mode == "all" else "Все", callback_data="side:set:all")],
            [InlineKeyboardButton(text="✅ Только pump" if mode == "pump" else "Только pump", callback_data="side:set:pump")],
            [InlineKeyboardButton(text="✅ Только dump" if mode == "dump" else "Только dump", callback_data="side:set:dump")],
            *_persistent_bottom_rows(),
        ]
    )


def market_type_kb(current_market_type: str) -> InlineKeyboardMarkup:
    market_type = (current_market_type or "both").lower()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Spot" if market_type == "spot" else "Spot", callback_data="market:set:spot")],
            [
                InlineKeyboardButton(
                    text="✅ Futures" if market_type == "futures" else "Futures",
                    callback_data="market:set:futures",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Spot + Futures" if market_type == "both" else "Spot + Futures",
                    callback_data="market:set:both",
                )
            ],
            *_persistent_bottom_rows(),
        ]
    )


def signal_modes_kb(feed_mode_enabled: bool, strategy_mode_enabled: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Лента pump/dump" if feed_mode_enabled else "Лента pump/dump",
                    callback_data="modes:toggle:feed",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Сигналы стратегии" if strategy_mode_enabled else "Сигналы стратегии",
                    callback_data="modes:toggle:strategy",
                )
            ],
            *_persistent_bottom_rows(),
        ]
    )


def reset_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да", callback_data="reset:yes"),
                InlineKeyboardButton(text="Нет", callback_data="reset:no"),
            ],
            *_persistent_bottom_rows(),
        ]
    )


def rsi_settings_kb(rsi_enabled: bool, lower_rsi: float, upper_rsi: float) -> InlineKeyboardMarkup:
    toggle_text = "✅ RSI включен" if rsi_enabled else "⬜ RSI выключен"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle_text, callback_data="rsi:toggle")],
            [InlineKeyboardButton(text=f"Pump RSI ≥ {upper_rsi:.0f}", callback_data="rsi:upper")],
            [InlineKeyboardButton(text=f"Dump RSI ≤ {lower_rsi:.0f}", callback_data="rsi:lower")],
            *_persistent_bottom_rows(),
        ]
    )
