# ТЗ-05: Параллельный backend Telegram-бота (очередь + workers)

**Проект:** video-to-text  
**Этап:** 5 из 7 (рефакторинг backend после [ТЗ-04](TZ-04-telegram-bot.md))  
**Архитектура:** монолит (Python) + **Redis** + **RQ workers** в Docker  
**Зависит от:** [ТЗ-01](TZ-01-audio-extraction.md) … [ТЗ-04](TZ-04-telegram-bot.md)  
**Версия ТЗ:** 1.0  
**Дата:** 2026-05-20  

---

## 1. Цель

Перевести backend Telegram-бота из **single-process / single-lock** в **multi-user architecture** с очередью задач и ограниченным параллелизмом на VPS.

**Сейчас (ТЗ-04 v1):** один Python-процесс, глобальный `JobCoordinator` — **1 активная задача**, in-memory registry, `asyncio.to_thread` для STT/Ollama.

**Цель (ТЗ-05):**

- несколько запросов одновременно → **очередь**;
- **N задач параллельно** (лимит через ENV);
- **отдельные worker-процессы** от Telegram bot;
- STT и summary с **разными лимитами** concurrency;
- production-ready деплой на **Docker**, целевой VPS: **2 vCPU, 4 GB RAM**.

**Не делаем:** Kubernetes, микросервисы, распределённый кластер, отдельная БД (PostgreSQL) — только монолит + Redis + workers.

**URL-загрузка** переносится на [ТЗ-06](TZ-06-url-download.md) (бывший «этап 5»).

---

## 2. Анализ текущей архитектуры (as-is)

### 2.1. Компоненты

```
┌─────────────────────────────────────────────────────────────┐
│  python -m app bot  (один процесс)                          │
│  app/telegram/bot.py      → Application.run_polling()         │
│  app/telegram/handlers.py → on_media, on_theses_callback    │
│  app/telegram/queue.py    → JobCoordinator (asyncio Lock)   │
│  app/telegram/jobs.py     → transcript_jobs in bot_data RAM │
│  app/telegram/pipeline.py → run_transcript_pipeline (sync)  │
└───────────────────────────┬─────────────────────────────────┘
                            │ asyncio.to_thread()
                            ▼
              extract_audio() → transcribe_audio() → summarize_transcript()
                            │
              app/stt/chunks.resolve_workers(None)
              → min(4, cpu_count-1)   ← жёстко, не из ENV бота
```

### 2.2. Ограничения as-is

| Проблема | Где | Последствие |
|----------|-----|-------------|
| Global lock 1 job | `JobCoordinator.try_begin()` | 2-й пользователь → «Уже идёт обработка» |
| Нет персистентной очереди | — | рестарт бота = потеря контекста |
| In-memory `transcript_jobs` | `app/telegram/jobs.py` | рестарт → кнопка «Сделать тезисы» мёртвая |
| STT в thread event loop | `handlers.on_media` | блокирует только 1 job, но event loop жив |
| Whisper workers | `resolve_workers(None)` | на 2c/4GB может OOM при 4 процессах |
| Summary без лимита | один lock на всё | STT и summary не параллелятся, но и не масштабируются |
| Нет retry / failed state | — | падение worker = зависший пользователь |
| Нет structured logging | `logging.basicConfig` | сложно дебажить на VPS |

### 2.3. Что переиспользовать без переписывания

| Модуль | Роль после рефакторинга |
|--------|-------------------------|
| `app/audio/extractor.py` | worker: extract |
| `app/stt/transcriber.py` | worker: STT (с явным `workers=` из ENV) |
| `app/summary/summarizer.py` | worker: summary |
| `app/telegram/handlers.py` | только enqueue + notify (тонкий слой) |
| `app/telegram/formatting.py`, `messages.py` | без изменений |
| `app/telegram/credentials.py`, `auth.py` | без изменений |
| CLI `extract-audio`, `transcribe`, `summarize` | без изменений (offline) |

---

## 3. Целевая архитектура (to-be)

### 3.1. Процессы (Docker Compose)

