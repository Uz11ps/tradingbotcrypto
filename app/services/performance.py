from __future__ import annotations

from statistics import fmean

from sqlalchemy import Select, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Signal, SignalDirection, SignalPerformance
from app.services.market_data import fetch_market_snapshot


def _calc_pnl_pct(direction: SignalDirection, entry_price: float, current_price: float) -> float:
    if entry_price <= 0:
        return 0.0
    if direction == SignalDirection.up:
        return ((current_price - entry_price) / entry_price) * 100
    return ((entry_price - current_price) / entry_price) * 100


def _max_drawdown(values: list[float]) -> float:
    if not values:
        return 0.0
    peak = values[0]
    max_dd = 0.0
    for v in values:
        peak = max(peak, v)
        dd = peak - v
        max_dd = max(max_dd, dd)
    return max_dd


async def refresh_signal_performance(
    session: AsyncSession,
    *,
    symbol: str | None = None,
    timeframe: str | None = None,
    limit: int = 250,
) -> int:
    stmt: Select[tuple[Signal]] = select(Signal).order_by(desc(Signal.created_at)).limit(limit)
    if symbol:
        stmt = stmt.where(Signal.symbol == symbol)
    if timeframe:
        stmt = stmt.where(Signal.timeframe == timeframe)
    signals = (await session.execute(stmt)).scalars().all()
    if not signals:
        return 0

    updated = 0
    cache: dict[tuple[str, str], float] = {}
    for signal in signals:
        if signal.price is None:
            continue
        existing = await session.scalar(
            select(SignalPerformance).where(SignalPerformance.signal_id == signal.id)
        )
        if existing:
            continue

        key = (signal.symbol, signal.timeframe)
        if key not in cache:
            snapshot = await fetch_market_snapshot(symbol=signal.symbol, timeframe=signal.timeframe, limit=60)
            cache[key] = float(snapshot["price"])
        current_price = cache[key]
        pnl_pct = _calc_pnl_pct(signal.direction, signal.price, current_price)
        item = SignalPerformance(
            signal_id=signal.id,
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            pnl_pct=pnl_pct,
            is_win=pnl_pct > 0,
        )
        session.add(item)
        updated += 1

    if updated:
        await session.commit()
    return updated


async def build_performance_stats(
    session: AsyncSession,
    *,
    symbol: str | None = None,
    timeframe: str | None = None,
    limit: int = 300,
) -> dict[str, float | int]:
    await refresh_signal_performance(session, symbol=symbol, timeframe=timeframe, limit=limit)

    stmt = select(SignalPerformance).order_by(desc(SignalPerformance.evaluated_at)).limit(limit)
    if symbol:
        stmt = stmt.where(SignalPerformance.symbol == symbol)
    if timeframe:
        stmt = stmt.where(SignalPerformance.timeframe == timeframe)
    rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        return {
            "evaluated_signals": 0,
            "winrate_pct": 0.0,
            "hit_ratio_pct": 0.0,
            "avg_pnl_pct": 0.0,
            "total_pnl_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "profit_factor": 0.0,
        }

    pnls = [r.pnl_pct for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    cumulative: list[float] = []
    running = 0.0
    for value in reversed(pnls):
        running += value
        cumulative.append(running)

    winrate = (len(wins) / len(rows)) * 100
    hit_ratio = (len([p for p in pnls if abs(p) >= 0.35]) / len(rows)) * 100
    avg_pnl = fmean(pnls)
    total_pnl = sum(pnls)
    drawdown = _max_drawdown(cumulative)
    gross_profit = sum(wins)
    gross_loss_abs = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss_abs) if gross_loss_abs > 0 else gross_profit

    return {
        "evaluated_signals": len(rows),
        "winrate_pct": round(winrate, 2),
        "hit_ratio_pct": round(hit_ratio, 2),
        "avg_pnl_pct": round(avg_pnl, 4),
        "total_pnl_pct": round(total_pnl, 4),
        "max_drawdown_pct": round(drawdown, 4),
        "profit_factor": round(profit_factor, 4),
    }

