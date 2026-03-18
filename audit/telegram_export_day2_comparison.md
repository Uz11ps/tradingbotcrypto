# Telegram Export Comparison (2026-03-17 vs 2026-03-18)

## Sources
- `C:\Users\t6are\Downloads\Telegram Desktop\ChatExport_2026-03-17\messages.html`
- `C:\Users\t6are\Downloads\Telegram Desktop\ChatExport_2026-03-18\messages.html`

## Key Counts
- `Движение:` cards:
  - 2026-03-17: `287`
  - 2026-03-18: `188`
  - Delta: `-99` (`-34.5%`)
- `Движение: +/-4.x%` (below configured 5% threshold):
  - 2026-03-17: `88`
  - 2026-03-18: `0`
- Strategy cards (`Сигнал: Лонг|Шорт`):
  - 2026-03-17: `0`
  - 2026-03-18: `58`

## Interpretation
- Threshold enforcement improved materially: day 2 has no visible 4.x% movement cards.
- Total feed volume is lower, consistent with reduced noise/spam.
- Strategy stream appeared on day 2 and should be evaluated separately from live_spike feed quality.

## Operational Note
- During a `scale=5` run under safe config (`count=1/index=0`), multiple workers can scan the full universe in parallel, increasing duplicate risk.
- Keep production in `scale=1` safe mode until shard-resilience (PR5/B3) is completed and validated.
