Вопрос 1 — Проблема «мертвой» цены
Основной вопрос

Как проверить, возникает ли расхождение цены из-за задержки источника данных (биржи/API) или из-за ошибки в нашем коде при фиксации price snapshot в момент генерации сигнала?

Уточняющие технические вопросы

Из какого именно источника берётся цена, которая записывается в сигнал?
Проверить в коде:

используется ли last trade price

mark price

bid/ask midpoint

или close последней свечи.

В какой момент времени происходит snapshot цены?
Нужно проверить последовательность:

market_data_received
→ signal_detected
→ price_snapshot_taken
→ signal_saved
→ notification_sent

Важно понять:
цена фиксируется до отправки сигнала или используется ранее сохранённое значение.

Есть ли лаг между тиком биржи и нашим snapshot?

Добавить логирование:

exchange_trade_timestamp
local_receive_timestamp
signal_detection_timestamp
price_snapshot_timestamp
notification_sent_timestamp

Это позволит проверить:

delta1 = receive_time - exchange_trade_time
delta2 = snapshot_time - receive_time
delta3 = notification_time - snapshot_time

Используем ли мы кешированные данные?

Проверить:

price_cache
ticker_cache
candles_cache

Возможная проблема:

signal detected at T
price taken from cache updated at T-3s

Синхронизированы ли часы системы и биржи?

Проверить:

server_time_offset = exchange_time - local_time

Если offset > 500–1000 ms, могут возникать ложные “мертвые цены”.

Технический запрос разработчику
Проверить функцию формирования сигнала:

1. Где именно берётся price_snapshot для сигнала.
2. Не используется ли cached ticker вместо последней сделки.
3. Не берётся ли цена из close свечи вместо real-time trade.
4. Добавить логирование временных меток:
   exchange_trade_time
   local_receive_time
   signal_detect_time
   snapshot_time
   message_sent_time.
Вопрос 2 — Низкая частота сигналов
Основной вопрос

Как определить: низкая частота сигналов вызвана реальными рыночными условиями или алгоритм пропускает сигналы из-за слишком жёстких фильтров или ошибки в коде?

Что нужно проверить в логике
1. Сколько потенциальных сигналов отбрасывается фильтрами

Добавить метрику:

signals_detected_raw
signals_after_filters
signals_sent

Пример:

raw_candidates = 120
after_volume_filter = 40
after_rsi_filter = 12
final_signals = 2

Это сразу покажет, где именно “умирают” сигналы.

2. Проверить чувствительность основных параметров

Нужно логировать:

price_change_percent
volume_spike
liquidity
RSI
time_window

И смотреть распределение.

Если большинство движений:

4.8–5.2%

а порог установлен:

>=10%

то алгоритм просто не может генерировать сигналы.

3. Проверить universe рынка

Добавить метрику:

total_pairs_on_exchange
pairs_scanned
pairs_filtered_by_liquidity
pairs_with_valid_data

Частая ошибка:

exchange_pairs = 700
bot_scans = 120
4. Проверить частоту сканирования рынка

Нужно измерить:

scan_cycle_duration
pairs_per_cycle
poll_interval

Если сканирование идёт медленно:

scan takes 40 sec

бот может пропускать короткие импульсы.

Метрики для дашборда

Рекомендуется добавить:

signals_per_hour
raw_candidates_per_hour
filter_rejection_rate
avg_price_move_detected
pairs_scanned
scan_cycle_time
latency_market_data

Дополнительно:

distribution(price_change_percent)
distribution(volume_spike)

Это покажет, соответствует ли стратегия реальным движениям рынка.

Технический запрос разработчику
Добавить debug-логирование кандидатов сигналов.

Для каждого symbol scan записывать:
symbol
price_start
price_current
price_change_percent
volume_spike
liquidity
RSI
reject_reason

Цель: определить, какие фильтры отсекают большинство сигналов.
Вопрос 3 — Дублирование сигналов
Основной вопрос

Как реализовать защиту от повторных сигналов по одному активу, чтобы избежать дублей в течение короткого интервала, но при этом не блокировать новый сигнал, если спустя время сформировалось новое движение?

Что нужно проверить в текущей логике

Есть ли проверка последнего сигнала по символу?

Проверить структуру:

last_signal_time[symbol]
last_signal_direction[symbol]

Если этого нет — сигналы могут повторяться.

Есть ли cooldown для символа

Например:

cooldown_per_symbol = 60 seconds

Логика:

if now - last_signal_time[symbol] < cooldown:
    skip signal

Проверяется ли изменение состояния движения

Например:

previous_signal = pump
current_signal = pump

Если движение не изменилось — это может быть дубль.

Есть ли проверка открытой позиции

Если бот торгует автоматически:

if position_open(symbol):
    skip signal
Стандартные паттерны защиты от дублей
1. Cooldown по времени
cooldown = 60–180 seconds

Подходит для high-frequency сигналов.

2. Cooldown по изменению цены

Разрешать новый сигнал только если:

|price - last_signal_price| > threshold
3. Cooldown по состоянию тренда

Новый сигнал разрешён если:

previous_direction != current_direction

Например:

pump → dump
Рекомендуемая комбинированная логика
if now - last_signal_time[symbol] < cooldown:
    reject

if abs(price - last_signal_price) < min_delta:
    reject

if direction == last_signal_direction and time < trend_reset_window:
    reject
Технический запрос разработчику
Проверить, реализована ли защита от дублирования сигналов:

1. Хранится ли last_signal_time и last_signal_price по symbol.
2. Есть ли cooldown (60–180 сек).
3. Есть ли проверка direction change.
4. Есть ли проверка открытой позиции.

Если нет — добавить deduplication layer перед отправкой сигнала.
Итог

Ваши вопросы в правильной постановке сводятся к трём ключевым техническим проверкам:

1️⃣ Data integrity
— корректность получения и фиксации цены.

2️⃣ Signal detection
— правильность фильтров и чувствительности алгоритма.

3️⃣ Signal deduplication
— защита от повторных сигналов.