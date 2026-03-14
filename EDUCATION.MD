Pump/Dump signal bots в 2025–2026: технический аудит-референс для разработки и проверки
Executive summary
В 2025–2026 “памп/дамп” сигнал‑боты (в смысле скринеров резких движений) почти всегда эволюционировали в сторону потоковой (streaming) архитектуры: WebSocket‑лента сделок/тиков и/или best bid/ask вместо REST‑опроса. Причина практическая: значимая часть пампов достигает пика за секунды/десятки секунд, поэтому любая задержка и “свечные” снапшоты часто дают “мертвую” цену и пропуск импульса. Это явно видно в исследованиях по P&D: в одном из кейсов среднее время до максимума было около 0.12 минуты (~7 секунд) на менее ликвидной бирже и около 1.49 минуты на более крупной; авторы также используют baseline как midprice (середина bid/ask), а не close свечи. 

С точки зрения инженерии, типовая прод‑архитектура 2025–2026 выглядит как конвейер: ingest WebSocket → нормализация/кэш → вычисление rolling‑метрик (price/volume/liquidity) → скоринг/фильтры → dedup/cooldown → уведомления → хранилище и метрики. Показательно, что исследовательский real‑time pipeline для P&D уже описывается как облачно развернутый, потоковый и “тяжёлый” по данным (миллионы строк по order book и trades), с хранением в PostgreSQL и расчётом метрик каждые несколько секунд. 

Ключевые инженерные риски (и источник ваших текущих болей) почти всегда одни и те же:

“Мертвая” цена возникает, когда цена в сигнале берется из REST‑опроса, “свечи” или кэша без контроля свежести, либо когда метка времени локальная и не сопоставляется с exchange‑timestamp. Источники данных на биржах прямо подразумевают, что для real‑time лучше WebSocket (trade/aggTrade/bookTicker/markPrice), а не “дергать” REST непрерывно. 
Низкая частота сигналов чаще всего объясняется не “рынком”, а тем, что вы (а) используете длинный таймфрейм/редкое сканирование, (б) держите пороги слишком высокими, (в) применяете осцилляторы как hard‑фильтр, (г) сканируете пары последовательно (latency на ветке обработки), из‑за чего импульс заканчивается раньше, чем вы до него дошли. Практики “в реальном времени” часто опираются на потоковые данные и буферизацию в памяти. 
Дубли сигналов решаются не одним “cooldown”, а сочетанием fingerprint + direction‑aware правил + правил “follow‑up move” и корректного состояния позиции/сделки.
Этот документ опирается на: официальные API‑доки бирж (WebSocket/REST/таймстампы/частоты/локальный стакан), тех‑источники 2025–2026 (Binance Academy 2025 по локальному стакану, обновления WebSocket URL, SBE‑каналы), исследования 2025–2026 по P&D и публичные реализации сигнал‑ботов. 

Архитектуры и технологический стек
Базовые источники данных и почему WebSocket побеждает REST
Практический стандарт 2025–2026 для “памп/дамп” скринеров: держать актуальную цену и микро‑метрики в памяти, обновляя их из WebSocket‑потоков сделок и/или лучшего bid/ask, а REST использовать для разовых снапшотов, справочников и бэктеста.

Официальные API‑доки бирж буквально подталкивают к этому подходу:

На споте у Binance для реального времени предлагаются WebSocket‑потоки @trade, @aggTrade, @kline, @bookTicker (обновления bid/ask в real‑time), и в REST‑доках прямо рекомендуют “для real‑time используйте Streams”. 
На деривативах у Binance есть отдельный поток mark price с частотой 1–3 секунды (важно для фьючерсов, где mark price отличается от last trade и используется для маржи/ликвидаций). 
У Bybit WebSocket orderbook поддерживает snapshot/delta режим и публикует стакан с частотами до 10ms на Level 1, фиксируя timestamp генерации данных в сообщении. 
У OKX incremental‑каналы стакана (books, books-l2-tbt, books50-l2-tbt) публикуют изменения каждые 100ms или даже 10ms (часть каналов доступна только VIP) и описывают поведение keep‑alive/переотправки. 
В доках BingX по WebSocket отмечены: отдельный market WS endpoint, gzip‑сжатие сообщений, наличие trade/kline/depth потоков, и формат событий содержит event time / trade time. 
С инженерной точки зрения takeaway простой: REST‑polling в цикле + последовательный обход 200–500 символов почти гарантирует устаревание цены “в момент сигнала”, даже если вы берете “last price”. Для high‑frequency сигналов нужно держать “последнюю цену” в локальном кэше, обновляемом потоками. 

