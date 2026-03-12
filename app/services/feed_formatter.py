from __future__ import annotations

from app.services.rsi_engine import RsiSignalCandidate
from app.services.strategy_engine import StrategySignalCandidate


def _smart_price(price: float) -> str:
    if price >= 100:
        return f"{price:,.0f}"
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
    marker = "🟢" if candidate.signal_type == "pump" else "🔴"
    vol_str = _fmt_volume(candidate.quote_volume_24h)
    return (
        f"{marker} {candidate.symbol}\n"
        f"Движение: {candidate.pct_change:+.1f}%\n"
        f"Цена: {_smart_price(candidate.current_price)}\n"
        f"RSI: {candidate.rsi_value:.1f}\n"
        f"Объём 24ч: {vol_str}"
    )


def format_strategy_signal_card(candidate: StrategySignalCandidate) -> str:
    marker = "📉" if candidate.direction == "short" else "📈"
    direction_label = "Шорт" if candidate.direction == "short" else "Лонг"
    return (
        f"{marker} {candidate.symbol}\n"
        f"Стратегия: Pin Bar + отклонение\n"
        f"Сигнал: {direction_label}\n"
        f"Отклонение: {candidate.deviation_pct:+.2f}%\n"
        f"Цена: {_smart_price(candidate.current_price)}"
    )

