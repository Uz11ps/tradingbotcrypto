Технический аудит pump/dump signal‑ботов в 2025–2026 как референс для разработки
Executive summary
В 2025–2026 большинство “pump/dump” signal‑ботов (в смысле скринеров резких импульсов и/или детекторов манипуляций) перешли от REST‑опроса к потоковой архитектуре на WebSocket: trade/aggTrade, best bid/ask (BBO), стакан (snapshot+delta), а для деривативов — mark price. Это не мода, а следствие физики рынка: в реальных P&D событиях “пик” может достигаться за секунды (в одном исследовании среднее время до максимума было ~1.49 минуты на KuCoin и ~0.12 минуты (~7 секунд) на Poloniex, при baseline как midpoint bid/ask). 

Ключевой инженерный вывод: если вы пытаетесь торговать контртренд (short после быстрого pump, когда цена “захлебнулась” и дала небольшой откат; long после dump) — ваша система обязана держать актуальную цену и микро‑метрики в памяти, обновляемые из WS, и контролировать “свежесть” снапшота (stale_ms). Иначе вы почти гарантированно получите (а) “мертвую” цену (данные устарели к моменту сообщения), (б) пропуск импульсов (цикл обхода инструментов дольше, чем жизнь движения), (в) дубли сигналов (нет корректного dedup/cooldown по состоянию). 

Для ориентира по источникам данных:

у Binance Spot WS есть явные лимиты по сообщениям/соединениям, ping/pong, срок жизни соединения 24 часа, максимум 1024 stream на одно соединение, возможность получать timestamps в микросекундах. 
у BingX market WS данные gzip‑сжаты, heartbeat ping приходит раз в ~5 секунд, нужно отвечать pong. 
у Bybit порядок локального стакана описан как snapshot+delta, а ticker пушится до 50ms на spot и 100ms на деривативах; отдельно в 2025–2026 расширяются “низколатентные” SBE (binary) каналы с микросекундной точностью. 
у OKX есть snapshot‑каналы bbo‑tbt (10ms) и books5 (100ms), а также incremental‑каналы до 10ms для VIP уровней. 
Ниже — практический, “код‑ориентированный” референс: архитектуры, паттерны сигналов, data integrity, чек‑листы функций, backtest/реверс‑инжиниринг референса, операционные практики и план P0/P1/P2.

Типовые архитектуры и стек
В 2025–2026 типовая прод‑архитектура для импульс‑скринера — event‑driven конвейер: WS ingest → нормализация (символы/время) → in‑memory cache → rolling feature engine → scoring/filtering → dedup/cooldown → notifier → storage + metrics/tracing. Такой подход согласуется как с практическими инженерными описаниями, так и с исследовательскими pipeline для real‑time P&D, где объединяют “высокочастотные” trade+orderbook признаки и статистические модели (z‑scores) и подчёркивают деградацию качества при увеличении временного сдвига. 

WebSocket market data
trade/aggTrade • bookTicker/BBO • depth • markPrice

Normalizer
symbol map • tick size • exchange_ts

REST APIs
instruments • rare snapshots • metadata

In-memory cache
last_trade • mid • mark • spread

Rolling features
Δprice(T) • volume spike • imbalance • VWAP

Multi-factor scoring
soft filters + penalties

Dedup/cooldown layer
fingerprint • direction • follow-up

Notifier
Telegram/Discord/Webhook

Storage
snapshots • signals • rejects

Observability
Prometheus metrics • OTel traces/logs



Показать код
WebSocket vs REST и tick vs candle
Практика 2025–2026: WS для оперативного рынка, REST — “для справочников и редких запросов”. Это подчёркивают и биржи напрямую: например Bybit в FAQ пишет, что если нужна только market data, то лучше WebSockets, потому что WS‑запросы не учитываются в rate limits. 

У Binance Spot WS явно указаны: ping каждые 20 секунд, необходимость pong, срок жизни соединения 24 часа, лимит 1024 stream на соединение, лимит входящих сообщений/сек, лимит соединений/IP, и возможность получать timestamps в микросекундах через timeUnit=MICROSECOND. 