Типовая схема компонентов
Ниже — канонический контур (микросервисы или модули в одном процессе). Он близок к тому, как исследовательские и практические системы описывают real‑time пайплайны (потоки данных, скоринг, хранилище, облачная инфраструктура). 

WebSocket Market Data
trades / bookTicker / depth / markPrice

Normalizer
symbol map + time sync

REST APIs
instruments / limits / snapshots

In-memory cache
last_trade, mid, vwap, ohlcv_1m

Rolling features
Δprice%, volume spike,
spread, imbalance

Multi-factor scoring
+ soft filters

Dedup & cooldown
fingerprint + direction

Notifier
Telegram/Discord/Webhook

Storage
snapshots, signals

Metrics/Tracing
Prometheus/OTel



Показать код
Технологический стек “как обычно делали в 2025–2026”
Ниже — практичная матрица “что ставили и почему”, без привязки к конкретному языку.

Слой	Наиболее типичный выбор	Зачем именно в pump/dump‑боте	На что смотреть в проде
Ingest	WebSocket клиент + авто‑reconnect	Постоянная свежая цена и быстрые метрики; минимизация “мертвой” цены. 
ws_disconnects_total, ws_reconnects_total, marketdata_lag_ms
Нормализация	Symbol mapper + time sync (server time)	Разные форматы символов/тайм‑единиц; контроль задержки. 
exchange_time_offset_ms, %stale_snapshots
Кэш	In‑memory (dict/LMDB/Redis)	O(1) доступ к последнему trade/mid; быстрый rolling window	cache_hit_ratio, cache_age_ms
Очередь событий	Kafka / RabbitMQ / NATS / Redis Streams (по масштабу)	Развязка ingest и signal engine; backpressure при пиках. 
lag по consumer group, dropped events
Storage	PostgreSQL/ClickHouse/Timescale (по объему)	История снапшотов для дебага/бэктеста; сравнение со reference	write latency, размер партиций
Observability	Prometheus + Grafana + OpenTelemetry	Метрики лагов, ошибок, реконов, производительности; трассировка. 
p95 latency на стадиях pipeline
Infra	Docker + VM/K8s (по SLA)	Репликация, изоляция, простая выкладка	autoscaling, health checks

Почему отдельно упоминают очереди: в условиях, когда update‑частоты стакана — миллисекунды, “медленный потребитель” становится реальной инженерной проблемой, и системы pub/sub обычно имеют концепции backpressure/slow consumers. 

Отдельно важно, что биржи в 2025–2026 “подкручивали” инфраструктуру под тяжелый WebSocket‑трафик: например, Binance вводила разделение WebSocket‑базовых URL по типу трафика (/public, /market, /private) и прямо рекомендует разделять соединения, чтобы снизить jitter и перегруз. 
 У Bybit появляется бинарный SBE‑фид (Market Maker) с микросекундной точностью и меньшим payload (под стратегии, чувствительные к задержкам). 

Паттерны формирования сигналов
Сигналы “памп/дамп” как инженерная задача
Если убрать маркетинг, “памп/дамп” сигнал‑бот = детектор аномалии в кратком окне. В реальном проде (и в исследованиях) чаще всего смотрят:

