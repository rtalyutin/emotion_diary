Цель. Референс по данным и метрикам.

Схема БД (минимум):

ident(pid PK, chat_id UNIQUE, created_at) — сопоставление псевдонима к чату.

users(pid FK, tz, notify_hour, created_at).

entries(id PK, pid, ts, mood {-1,0,1}).

Индекс (pid, ts). Псевдоним pid = HMAC(chat_id, SALT).

Хранение: SQLite(WAL) на MVP, миграция на Postgres без смены моделей. (12-Factor для конфигов/URL.) 

Ретеншн и экспорт/удаление — см. PRIVACY.md.

Наблюдаемость (Prometheus):

Counters: ping_sent_total, checkin_saved_total, errors_total.

Gauges: active_users_gauge.

Histograms: latency_checkin_seconds. (Типы/назначение метрик.)
