from __future__ import annotations

from statistics import fmean

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AISetting, SignalPerformance

DEFAULT_SETTINGS: dict[str, float] = {
    "ai_weight_cex": 0.55,
    "ai_weight_dex": 0.25,
    "ai_weight_sentiment": 0.20,
    "ai_entry_threshold": 0.66,
    "ai_watch_threshold": 0.42,
}


async def get_ai_setting(session: AsyncSession, key: str, default: float) -> float:
    row = await session.scalar(select(AISetting).where(AISetting.key == key))
    if not row:
        session.add(AISetting(key=key, value=str(default)))
        await session.commit()
        return default
    try:
        return float(row.value)
    except ValueError:
        return default


async def load_ai_settings(session: AsyncSession) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, default in DEFAULT_SETTINGS.items():
        result[key] = await get_ai_setting(session, key, default)
    return result


def _normalize_score(value: float, cap: float = 10.0) -> float:
    v = abs(value) / cap
    return max(0.0, min(1.0, v))


def build_ai_recommendation(
    *,
    cex_strength: float,
    dex_price_change_pct: float,
    sentiment: float,
    settings: dict[str, float],
) -> dict[str, str | float]:
    cex_score = max(0.0, min(1.0, cex_strength))
    dex_score = _normalize_score(dex_price_change_pct, cap=8.0)
    sentiment_score = (sentiment + 1.0) / 2.0

    score = (
        cex_score * settings["ai_weight_cex"]
        + dex_score * settings["ai_weight_dex"]
        + sentiment_score * settings["ai_weight_sentiment"]
    )
    score = max(0.0, min(1.0, score))

    if score >= settings["ai_entry_threshold"]:
        action = "entry"
    elif score >= settings["ai_watch_threshold"]:
        action = "watch"
    else:
        action = "hold"

    explanation = (
        f"AI score={score:.2f}: cex={cex_score:.2f}, dex={dex_score:.2f}, "
        f"sentiment={sentiment_score:.2f}. Recommended action={action}."
    )
    return {"score": score, "action": action, "explanation": explanation}


def _clamp(v: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, v))


async def tune_strategy_from_history(session: AsyncSession, *, last_n: int = 150) -> dict[str, float]:
    rows = (
        await session.execute(
            select(SignalPerformance).order_by(SignalPerformance.evaluated_at.desc()).limit(last_n)
        )
    ).scalars().all()
    if len(rows) < 30:
        return await load_ai_settings(session)

    winrate = fmean([1.0 if row.is_win else 0.0 for row in rows])
    avg_pnl = fmean([row.pnl_pct for row in rows])

    settings = await load_ai_settings(session)
    entry = settings["ai_entry_threshold"]
    watch = settings["ai_watch_threshold"]

    if winrate < 0.48 or avg_pnl < 0:
        entry = _clamp(entry + 0.03, 0.55, 0.9)
        watch = _clamp(watch + 0.02, 0.3, 0.8)
    elif winrate > 0.58 and avg_pnl > 0:
        entry = _clamp(entry - 0.02, 0.45, 0.85)
        watch = _clamp(watch - 0.01, 0.25, 0.75)

    await _save_settings(
        session,
        {
            "ai_entry_threshold": entry,
            "ai_watch_threshold": watch,
        },
    )
    settings["ai_entry_threshold"] = entry
    settings["ai_watch_threshold"] = watch
    return settings


async def _save_settings(session: AsyncSession, values: dict[str, float]) -> None:
    for key, value in values.items():
        row = await session.scalar(select(AISetting).where(AISetting.key == key))
        if row:
            row.value = f"{value:.6f}"
        else:
            session.add(AISetting(key=key, value=f"{value:.6f}"))
    await session.commit()

