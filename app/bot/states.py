from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class UserFlow(StatesGroup):
    main = State()
    choosing_timeframe = State()
    choosing_symbol = State()

