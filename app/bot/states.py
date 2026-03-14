from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class UserFlow(StatesGroup):
    main = State()
    choosing_timeframe = State()
    entering_min_price_move = State()
    entering_rsi = State()
    entering_rsi_upper = State()
    entering_rsi_lower = State()
    entering_min_volume = State()
    choosing_signal_side = State()
    choosing_market_type = State()
    confirming_reset = State()

