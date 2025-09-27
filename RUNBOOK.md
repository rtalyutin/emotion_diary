# Emotion Diary Runbook

## Цель
Справочник по эксплуатационным процедурам и реагированию на инциденты Telegram-бота Emotion Diary.

## Мониторинг и проверки
- **Health-check API**: `GET https://emotion.example.com/healthz` (возвращает `{ "status": "ok" }`). Для ручного запроса: `curl -fsS https://emotion.example.com/healthz`.
- **Worker/Scheduler**: бот и планировщик развёрнуты в Kubernetes `prod-emotion`. Проверка статуса: `kubectl -n emotion-diary get pods -l app=emotion-diary-bot` и `kubectl -n emotion-diary get pods -l app=emotion-diary-scheduler`. Логи: `kubectl -n emotion-diary logs deploy/emotion-diary-bot` (включая worker) и `kubectl -n emotion-diary logs cronjob/emotion-diary-scheduler --since=1h`.
- **Проверка БД**: PostgreSQL 14 `emotion-diary` (CloudSQL). Статус соединений: `kubectl -n emotion-diary exec deploy/emotion-diary-bot -- pg_isready -h $DATABASE_HOST -p 5432 -d emotion_diary`. Диагностика задержек: `kubectl -n emotion-diary exec deploy/emotion-diary-bot -- psql $DATABASE_URL -c "select now(), count(*) from entries where created_at > now() - interval '1 day';"`.
- **Обязательные переменные окружения**:
  - `BOT_TOKEN` — токен Telegram Bot API.
  - `DATABASE_URL` — строка подключения PostgreSQL.
  - `SCHEDULER_TIMEZONE` — таймзона пользователя по умолчанию (UTC при отсутствии настройки).
  - `PING_HOUR_DEFAULT` — час отправки пинга (целое, локальное время).
  - `SENTRY_DSN` — DSN для ошибок (может быть пустым в стейджинге).
  - `LOG_LEVEL` — уровень логирования (`INFO` в продакшене).
  - `REDIS_URL` — соединение для дедупликации.
  - `TELEGRAM_WEBHOOK_URL` — URL вебхука, зарегистрированный в Bot API.
  - `PROM_PUSHGATEWAY_URL` — адрес Pushgateway для метрик.

## SLO
- **Доставка пингов**: ≥99% ежедневных `ping.request` должны переходить в `ping.sent` в течение 5 минут после запланированного времени (квартиль 7 дней).
- **Ответность чек-ина**: p95 времени от получения `tg.update` до отправки ответа `checkin.saved` ≤1.5 секунды (измеряется по метрике `checkin_latency_seconds`).

## Алерты (Prometheus/Alertmanager)
| Название | PromQL | Порог и длительность | Канал уведомления |
| --- | --- | --- | --- |
| `PingDeliveryDropMajor` | `1 - (sum(rate(ping_sent_total{env="prod"}[15m])) / sum(rate(ping_request_total{env="prod"}[15m])))` | >0.05 в течение 15 минут | `#emotion-sre` Slack (PagerDuty if >0.15)|
| `CheckinLatencyHigh` | `histogram_quantile(0.95, sum by (le) (rate(checkin_latency_seconds_bucket{env="prod"}[5m])))` | >1.5 секунд 3 из 4 интервалов | `#emotion-sre` Slack |
| `Telegram429Burst` | `increase(telegram_rate_limit_hits_total{env="prod"}[5m])` | ≥50 за 5 минут | Slack `#emotion-sre` + email on-call |
| `DBLatencyCritical` | `avg_over_time(db_query_duration_seconds{env="prod"}[10m])` | >0.8 секунд 10 минут | PagerDuty rotation |
| `BackupStale` | `time() - last_success_backup_timestamp_seconds{env="prod"}` | >86400 | Email SRE DL |

Alertmanager маршрутизация: high severity (PagerDuty) → on-call телефон (<5 минут отклика), medium → Slack (<15 минут), low → email (<24 часов).

## Общие принципы реагирования
1. Зафиксировать время, инициатора, используемые команды в `#emotion-incident-log` (Slack) и в журнале PagerDuty инцидента.
2. Минимизировать воздействие («остановить кровотечение»), затем восстанавливать нормальную работу.
3. Все временные изменения документировать в Jira тикете `EMO-SRE-INC-<id>`.
4. По завершении — оформить постмортем (см. шаблон ниже) в течение 48 часов.

## Плейбуки

### Telegram 429 (rate limiting)
**Симптомы**: рост `telegram_rate_limit_hits_total`, ответы API 429, пользователи не получают ответы.

**Действия**:
1. Подтвердить алерт: `kubectl -n emotion-diary logs deploy/emotion-diary-bot --since=5m | grep 429`.
2. Проверить распределение по чатам: `kubectl -n emotion-diary exec deploy/emotion-diary-bot -- python manage.py show_rate_limits` (лог в stdout).
3. Включить деградацию: `kubectl -n emotion-diary set env deploy/emotion-diary-bot RATE_LIMIT_MODE=slow` (режим отправки с 1.5с задержкой).
4. При глобальном лимите — отключить новые пинги: `kubectl -n emotion-diary scale deploy emotion-diary-scheduler --replicas=0`. Зафиксировать в канале.
5. Связаться с on-call продукта о влиянии на пользователей.
6. После стабилизации (<5 лимитов/мин) вернуть настройки: удалить `RATE_LIMIT_MODE`, вернуть scheduler.
7. Создать тикет на оптимизацию/шардинг.