Скорость важна потому, что реальный “окно жизни” импульса может быть меньше вашей длительности “полного скана рынка” (особенно если вы последовательны). В русскоязычных инженерных описаниях алгосканеров прямо отмечается, что изменения цен бывают “коротким импульсом в несколько миллисекунд”, на который реагируют только HFT‑боты, а архитектуру часто строят сервисно (collector/верификация/шина/DB). 

Сравнительная таблица решений
Выбор	Когда это работает	Риски для pump/dump‑скринера	Практика 2025–2026 (что делали чаще)
WebSocket market data	Реальное время, много символов, нужна минимальная задержка	Нужно обрабатывать reconnect, backpressure, state (стакан)	Стандарт: trade/BBO/depth/mark WS; у BingX WS ещё gzip и ping/pong. 
REST polling	Небольшое число символов, “медленные” стратегии	“Мертвая цена”, пропуск импульсов, rate limits	Используют ограниченно; на Bybit явно советуют WS для market data. 
Tick‑based (trade/BBO)	Лучше для импульсов и “stall/pullback”	Сложнее бэктест: нужен tick data и симуляция fill	Биржи публикуют частые тикеры: Bybit spot 50ms, деривативы 100ms; OKX snapshot до 10ms. 
Candle‑based (1m/5m)	Подходит для грубых сигналов	Поздний вход; неверная “цена входа”	В P&D исследованиях baseline берут как midprice, а не close свечи. 
In‑memory cache	Быстрые вычисления rolling‑окон	Нужно контролировать stale и консистентность	Must‑have: last_trade/mid/mark + exchange_ts иначе “мертвая цена”. 
Очереди	Большой поток событий/изолировать ingest и скоринг	Сложность эксплуатации	Kafka для event streaming; NATS JetStream для stateful consumers; Redis Streams для consumer groups; RabbitMQ для ack/confirm. 
Storage (Postgres/Timescale/ClickHouse)	История снапшотов, аудит и бэктест	Тяжёлая запись при high‑freq	Postgres partitioning помогает при больших таблицах; Timescale continuous aggregates; ClickHouse хорошо для time‑series/аналитики. 
Observability (Prometheus/OTel/Grafana)	Понимать лаги и stale в проде	Без этого баги “невидимы”	Naming/labels, histogram/quantiles в Prometheus; semantic conventions в OTel; time series/state timeline в Grafana. 
Infra (VM vs K8s)	SLA, масштабирование, релизы	Оверхед	K8s Deployment/rolling update/HPA как стандарт для сервисов; VM (EC2) для простого хостинга. 

Очереди: что реально важно для сигнал‑бота
Если у вас поток событий высокочастотный (стакан/тики), проблема почти всегда не “как читать”, а что делать со slow consumers и как не “задушить” систему:

Apache Kafka — event streaming, партиции + consumer groups для параллельной обработки. 
RabbitMQ — модель ack/confirm для надежности доставки; без ack брокер не удаляет сообщение окончательно. 
NATS — JetStream consumers дают at‑least‑once и хранят state доставки/ack; отдельно описывается феномен slow consumer и давление на систему. 
Redis Streams — consumer groups через XREADGROUP. 
Минимальный практический критерий выбора:

если вам важны исторические повторные воспроизводимые прогонки (replay) — Kafka/Redpanda‑класс;
если нужен “легкий” bus внутри одного сервера — Redis Streams/NATS;
RabbitMQ часто выбирают, когда важна классическая очередь задач с ack и routing.
Паттерны логики сигналов
Ключ: “pump/dump” сигнал‑бот в 2025–2026 — это почти всегда детектор аномалии в rolling‑окне + фильтры ликвидности + dedup/cooldown. Современные исследования и практические реализации сходятся в том, что trade и order book признаки в комбинации дают лучший результат, чем по отдельности (в реальном‑времени и особенно “почти перед событием”). 