Price impulse: изменение цены в rolling‑окне (секунды/минуты). 
Volume impulse: spikes в объеме/числе сделок/market buys. 
Microstructure: spread, depth, imbalance, давление заявок, VWAP, impact. 
Liquidity filters: отсечь мертвые пары/сомнительную ликвидность. 
В 2025‑исследовании для предикта P&D “до события” используются Z‑score аномалии по набору трейд‑ и order book‑метрик (order book pressure, average order size, imbalance ratio, VWAP, high‑low spread, trade count и др.) и ранжирование кандидатов. 

Rolling windows и пороги
Rolling window — основной механизм. Он может быть:

tick‑based: N последних trades,
time‑based: последние 10/30/60 секунд,
candle‑based: “текущая 1m свеча” (хуже для ultra‑fast импульсов, но проще).
Ключевой момент 2025–2026: импульсы P&D могут быть настолько быстрыми, что от “свечи” часто остаётся только пост‑фактум состояние; поэтому многие системы считают baseline как midprice (bid/ask midpoint) и смотрят окно “минуты/секунды”. 

Практический ориентир порогов (не “истина”, а то, что встречается у публичных реализаций):

простой сигнал: abs(Δprice%) >= X% в окне T,
где X часто держат в диапазоне 3–10% в зависимости от universe и таймфрейма,
volume spike: vol_now / vol_avg >= k или z‑score по vol/trades.
Пример публичной реализации “аномалия‑сканера”: запись снапшотов, расчет %‑изменения по sliding window и отправка сигнала при превышении порога (в одном из репозиториев порог по умолчанию 20% и используется фильтр по 24h volume + WebSocket мониторинг). 
 Это не “эталон”, но демонстрирует распространенный паттерн.

Объем, ликвидность и “не душить” рынок
Частая ошибка: применять RSI как жесткий фильтр, из‑за чего вы режете почти все кандидаты. В практических системах осцилляторы обычно работают как:

soft‑фактор в скоринге (добавляет/убирает баллы),
правило форматирования (“RSI высокий → риск продолжения/разворота”),
либо как “запрет” только в экстремально узких режимах.
Исследования и engineering‑практика часто показывают, что “рыночные” характеристики (цена/объем/микроструктура) остаются главным источником сигнала, а дополнительные признаки лишь улучшают ранжирование. 

Multi‑factor scoring вместо “одного if”
Вместо жесткой воронки “движение AND RSI AND …” в 2025–2026 широко используют скоринг:

ScorePrice: z‑score/percentile по Δprice на 30–120 сек окне
ScoreVolume: spike по trade count / volume
ScoreLiquidity: spread/depth (или отсекающий минимум)
ScoreMicro: imbalance/pressure
Penalty: “данные stale”, “слишком широкий spread”, “слишком низкий depth”
Такой подход близок к тому, как описываются real‑time модели/пайплайны в исследовании: сначала фильтры (например, market cap), затем аномальность (z‑score) по набору метрик и ранжирование. 

Dedup, fingerprint и cooldown
Dedup‑слой — отдельная подсистема, а не “одна переменная”. В публичных Telegram‑ботах встречается классический набор: cooldown + настройка порога в процентах + “real‑time tracking” и хранение состояния в БД. 

Рекомендуемый паттерн (direction‑aware):

score>=threshold AND not_stale

emit(signal)

now-last_sent >= cooldown

direction_changed

followup_move >= followup_pct

Ready

Sent

Cooldown



Показать код
Где fingerprint обычно включает: symbol, direction, bucket(window_start), “квант” цены/Δprice, и (опционально) режим стратегии.

Источники данных и целостность: trade vs mark vs mid, время и типовые сбои
Что такое “правильная цена” для сигнала
В реальном использовании “правильность” цены зависит от рынка и цели:

