from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class UserFlow(StatesGroup):
    main = State()
    choosing_timeframe = State()
    entering_price_triggers = State()
    entering_rsi = State()
    entering_min_volume = State()
    confirming_reset = State()