```
┌──────────────┐     enqueue      ┌─────────────┐
│  bot         │ ───────────────► │   Redis     │
│  (polling)   │ ◄── job status ─ │   (queue)   │
└──────────────┘                  └──────┬──────┘
                                       │
              ┌────────────────────────┼────────────────────────┐
              ▼                        ▼                        ▼
     ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
     │ worker-transcript│    │ worker-transcript│   │ worker-summary  │
     │ (RQ, queue:      │    │ (replica 2…)     │   │ (RQ, queue:     │
     │  transcript)     │    │                  │   │  summary)       │
     └────────┬─────────┘    └────────┬─────────┘   └────────┬─────────┘
              │ extract+STT           │                      │ Ollama
              ▼                       ▼                      ▼
     output/jobs/{job_id}/   shared volumes          output/summaries/
```

**Bot process:**

- принимает Telegram updates;
- скачивает файл в `output/jobs/{job_id}/inbox/`;
- ставит job в Redis (RQ);
- шлёт статусы пользователю;
- **не** вызывает STT/Ollama напрямую.

**Worker processes:**

- `worker-transcript` — FFmpeg extract + STT;
- `worker-summary` — Ollama summarize;
- количество реплик / concurrency — из ENV (см. п. 5).

### 3.2. Выбор очереди: **Redis + RQ**

| Критерий | RQ | Dramatiq |
|----------|-----|----------|
| Простота | высокая | средняя |
| Redis | да | да (или RabbitMQ) |
| Retry / failed registry | встроено | встроено |
| Отдельные очереди | да (`Queue('transcript')`) | да |
| Монолит + Docker | хорошо | хорошо |

**Решение:** **Redis 7 + RQ 2.x** — минимум абстракций, один стек с Docker.

Альтернатива (если RQ не подойдёт по timeout): Dramatiq — только по решению исполнителя в v1.1, не блокирует ТЗ.

### 3.3. Две очереди RQ

| Очередь | Задача | Worker pool |
|---------|--------|-------------|
| `transcript` | extract + STT | `MAX_CONCURRENT_JOBS` workers |
| `summary` | summarize (Ollama) | `MAX_CONCURRENT_SUMMARIES` workers |

Разделение нужно, чтобы **не запускать unlimited parallel summary** и не смешивать RAM-heavy STT с LLM.

---

## 4. Модель задачи (Job)

### 4.1. Поля (Redis hash / JSON key `job:{job_id}`)

| Поле | Тип | Описание |
|------|-----|----------|
| `job_id` | UUID str | уникальный id |
| `type` | `transcript` \| `summary` | тип задачи |
| `status` | enum | см. п. 4.2 |
| `user_id` | int | Telegram user |
| `chat_id` | int | для уведомлений |
| `message_id` | int | исходное сообщение (опционально) |
| `status_message_id` | int | сообщение «идёт обработка» |
| `language` | str | `ru` |
| `created_at` | ISO8601 | |
| `updated_at` | ISO8601 | |
| `rq_job_id` | str | id задачи в RQ |
| `parent_job_id` | str | для summary → transcript job |
| `paths` | object | inbox, wav, txt, json, summary_md |
| `error` | str \| null | текст ошибки |
| `retry_count` | int | |
| `duration_sec` | float | после STT |
| `processing_sec` | float | wall time |

### 4.2. Статусы

```
queued → downloading → extract → stt → done          (transcript)
queued → summary → done                              (summary)
         ↘ failed
         ↘ cancelled
         ↘ timeout
```

| Статус | Кто выставляет | Сообщение пользователю |
|--------|----------------|------------------------|
| `queued` | bot | «В очереди, позиция N…» |
| `downloading` | bot | «Скачиваю…» |
| `extract` | worker | «Извлекаю аудио…» |
| `stt` | worker | «Распознаю речь…» |
| `summary` | worker | «Готовлю тезисы…» |
| `done` | worker/bot | результат |
| `failed` | worker | ошибка + код |
| `cancelled` | bot | отменено |
| `timeout` | RQ/worker | таймаут |

### 4.3. Изолированный каталог

```
output/jobs/{job_id}/
  inbox/          # скачанный медиафайл (bot)
  work/           # wav, chunk temp (worker)
  out/            # txt, json (worker) — или symlinks в output/transcripts с префиксом job_id
```

**Cleanup:** после `done` / `failed` (TTL, по умолчанию **24 ч**) — cron-скрипт или worker hook удаляет `output/jobs/{job_id}/`. Артеfact paths в meta для отладки.

**Callback «Сделать тезисы»:** `callback_data=theses:{job_id}` — `job_id` **персистентный UUID**, metadata в Redis, не in-memory.

---

## 5. Конфигурация (ENV)

### 5.1. Обязательные лимиты

