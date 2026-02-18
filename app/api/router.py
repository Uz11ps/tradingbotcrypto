from __future__ import annotations

import json
from contextlib import suppress

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    AnalyticsOut,
    LiveSignalOut,
    MarketOverviewOut,
    NewsSentimentOut,
    PerformanceStatsOut,
    SignalCreate,
    SignalOut,
    StatsOverviewOut,
    SubscriptionCreate,
    SubscriptionDelete,
    SubscriptionOut,
)
from app.db.models import (
    AnalyticsLog,
    NewsAndSentiment,
    Signal,
    SignalDirection,
    UserSubscription,
)
from app.db.session import get_session
from app.services.ai_engine import (
    build_ai_recommendation,
    load_ai_settings,
    tune_strategy_from_history,
)
from app.services.dex_data import DexDataError, fetch_dex_snapshot
from app.services.market_data import MarketDataError, fetch_market_snapshot
from app.services.news_sentiment import NewsSentimentError, fetch_news_and_sentiment
from app.services.performance import build_performance_stats

router = APIRouter()
ALLOWED_SOURCES = {"cex", "dex", "hybrid"}


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/signals", response_model=list[SignalOut])
async def list_signals(
    symbol: str | None = None,
    timeframe: str | None = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
) -> list[SignalOut]:
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 500")

    stmt = select(Signal).order_by(desc(Signal.created_at)).limit(limit)
    if symbol:
        stmt = stmt.where(Signal.symbol == symbol)
    if timeframe:
        stmt = stmt.where(Signal.timeframe == timeframe)

    rows = (await session.execute(stmt)).scalars().all()
    return [
        SignalOut(
            id=s.id,
            created_at=s.created_at,
            symbol=s.symbol,
            timeframe=s.timeframe,
            direction=s.direction.value,
            strength=s.strength,
            action=s.action,
            source="hybrid",
            price=s.price,
            volume=s.volume,
            liquidity=None,
            reason=s.reason,
        )
        for s in rows
    ]


@router.post("/signals", response_model=SignalOut)
async def create_signal(
    payload: SignalCreate,
    session: AsyncSession = Depends(get_session),
) -> SignalOut:
    try:
        direction = SignalDirection(payload.direction)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="direction must be 'up' or 'down'") from e
    if payload.source not in ALLOWED_SOURCES:
        raise HTTPException(status_code=400, detail="source must be 'cex', 'dex' or 'hybrid'")

    s = Signal(
        symbol=payload.symbol,
        timeframe=payload.timeframe,
        direction=direction,
        strength=payload.strength,
        action=payload.action,
        price=payload.price,
        volume=payload.volume,
        reason=payload.reason,
    )
    session.add(s)
    await session.commit()
    await session.refresh(s)

    return SignalOut(
        id=s.id,
        created_at=s.created_at,
        symbol=s.symbol,
        timeframe=s.timeframe,
        direction=s.direction.value,
        strength=s.strength,
        action=s.action,
        source=payload.source,
        price=s.price,
        volume=s.volume,
        liquidity=payload.liquidity,
        reason=s.reason,
    )


@router.get("/signals/live", response_model=LiveSignalOut)
async def live_signal(
    symbol: str,
    timeframe: str,
    source: str = "hybrid",
    persist: bool = True,
    session: AsyncSession = Depends(get_session),
) -> LiveSignalOut:
    if source not in ALLOWED_SOURCES:
        raise HTTPException(status_code=400, detail="source must be 'cex', 'dex' or 'hybrid'")

    try:
        cex = await fetch_market_snapshot(symbol=symbol, timeframe=timeframe)
    except MarketDataError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=502, detail=f"Market source error: {e}") from e

    dex: dict[str, object] | None = None
    if source in {"dex", "hybrid"}:
        try:
            dex = await fetch_dex_snapshot(symbol)
        except DexDataError:
            dex = None

    news_payload = {"avg_sentiment": 0.0}
    with suppress(NewsSentimentError):
        news_payload = await fetch_news_and_sentiment(symbol, limit=6)

    ai_settings = await load_ai_settings(session)
    ai = build_ai_recommendation(
        cex_strength=float(cex["strength"]),
        dex_price_change_pct=float((dex or {}).get("price_change_1h_pct", 0.0)),
        sentiment=float(news_payload["avg_sentiment"]),
        settings=ai_settings,
    )

    direction = cex["direction"]
    if source == "dex" and dex:
        direction = "up" if float(dex["price_change_1h_pct"]) >= 0 else "down"
    strength = max(float(cex["strength"]), float(ai["score"]))
    action = str(ai["action"])
    price = float(cex["price"])
    volume = float(cex["volume"])
    liquidity = float((dex or {}).get("liquidity_usd", 0.0) or 0.0) or None
    summary = (
        f"{symbol} {timeframe}: cex_change={float(cex['price_change_pct']):+.2f}%, "
        f"dex_change_1h={float((dex or {}).get('price_change_1h_pct', 0.0)):+.2f}%, "
        f"sentiment={float(news_payload['avg_sentiment']):+.2f}, ai={float(ai['score']):.2f}."
    )

    if persist:
        s = Signal(
            symbol=symbol,
            timeframe=timeframe,
            direction=SignalDirection(direction),
            strength=strength,
            action=action,
            price=price,
            volume=volume,
            reason=summary,
        )
        session.add(s)
        await session.commit()

    return LiveSignalOut(
        symbol=symbol,
        timeframe=timeframe,
        generated_at=cex["generated_at"],
        direction=direction,
        strength=strength,
        action=action,
        source=source,
        price=price,
        price_change_pct=float(cex["price_change_pct"]),
        volume=volume,
        liquidity=liquidity,
        volume_change_pct=float(cex["volume_change_pct"]),
        volatility_pct=float(cex["volatility_pct"]),
        trend=str(cex["trend"]),
        summary=summary,
        ai_score=float(ai["score"]),
        ai_explanation=str(ai["explanation"]),
    )