Last trade price: “последняя сделка”, полезно для реакции “прямо сейчас”. Обычно приходит в trade/aggTrade потоках. 
Mid price = (best bid + best ask) / 2: устойчивее к случайному “шпилю” в одной сделке и удобно как baseline (в исследованиях P&D baseline именно так и задается). 
Mark price (деривативы): может быть важнее last trade для риск‑метрик и ликвидаций; биржи дают отдельный поток. 
Candle close/open: допустимы для медленных стратегий, но для пампов/дампов дают высокую вероятность “мертвой” цены.
Практический рецепт реального времени: держать одновременно last trade и mid, плюс mark (если фьючи) и выбирать “цена для сообщения” по вашей цели (например, “вход ориентируйтесь на диапазон bid/ask”). Это напрямую следует из того, какие потоки предоставляют биржи (trade + bookTicker + markPrice). 

Проблема времени: exchange timestamps vs local time
Типовые проблемы:

Локальные часы не совпадают с биржевым временем → неверная интерпретация “в ту же секунду”. Биржи в REST‑доках выделяют “server time” и требования к timestamp/recvWindow для подписанных запросов и единицы времени (ms/µs). 
Внутренний лаг пайплайна: данные пришли в процесс, но обработались/отправились позже. Поэтому любые серьезные системы логируют несколько времен: exchange_event_time, local_receive_time, processed_time, sent_time. Это соответствует лучшим практикам observability (метрики/трейсы/логи) и особенно важно для high‑frequency данных. 
API‑ноды “расходятся”: редкая, но реальная проблема. Показательный пример из 2025: в issue по одной бирже описано, что REST‑эндпоинт klines иногда возвращает “не последнюю свечу”, а предыдущую, что выглядит как out‑of‑sync на стороне провайдера данных. 
Локальный стакан и data integrity
Если вы используете order book (а это часто очень полезно в pump/dump), важно корректно поддерживать локальную копию:

У Binance есть пошаговый рецепт “buffer events → взять depth snapshot → применить только валидные update IDs → следить за непрерывностью pu/u”. 
У Bybit snapshot/delta модель: сначала snapshot, затем delta; при проблемах переотправляется snapshot “гарантированно последний”, а в сообщениях есть ts и seq для сопоставления. 
У OKX четко описаны snapshot‑и incremental‑каналы и частоты (10ms/100ms), плюс keep‑alive поведение. 
Смысл: “стакан” почти всегда требует собственной state‑машины синхронизации. Если вы не хотите этой сложности, берите хотя бы bookTicker (best bid/ask) — он дешевле и проще, но уже позволяет корректно считать mid и spread. 

Реализация и аудит кода: функции, логи, схемы хранения и мониторинг
Функции, которые почти всегда нужно аудировать
Ниже — тот набор, который вы перечислили, но в виде “что проверить” (code‑level). Он основан на типовых источниках данных (trade/bookTicker/markPrice/klines) и типовых отказах (stale, time drift, потеря WS, rate limits). 

get_current_price(symbol)
Проверки:

Источник: читает ли она из in‑memory cache, обновляемого WebSocket, или делает REST‑запрос “в момент вызова”. 
Возвращает ли она структуру, а не “одно число”: last_trade, best_bid, best_ask, mid, mark, exchange_ts, local_receive_ts. 
Есть ли “stale‑guard”: если now - local_receive_ts > X ms, цена помечается как устаревшая или берётся запасной источник.
Пример рекомендуемого контракта (JSON‑ответ вашей функции):

json
Копировать
{
  "symbol": "BTC-USDT",
  "last_trade": 68000.12,
  "best_bid": 67999.90,
  "best_ask": 68000.30,
  "mid": 68000.10,
  "mark": 68001.00,
  "exchange_event_ts": 1710000000123,
  "local_receive_ts": 1710000000456,
  "local_processed_ts": 1710000000470,
  "source": "ws:trade+bookTicker",
  "stale_ms": 347
}
build_snapshot(...)
Проверки:

Snapshot строится из актуальных данных (см. stale_ms) или из свечи.
Вы пишете baseline → trigger (диапазон), а не только “одну цену”. Исследования по P&D и реальная торговая микро‑структура показывают, что baseline разумно брать как midprice, а не “последний close”. 
В snapshot обязательно сохраняются exchange_ts и local_ts, иначе вы не отличите “биржа дала старое” от “код запоздал”.
detect_signal(snapshot, rolling_state)
Проверки:

