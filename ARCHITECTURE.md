# Архитектура Emotion Diary

## 1. Цели и ограничения
- **Цель продукта** — помогать пользователю фиксировать настроение и получать эмоциональную поддержку в Telegram с минимальным трением.
- **Операционные принципы** — 12-Factor: конфигурация через `ENV`, статeless-процессы, независимые контейнеры для webhook, воркеров и планировщика; взаимодействие между ними построено на обмене событиями.
- **Ограничения среды** — использование Telegram Bot API (webhook с секретным заголовком), хранение пользовательских данных в управляемом хранилище с возможностью экспорта/удаления, минимальная задержка ответа пользователю (<2 c).
- **Качества** — устойчивость к повторной доставке (`Dedup`), наблюдаемость (метрики и логи по каждому контейнеру), защищённое хранение секретов (token, ключи экспорта).

## 2. Контекст системы (C4 L1)
Emotion Diary Bot взаимодействует с пользователем через Telegram Bot API: входящие сообщения поступают по webhook, ответы формируются ботом; доменные данные сохраняются в отдельном хранилище для дальнейших операций экспорта и удаления.

```mermaid
%% C4 L1 Context diagram
graph TD
    User((Пользователь))
    TelegramAPI[[Telegram Bot API]]
    EmotionBot[(Emotion Diary Bot)]
    Storage[(БД/Хранилище чек-инов)]

    User -->|сообщения, команды| TelegramAPI
    TelegramAPI -->|tg.update webhook| EmotionBot
    EmotionBot -->|ответы, карточки| TelegramAPI
    EmotionBot -->|чтение/запись состояний| Storage
```
[Источник диаграммы: `docs/diagrams/c4-l1-context.mmd`]

## 3. Контейнеры (C4 L2)
- **Webhook-сервис** принимает webhook-и Telegram, валидирует подпись, публикует событие `tg.update` в очередь.
- **Worker-сервис** исполняет доменную логику (Router, Dedup, Notifier, Export/Delete, PetRender, CheckinWriter) и взаимодействует с базой/файловым хранилищем.
- **Планировщик** (CronJob) раз в сутки публикует `ping.request` для пользователей, чтобы инициировать вечерний чек-ин.
- **Очередь событий** гарантирует поставку событий и развязывает компоненты по времени; используется также как канал обратной связи для уведомлений.
- **Хранилище** сохраняет чек-ины, медиа и экспортированные файлы.

```mermaid
%% C4 L2 Container diagram
flowchart TD
    TelegramAPI[[Telegram Bot API]]
    Webhook[(Webhook-сервис)]
    Scheduler[(Планировщик)]
    Worker[(Worker-сервис<br/>Router/Dedup/...)]
    Queue{{Очередь событий / Cron}}
    Storage[(БД/хранилище)]

    TelegramAPI -->|tg.update HTTPS| Webhook
    Webhook -->|tg.update| Queue
    Scheduler -->|ping.request| Queue
    Queue -->|tg.update, ping.request| Worker
    Worker -->|checkin.save| Storage
    Worker -->|checkin.saved, pet.render, export.request, delete.request| Queue
    Queue -->|pet.rendered, export.ready, delete.done| Worker
    Worker -->|ответы, карточки| Webhook
    Webhook -->|ответы| TelegramAPI
```
[Источник диаграммы: `docs/diagrams/c4-l2-container.mmd`]