@router.get("/analytics", response_model=AnalyticsOut)
async def analytics(
    symbol: str,
    timeframe: str,
    session: AsyncSession = Depends(get_session),
) -> AnalyticsOut:
    try:
        cex = await fetch_market_snapshot(symbol=symbol, timeframe=timeframe)
    except MarketDataError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=502, detail=f"Market source error: {e}") from e

    try:
        dex = await fetch_dex_snapshot(symbol)
    except DexDataError:
        dex = None
    try:
        news = await fetch_news_and_sentiment(symbol, limit=8)
    except NewsSentimentError:
        news = {"avg_sentiment": 0.0, "headlines": []}

    ai_settings = await load_ai_settings(session)
    ai = build_ai_recommendation(
        cex_strength=float(cex["strength"]),
        dex_price_change_pct=float((dex or {}).get("price_change_1h_pct", 0.0)),
        sentiment=float(news["avg_sentiment"]),
        settings=ai_settings,
    )

    payload = {
        "cex_price": cex["price"],
        "cex_price_change_pct": cex["price_change_pct"],
        "cex_volume_change_pct": cex["volume_change_pct"],
        "cex_volatility_pct": cex["volatility_pct"],
        "trend": cex["trend"],
        "dex_price": (dex or {}).get("price"),
        "dex_price_change_1h_pct": (dex or {}).get("price_change_1h_pct"),
        "dex_liquidity_usd": (dex or {}).get("liquidity_usd"),
        "avg_news_sentiment": news["avg_sentiment"],
        "ai_score": ai["score"],
        "ai_action": ai["action"],
    }
    log = AnalyticsLog(symbol=symbol, timeframe=timeframe, payload=json.dumps(payload))
    session.add(log)
    await session.commit()

    summary = (
        f"{symbol} {timeframe}: cex={float(cex['price']):.4f} ({float(cex['price_change_pct']):+.2f}%), "
        f"dex={float((dex or {}).get('price', 0.0)):.4f}, "
        f"news_sentiment={float(news['avg_sentiment']):+.2f}, ai_action={ai['action']}."
    )
    return AnalyticsOut(
        symbol=symbol,
        timeframe=timeframe,
        summary=summary,
        ai_explanation=str(ai["explanation"]),
        avg_news_sentiment=float(news["avg_sentiment"]),
    )


@router.get("/stats/overview", response_model=StatsOverviewOut)
async def stats_overview(session: AsyncSession = Depends(get_session)) -> StatsOverviewOut:
    total_stmt = select(func.count(Signal.id))
    up_stmt = select(func.count(Signal.id)).where(Signal.direction == SignalDirection.up)
    down_stmt = select(func.count(Signal.id)).where(Signal.direction == SignalDirection.down)

    total = int((await session.execute(total_stmt)).scalar_one() or 0)
    up = int((await session.execute(up_stmt)).scalar_one() or 0)
    down = int((await session.execute(down_stmt)).scalar_one() or 0)

    return StatsOverviewOut(total_signals=total, up_signals=up, down_signals=down)