Rolling‑окно реально rolling (по времени или по N тиков), а не “последняя закрытая свеча”.
Порог движения и объема не “зашит”, а конфигурируется и логируется.
RSI/осцилляторы применяются как soft‑фактор в скоринге, иначе вы режете частоту. Эта рекомендация согласуется с тем, что market‑данные дают основной вклад, а дополнительные фичи — вторичный. 
send_notification(signal)
Проверки:

Сообщение содержит: signal_ts, price_range, data_age_ms, source, spread, (для фьючей) mark price. Это напрямую повышает “торговую применимость” сигнала. 
Dedup перед отправкой учитывает direction и follow‑up.
Логирование: точные поля и формат
Чтобы дебажить “мертвую цену” и “мало сигналов”, вы должны логировать кандидатов, а не только “финальные сигналы”.

Рекомендуемый JSON‑лог на каждый символ в каждый цикл (минимальный, но достаточный):

json
Копировать
{
  "ts": "2026-03-11T12:34:56.789Z",
  "event": "scan_candidate",
  "symbol": "XYZ-USDT",
  "window_sec": 60,
  "price_start_mid": 0.01230,
  "price_now_mid": 0.01295,
  "dprice_pct": 5.28,
  "trade_count_60s": 184,
  "vol_quote_60s": 125000.55,
  "spread_bps": 12.4,
  "imbalance": 0.18,
  "rsi": 71.2,
  "score": 0.83,
  "decision": "reject",
  "reject_reason": "rsi_hard_filter",
  "exchange_event_ts": 1710000000789,
  "local_receive_ts": 1710000000810,
  "stale_ms": 21,
  "md_source": "ws"
}
И отдельный лог на отправку:

json
Копировать
{
  "ts": "2026-03-11T12:34:56.900Z",
  "event": "signal_emit",
  "symbol": "XYZ-USDT",
  "direction": "PUMP",
  "dprice_pct": 5.28,
  "price_range": [0.01230, 0.01295],
  "cooldown_sec": 90,
  "fingerprint": "XYZ-USDT|PUMP|60s|bucket=...|q=...",
  "latency_ms": {
    "exchange_to_receive": 21,
    "receive_to_emit": 70,
    "emit_to_send": 12
  }
}
Такое логирование прямо следует из необходимости видеть временные цепочки и устранять stale/lag, что является практикой observability (метрики+логи+трейсы). 

Схемы хранения снапшотов и сигналов
Минимальная SQL‑схема (PostgreSQL‑стиль):

sql
Копировать
CREATE TABLE md_snapshot (
  id            BIGSERIAL PRIMARY KEY,
  symbol        TEXT NOT NULL,
  exchange_ts   BIGINT NOT NULL,
  received_ts   BIGINT NOT NULL,
  mid           NUMERIC,
  last_trade    NUMERIC,
  best_bid      NUMERIC,
  best_ask      NUMERIC,
  mark          NUMERIC,
  spread_bps    NUMERIC,
  trade_count   INT,
  vol_quote     NUMERIC,
  meta          JSONB
);

CREATE INDEX ON md_snapshot (symbol, exchange_ts);

CREATE TABLE signal_event (
  id            BIGSERIAL PRIMARY KEY,
  symbol        TEXT NOT NULL,
  direction     TEXT NOT NULL, -- PUMP/DUMP
  window_sec    INT NOT NULL,
  dprice_pct    NUMERIC NOT NULL,
  price_start   NUMERIC,
  price_end     NUMERIC,
  exchange_ts   BIGINT NOT NULL,
  emitted_ts    BIGINT NOT NULL,
  fingerprint   TEXT NOT NULL,
  payload       JSONB NOT NULL
);

CREATE UNIQUE INDEX ON signal_event (fingerprint);
JSON‑схема “signal payload” (для сохранения/отправки):

