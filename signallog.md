# signalog

## 19.03 21:20 - PR9/E hotfix (chat round-robin)

### Что исправлено
- Добавлен round-robin порядок обхода chat_id между циклами worker-а.
- Добавлен trace:
  - `chat_round_robin_trace cycle=... chat_ids=... rotated=...`

### Зачем
- Убрать залипание на одном chat_id в runtime.
- Обеспечить стабильную обработку нескольких чатов без ручных workaround.

## 19.03 20:50 - PR9/D hotfix (fair chat scheduling)

### Что исправлено
- Убран starvation chat-очереди в worker scan-loop при большом universe.
- Введен bounded scan-budget на chat за цикл + ротация окна символов по циклам.
- Добавлен trace:
  - `chat_scan_budget_trace ... shard_symbols=... scan_symbols=...`

### Ожидаемый эффект
- `settings_trace` и decision-логи должны появляться по всем активным chat_id, а не только по одному.
- Нет необходимости вручную удалять чаты из `user_signal_settings`.

## 19.03 02:05 - PR9 / Этап C (статистика + короткая история)

### Что добавлено
- Новый bounded endpoint: `GET /stats/short-history`
  - окно по времени ограничено (`window_hours`);
  - количество строк ограничено (`limit`);
  - summary по сигналам (`total/up/down`, `market_type_counts`);
  - краткий reject-срез (`rejects_total`, `reject_reasons_top`);
  - короткий список `recent_signals`.
- Ограничители вынесены в конфиг:
  - `SIGNAL_STATS_SHORT_WINDOW_HOURS`
  - `SIGNAL_STATS_SHORT_MAX_ROWS`

### Что проверить
- endpoint отдает только bounded-данные;
- без бесконечного накопления ответа при больших таблицах;
- показатели reject/signal пригодны для короткого аудита качества.

## 19.03 01:35 - PR9 / Этап B + PR8.1

### Что закрыто
- Futures-путь переведен на отдельный data source:
  - отдельные futures URLs для klines/ticker;
  - route reason теперь `futures_route_live_source`;
  - universe подгружается по route (`spot` и `futures` раздельно).
- UX hotfix:
  - убраны inline-кнопки под каждым сигналом;
  - добавлена одна постоянная нижняя кнопка `⬅️ Главное меню`.

### Что проверить в проде
- `market_route_trace` показывает `futures:bingx_futures` в режиме `both`.
- В логах есть futures fetch labels (`bingx ... futures ...`).
- В Telegram под сигналами нет inline-кнопок, внизу одна кнопка меню.

## 19.03 00:55 - PR9 / Этап A (market provider abstraction)

### Что добавлено
- Формализована policy маршрутизации market type через router:
  - `spot` -> всегда активный route;
  - `futures` -> только через adapter policy;
  - `both` -> детерминированное разложение на route-список.
- В воркере включен явный route trace лог:
  - `market_route_trace chat_id=... requested=... normalized=... policy=... enabled=... skipped=...`
- Route-решения вынесены из scan-loop в abstraction, чтобы не разрастался inline `if/else`.

### Что проверяем в проде
- В логах есть `market_route_trace` для активных чатов.
- При `SIGNAL_ENABLE_FUTURES_ADAPTER=false` есть явные `futures_route_skipped`.
- Universe/candle path продолжает работать без деградации latency/error.

## 17.03 22:04 — Аудит сигналов (новая логика)

### Наблюдения
- Всего сигналов за период: 287 (🟢 155 / 🔴 132)
- Сильная концентрация на: MED, WP, POKEE, CRK
- Есть быстрые перевороты по одним и тем же монетам (+/-/+/-), выглядит как недожатый dedup/cooldown

### Основные проблемы
1) Порог/ТФ применяются не так, как ожидается
2) Повторные сигналы по "живым" монетам приходят слишком часто
3) Перекос по пулу монет + вопрос памяти при расширении universe

### Решения (план)
- Привести модель порога к одному правилу (строго по выбранному ТФ/режиму)
- Усилить dedup/cooldown с anti-flip окном
- Для universe 900: шардирование + жестко bounded cache + быстрый TTL/prune
- В UI убрать путаницу close/live, показывать baseline/current/window/trigger_source