@router.get("/stats/performance", response_model=PerformanceStatsOut)
async def stats_performance(
    symbol: str | None = None,
    timeframe: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> PerformanceStatsOut:
    stats = await build_performance_stats(session, symbol=symbol, timeframe=timeframe, limit=300)
    return PerformanceStatsOut(**stats)


@router.get("/news/sentiment", response_model=NewsSentimentOut)
async def news_sentiment(
    symbol: str,
    session: AsyncSession = Depends(get_session),
) -> NewsSentimentOut:
    try:
        payload = await fetch_news_and_sentiment(symbol, limit=8)
    except NewsSentimentError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    # Храним последние новости в таблице для аудита аналитики.
    for item in payload["headlines"]:
        row = NewsAndSentiment(
            symbol=symbol,
            source=item["source"],
            title=item["title"],
            url=item["url"],
            sentiment=item["sentiment"],
            raw=None,
        )
        session.add(row)
    await session.commit()

    return NewsSentimentOut(**payload)


@router.get("/market/overview", response_model=MarketOverviewOut)
async def market_overview(
    symbol: str,
    timeframe: str,
    session: AsyncSession = Depends(get_session),
) -> MarketOverviewOut:
    try:
        cex = await fetch_market_snapshot(symbol=symbol, timeframe=timeframe)
    except MarketDataError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        dex = await fetch_dex_snapshot(symbol)
    except DexDataError:
        dex = None
    try:
        news = await fetch_news_and_sentiment(symbol, limit=6)
    except NewsSentimentError:
        news = {"avg_sentiment": 0.0, "headlines": []}

    ai_settings = await load_ai_settings(session)
    ai = build_ai_recommendation(
        cex_strength=float(cex["strength"]),
        dex_price_change_pct=float((dex or {}).get("price_change_1h_pct", 0.0)),
        sentiment=float(news["avg_sentiment"]),
        settings=ai_settings,
    )
    summary = (
        f"CEX {float(cex['price']):.4f} ({float(cex['price_change_pct']):+.2f}%), "
        f"DEX {float((dex or {}).get('price', 0.0)):.4f}, "
        f"news {float(news['avg_sentiment']):+.2f}, AI {ai['action']} ({float(ai['score']):.2f})."
    )

    return MarketOverviewOut(
        symbol=symbol,
        timeframe=timeframe,
        cex_price=float(cex["price"]),
        cex_price_change_pct=float(cex["price_change_pct"]),
        cex_volume=float(cex["volume"]),
        dex_price=float((dex or {}).get("price", 0.0)) if dex else None,
        dex_price_change_1h_pct=float((dex or {}).get("price_change_1h_pct", 0.0)) if dex else None,
        dex_liquidity_usd=float((dex or {}).get("liquidity_usd", 0.0)) if dex else None,
        avg_news_sentiment=float(news["avg_sentiment"]),
        ai_score=float(ai["score"]),
        ai_action=str(ai["action"]),
        ai_explanation=str(ai["explanation"]),
        summary=summary,
    )


@router.get("/subscriptions", response_model=list[SubscriptionOut])
async def list_subscriptions(
    chat_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[SubscriptionOut]:
    stmt = select(UserSubscription).where(UserSubscription.is_active.is_(True))
    if chat_id is not None:
        stmt = stmt.where(UserSubscription.chat_id == chat_id)
    stmt = stmt.order_by(desc(UserSubscription.created_at))
    rows = (await session.execute(stmt)).scalars().all()
    return [
        SubscriptionOut(
            id=row.id,
            chat_id=row.chat_id,
            symbol=row.symbol,
            timeframe=row.timeframe,
            is_active=row.is_active,
        )
        for row in rows
    ]


@router.post("/subscriptions", response_model=SubscriptionOut)
async def add_subscription(
    payload: SubscriptionCreate,
    session: AsyncSession = Depends(get_session),
) -> SubscriptionOut:
    existing = await session.scalar(
        select(UserSubscription).where(
            UserSubscription.chat_id == payload.chat_id,
            UserSubscription.symbol == payload.symbol,
            UserSubscription.timeframe == payload.timeframe,
        )
    )
    if existing:
        existing.is_active = True
        await session.commit()
        return SubscriptionOut(
            id=existing.id,
            chat_id=existing.chat_id,
            symbol=existing.symbol,
            timeframe=existing.timeframe,
            is_active=existing.is_active,
        )

    row = UserSubscription(
        chat_id=payload.chat_id,
        symbol=payload.symbol,
        timeframe=payload.timeframe,
        is_active=True,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return SubscriptionOut(
        id=row.id,
        chat_id=row.chat_id,
        symbol=row.symbol,
        timeframe=row.timeframe,
        is_active=row.is_active,
    )


@router.delete("/subscriptions")
async def remove_subscription(
    payload: SubscriptionDelete,
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    row = await session.scalar(
        select(UserSubscription).where(
            UserSubscription.chat_id == payload.chat_id,
            UserSubscription.symbol == payload.symbol,
            UserSubscription.timeframe == payload.timeframe,
        )
    )
    if not row:
        return {"ok": True}
    row.is_active = False
    await session.commit()
    return {"ok": True}


@router.post("/ai/tune")
async def ai_tune(session: AsyncSession = Depends(get_session)) -> dict[str, float]:
    settings = await tune_strategy_from_history(session, last_n=200)
    return settings