Rolling windows и метрики импульса
Типовые метрики:

Δprice% в окне T (10–120 секунд для импульсов)
trade_count(T), volume_quote(T), taker_buy_ratio(T)
spread_bps, orderbook_imbalance, orderbook_pressure
VWAP(T) и отклонение от него
В реальном‑time модели P&D (DeFi’25) явно используются: bid‑ask spread, imbalance ratios, VWAP, trade count, high‑low spread, order size и др., и строятся z‑scores “short‑term vs historical”. 

Пороговые правила и “антишум”
Помимо z‑scores, в 2025 выходят работы, где “простая” thresholding‑логика усиливается EWMA и волатильностью, чтобы не ловить мусорные всплески на мёртвых токенах. Там прямо описан режим “90% рост High относительно 12‑часовой MA open + 400% порог объёма”, плюс EWMA/volatility как фильтр шума. 

В практических ботах это обычно превращается в:

базовый “trigger” (короткий импульс),
подтверждение объёмом/сделками,
штраф за широкий spread/низкую глубину,
dedup и cool‑down.
RSI и осцилляторы: soft vs hard
Практически полезное правило проектирования:

hard‑фильтры (запреты) оставляйте только для data‑quality и торговых ограничений (нет ликвидности, stale data, стоп‑лист инструментов).
RSI/осцилляторы чаще держат как soft‑фактор скоринга (уменьшает/увеличивает score), иначе вы резко режете частоту сигналов и превращаете “скринер импульсов” в редкий “идеальный сетап”. Это согласуется с тем, что в моделях раннего выявления P&D основную информативность дают market‑данные (trade+order book), а не один индикатор. 
Dedup/cooldown: state machine
Требование: не спамить, но и не “убивать” follow‑up импульсы. Базовый паттерн:

score>=S_min AND not_stale

send_notification()

now-last_emit >= cooldown_sec

direction_changed

followup_move_pct >= X

Ready

Emitted

Cooldown



Показать код
Где:

fingerprint ≈ symbol + direction + window_bucket + quantized_price + trigger_id
direction_changed (pump→dump) обычно сбрасывает cooldown
followup_move_pct нужен, чтобы ловить продолжение движения (или “вторую ногу”)
Псевдокод: сигнал для стратегии “short после pump‑stall‑pullback / long после dump‑stall‑bounce”
Ниже — конкретный набор правил как стартовая точка (не “финсовет”, а инженерная спецификация, которую дальше калибруют бэктестом).

pseudo
Копировать
# Rolling state per symbol:
# - mid_price series (from BBO)
# - last_trade series
# - volume_quote series
# - trade_count series
# - spread_bps series
# - optional: mark price (futures)

PARAMS:
  T_impulse = 60s
  T_stall   = 20s
  pump_threshold = +5.0%      # tune per universe
  dump_threshold = -5.0%
  pullback_pct   = 0.8%       # retracement from local extreme
  min_vol_quote_T = 50_000 USDT (example)
  max_spread_bps  = 25 bps
  stale_limit_ms  = 2000 ms

FUNCTION detect_setups(symbol):
  snap = get_current_price(symbol)  # returns last_trade, best_bid, best_ask, mid, mark, timestamps
  if snap.stale_ms > stale_limit_ms: return NO_SIGNAL("stale_data")

  feats = rolling_features(symbol, T_impulse, T_stall)

  if feats.spread_bps_p95 > max_spread_bps: return NO_SIGNAL("illiquid_spread")
  if feats.vol_quote_T_impulse < min_vol_quote_T: return NO_SIGNAL("low_volume")

  # 1) Identify impulse
  if feats.dprice_pct_T_impulse >= pump_threshold:
     # 2) Stall: no new highs lately + momentum fades
     if feats.no_new_high_for_T_stall and feats.trade_count_declining:
        # 3) Pullback: price retreats from local high by pullback_pct
        if feats.retracement_from_high_pct >= pullback_pct:
           return SIGNAL(direction="SHORT", kind="post_pump_pullback", price_range=[baseline_mid, current_mid])

  if feats.dprice_pct_T_impulse <= dump_threshold:
     if feats.no_new_low_for_T_stall and feats.trade_count_declining:
        if feats.retracement_from_low_pct >= pullback_pct:
           return SIGNAL(direction="LONG", kind="post_dump_bounce", price_range=[baseline_mid, current_mid])

  return NO_SIGNAL("no_setup")
