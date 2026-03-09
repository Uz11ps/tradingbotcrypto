from __future__ import annotations

import json
from contextlib import suppress
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    AnalyticsOut,
    FeedMoverOut,
    FeedOut,
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
    UserSignalSettingsOut,
    UserSignalSettingsUpdate,
)
from app.core.config import settings
from app.db.models import (
    AnalyticsLog,
    NewsAndSentiment,
    Signal,
    SignalDirection,
    SignalType,
    UserSignalSettings,
    UserSubscription,
)
from app.db.session import get_session
from app.services.ai_engine import (
    build_ai_recommendation,
    load_ai_settings,
    tune_strategy_from_history,
)
from app.services.binance_candles import (
    TIMEFRAME_MAP,
    BinanceCandlesError,
    build_snapshot,
    fetch_closes,
)
from app.services.binance_universe import BinanceUniverseError, fetch_spot_symbols
from app.services.dex_data import DexDataError, fetch_dex_snapshot
from app.services.market_data import MarketDataError, fetch_market_snapshot
from app.services.market_feed import MarketFeedError, fetch_top_movers
from app.services.news_sentiment import NewsSentimentError, fetch_news_and_sentiment
from app.services.performance import build_performance_stats
from app.services.rsi_engine import compute_rsi, evaluate_rsi_signal, validate_candidate_filters
from app.services.user_settings import get_effective_settings, upsert_user_settings