```env
# Queue & concurrency
REDIS_URL=redis://redis:6379/0
MAX_CONCURRENT_JOBS=2
MAX_STT_WORKERS_PER_JOB=2
MAX_CONCURRENT_SUMMARIES=1
MAX_QUEUE_SIZE=10

# Timeouts (seconds)
JOB_TRANSCRIPT_TIMEOUT_SEC=7200
JOB_SUMMARY_TIMEOUT_SEC=1800
JOB_DOWNLOAD_TIMEOUT_SEC=300

# Retry
JOB_MAX_RETRIES=2
JOB_RETRY_DELAY_SEC=60

# Paths
JOBS_BASE_DIR=output/jobs
JOB_CLEANUP_TTL_HOURS=24

# Logging
LOG_FORMAT=json          # json | text
LOG_LEVEL=INFO

# STT (override resolve_workers default)
# Used by workers only — NOT min(4, cpu_count-1)
MAX_STT_WORKERS_PER_JOB=2
```

### 5.2. Профиль для целевого VPS **2 vCPU / 4 GB RAM** (production default)

| Переменная | Значение | Обоснование |
|------------|----------|-------------|
| `MAX_CONCURRENT_JOBS` | **1** | 1× STT ~2–3 GB RAM |
| `MAX_STT_WORKERS_PER_JOB` | **1** | без parallel workers внутри job |
| `MAX_CONCURRENT_SUMMARIES` | **1** | Ollama 3B ~3 GB |
| `MAX_QUEUE_SIZE` | **5** | защита от flood |
| `transcribe parallel` | **false** или workers=1 | см. FR-07 |

> **Правило:** STT job и summary job **не должны** выполняться одновременно на 4 GB, если суммарный RAM > 4 GB. RQ summary worker на 4 GB VPS — **1 реплика**, transcript worker — **1 реплика**; очередь serializes по RAM.

### 5.3. Профиль масштабирования (справочно, не 4 GB VPS)

| VPS | MAX_CONCURRENT_JOBS | MAX_STT_WORKERS_PER_JOB | MAX_CONCURRENT_SUMMARIES |
|-----|---------------------|-------------------------|--------------------------|
| 2c / 4 GB | 1 | 1 | 1 |
| 4c / 8 GB | 1 | 2 | 1 |
| 8c / 16 GB | 2 | 2 | 1 |
| 16c / 32 GB | 4–5 | 2 | 2 |

---

## 6. Функциональные требования

### FR-01. Bot process (`python -m app bot`)

- Long polling без изменений для пользователя.
- При медиа: создать `job_id`, скачать файл, `status=queued`, enqueue RQ `transcript` queue.
- Если `queue_length >= MAX_QUEUE_SIZE` → отказ «Очередь переполнена, попробуйте позже».
- Если workers заняты, но очередь не полна → «В очереди (позиция N)».
- `/status` — статус **своих** jobs (из Redis) + глобальная длина очереди.
- `/cancel` — отмена job в статусе `queued`; для running — best-effort (RQ `cancel_job`).
- Кнопка «Сделать тезисы» → enqueue `summary` queue (проверка `parent_job_id`, `user_id`).

### FR-02. Worker transcript (`python -m app worker transcript`)

```bash
python -m app worker transcript [-v]
```

- Слушает очередь `transcript`.
- Concurrency: **не больше** `MAX_CONCURRENT_JOBS` (число процессов/replicas в Docker или `--burst` в RQ).
- Шаги: `extract_audio` → `transcribe_audio(parallel=workers>1, workers=MAX_STT_WORKERS_PER_JOB)`.
- Обновляет Redis status: `extract` → `stt` → `done`.
- Пишет артефакты; bot получает event (Redis pub/sub или poll) и шлёт `.txt` + кнопку.

### FR-03. Worker summary (`python -m app worker summary`)

```bash
python -m app worker summary [-v]
```

- Слушает очередь `summary`.
- Concurrency: **строго** `MAX_CONCURRENT_SUMMARIES` (отдельный Docker service, `replicas: 1` по умолчанию).
- Вызывает `summarize_transcript(json_path)`.
- Bot шлёт тезисы **только текстом** (как в ТЗ-04 v1.2).

### FR-04. Уведомления пользователю

- Bot подписан на изменения status (Redis pub/sub channel `job:{job_id}:events` или polling каждые N сек для active jobs).
- Редактирование status-сообщения не чаще 30 с (как сейчас).
- При `done` / `failed` — финальное сообщение + документ/текст.

