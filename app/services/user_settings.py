from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import UserSignalSettings
from app.services.signal_presentation import normalize_market_type, normalize_signal_side_mode

DEFAULT_TFS = ("15m",)
ALLOWED_TFS = set(DEFAULT_TFS)
ALLOWED_TFS.update({"5m", "1h", "4h"})


@dataclass(slots=True)
class EffectiveUserSettings:
    lower_rsi: float
    upper_rsi: float
    active_timeframes: list[str]
    min_price_move_pct: float
    min_quote_volume: float
    price_change_15m_trigger_pct: float
    signal_side_mode: str
    market_type: str
    feed_mode_enabled: bool
    strategy_mode_enabled: bool
    strategy_impulse_window: int
    strategy_deviation_threshold_pct: float
    strategy_min_pinbar_strength: float
    strategy_max_body_ratio: float
    strategy_max_signals_per_cycle: int
    rsi_enabled: bool


def _parse_tfs(raw: str | None) -> list[str]:
    if not raw:
        return list(DEFAULT_TFS)
    tfs = [x.strip() for x in raw.split(",") if x.strip()]
    normalized = [tf for tf in tfs if tf in ALLOWED_TFS]
    return normalized or list(DEFAULT_TFS)


def get_global_defaults() -> EffectiveUserSettings:
    default_min_move = 5.0
    return EffectiveUserSettings(
        lower_rsi=float(settings.rsi_default_lower),
        upper_rsi=float(settings.rsi_default_upper),
        active_timeframes=_parse_tfs(settings.rsi_default_timeframes),
        min_price_move_pct=default_min_move,
        min_quote_volume=float(settings.bingx_min_quote_volume),
        # Keep 15m trigger aligned with user threshold to avoid hidden defaults.
        price_change_15m_trigger_pct=default_min_move,
        signal_side_mode="all",
        market_type="both",
        feed_mode_enabled=True,
        strategy_mode_enabled=True,
        strategy_impulse_window=max(2, int(settings.signal_strategy_impulse_window)),
        strategy_deviation_threshold_pct=max(0.1, float(settings.signal_strategy_deviation_threshold_pct)),
        strategy_min_pinbar_strength=max(0.1, float(settings.signal_strategy_min_pinbar_strength)),
        strategy_max_body_ratio=min(1.0, max(0.01, float(settings.signal_strategy_max_body_ratio))),
        strategy_max_signals_per_cycle=max(1, int(settings.signal_strategy_max_signals_per_cycle)),
        rsi_enabled=True,
    )


async def get_effective_settings(
    session: AsyncSession,
    *,
    chat_id: int | None = None,
) -> EffectiveUserSettings:
    defaults = get_global_defaults()
    if not chat_id:
        return defaults

    row = await session.scalar(select(UserSignalSettings).where(UserSignalSettings.chat_id == chat_id))
    if not row:
        return defaults

    resolved_min_move = (
        float(row.min_price_move_pct)
        if row.min_price_move_pct is not None
        else defaults.min_price_move_pct
    )
    return EffectiveUserSettings(
        lower_rsi=float(row.lower_rsi) if row.lower_rsi is not None else defaults.lower_rsi,
        upper_rsi=float(row.upper_rsi) if row.upper_rsi is not None else defaults.upper_rsi,
        active_timeframes=_parse_tfs(row.active_timeframes) if row.active_timeframes else defaults.active_timeframes,
        min_price_move_pct=resolved_min_move,
        min_quote_volume=(
            float(row.min_quote_volume) if row.min_quote_volume is not None else defaults.min_quote_volume
        ),
        price_change_15m_trigger_pct=resolved_min_move,
        signal_side_mode=normalize_signal_side_mode(row.signal_side_mode),
        market_type=normalize_market_type(row.market_type),
        feed_mode_enabled=(
            bool(row.feed_mode_enabled)
            if row.feed_mode_enabled is not None
            else defaults.feed_mode_enabled
        ),
        strategy_mode_enabled=(
            bool(row.strategy_mode_enabled)
            if row.strategy_mode_enabled is not None
            else defaults.strategy_mode_enabled
        ),
        strategy_impulse_window=(
            max(2, int(row.strategy_impulse_window))
            if row.strategy_impulse_window is not None
            else defaults.strategy_impulse_window
        ),
        strategy_deviation_threshold_pct=(
            max(0.1, float(row.strategy_deviation_threshold_pct))
            if row.strategy_deviation_threshold_pct is not None
            else defaults.strategy_deviation_threshold_pct
        ),
        strategy_min_pinbar_strength=(
            max(0.1, float(row.strategy_min_pinbar_strength))
            if row.strategy_min_pinbar_strength is not None
            else defaults.strategy_min_pinbar_strength
        ),
        strategy_max_body_ratio=(
            min(1.0, max(0.01, float(row.strategy_max_body_ratio)))
            if row.strategy_max_body_ratio is not None
            else defaults.strategy_max_body_ratio
        ),
        strategy_max_signals_per_cycle=(
            max(1, int(row.strategy_max_signals_per_cycle))
            if row.strategy_max_signals_per_cycle is not None
            else defaults.strategy_max_signals_per_cycle
        ),
        rsi_enabled=(
            bool(row.rsi_enabled)
            if row.rsi_enabled is not None
            else defaults.rsi_enabled
        ),
    )