Почему именно 5% как старт: в реальных P&D динамиках пики достигаются быстро и амплитуда может быть высокой, особенно на менее ликвидных площадках; baseline как midprice часто более устойчив, чем close свечи. 

Источники данных и Data Integrity
Биржевые потоки: что реально использовать
Единая логика для CEX в 2025–2026:

Last trade / aggTrade: реакция на “факт сделки” (самый чувствительный скальперский сигнал). У Binance futures aggTrade агрегируется и пушится с частотой порядка 100ms. 
BBO / bookTicker: вычисление mid/spread, первичная симуляция входа (bid/ask) — критично для вашей стратегии “stall+pullback”, потому что вход часто “по стакану”, а не по last trade. (Механика BBO логически следует из WS market streams и best bid/ask потоков; у OKX/Bybit явно выделены snapshot‑каналы для depth/BBO). 
Order book snapshot+delta: если вы хотите микро‑признаки (imbalance, pressure). Важно поддерживать локальный стакан корректно. Для Binance futures есть пошаговый алгоритм (buffer events → depth snapshot → проверка U/u/pu → пересинхронизация при разрыве). 
Mark price (деривативы): для фьючерсов “рыночная цена” может отличаться от mark; Binance публикует mark price stream каждые 1s или 3s. 
Конкретика по биржам (официальные детали)
BingX: market WS base URL wss://open-api-ws.bingx.com/market, данные сжаты gzip, heartbeat ping каждые ~5 секунд (частота может меняться), клиент должен отвечать pong. 
Bybit: локальный стакан нужно строить из snapshot+delta; при новом snapshot — reset; snapshot может быть переотправлен и “гарантированно содержит 최신 данные”. 
 Тикер‑стрим имеет snapshot/delta, частота пуша: spot 50ms, деривативы/опционы 100ms; в payload есть ts (timestamp генерации данных системой), lastPrice, markPrice и др. 
 В FAQ прямо рекомендуют WS для market data, так как WS не считается в rate limits. 
OKX: depth snapshots: bbo-tbt (10ms) и books5 (100ms); incremental channels books (100ms), books-l2-tbt/books50-l2-tbt (10ms) доступны только после логина и ограничены VIP уровнями; описано поведение resend при отсутствии апдейтов, чтобы подтвердить активность соединения. 
Binance Spot WS: ping/pong и 24h TTL соединения; лимиты по входящим сообщениям/сек и по числу streams/соединений/IP; timestamps обычно ms, но можно запросить microsecond через timeUnit. 
 Для futures в 2026 есть системные апгрейды WS и миграция на новые base URLs (/public, /market, /private) с дедлайном, что важно для стабильности боевого бота. 
Trade vs mark vs mid: что писать в сигнал
Для стратегии “вход после stall/pullback” ваша “цена для сообщения” должна быть торгуемо‑интерпретируемой:

mid = (bid+ask)/2: хороший baseline и честное представление “где рынок”, особенно когда last trade скачет. В P&D исследовании baseline берут именно как midpoint bid/ask до события. 
bid/ask: нужен для оценки проскальзывания и реальной точки входа (short чаще ближе к bid/ask в зависимости от типа ордера).
mark (фьючерсы): важен для риск‑контролей; Binance даёт отдельный поток. 
Практически лучший формат алерта для пользователя — не “одна цена”, а диапазон: baseline → trigger + текущий BBO и stale_ms.

