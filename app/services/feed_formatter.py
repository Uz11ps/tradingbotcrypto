from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.rsi_engine import RsiSignalCandidate

MSK = timezone(timedelta(hours=3))


def _smart_price(price: float) -> str:
    if price >= 100:
        return f"{price:.2f}"
    if price >= 1:
        return f"{price:.4f}"
    if price >= 0.01:
        return f"{price:.6f}"
    return f"{price:.8f}"


def _fmt_volume(vol: float) -> str:
    if vol >= 1_000_000_000:
        return f"${vol / 1_000_000_000:.1f}B"
    if vol >= 1_000_000:
        return f"${vol / 1_000_000:.1f}M"
    if vol >= 1_000:
        return f"${vol / 1_000:.0f}K"
    return f"${vol:.0f}"


def format_signal_card(candidate: RsiSignalCandidate) -> str:
    is_pump = candidate.signal_type == "pump"
    emoji = "🟢" if is_pump else "🔴"
    signal_label = "PUMP" if is_pump else "DUMP"
    ts = candidate.generated_at
    ts_str = "-"
    if isinstance(ts, datetime):
        msk_time = ts.astimezone(MSK)
        ts_str = msk_time.strftime("%H:%M МСК")
    vol_str = _fmt_volume(candidate.quote_volume_24h)
    div_type_map = {
        "bullish": "бычья",
        "bearish": "медвежья",
        "hidden_bullish": "скрытая бычья",
        "hidden_bearish": "скрытая медвежья",
    }
    if candidate.rsi_divergence_type and candidate.rsi_divergence_pct is not None:
        div_text = (
            f"{div_type_map.get(candidate.rsi_divergence_type, candidate.rsi_divergence_type)} "
            f"{candidate.rsi_divergence_pct:.1f}%"
        )
    else:
        div_text = "нет"
    return (
        f"{emoji} {candidate.symbol} ({candidate.timeframe})\n"
        f"{signal_label}: {candidate.pct_change:+.2f}%\n"
        f"Цена: {_smart_price(candidate.prev_price)} → {_smart_price(candidate.current_price)}\n"
        f"RSI: {candidate.rsi_value:.1f} | Объём 24h: {vol_str}\n"
        f"Дивергенция RSI: {div_text}\n"
        f"Время: {ts_str}"
    )

