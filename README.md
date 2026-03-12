# cryptoarbitrajbot

Telegram-бот на Aiogram + FastAPI backend + PostgreSQL/Redis.  
Бот получает живые рыночные данные CEX (Binance public API), считает базовые метрики и формирует сигналы.

## Что умеет сейчас

- Настройки в боте: выбор монеты и таймфрейма без сброса в главное меню.
- Живой сигнал (CEX + DEX + news sentiment + AI score/action).
- Обзор по монете/таймфрейму: ключевые показатели CEX/DEX + news + AI пояснение.
- Аналитика по выбранной паре/таймфрейму + подборка новостей.
- Статистика эффективности: PnL, winrate, hit ratio, drawdown, profit factor.
- Подписки по `chat_id + symbol + timeframe` и фильтрация рассылки по подпискам.
- Self-tuning AI-порогов на основе истории эффективности.

## Быстрый старт (Docker)

1) Создай `.env` по примеру `.env.example` (минимум `TELEGRAM_BOT_TOKEN`).
2) Запусти стек:

```bash
docker compose up -d --build
```

3) (Опционально) включи воркер отправки сигналов:

```bash
docker compose --profile worker up -d signal_worker
```

Масштабирование воркеров (пример на 5 реплик):

```bash
docker compose --profile worker up -d --scale signal_worker=5
```

### Полный стек с воркером сразу

```bash
docker compose --profile worker up -d --build
```

## Локальный запуск без Docker

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -U pip
pip install -e .[dev]
docker compose up -d postgres redis
python -m app.api.main
python -m app.bot.main
```

## Деплой на сервер (SSH)

В проекте есть скрипт `scripts/deploy_server.py`, который:
- подключается по SSH;
- ставит Docker/compose (если нужно);
- обновляет репозиторий на сервере;
- создает `.env`;
- поднимает стек `docker compose` с профилем `worker`.

Пример запуска:

```bash
python scripts/deploy_server.py \
  --host 72.56.121.150 \
  --user root \
  --password "YOUR_PASSWORD" \
  --repo-url "https://github.com/Uz11ps/tradingbotcrypto.git" \
  --branch main \
  --bot-token "YOUR_TELEGRAM_BOT_TOKEN" \
  --signals-chat-id 0
```