Типовые failure modes и mitigations
Ниже — “карта причин”, почему в 2025–2026 чаще всего ломается data integrity.

Notifier
Signal Engine
Feature Engine
WS Client
Exchange
Notifier
Signal Engine
Feature Engine
WS Client
Exchange
"мертвая цена" если snapshot взят из REST/кэша\nили exchange_ts сильно раньше emit_ts
trade/BBO event (exchange_ts)
normalize + cache update (receive_ts)
compute rolling features
take price snapshot
send alert (emit_ts)


Показать код
Классические проблемы и решения:

Stale из‑за REST polling: при обходе сотен символов “полный цикл” часто дольше, чем жизнь движения; Bybit прямо подсказывает избегать rate‑limit блоков и брать market data через WS. 
WS disconnect / ping‑pong: Binance требует pong на ping, иначе disconnect; BingX шлёт ping каждые ~5 секунд, тоже надо отвечать. 
Неконсистентный локальный стакан: без правильного алгоритма U/u/pu вы получаете “ложный spread/imbalance”; Binance публикует конкретную процедуру пересборки. 
Time drift: timestamps должны идти “exchange_ts → receive_ts → processed_ts → emitted_ts”; иначе вы не докажете, это биржа дала задержку или ваш код. (Это прямо следует из необходимости near-real-time в моделях и общих практик observability: семантические конвенции для унификации атрибутов в телеметрии). 
Реализация и аудит на уровне кода
Ниже — чек‑лист “что именно проверять” в ключевых функциях и какая телеметрия делает проблему измеримой.

Чек‑лист функций
get_current_price
Проверить:

берётся ли цена из WS‑кэша (желательно) или делает REST запрос “прямо сейчас” (почти всегда источник stale). 
возвращает ли функция структуру: last_trade, bid, ask, mid, mark, exchange_ts, receive_ts, stale_ms. (Bybit ticker payload включает ts как system timestamp и поля lastPrice/markPrice; это хороший ориентир. 
)
есть ли guard: if stale_ms > limit → reject сигнал / пометить как stale.
build_snapshot
Проверить:

базовая цена baseline — это mid/bbo, а не close свечи. 
snapshot сохраняет exchange_ts и receive_ts для аудита
snapshot хранит “range” baseline→trigger для объяснимости.
detect_signal
Проверить:

rolling окно действительно rolling (time‑based или N trades)
фильтры ликвидности не “убивают” рынок: spread_bps, min volume, min trade_count
RSI/осцилляторы — soft, а не hard (если нет специального режима) 
есть ли Raw Candidates логирование (см. ниже).
send_notification
Проверить:

отправка идёт после фиксации snapshot (и записывается в логи latency)
сообщение содержит stale_ms, источник цены, диапазон и bid/ask
dedup проверяется непосредственно перед send.
Логи: точные поля и формат
Метрика “рынок не дал” vs “код пропустил” почти всегда решается одним: логировать кандидатов и причину отбраковки.

Рекомендуемый JSON‑лог на каждый symbol‑scan:

json
Копировать
{
  "ts": "2026-03-11T12:34:56.789Z",
  "event": "scan_candidate",
  "symbol": "XYZ-USDT",
  "window_sec": 60,
  "exchange_event_ts": 1710000000123,
  "local_receive_ts": 1710000000230,
  "local_processed_ts": 1710000000250,
  "stale_ms": 127,

  "price": { "mid": 0.01295, "bid": 0.01294, "ask": 0.01296, "last": 0.01295, "mark": null },
  "features": {
    "dprice_pct": 5.28,
    "trade_count": 184,
    "vol_quote": 125000.55,
    "spread_bps": 12.4,
    "imbalance": 0.18,
    "vwap": 0.01288
  },
  "score": 0.83,
  "decision": "reject",
  "reject_reason": "cooldown" 
}
Почему так: в исследованиях, ориентированных на “секунды до pump”, качество резко падает при увеличении time offset (20 секунд → 1 минута), значит latency и stale — не “побочный эффект”, а центральная характеристика pipeline. 