## 4. Ключевые компоненты (C4 L3)
Компоненты внутри Worker-сервиса реализованы как независимые агенты (см. `AGENTS.md`), которые общаются через доменные события:
- **Router** — принимает `tg.update`, распознаёт команды `/start`, кнопки и свободный текст, транслируя их в доменные события: `checkin.save`, `export.request`, `delete.request`.
- **Dedup** — фильтрует повторно доставленные `tg.update` в окне 10 минут, чтобы избежать дублей операций.
- **CheckinWriter** — валидирует настроение и комментарий, записывает в БД/хранилище, эмитит `checkin.saved`.
- **PetRender** — по `ping.request` и `checkin.saved` выбирает визуальный спрайт питомца, возвращает `pet.rendered`.
- **Notifier** — по `pet.rendered`, `checkin.saved`, `export.ready`, `delete.done` формирует карточки и ответы пользователю в Telegram.
- **Export** — формирует CSV, выкладывает в временное хранилище, публикует `export.ready`.
- **Delete** — проводит полное удаление данных пользователя, сообщает `delete.done`.

```mermaid
%% C4 L3 Component diagram
flowchart LR
    Bus{{Event Bus}}
    Dedup[Dedup]
    Router[Router]
    CheckinWriter[CheckinWriter]
    PetRender[PetRender]
    Notifier[Notifier]
    Exporter[Export]
    Deleter[Delete]
    Store[(БД/файлы)]

    Bus -->|tg.update| Dedup
    Dedup -->|tg.update| Router
    Router -->|checkin.save| Bus
    Router -->|export.request| Bus
    Router -->|delete.request| Bus
    Bus -->|checkin.save| CheckinWriter
    CheckinWriter -->|чтение/запись| Store
    CheckinWriter -->|checkin.saved| Bus
    Bus -->|checkin.saved| PetRender
    Bus -->|ping.request| PetRender
    PetRender -->|asset lookup| Store
    PetRender -->|pet.rendered| Bus
    Bus -->|ping.request| Notifier
    Bus -->|pet.rendered| Notifier
    Bus -->|checkin.saved| Notifier
    Bus -->|export.ready| Notifier
    Bus -->|delete.done| Notifier
    Exporter -->|чтение записей| Store
    Bus -->|export.request| Exporter
    Exporter -->|export.ready| Bus
    Bus -->|delete.request| Deleter
    Deleter -->|удаление данных| Store
    Deleter -->|delete.done| Bus
```
[Источник диаграммы: `docs/diagrams/c4-l3-components.mmd`]

## 5. Runtime-сценарии
### 5.1 Вечерний чек-ин
1. Пользователь отправляет команду/кнопку чек-ина; `Dedup` гарантирует уникальность `tg.update`.
2. `Router` формирует `checkin.save`, `CheckinWriter` фиксирует запись и публикует `checkin.saved`.
3. `PetRender` выбирает спрайт (`pet.render` → `pet.rendered`), `Notifier` отправляет карточку пользователю.

```mermaid
%% Runtime scenario: evening check-in
sequenceDiagram
    participant U as Пользователь
    participant TG as Telegram API
    participant WH as Webhook-сервис
    participant Q as Очередь
    participant D as Dedup
    participant R as Router
    participant CW as CheckinWriter
    participant PR as PetRender
    participant N as Notifier

    U->>TG: Сообщение /checkin
    TG->>WH: tg.update
    WH->>Q: publish tg.update
    Q->>D: deliver tg.update
    D->>R: tg.update (уникальный)
    R->>CW: checkin.save (оценка настроения)
    CW->>CW: Запись в БД
    CW->>Q: checkin.saved
    Q->>PR: deliver checkin.saved
    PR->>PR: Выбор спрайта (pet.render)
    PR->>N: pet.rendered
    N->>Q: уведомление (карточка)
    Q->>WH: deliver tg.response
    WH->>TG: ответ/картинка
    TG->>U: Сообщение с питомцем
```
[Источник диаграммы: `docs/diagrams/runtime-evening-checkin.mmd`]

### 5.2 Экспорт данных
1. Команда `/export` проходит через `Dedup` и `Router`, создавая `export.request`.
2. `Export` агрегирует чек-ины, сохраняет CSV и публикует `export.ready`.
3. `Notifier` отправляет пользователю ссылку на выгрузку.