**Ответственные**: первично on-call SRE, при необходимости привлекаем инженера интеграции Telegram.

### Деградация БД
**Симптомы**: медленные запросы, рост `db_query_duration_seconds`, ошибки `timeout`.

**Действия**:
1. Проверить состояние PostgreSQL: `kubectl -n emotion-diary exec deploy/emotion-diary-bot -- pg_isready -h $DATABASE_HOST`.
2. Посмотреть блокировки: `psql $DATABASE_URL -c "select pid, state, query from pg_stat_activity where state <> 'idle';"` (логируется в `postgresql.log`).
3. Ограничить нагрузку: включить фичу-флаг `READ_ONLY_MODE=true` через `kubectl set env` для бота (запрет новых записей, информируем пользователей). Записать в Slack.
4. Увеличить размер пула/перезапустить поды: `kubectl rollout restart deploy/emotion-diary-bot`.
5. Если БД вне строя → переключить на реплику: `kubectl set env deploy/emotion-diary-bot DATABASE_URL=$DATABASE_URL_FALLBACK`.
6. По завершении — снять флаг, открыть доступ, инициировать RCA с DBA.

**Ответственные**: on-call SRE + DBA (эскалация, если восстановление >15 мин).

### Компрометация токена Telegram Bot API
**Симптомы**: подозрительная активность, уведомление от Telegram, обнаружена утечка.

**Действия**:
1. Зафиксировать источник подозрения, время, кто сообщил (Slack `#emotion-incident-log`).
2. Немедленно revoke токен: `curl -XPOST https://api.telegram.org/bot$BOT_TOKEN/deleteWebhook` и запрос нового токена через `@BotFather` (использовать резервного владельца).
3. Обновить секреты: `kubectl -n emotion-diary create secret generic emotion-bot-token --from-literal=BOT_TOKEN=<new> --dry-run=client -o yaml | kubectl apply -f -`.
4. Перекатить деплой: `kubectl rollout restart deploy/emotion-diary-bot`.
5. Проверить лог входящих запросов на сторонние IP (Stackdriver log `emotion-webhook`).
6. Обновить `TELEGRAM_WEBHOOK_URL`: `kubectl -n emotion-diary exec deploy/emotion-diary-bot -- python manage.py set_webhook`.
7. Уведомить безопасность и продукт, выпустить сообщение пользователям при необходимости.
8. Подготовить отчёт и ротацию доступов (Git, CI).

**Ответственные**: on-call SRE + security officer.

### Восстановление из бэкапа
**Предпосылки**: ежедневные снапшоты `gs://emotion-backups/` (WAL-G).

**Действия**:
1. Убедиться в необходимости Point-in-Time: получить время инцидента и желаемую точку восстановления.
2. Подготовить временную БД: `cloudsql instances clone emotion-diary emotion-diary-restore --point-in-time <ts>`.
3. Проверить целостность: `psql $RESTORE_DATABASE_URL -c "select count(*) from entries;"`.
4. Перевести приложение в режим обслуживания: `kubectl set env deploy/emotion-diary-bot MAINTENANCE_MODE=true` и убедиться, что пользователи получают сообщение о технических работах.
5. Обновить `DATABASE_URL` на восстановленную БД и перезапустить деплой.
6. Прогнать smoke-тест: `pytest tests/smoke/test_checkin.py --base-url https://emotion.example.com` (логируется в CI pipeline `restore-smoke`).
7. После подтверждения — удалить старую инстанцию или сохранить для RCA. Обновить документацию о восстановлении.

**Ответственные**: on-call SRE + DBA, согласование с продуктом.

## Эскалации
- **Slack `#emotion-sre`** — первичный канал, отклик ≤15 минут.
- **PagerDuty rota `Emotion Diary`** — high severity, телефон/Push, отклик ≤5 минут.
- **Security hotline +7-XXX-XXX-00-00** — для компрометации токенов/данных, уведомить в течение 10 минут.
- **Product manager (телеграм @emotion_pm)** — при влиянии на пользователей >30 минут.

Все эскалации фиксируются в журнале инцидента. Ответственный on-call инициирует вовлечение нужных ролей.

## Шаблон постмортема
```
# Emotion Diary Postmortem – <инцидент>

## Краткое описание
- Дата/время (UTC):
- Длительность:
- Влияние на пользователей/бизнес:

## Timeline
| Время | Событие | Источник |
| --- | --- | --- |

## Первопричина

## Детали обнаружения
- Как был обнаружен:
- Почему не обнаружили раньше:

## Реакция
- Что сработало:
- Что не сработало:

## Действия по устранению
- Временные меры:
- Постоянные изменения (с ответственными и датами):

## Метрики
- Данные SLO/алертов:
- Другие показатели:

## Уроки и follow-up
- Процессы:
- Инструменты/мониторинг:
- Коммуникация:

## Приложения
- Ссылки на логи:
- Дашборды:
- Диаграммы архитектуры:
```