SQL‑схемы хранения снапшотов/сигналов
Если вы хотите строгий аудит “цена была мертвой или нет”, храните снапшоты как time‑series.

sql
Копировать
CREATE TABLE md_snapshot (
  id            BIGSERIAL PRIMARY KEY,
  symbol        TEXT NOT NULL,
  exchange_ts   BIGINT NOT NULL,
  receive_ts    BIGINT NOT NULL,
  mid           NUMERIC,
  bid           NUMERIC,
  ask           NUMERIC,
  last_trade    NUMERIC,
  mark          NUMERIC,
  spread_bps    NUMERIC,
  trade_count   INT,
  vol_quote     NUMERIC,
  raw           JSONB
);

CREATE INDEX ON md_snapshot (symbol, exchange_ts);

CREATE TABLE signal_event (
  id            BIGSERIAL PRIMARY KEY,
  symbol        TEXT NOT NULL,
  direction     TEXT NOT NULL, -- LONG/SHORT or PUMP/DUMP
  window_sec    INT NOT NULL,
  dprice_pct    NUMERIC NOT NULL,
  baseline_mid  NUMERIC,
  trigger_mid   NUMERIC,
  exchange_ts   BIGINT NOT NULL,
  emitted_ts    BIGINT NOT NULL,
  fingerprint   TEXT NOT NULL UNIQUE,
  payload       JSONB NOT NULL
);
Если объем большой, используйте партиционирование таблиц по времени; PostgreSQL описывает, что partitioning может сильно улучшать производительность в сценариях больших таблиц и повышает шанс держать горячие части индексов в памяти. 

Альтернатива: Timescale continuous aggregates для агрегатов по минутам/часам. 

Для аналитики “много записей → быстрые срезы” часто выбирают ClickHouse как time‑series аналитическое хранилище. 

Методология детекции, backtest и реверс‑инжиниринг референса
Как “снять” логику reference‑бота по логам/сообщениям
Если у вас есть только сообщения вида time, symbol, %, price, можно восстановить много:

Распределение процентов
найдите min/медиану/квантили “%”; “ступени” (например, ровно 5.00%) намекают на пороги и квантование.
Скорость и частота
сколько сигналов/минуту. Высокая плотность сигналов типична для WS‑архитектуры; низкая — для последовательного REST‑скана. Это согласуется с тем, почему исследования делают ставку на near-real-time, иначе точность падает. 
Как reference фиксирует цену
если reference показывает range baseline→trigger, это почти всегда rolling baseline (mid/bbo) + фиксация экстремума/текущего значения; базовый ориентир — baseline mid (midpoint bid/ask), как в исследованиях. 
Сопоставление по рынку
подтяните исторические trade/BBO и проверьте, соответствует ли % движению в окне T.
Какие метрики сравнивать (reference vs your bot)
signals_per_hour
raw_candidates_per_hour
reject_rate_by_reason
stale_ms p95/p99
scan_cycle_seconds
missed_reference_events (время, symbol, reference_has_signal=1, ours=0)
Статистические пороги: z‑score / EWMA / volatility
Два “рабочих” семейства:

Z‑score по фичам: short-term поведение сравнивается с историческим (mean/std) и ранжируется; именно так строится модель, где комбинация trade+orderbook даёт лучший TOP5/TOP10 результат, а качество быстро падает при увеличении lead time. 
Threshold + EWMA + volatility: полезно для борьбы с шумом и “мертвым рынком”; в 2025 показано, что добавление EWMA и volatility помогает фильтровать нерелевантные spikes (и приводятся конкретные конфигурации порогов). 
Пример SQL‑запросов для диагностики
sql
Копировать
-- Где чаще всего режете кандидатов
SELECT reject_reason, COUNT(*) AS n
FROM scan_log
WHERE ts >= now() - interval '24 hours'
  AND decision = 'reject'
GROUP BY 1
ORDER BY n DESC;

