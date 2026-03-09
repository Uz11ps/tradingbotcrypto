from __future__ import annotations

from datetime import datetime

from app.services.rsi_engine import RsiSignalCandidate


def format_signal_card(candidate: RsiSignalCandidate) -> str:
    is_pump = candidate.signal_type == "pump"
    emoji = "🟢" if is_pump else "🔴"
    signal_label = "PUMP" if is_pump else "DUMP"
    ts = candidate.generated_at
    ts_str = "-" if not isinstance(ts, datetime) else ts.strftime("%H:%M")
    context_line = "\nКонтекст: weak_context" if candidate.context_tag == "weak_context" else ""
    return (
        f"{emoji} {candidate.symbol}\n"
        f"{signal_label}: {candidate.pct_change:+.2f}%\n"
        f"Цена: {candidate.prev_price:.6f} -> {candidate.current_price:.6f}\n"
        f"Время: {ts_str}"
        f"{context_line}"
    )