### FR-05. Job status tracking

- API модуля `app/jobs/store.py`: `create_job`, `update_status`, `get_job`, `list_user_jobs`.
- Хранение: Redis (primary); опционально mirror в JSON file для debug.

### FR-06. Structured logging

```json
{"ts":"...","level":"INFO","logger":"app.worker.transcript","job_id":"...","user_id":123,"status":"stt","msg":"..."}
```

- Поля: `job_id`, `user_id`, `queue`, `rq_job_id`, `duration_ms`.
- `LOG_FORMAT=json` на VPS.

### FR-07. Whisper workers только через ENV

- В `app/stt/chunks.py`: **не использовать** `min(4, cpu_count-1)` как default для worker path.
- Default для worker: `MAX_STT_WORKERS_PER_JOB` из config (fallback **1**).
- CLI `transcribe` сохраняет текущее поведение с явным `--workers` (обратная совместимость).

### FR-08. Ограничение parallel summary

- Отдельная очередь `summary` + `MAX_CONCURRENT_SUMMARIES` worker replicas.
- Дополнительно: Redis semaphore key `summary:inflight` (INCR/DECR) как belt-and-suspenders.

### FR-09. Crash recovery

| Сценарий | Поведение |
|----------|-----------|
| Worker SIGKILL mid-STT | RQ помечает job failed; retry до `JOB_MAX_RETRIES`; status `failed` |
| Worker OOM | то же |
| Bot restart | polling resume; jobs в Redis; status polling продолжается |
| Redis restart | jobs lost (documented); v1.1: RQ persistence AOF |
| Orphan temp dir | cleanup TTL |

Bot **не падает** при ошибке worker — только лог + notify user.

### FR-10. Health checks

```bash
python -m app health
```

- Redis PING;
- опционально Ollama `/api/tags`;
- FFmpeg in PATH;
- exit 0 / 1 для Docker `HEALTHCHECK`.

Docker Compose healthcheck для `bot`, `worker-*`, `redis`.

### FR-11. Timeout handling

- RQ: `job_timeout=JOB_TRANSCRIPT_TIMEOUT_SEC` / `JOB_SUMMARY_TIMEOUT_SEC`.
- При timeout → status `timeout`, сообщение пользователю, cleanup schedule.

---

## 7. Структура кода (план рефакторинга)

### 7.1. Новые модули

```
app/
  jobs/
    __init__.py
    models.py          # Job, JobStatus, JobType dataclasses
    store.py           # Redis CRUD
    events.py          # pub/sub notify
  queue/
    __init__.py
    rq_connection.py   # Redis URL, queues
    tasks.py           # @job transcript_task, summary_task
    enqueue.py         # enqueue_transcript, enqueue_summary
  worker/
    __init__.py
    runner.py          # RQ worker entry, signal handlers
    health.py          # health check CLI
  telegram/
    handlers.py        # thin: enqueue only
    notify.py          # send status/result from job events
    queue.py           # DEPRECATED → app/jobs (удалить JobCoordinator в v2)
    pipeline.py        # move logic to app/queue/tasks.py
```

### 7.2. CLI

| Команда | Назначение |
|---------|------------|
| `python -m app bot` | Telegram polling |
| `python -m app worker transcript` | RQ worker STT |
| `python -m app worker summary` | RQ worker Ollama |
| `python -m app health` | healthcheck |
| `python -m app jobs cleanup` | удаление старых `output/jobs/*` |

### 7.3. Docker Compose (целевой)

```yaml
services:
  redis:
    image: redis:7-alpine
    volumes: [redis_data:/data]

  bot:
    build: .
    command: python -m app bot
    env_file: .env
    depends_on: [redis]
    volumes: [./output:/app/output]

  worker-transcript:
    build: .
    command: python -m app worker transcript
    env_file: .env
    depends_on: [redis]
    deploy:
      replicas: 1   # = MAX_CONCURRENT_JOBS на 4GB VPS

  worker-summary:
    build: .
    command: python -m app worker summary
    env_file: .env
    depends_on: [redis]
    deploy:
      replicas: 1   # = MAX_CONCURRENT_SUMMARIES

  ollama:
    image: ollama/ollama
    volumes: [ollama:/root/.ollama]
    # optional — может быть на host
```

Файлы: `Dockerfile`, `docker-compose.yml`, `.env.example` (дополнить REDIS_*, MAX_*).

---

## 8. План реализации (этапы — код только после согласования ТЗ)