json
Копировать
{
  "symbol": "XYZ-USDT",
  "direction": "DUMP",
  "window_sec": 60,
  "dprice_pct": -6.1,
  "price": {
    "baseline_mid": 0.01295,
    "trigger_mid": 0.01216,
    "best_bid": 0.01215,
    "best_ask": 0.01217,
    "mark": null
  },
  "times": {
    "exchange_event_ts": 1710000000789,
    "local_receive_ts": 1710000000810,
    "emitted_ts": 1710000000900
  },
  "quality": {
    "stale_ms": 21,
    "spread_bps": 12.4,
    "liquidity_ok": true
  },
  "explain": {
    "score": 0.83,
    "factors": {
      "price_impulse": 0.92,
      "volume_spike": 0.71,
      "imbalance": 0.40,
      "rsi_penalty": -0.10
    }
  }
}
Метрики и дашборды: что именно строить
Метрики лучше именовать по правилам Prometheus (единицы в имени, стабильные label’ы, избегать произвольной генерации). 
 Ниже — “минимальный боевой” набор:

Группа	Метрика	Тип графика в Grafana	Зачем
Свежесть данных	`marketdata_stale_ms{source="ws	rest"}`	Time series (p50/p95/p99) 
Лаг pipeline	`signal_pipeline_latency_ms{stage="receive	score	dedup
WS стабильность	ws_reconnects_total, ws_disconnects_total	Bar/time series	Проблемы соединения/лимитов
Отбраковка фильтрами	`candidates_total{decision="accept	reject",reason="..."}`	Stacked bar
Частота сигналов	`signals_total{direction="pump	dump"}`	Time series + table
Сканирование	symbols_scanned_per_cycle, scan_cycle_seconds	Time series	Если цикл длинный — вы пропускаете импульсы
Rate limits	rest_requests_total{endpoint="..."}, http_429_total	Time series	Упираетесь ли в лимиты

Grafana как инструмент описывает dashboard как набор панелей для “at-a-glance” контроля; для временных рядов базовая визуализация — time series. 

Reverse-engineering и бэктест: как анализировать reference‑бот по логам
Как извлечь логику из логов reference
Если у вас есть только сообщения “символ / время / % / цена”, вы все равно можете восстановить значительную часть поведения:

Распределение процентов: найдите “минимальный %” и “ступени” (например, ровно 5.00%, 5.25% и т.п.) — это часто указывает на порог и/или квантование.
Интенсивность по времени: сколько сигналов в минуту/час — это косвенно даёт окно и частоту сканирования.
Цена как диапазон (baseline → trigger) или “одна цена”: если диапазон есть, то reference почти наверняка строит rolling baseline (как в исследованиях baseline=mid) и фиксирует две точки. 
Сопоставление с рынком: по внешним данным (исторические trades/klines) проверить, действительно ли “%” соответствует Δ в окне T.
В исследованиях P&D для оценки “раннего обнаружения” используется backtesting с временными смещениями (например, 20 секунд до события, 40 секунд, 1 минута) и показывается деградация качества при увеличении offset — это хороший индикатор того, почему важна задержка и точность timestamp. 

Методика сравнения “рынок не дает” vs “код пропускает”
Ключ — иметь Raw Candidates и Reject Reasons.

Если у вас в логах/метриках:

raw_candidates_per_hour стабильно высокий, но signals_sent низкий → фильтры/дедуп душат.
raw_candidates_per_hour низкий на всех биржах/символах → либо действительно спокойный рынок, либо вы неправильно считаете rolling‑метрики (например, окно не то, данные stale, цикл слишком длинный).
scan_cycle_seconds сравним/больше, чем типичное время “до пика” (секунды-десятки секунд) → вы фундаментально не успеваете. 
Пример SQL‑запросов для диагностики:

sql
Копировать
-- Сколько кандидатов отбрасывается по причинам
SELECT
  reject_reason,
  COUNT(*) AS n
FROM scan_log
WHERE ts >= now() - interval '24 hours'
  AND decision = 'reject'
GROUP BY 1
ORDER BY n DESC;

-- Насколько часто данные stale
SELECT
  date_trunc('minute', ts) AS minute,
  percentile_cont(0.95) WITHIN GROUP (ORDER BY stale_ms) AS p95_stale_ms
FROM scan_log
WHERE ts >= now() - interval '6 hours'
GROUP BY 1
ORDER BY 1;
Операционные практики: формат алерта, лимиты, безопасность, право и этика
Формат алерта: “одна цена” vs “диапазон”
Для pump/dump‑скринера в 2025–2026 наиболее адекватный формат уведомления обычно включает:

направление (PUMP/DUMP),
окно (например, 60s),
процент,
baseline → trigger (или bid/ask диапазон),
свежесть данных (stale_ms),
источник цены (trade/mid/mark).
Это напрямую связано с практической проблемой “мертвой цены”: пользователь должен понимать, что сигнал фиксирует движение, а вход будет по текущему стакану.

Исследования P&D explicitly используют baseline midprice и оперируют краткими окнами (минуты/секунды), что делает диапазон логичнее одной цифры. 

Пример сообщения (шаблон):

text
Копировать
XYZ-USDT | PUMP | 60s
Δ +5.28%
Цена (mid): 0.01230 → 0.01295
BBO: bid 0.01294 / ask 0.01296 | spread 12.4 bps
Данные: ws | stale 21 ms
Rate limits и ограничения соединений
В 2025–2026 биржи активно поднимали лимиты, но они всё равно остаются ограничением архитектуры:

У BingX опубликованы изменения rate limit (вплоть до 2000 запросов/10 сек по графику) и изменения по торговым эндпоинтам. 
Binance в WebSocket‑части прямо описывает организационные изменения из‑за “heavy traffic” и рекомендует разделять соединения по типу трафика. 
У Bybit для SBE‑фидов упоминаются лимиты соединений и поведение при превышении (HTTP 429). 
Практический вывод: если ваш бот строится на REST‑опросе “каждый тик”, вы почти неизбежно упираетесь либо в лимиты, либо в задержку, либо в оба фактора.

Безопасность (ключи, доступ, abuse)
Любой бот, который имеет доступ к торговле, должен следовать базовым правилам безопасности:

минимальные permissions, IP whitelist, секреты не в логах,
ротация ключей,
отдельные ключи на окружения,
мониторинг аномальной активности.
Binance в документации по request security прямо подчеркивает чувствительность API key/secret и необходимость безопасного обращения с ключами. 

Право и этика
Pump‑and‑dump — форма рыночной манипуляции; регуляторы прямо описывают её как мошенническую практику. Даже если вы пишете “детектор”, важно избегать функционала, который облегчает координацию манипуляции. 

Приоритизированный чеклист изменений и тест-кейсы
Ниже — практический “аудит‑чеклист”, который можно брать как техническое ТЗ. Он ориентирован на ваши три болевых класса: stale price, низкая частота, дубли.

P0: исправить “мертвую цену” и доказать источник проблемы
Задача	Что изменить	Тест‑кейс	Ожидаемый результат
Перевести price‑источник на WS	Поднять WS потоки trade/aggTrade + bookTicker, для фьючей markPrice. REST оставить только для справочников/редких снапшотов. 
На 50–200 символах сравнить stale_ms в режиме REST‑polling vs WS	p95 stale_ms падает на порядок; “цена в сигнале” совпадает с рынком в пределах spread
Ввести строгую time‑модель	Во все снапшоты и сигналы писать exchange_event_ts и local_receive_ts; измерять offset. 
Синтетически добавить 2–5 сек задержки обработчика	Сигналы помечаются stale=true, алерт содержит stale_ms
Мониторинг свежести	Метрика marketdata_stale_ms + алерт на p95>2000ms	Дашборд за 24 часа	Инциденты “мертвой цены” ловятся как наблюдаемая метрика

P1: увеличить частоту сигналов без потери контроля качества
Задача	Что изменить	Тест‑кейс	Ожидаемый результат
Логировать Raw Candidates + Reject Reasons	На каждый symbol/цикл писать decision/reject_reason	Запустить 24ч, построить stacked bar по reject_reason	Становится видно, “душит” ли RSI/ликвидность/порог
Перейти на скоринг (soft‑RSI)	RSI не как “запрет”, а как фактор в score	A/B‑режим: hard‑RSI vs soft‑RSI	Рост signals_sent при близком precision (по вашей валидации)
Параллельность обработки	Вместо последовательного обхода символов: батчи, asyncio.gather + semaphore; либо multiplex streams	Нагрузочный тест: 300 символов	scan_cycle_seconds снижается; уменьшается пропуск быстрых импульсов
Согласовать окно с реальностью	Для pump/dump сделать rolling окно 10–120 сек (профили), а не только 5m/1h	Backtest на исторических импульсах	Режимы видно в метриках, меньше “пост‑фактум” сигналов

Обоснование необходимости скорости: реальные P&D пики могут наступать за секунды/минуты; чем больше ваш internal lag, тем меньше практическая ценность. 

P2: прод‑качество, устойчивость и расширение сигналов
Задача	Что изменить	Тест‑кейс	Ожидаемый результат
Local order book (опционально)	Реализовать snapshot+delta по правилам биржи (update IDs/seq), либо ограничиться bookTicker. 
Тест на реконнекте/пакет‑лоссе	Стакан остается консистентным, нет “перевернутого” spread
Отдельный ingest и очередь	Вынести ingest в отдельный сервис; прокидывать события через Kafka/NATS/Redis Streams. 
Stress test: burst update	Нет потерь; consumer lag контролируем
Traceability через OTel	Проставить traceId на pipeline обработки сигнала	Инцидент: spike latency	Можно “пройти” по trace и увидеть, где тормозит

Дедупликация: “не спамить, но не пропустить новое”
Рекомендуемая политика (практичная):

cooldown базовый: 60–180 сек для 10–120s окон,
если direction поменялся (PUMP→DUMP) — cooldown сбрасывать,
если price ушёл дальше на followup_move_pct — разрешать follow‑up сигнал,
fingerprint должен быть стабильным и включать quantized bucket (чтобы одинаковое событие давало один сигнал).
Публичные реализации Telegram‑сигнал‑ботов демонстрируют, что пользовательская настройка percent‑порогов и “real‑time tracking” — стандарт, но без правильного dedup это превращается в спам. 

Приоритетные источники
Официальные API‑доки и изменения:

BingX WebSocket base URL, gzip‑сжатие, trade/kline/depth потоки. 
Binance WebSocket Streams и рекомендации использовать WS для real‑time; mark price stream. 
Binance изменения WebSocket URL (разделение /public//market//private) из‑за heavy traffic. 
Bybit orderbook snapshot/delta, частоты, timestamps. 
OKX каналы стакана 10ms/100ms и поведение. 
Binance “How to manage a local order book correctly”. 
Binance spot REST: server time endpoint и timestamp‑правила. 
Binance changelog про вывод из эксплуатации старых REST v1 endpoint’ов (важно для совместимости 2026). 
Исследования P&D и market microstructure (2025–2026):

Real‑time pipeline для Telegram‑based P&D: order book + trades + z‑scores, time‑offset backtest, baseline midprice. 
Microstructure‑фичи из multi‑level order book (spread, imbalance и др.) и контроль качества данных/валидации. 
Публичные реализации/референсы (как иллюстрации паттернов, не как “истина”):

Telegram сигнал‑бот с типами PUMP/DUMP и percent‑порогами + хранением состояния. 
Sliding window + price snapshots + threshold + WS мониторинг как базовый паттерн. 
Observability / мониторинг (практики):

Prometheus naming/instrumentation и Grafana dashboards/time series. 
OpenTelemetry как vendor‑neutral стандарт для метрик/логов/трейсов. 
Право/этика:

Описания pump‑and‑dump как манипуляции/мошенничества у регуляторов. 