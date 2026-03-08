from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import UserSignalSettings

DEFAULT_TFS = ("5m", "15m", "1h", "4h")
ALLOWED_TFS = set(DEFAULT_TFS)


@dataclass(slots=True)
class EffectiveUserSettings:
    lower_rsi: float
    upper_rsi: float
    active_timeframes: list[str]
    min_quote_volume: float


def _parse_tfs(raw: str | None) -> list[str]:
    if not raw:
        return list(DEFAULT_TFS)
    tfs = [x.strip() for x in raw.split(",") if x.strip()]
    normalized = [tf for tf in tfs if tf in ALLOWED_TFS]
    return normalized or list(DEFAULT_TFS)


def get_global_defaults() -> EffectiveUserSettings:
    return EffectiveUserSettings(
        lower_rsi=float(settings.rsi_default_lower),
        upper_rsi=float(settings.rsi_default_upper),
        active_timeframes=_parse_tfs(settings.rsi_default_timeframes),
        min_quote_volume=float(settings.binance_min_quote_volume),
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

    return EffectiveUserSettings(
        lower_rsi=float(row.lower_rsi) if row.lower_rsi is not None else defaults.lower_rsi,
        upper_rsi=float(row.upper_rsi) if row.upper_rsi is not None else defaults.upper_rsi,
        active_timeframes=_parse_tfs(row.active_timeframes) if row.active_timeframes else defaults.active_timeframes,
        min_quote_volume=(
            float(row.min_quote_volume) if row.min_quote_volume is not None else defaults.min_quote_volume
        ),
    )


async def upsert_user_settings(
    session: AsyncSession,
    *,
    chat_id: int,
    lower_rsi: float | None = None,
    upper_rsi: float | None = None,
    active_timeframes: list[str] | None = None,
    min_quote_volume: float | None = None,
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
    if min_quote_volume is not None:
        row.min_quote_volume = float(min_quote_volume)

    await session.commit()
    await session.refresh(row)
    return await get_effective_settings(session, chat_id=chat_id)