router = APIRouter()
ALLOWED_SOURCES = {"cex", "dex", "hybrid"}


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/feed/movers", response_model=FeedOut)
async def feed_movers(
    universe: int = 100,
    limit: int = 15,
    min_change_pct: float = 2.5,
    chat_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> FeedOut:
    if settings.signal_engine_mode == "rsi":
        try:
            effective = await get_effective_settings(session, chat_id=chat_id)
            symbols = await fetch_spot_symbols(quote_asset=settings.binance_quote_asset)
        except BinanceUniverseError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

        selected = symbols[: max(10, min(universe, len(symbols)))]
        rows: list[FeedMoverOut] = []
        for symbol in selected:
            if len(rows) >= max(1, min(limit, 50)):
                break
            for timeframe in effective.active_timeframes:
                if timeframe not in TIMEFRAME_MAP:
                    continue
                try:
                    snapshot = await build_snapshot(
                        symbol=symbol,
                        timeframe=timeframe,
                        volume_avg_window=settings.signal_volume_avg_window,
                    )
                    closes = await fetch_closes(symbol=symbol, timeframe=timeframe, limit=100)
                    rsi = compute_rsi(closes, period=settings.rsi_period)
                    candidate = evaluate_rsi_signal(
                        symbol=symbol,
                        timeframe=timeframe,
                        rsi_value=rsi,
                        price_change_5m=snapshot.price_change_5m,
                        price_change_15m=snapshot.price_change_15m,
                        price_change_5m_trigger_pct=settings.signal_price_change_5m_trigger_pct,
                        price_change_15m_trigger_pct=settings.signal_price_change_15m_trigger_pct,
                        prev_price=snapshot.prev_close,
                        current_price=snapshot.current_close,
                        pct_change=snapshot.pct_change,
                        current_volume=snapshot.current_volume,
                        avg_volume_20=snapshot.avg_volume_20,
                        generated_at=snapshot.generated_at,
                    )
                    if not candidate:
                        continue
                    is_valid, _ = validate_candidate_filters(
                        candidate,
                        lower_rsi=max(effective.lower_rsi, 40.0),
                        upper_rsi=min(effective.upper_rsi, 60.0),
                    )
                    if not is_valid:
                        continue
                    rows.append(
                        FeedMoverOut(
                            symbol=candidate.symbol,
                            direction="up" if candidate.signal_type == "pump" else "down",
                            signal_type=candidate.signal_type,
                            change_pct=candidate.pct_change,
                            prev_price=candidate.prev_price,
                            current_price=candidate.current_price,
                            generated_at=candidate.generated_at,
                        )
                    )
                except (BinanceCandlesError, ValueError):
                    continue
        return FeedOut(generated_at=datetime.now(tz=UTC), universe_size=len(selected), movers=rows[:limit])

    try:
        payload = await fetch_top_movers(
            universe_size=universe,
            movers_limit=limit,
            min_abs_change_pct=min_change_pct,
        )
    except MarketFeedError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=502, detail=f"Feed source error: {e}") from e
    movers = [
        FeedMoverOut(
            symbol=m["symbol"],
            direction=m["direction"],
            signal_type="pump" if m["direction"] == "up" else "dump",
            change_pct=float(m["change_24h_pct"]),
            prev_price=float(m["last_price"]),
            current_price=float(m["last_price"]),
            generated_at=payload["generated_at"],
        )
        for m in payload.get("movers", [])
    ]
    return FeedOut(generated_at=payload["generated_at"], universe_size=payload["universe_size"], movers=movers)


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
            signal_type=s.signal_type,
            trigger_source=s.trigger_source,
            rsi_value=s.rsi_value,
            prev_price=s.prev_price,
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
    signal_type: str | None = None
    if payload.signal_type:
        try:
            signal_type = SignalType(payload.signal_type).value
        except ValueError as e:
            raise HTTPException(status_code=400, detail="signal_type must be 'pump' or 'dump'") from e

    s = Signal(
        symbol=payload.symbol,
        timeframe=payload.timeframe,
        direction=direction,
        strength=payload.strength,
        action=payload.action,
        signal_type=signal_type,
        trigger_source=payload.trigger_source,
        rsi_value=payload.rsi_value,
        prev_price=payload.prev_price,
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
        signal_type=s.signal_type,
        trigger_source=s.trigger_source,
        rsi_value=s.rsi_value,
        prev_price=s.prev_price,
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


@router.get("/user-settings", response_model=UserSignalSettingsOut)
async def get_user_settings(
    chat_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> UserSignalSettingsOut:
    effective = await get_effective_settings(session, chat_id=chat_id)
    return UserSignalSettingsOut(
        chat_id=chat_id or 0,
        lower_rsi=effective.lower_rsi,
        upper_rsi=effective.upper_rsi,
        active_timeframes=effective.active_timeframes,
        min_price_move_pct=effective.min_price_move_pct,
        min_quote_volume=effective.min_quote_volume,
    )


@router.post("/user-settings", response_model=UserSignalSettingsOut)
async def update_user_settings(
    chat_id: int,
    payload: UserSignalSettingsUpdate,
    session: AsyncSession = Depends(get_session),
) -> UserSignalSettingsOut:
    effective = await upsert_user_settings(
        session,
        chat_id=chat_id,
        lower_rsi=payload.lower_rsi,
        upper_rsi=payload.upper_rsi,
        active_timeframes=payload.active_timeframes,
        min_price_move_pct=payload.min_price_move_pct,
        min_quote_volume=payload.min_quote_volume,
    )
    return UserSignalSettingsOut(
        chat_id=chat_id,
        lower_rsi=effective.lower_rsi,
        upper_rsi=effective.upper_rsi,
        active_timeframes=effective.active_timeframes,
        min_price_move_pct=effective.min_price_move_pct,
        min_quote_volume=effective.min_quote_volume,
    )


@router.get("/user-settings/chats", response_model=list[int])
async def list_user_settings_chats(session: AsyncSession = Depends(get_session)) -> list[int]:
    rows = (await session.execute(select(UserSignalSettings.chat_id))).scalars().all()
    return [int(chat_id) for chat_id in rows if chat_id]


@router.post("/ai/tune")
async def ai_tune(session: AsyncSession = Depends(get_session)) -> dict[str, float]:
    settings = await tune_strategy_from_history(session, last_n=200)
    return settings