-- P95 stale по минутам (ищем "мертвую цену")
SELECT date_trunc('minute', ts) AS minute,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY stale_ms) AS p95_stale_ms
FROM scan_log
WHERE ts >= now() - interval '6 hours'
GROUP BY 1
ORDER BY 1;
Backtest для стратегии “post‑impulse stall+pullback” (short/long)
Чтобы backtest не был самообманом, он должен учитывать:

bid/ask fill (минимум), а лучше симуляцию по стакану, иначе вы системно недооцените проскальзывание;
latency injection: прогоните сценарии с задержкой 0ms / 250ms / 1s / 3s, потому что в реальных P&D окна очень короткие (0.12 минуты до пика в среднем для одной площадки в кейсе исследования). 
fees + funding (фьючи) и mark price (для риск‑событий). 
Примеры тест‑сценариев (минимальный набор):

“быстрый pump 5–10% за 60s → stall 20s → pullback 0.8% → short”
“быстрый dump → stall → bounce → long”
“ложный сигнал: wide spread / низкий volume → обязаны отфильтровать”
“WS disconnect на 10s → должен включиться stale_guard и не слать сигналы” (Binance/BingX требуют корректный ping/pong и reconnect). 
Операционные практики, лимиты, безопасность и комплаенс
Формат алерта: диапазон лучше, чем одна цена
Для реальной торговли “одна цена” почти всегда вводит в заблуждение (особенно в импульсе). Лучший практический формат:

Δ% за окно T
baseline_mid → trigger_mid
bid/ask + spread_bps
stale_ms и source (ws/rest, trade/bbo/mark)
Это согласуется с тем, что baseline mid используется как опорная точка в исследовательских измерениях price spikes. 

Rate limits и concurrency limits
Нужно учитывать ограничения биржевых потоков:

Binance Spot WS: лимит входящих сообщений/сек на соединение, лимит streams/соединение (1024), лимиты соединений/IP, ping/pong, TTL соединения. 
Bybit: в FAQ говорится, что WS market data не считается в rate limits, что делает WS предпочтительным для скринеров. 
BingX: публикуется повышение rate limit для торговых эндпоинтов (пример: order placement с 5 rps до 10 rps с 2025‑10‑16), что важно для автоторговли, но это не заменяет WS для market data. 
Observability: какие графики должны быть “на стене”
С точки зрения практик Prometheus и OpenTelemetry:

metric naming и labels должны быть стабильными и не иметь high‑cardinality. 
latency лучше собирать histogram’ами и считать p95/p99. 
semantic conventions помогают стандартизировать атрибуты телеметрии (в том числе для traces/logs). 
В Grafana для этого подходят:

Time series panel для рядов. 
State timeline для состояния соединений/режимов (ws_connected/ws_reconnecting/data_stale). 
Инфраструктура: VM против Kubernetes
Минимально жизнеспособно: одна VM (например Amazon EC2) с контейнером бота; EC2 описывается как виртуальный сервер в AWS, которым вы управляете от запуска до остановки. 

Если вы хотите scale‑out и управляемые обновления — Kubernetes:

Deployments для управления репликами и обновлениями. 
rolling updates для обновлений с минимальным downtime. 
HPA для автоматического масштабирования по метрикам нагрузки. 
Контейнеризация через Docker: контейнер — это изолированный процесс со своим FS/сетями/process tree. 

Безопасность, abuse и правовые заметки
Pump‑and‑dump как схема — это форма мошенничества/манипуляции: Investor.gov описывает “pump” как разгон цены ложной/вводящей информацией и “dump” как продажу разогнанного актива, после чего цена падает и инвесторы теряют деньги. 

Регуляторы продолжают преследование таких схем: например Australian Securities and Investments Commission публиковал релизы о признании вины и приговорах по Telegram‑координации “pump and dump”. 

(Это важно даже для “детектора”: вы должны явно позиционировать продукт как risk‑индикатор/скринер, избегать функционала, который облегчает координацию манипуляций.)