```mermaid
%% Runtime scenario: export request
sequenceDiagram
    participant U as Пользователь
    participant TG as Telegram API
    participant WH as Webhook-сервис
    participant Q as Очередь
    participant D as Dedup
    participant R as Router
    participant E as Export
    participant N as Notifier

    U->>TG: Команда /export
    TG->>WH: tg.update
    WH->>Q: publish tg.update
    Q->>D: deliver tg.update
    D->>R: tg.update (уникальный)
    R->>E: export.request
    E->>E: Сбор чек-инов
    E->>Q: export.ready (ссылка на CSV)
    Q->>N: deliver export.ready
    N->>Q: уведомление с ссылкой
    Q->>WH: deliver tg.response
    WH->>TG: Ответ с CSV ссылкой
    TG->>U: Получение ссылки на экспорт
```
[Источник диаграммы: `docs/diagrams/runtime-export.mmd`]

### 5.3 Удаление данных
1. `/delete` инициирует `delete.request` через `Router`.
2. `Delete` очищает данные пользователя и отправляет `delete.done`.
3. `Notifier` уведомляет пользователя о завершении операции.

```mermaid
%% Runtime scenario: delete request
sequenceDiagram
    participant U as Пользователь
    participant TG as Telegram API
    participant WH as Webhook-сервис
    participant Q as Очередь
    participant D as Dedup
    participant R as Router
    participant Del as Delete
    participant N as Notifier

    U->>TG: Команда /delete
    TG->>WH: tg.update
    WH->>Q: publish tg.update
    Q->>D: deliver tg.update
    D->>R: tg.update (уникальный)
    R->>Del: delete.request
    Del->>Del: Полное удаление данных
    Del->>Q: delete.done
    Q->>N: deliver delete.done
    N->>Q: уведомление об удалении
    Q->>WH: deliver tg.response
    WH->>TG: Ответ "данные удалены"
    TG->>U: Подтверждение удаления
```
[Источник диаграммы: `docs/diagrams/runtime-delete.mmd`]

## 6. Развертывание и эксплуатация
- **Хостинг** — контейнеры развёрнуты в Kubernetes (или эквивалентной облачной оркестрации) внутри namespace `emotion-diary`: Deployment для webhook, Deployment для worker, CronJob для планировщика.
- **Secrets** — токен Telegram, ключи экспорта, параметры БД предоставляются через Secret + `ENV`. Политика 12-Factor упрощает перенос конфигурации между средами.
- **Observability** — все контейнеры шлют метрики/логи в стек Prometheus/Grafana + централизованный логгер; алерты на рост ошибок webhook или задержек очереди.
- **Данные** — основная БД (PostgreSQL/Managed) для чек-инов и объектное хранилище (S3) для экспортов.

```mermaid
%% Deployment diagram
flowchart TB
    subgraph Cloud[Облако / Kubernetes]
        subgraph BotNamespace[Namespace emotion-diary]
            WebhookPod[(Deployment: Webhook)]
            WorkerPod[(Deployment: Worker)]
            SchedulerJob[(CronJob: Scheduler)]
        end
        Secrets[(Secrets: ENV + Telegram token)]
        Observability[(Observability: Prometheus/Grafana + Logs)]
    end
    ManagedDB[(Managed DB / S3-хранилище)]
    TelegramAPI[[Telegram Bot API]]

    TelegramAPI -->|HTTPS webhook| WebhookPod
    WebhookPod -->|ENV| Secrets
    WorkerPod -->|ENV| Secrets
    SchedulerJob -->|ENV| Secrets
    WebhookPod -->|метрики/логи| Observability
    WorkerPod -->|метрики/логи| Observability
    SchedulerJob -->|метрики/логи| Observability
    WorkerPod -->|чтение/запись| ManagedDB
    WebhookPod -->|чтение/запись| ManagedDB
```
[Источник диаграммы: `docs/diagrams/deployment.mmd`]
