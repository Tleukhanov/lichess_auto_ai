# lichess_auto_ai — автоматизация шахматной федерации

Скрипты + бот для онлайн-шахматной федерации: создание турниров на Lichess
по расписанию, WhatsApp-бот с RAG (фаза 1), разбор партий и недельный дашборд
(фаза 2), античит-метрики (фаза 3).

## Что работает сейчас (этап 1: создание турниров)

- `python -m backend.lichess_auto.schedule` — читает `schedule.json`, создаёт
  недостающие турниры внутри клуба, дубли пропускает
- Клубное условие входа (только члены клуба), проверка дублей по имени,
  ретраи временных ошибок API, валидация конфигов до запроса
- Время старта задаётся полем `starts_at` (ISO с часовым поясом)

## Структура

```
backend/
  lichess_auto/     создание турниров (client, transport, tournaments, schedule)
  db/
    schema.sql      аналитическая схема (фаза 2): members, tournaments, results
whatsapp_auto/      WhatsApp-бот (фаза 1, Green-API)
requirements.txt    requests, python-dotenv
```

## Настройка

```bash
pip install -r requirements.txt
cp .env.example .env   # если есть; иначе создай .env:
# LICHESS_TOKEN=<токен lichess.org → Settings → API tokens>
# LICHESS_USERNAME=<ник>
```

Расписание — `backend/lichess_auto/schedule.json` (имя ≤ 30 символов, минуты
из списка Lichess: 20, 25, 30 ... 90 ...).

## Дорожная карта

- [x] Этап 1: создание клубных турниров по расписанию
- [ ] Этап 2: WhatsApp-бот (FAQ на RAG + эскалация человеку)
- [ ] Этап 3: PGN-разбор + недельный дашборд
- [ ] Этап 4: античит-метрики (флаги человеку, не автожалобы)