Приоритизированный чек‑лист P0/P1/P2 с тест‑кейсами
P0: устранить “мертвую цену” и сделать latency измеримой
Задача	Изменение	Тест‑кейс	Ожидаемый результат
WS‑кэш вместо REST для price snapshot	Подключить trade + BBO/тикер + (фьючи) mark; snapshot брать из in‑memory, не из REST	A/B прогон 1 час на 200 символах	p95 stale_ms резко падает; “цена в сигнале” близка к mid/bid/ask в момент алерта. 
Ввести 4 timestamp’а	Логировать exchange_event_ts, local_receive_ts, local_processed_ts, emitted_ts	Инъекция задержки 1–3s искусственно	stale_guard срабатывает; сигнал либо не отправлен, либо помечен stale=true. 
Учитывать ping/pong и reconnect	Реализовать heartbeat‑handling: Binance ping/pong, BingX ping/pong; backoff reconnect	Тест выключения сети на 30s	Система восстанавливается, а state timeline фиксирует периоды disconnect/reconnect. 

P1: поднять частоту валидных сигналов и снизить пропуски
Задача	Изменение	Тест‑кейс	Ожидаемый результат
Raw Candidates + Reject Reasons	Логировать каждого кандидата и причину reject	24ч прогон + агрегаты	Видно, что “душит” стратегию (RSI/ликвидность/cooldown/порог). 
Перевести RSI в soft‑score	Заменить hard‑reject на штраф/бонус в score	A/B режим	Рост signals/hour при контролируемом noise. 
Параллелизм/батчинг	Отказ от последовательного обхода; ограниченный concurrency и/или multiplex WS	Нагрузочный тест: 300+ символов	scan_cycle_seconds уменьшается, меньше пропусков быстрых импульсов. 
Ликвидность через spread+depth	Фильтровать не только vol, но и spread_bps/глубину	Тест на low‑cap	Снижение ложных входов на “пустых” парах; меньше проскальзывания. 

P2: прод‑качество и расширение микро‑признаков
Задача	Изменение	Тест‑кейс	Ожидаемый результат
Локальный стакан по правилам биржи	Реализовать snapshot+delta и контроль update IDs (Binance futures алгоритм U/u/pu)	Тест packet loss / reorder	Нет “сломанных” spread/imbalance; при разрыве — пересборка. 
Хранилище и агрегаты	Партиционирование Postgres или Timescale continuous aggregates, либо ClickHouse для аналитики	7 дней high‑freq записи	Быстрые отчеты по сигналам/лагам; стабильные inserts. 
Трейсинг по pipeline	OTel traces для receive→score→emit→send	Инцидент: spike latency	Можно точно локализовать “узкое место”. 
Подготовка к инфра‑изменениям	Следить за changelog/upgrade notices	Dry‑run на тестнете	Нет деградации при изменении WS base URLs (пример: Binance Futures upgrade и дедлайн миграции). 

Ключевые источники, на которые можно опираться
Биржевые WS/market data спецификации и ограничения: Binance Spot WS (лимиты/TTL/ping/pong/timeUnit), Binance futures order book sync, BingX WS gzip+heartbeat, Bybit ticker/orderbook/SBE, OKX snapshot/incremental каналы. 
Исследования 2025 по P&D: real‑time pipeline, измерение времени до пика, baseline midprice, важность near-real-time, trade+orderbook vs по отдельности. 
Пороговые/антишум подходы 2025: EWMA+volatility для фильтрации noise. 
Observability: metric naming, histogram/quantiles, semantic conventions; Grafana time series/state timeline. 
Русскоязычные инженерные описания архитектур сканеров и микроструктуры: Habr (сервисная архитектура, очереди, выбор ClickHouse, упоминание импульсов и WS; разбор стакана как event-driven snapshot+updates и миллисекундных реакций). 
Правовые/этические справки: Investor.gov о pump‑and‑dump; публичные релизы ASIC по делам “pump and dump”. 