async def upsert_user_settings(
    session: AsyncSession,
    *,
    chat_id: int,
    lower_rsi: float | None = None,
    upper_rsi: float | None = None,
    active_timeframes: list[str] | None = None,
    min_price_move_pct: float | None = None,
    min_quote_volume: float | None = None,
    signal_side_mode: str | None = None,
    market_type: str | None = None,
    feed_mode_enabled: bool | None = None,
    strategy_mode_enabled: bool | None = None,
    strategy_impulse_window: int | None = None,
    strategy_deviation_threshold_pct: float | None = None,
    strategy_min_pinbar_strength: float | None = None,
    strategy_max_body_ratio: float | None = None,
    strategy_max_signals_per_cycle: int | None = None,
    rsi_enabled: bool | None = None,
) -> EffectiveUserSettings:
    row = await session.scalar(select(UserSignalSettings).where(UserSignalSettings.chat_id == chat_id))
    if not row:
        row = UserSignalSettings(chat_id=chat_id)
        session.add(row)

    if lower_rsi is not None:
        row.lower_rsi = float(lower_rsi)
    if upper_rsi is not None:
        row.upper_rsi = float(upper_rsi)
    if active_timeframes is not None:
        row.active_timeframes = ",".join(tf for tf in active_timeframes if tf in ALLOWED_TFS)
    if min_price_move_pct is not None:
        row.min_price_move_pct = float(min_price_move_pct)
    if min_quote_volume is not None:
        row.min_quote_volume = float(min_quote_volume)
    if signal_side_mode is not None:
        row.signal_side_mode = normalize_signal_side_mode(signal_side_mode)
    if market_type is not None:
        row.market_type = normalize_market_type(market_type)
    if feed_mode_enabled is not None:
        row.feed_mode_enabled = bool(feed_mode_enabled)
    if strategy_mode_enabled is not None:
        row.strategy_mode_enabled = bool(strategy_mode_enabled)
    if strategy_impulse_window is not None:
        row.strategy_impulse_window = max(2, int(strategy_impulse_window))
    if strategy_deviation_threshold_pct is not None:
        row.strategy_deviation_threshold_pct = max(0.1, float(strategy_deviation_threshold_pct))
    if strategy_min_pinbar_strength is not None:
        row.strategy_min_pinbar_strength = max(0.1, float(strategy_min_pinbar_strength))
    if strategy_max_body_ratio is not None:
        row.strategy_max_body_ratio = min(1.0, max(0.01, float(strategy_max_body_ratio)))
    if strategy_max_signals_per_cycle is not None:
        row.strategy_max_signals_per_cycle = max(1, int(strategy_max_signals_per_cycle))
    if rsi_enabled is not None:
        row.rsi_enabled = bool(rsi_enabled)

    await session.commit()
    await session.refresh(row)
    return await get_effective_settings(session, chat_id=chat_id)