## 18.03 14:58 — Валидация после hotfix (прод)

### Что подтверждено
- `NameError` в strategy-ветке устранен: воркер не падает в рабочем цикле.
- API `500` из-за varchar-лимитов устранены: `/signals` и `/telemetry/scan-logs` дают `200 OK`.
- Порог `5%` применяется корректно:
  - есть `reject_user_min_move` на `4.x%`;
  - есть `signal_sent` на `>=5%`.
- Fallback-прозрачность работает:
  - для `tf=1h` в `live_spike` видим `eval_tf=15m`, `fallback=True`.

### Сравнение day1 vs day2 (экспорт Telegram)
- 17.03: `287` карточек `Движение`.
- 18.03: `188` карточек `Движение` (примерно `-34.5%` шумовой нагрузки).
- Карточек `4.x%`:
  - 17.03: `88`
  - 18.03: `0`
- Появился отдельный strategy-поток (`Лонг/Шорт`), требует отдельной калибровки.

### Текущий блокер
- При `scale=5` в safe-конфиге все воркеры стартуют как `index=0 count=1` и сканируют полный universe.
- Риск: дубли сигналов и лишняя нагрузка.
- В проде держим `scale=1` до завершения PR5/B3 (shard resilience).

## 18.03 18:45 — PR5/B3 runtime gate PASS (scale=5)

### Что подтвердили логами
- Шардирование восстановлено:
  - `count=5`, индексы уникально распределились `0..4`.
- Распределение нагрузки корректное:
  - `RSI shard 0: 14 symbols`
  - `RSI shard 1..4: 13 symbols`
- `HTTP 500` в проверочном окне не наблюдались, API-пути работали с `200`.

### Вывод
- Модель перестала быть full-duplicate при `scale=5`.
- Можно переходить к этапу роста universe (PR6/B2), но с контролем:
  - latency цикла,
  - доли reject/sent,
  - ошибок API и роста CPU/RAM.

## 18.03 19:05 — PR5/B3 hardening (anti-stall)

### Что добавлено
- Fail-open режим для shard lease:
  - если slot долго не захватывается, воркер уходит в fallback-shard вместо полного простоя.
- Сокращен lock TTL slot-lease:
  - `600 -> 120` секунд для более быстрого самовосстановления после recreate.
- В `runtime_state` добавлена диагностическая телеметрия:
  - `shard_fail_open`, `no_slot_streak`.

### Зачем
- Исключить сценарий, когда все воркеры стоят в `index=-1` и не сканируют рынок.
- Снизить операционную зависимость от ручной очистки `signal:worker_shard_slot:*`.

## 18.03 20:35 — PR7 (light) anti-duplicate/anti-flip

### Что добавлено
- Soft anti-flip guard на уровне фильтра сигналов:
  - отслеживает быструю смену стороны `pump <-> dump` по `(scope,symbol,timeframe)`.
  - текущий режим: `log_only=true` (сигнал не режется, только trace).
- Введены параметры:
  - `SIGNAL_SOFT_FLIP_WINDOW_SECONDS=300`
  - `SIGNAL_SOFT_FLIP_MIN_MOVE_PCT=1.0`
  - `SIGNAL_SOFT_FLIP_LOG_ONLY=true`

### Почему в light-режиме
- По фактическим логам за 12ч:
  - `PIXEL/USDT`: `0 flips / 5 events`
  - `ENJ/USDT`: `0 flips / 3 events`
  - `WP/USDT`: `0 flips / 1 events`
- То есть агрессивная фильтрация сейчас не нужна, важнее безопасная observability.

## 18.03 21:15 — PR8 UX (навигация)

### Что улучшили
- В каждую входящую карточку сигнала (feed + strategy) добавлена постоянная inline-панель:
  - `ℹ️ Текущие настройки`
  - `⬅️ Главное меню`
- Стартовый экран (`/start`) упрощен:
  - короткая подсказка «Настройки» / «Лента» + текущий статус.

### Практический эффект
- Пользователь всегда может вернуться в меню из любого сигнала в 1 тап.
- Меньше “застреваний” в длинных цепочках сообщений.