| # | Этап | Содержание | Оценка |
|---|------|------------|--------|
| **0** | Согласование | это ТЗ, профиль 4 GB | — |
| **1** | Job model + Redis store | `app/jobs/*`, тесты с fakeredis | 6 ч |
| **2** | RQ tasks | `transcript_task`, `summary_task`, перенос pipeline | 8 ч |
| **3** | Workers CLI | `worker transcript/summary`, signals, timeout | 4 ч |
| **4** | Bot refactor | handlers → enqueue; убрать `to_thread` pipeline | 6 ч |
| **5** | Notify layer | pub/sub, статусы, кнопка theses по UUID | 4 ч |
| **6** | ENV limits | config, STT workers fix, queue size | 3 ч |
| **7** | Logging + health | JSON logs, `app health` | 3 ч |
| **8** | Docker | Dockerfile, compose, README deploy | 4 ч |
| **9** | Tests | unit + integration (fakeredis, mock RQ) | 8 ч |
| **10** | Приёмка на 2c/4GB | load test 3 users, queue | 4 ч |
| | **Итого** | | **~50 ч** |

**Порядок:** 1 → 2 → 3 → 4 → 5 → 6 параллельно с 7 → 8 → 9 → 10.

**Не трогать в этапе 1–4:** CLI `extract-audio`, `transcribe`, `summarize`, `process` (offline).

---

## 9. Поведение при параллельных пользователях (4 GB VPS)

| Ситуация | Поведение |
|----------|-----------|
| User A STT running, User B sends file | B → `queued`, позиция 1 |
| Queue length 5, User F sends | отказ `MAX_QUEUE_SIZE` |
| User A done, User B next | worker забирает B из очереди |
| A нажал «тезисы», B в STT | summary queue ждёт (1 summary worker); STT не стартует summary параллельно на том же worker |
| 2 summary requests | второй в очереди `summary` |

---

## 10. Критерии приёмки (DoD)

### A — очередь

- [ ] 3 пользователя отправляют файл → 1 processing, 2 queued (на 4 GB, `MAX_CONCURRENT_JOBS=1`).
- [ ] Пользователь видит «В очереди, позиция N».
- [ ] `MAX_QUEUE_SIZE` — отказ с понятным текстом.

### B — workers

- [ ] Bot process не импортирует/не грузит Whisper model.
- [ ] `MAX_STT_WORKERS_PER_JOB=1` — в логах worker 1 процесс STT.
- [ ] `MAX_CONCURRENT_SUMMARIES=1` — два summary не идут параллельно.

### C — изоляция

- [ ] Каждый job — каталог `output/jobs/{uuid}/`.
- [ ] Cleanup удаляет каталог старше TTL.

### D — устойчивость

- [ ] Kill worker mid-job → status `failed`, retry, bot жив.
- [ ] Restart bot → активные jobs продолжают отображаться в `/status`.

### E — Docker

- [ ] `docker compose up` на 2c/4GB VPS поднимает redis + bot + 2 workers.
- [ ] `python -m app health` exit 0 в контейнере bot.

### F — регрессия

- [ ] `pytest tests/` — зелёный;
- [ ] CLI этапов 1–3 без изменений поведения.

---

## 11. Риски

| Риск | Митигация |
|------|-----------|
| OOM на 4 GB при `MAX_CONCURRENT_JOBS>1` | default profile 1/1/1 |
| RQ job lost при Redis без AOF | Redis volume + AOF v1.1 |
| Длинный STT блокирует очередь | expected; масштаб RAM/CPU |
| Telegram 20 MB | без изменений (ТЗ-06 URL) |
| Duplicate theses (3B LLM) | вне scope; dedup v1.1 |

---

## 12. Вне scope (ТЗ-05)

- Kubernetes, horizontal multi-node;
- PostgreSQL job history;
- Webhook Telegram (можно v1.1);
- URL download → **ТЗ-06**;
- GPU STT;
- Billing / multi-tenant admin UI.

---

## 13. Следующий шаг

1. **Согласовать** это ТЗ (особенно профиль 4 GB и RQ).
2. **Реализация** по п. 8 (этапы 1–10).
3. **ТЗ-06:** загрузка по URL.
4. **ТЗ-07:** единый `install.sh` / systemd без Docker (опционально).

---

## Согласование

| Роль | Статус |
|------|--------|
| Заказчик | |
| Исполнитель | Черновик v1.0 |
