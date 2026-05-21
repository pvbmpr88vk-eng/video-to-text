# ТЗ-08: Подготовка к деплою в Docker

**Проект:** video-to-text  
**Этап:** 8 (production deploy)  
**Архитектура:** монолит (Python) + Redis/RQ + Docker Compose на VPS  
**Зависит от:** [ТЗ-05](TZ-05-parallel-backend.md), [ТЗ-04](TZ-04-telegram-bot.md), [ТЗ-06](TZ-06-url-download.md)  
**Связано с:** [ТЗ-07](TZ-07-speed-profiles.md) (профили ENV на VPS)  
**Версия ТЗ:** 1.0  
**Дата:** 2026-05-21  

---

## 1. Цель этапа

Подготовить **повторяемый production-деплой** всего стека Telegram-бота в **Docker** на Linux VPS:

- один `docker compose up` поднимает Redis, bot, workers;
- секреты и лимиты — через `.env`, без правок образа;
- артефакты и модели переживают перезапуск контейнеров;
- документированы профили **4 GB** и **8 GB** RAM, проверка приёмки и runbook.

**Не в scope v1:** Kubernetes, Helm, Terraform, CI/CD в облако (описать как v1.1), systemd без Docker.

**Код пишется после согласования ТЗ** (часть файлов уже есть — см. п. 2.2).

---

## 2. Контекст

### 2.1. Цепочка в контейнерах

```
[Telegram] → bot (polling, yt-dlp download)
                ↓ enqueue
            Redis (RQ)
         ↙              ↘
worker-transcript    worker-summary
  FFmpeg + Whisper      Ollama HTTP
         ↓                    ↓
    output/jobs/         output/jobs/
    + transcripts        + summaries
```

### 2.2. As-is (уже в репозитории)

| Артефакт | Состояние |
|----------|-----------|
| `Dockerfile` | Python 3.12-slim, FFmpeg, `pip install`, **без** yt-dlp cookies, без pre-pull Whisper |
| `docker-compose.yml` | redis + bot + worker-transcript + worker-summary |
| `app health` | Redis, FFmpeg, yt-dlp; Ollama опционально (`--skip-ollama`) |
| Workers | `SimpleWorker` на macOS, **`Worker` (fork)** на Linux — важно для Docker |
| README | краткая секция `docker compose up` |

### 2.3. Gaps (что доделать по этому ТЗ)

| # | Пробел | Риск |
|---|--------|------|
| 1 | Ollama только через `host.docker.internal` | на чистом Linux VPS summary **не работает** без Ollama на хосте |
| 2 | Нет сервиса `ollama` в compose (опционального) | непредсказуемый деплой |
| 3 | Whisper-кэш не в volume | каждый rebuild → долгая первая STT |
| 4 | `health` у transcript/bot без проверки Ollama, у summary — без полной проверки STT | ложный healthy |
| 5 | Нет `.env.docker.example` / профилей 4G vs 8G | OOM на 4 GB |
| 6 | Нет `docker-compose.prod.yml` override | сложно отделить dev/prod |
| 7 | Нет скрипта `scripts/deploy-check.sh` | ручная приёмка |
| 8 | Нет non-root user в образе | безопасность VPS |
| 9 | `LOG_FORMAT=json` не задокументирован для prod | слабый observability |
| 10 | Нет cron/cleanup job для `output/jobs` | диск забивается |
| 11 | ТЗ-07 `SPEED_PROFILE` не в коде | только ручные ENV |

---

## 3. Целевая архитектура

### 3.1. Сервисы Compose (production)

| Сервис | Образ | Роль | Обязателен |
|--------|-------|------|------------|
| `redis` | `redis:7-alpine` | очередь RQ, job state | да |
| `bot` | build `.` | Telegram polling, URL download | да |
| `worker-transcript` | build `.` | extract + STT | да |
| `worker-summary` | build `.` | Ollama summarize | да |
| `ollama` | `ollama/ollama` | LLM inference | **рекомендуется на VPS** |

**Решение по Ollama (выбрать один режим при деплое):**

| Режим | `OLLAMA_HOST` | Когда |
|-------|---------------|--------|
| **A — Ollama в Compose** | `http://ollama:11434` | VPS ≥ 8 GB, всё в Docker |
| **B — Ollama на хосте** | `http://host.docker.internal:11434` + `extra_hosts` | 4 GB, экономия RAM в контейнерах |
| **C — внешний Ollama** | URL в `.env` | отдельная машина с GPU |

ТЗ-08 v1: реализовать **режим A** в `docker-compose.yml` (опциональный profile `with-ollama`) и документировать **B** для 4 GB.

### 3.2. Сеть

```
bot ──► redis:6379
worker-transcript ──► redis:6379
worker-summary ──► redis:6379
worker-summary ──► ollama:11434   (режим A)
bot ──► api.telegram.org (HTTPS egress)
bot ──► youtube / CDN (yt-dlp egress)
```

**Не публиковать** Redis и Ollama наружу — только internal network Compose.

### 3.3. Тома (volumes)

| Mount | Сервисы | Назначение |
|-------|---------|------------|
| `./output:/app/output` | bot, workers | inbox, jobs, transcripts, summaries |
| `redis_data:/data` | redis | персистентность очереди |
| `whisper_cache:/root/.cache/huggingface` | worker-transcript | кэш faster-whisper (~500 MB `small`) |
| `ollama_data:/root/.ollama` | ollama | модели LLM |
| `./telegram-bot.access.txt:ro` | bot | токен (альтернатива env) |

Опционально: `./secrets/yt_cookies.txt:ro` для `YT_DLP_COOKIES_FILE`.

---

## 4. Профили VPS и ENV

### 4.1. Профиль **minimal** (2 vCPU, 4 GB RAM)

Целевой из [ТЗ-05](TZ-05-parallel-backend.md).

```env
MAX_CONCURRENT_JOBS=1
MAX_STT_WORKERS_PER_JOB=1
MAX_CONCURRENT_SUMMARIES=1
MAX_QUEUE_SIZE=3
WHISPER_MODEL=small
OLLAMA_MODEL=qwen2.5:3b-instruct
OLLAMA_NUM_CTX=6144
LOG_FORMAT=json
```

| Правило | Обоснование |
|---------|-------------|
| 1 transcript worker | Whisper `small` ~2 GB + FFmpeg |
| Ollama на **хосте** (режим B) или 1.5b в контейнере | 3B + STT одновременно → OOM |
| `MAX_STT_WORKERS_PER_JOB=1` | на 4 GB без запаса |
| Не запускать STT и тяжёлый summary параллельно на одной машине | уже лимит RQ |

### 4.2. Профиль **standard** (4 vCPU, 8 GB RAM)

```env
MAX_CONCURRENT_JOBS=1
MAX_STT_WORKERS_PER_JOB=2
MAX_CONCURRENT_SUMMARIES=1
MAX_QUEUE_SIZE=5
WHISPER_MODEL=small
OLLAMA_MODEL=qwen2.5:3b-instruct
OLLAMA_NUM_CTX=8192
LOG_FORMAT=json
```

| Возможность | Условие |
|-------------|---------|
| `ollama` в Compose (режим A) | 8 GB |
| Параллельные чанки STT (`workers=2`) | только Linux worker (`Worker`, не `SimpleWorker`) |
| [ТЗ-07](TZ-07-speed-profiles.md) `SPEED_PROFILE=fast` | после реализации в коде |

### 4.3. Файлы конфигурации (deliverables)

| Файл | Назначение |
|------|------------|
| `.env.example` | общий шаблон (уже есть) |
| `.env.docker.example` | **новый**: значения для Compose (`REDIS_URL=redis://redis:6379/0`) |
| `deploy/env/minimal-4gb.env` | снимок профиля 4 GB |
| `deploy/env/standard-8gb.env` | снимок профиля 8 GB |

---

## 5. Dockerfile

### 5.1. Требования к образу приложения

| # | Требование |
|---|------------|
| 1 | Base: `python:3.12-slim` (или bookworm) |
| 2 | Системные пакеты: `ffmpeg`, `ca-certificates`, при необходимости `curl` |
| 3 | `pip install -r requirements.txt` (включая `yt-dlp`, `faster-whisper`, `rq`, `redis`) |
| 4 | `COPY app`, `COPY docs` (опционально `scripts/` для health/deploy) |
| 5 | `ENV PYTHONUNBUFFERED=1`, `PYTHONPATH=/app` |
| 6 | Пользователь **не root** (`appuser`, uid 1000) — v1 |
| 7 | `VOLUME /app/output` |
| 8 | Не класть секреты в образ |
| 9 | `.dockerignore`: `.venv`, `output/`, `.git`, `__pycache__`, `*.pyc` |

### 5.2. Опционально (v1.1)

- multi-stage для уменьшения слоя;
- `ARG` для pre-download Whisper `small` на build (увеличивает образ, ускоряет первый STT);
- отдельный образ `worker-transcript-heavy` только при необходимости.

### 5.3. Размер образа (ориентир)

| Компонент | RAM runtime | Диск образа |
|-----------|-------------|-------------|
| app slim + deps | — | ~800 MB – 1.2 GB |
| Whisper `small` cache (volume) | ~2 GB | ~500 MB |
| Ollama `qwen2.5:3b` (volume) | ~3 GB | ~2 GB |

---

## 6. Docker Compose

### 6.1. Базовый `docker-compose.yml` (целевое состояние v1)

Доработать существующий файл:

| Сервис | Изменения |
|--------|-----------|
| `redis` | без изменений; `restart: unless-stopped` |
| `bot` | `depends_on` redis healthy; volume output + access file |
| `worker-transcript` | volume `whisper_cache`; health: Redis + FFmpeg + yt-dlp |
| `worker-summary` | `OLLAMA_HOST` из env; depends_on ollama (profile) или host |
| `ollama` | **добавить** с `profiles: [with-ollama]` |

### 6.2. `docker-compose.prod.yml` (override)

| Параметр | Значение |
|----------|----------|
| `logging` driver | `json-file`, `max-size: 10m`, `max-file: 3` |
| `restart` | `unless-stopped` |
| env | `LOG_FORMAT=json`, `LOG_LEVEL=INFO` |
| bot | без publish портов |
| resources | `deploy.resources.limits` memory (опционально compose v3) |

Запуск:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile with-ollama up -d --build
```

### 6.3. Dev override `docker-compose.dev.yml`

| Параметр | Значение |
|----------|----------|
| mount | исходники read-only для отладки (опционально) |
| `OLLAMA_HOST` | `host.docker.internal` для Mac Desktop |
| без profile ollama | Ollama с хоста разработчика |

### 6.4. Healthcheck по сервисам

| Сервис | Команда | Интервал |
|--------|---------|----------|
| `redis` | `redis-cli ping` | 10s |
| `bot` | `python -m app health --skip-ollama` | 30s |
| `worker-transcript` | `python -m app health --skip-ollama` | 30s |
| `worker-summary` | `python -m app health` (с Ollama) | 60s |
| `ollama` | `curl -f http://localhost:11434/api/tags` | 30s |

**FR:** worker-summary не помечается healthy, если Ollama не отвечает.

### 6.5. Порядок старта

```
redis (healthy) → ollama (healthy, if profile) → workers + bot
```

При первом деплое: **до** приёмки выполнить pull моделей (п. 7.3).

---

## 7. Секреты и первый запуск

### 7.1. Секреты (не в git)

| Секрет | Способ |
|--------|--------|
| `TELEGRAM_BOT_TOKEN` | `.env` или `telegram-bot.access.txt` |
| `TELEGRAM_ALLOWED_USER_IDS` | `.env` |
| `HF_TOKEN` | опционально, ускорение загрузки Whisper |
| `YT_DLP_COOKIES_FILE` | mount cookies для YouTube 403 |

**NFR:** `.env` в `.gitignore`; в CI — secrets store.

### 7.2. Чеклист первого деплоя на VPS

1. Ubuntu 22.04+ / Debian 12+, Docker Engine 24+, Compose v2.
2. Клонировать репозиторий, `cp .env.docker.example .env`.
3. Заполнить Telegram + `REDIS_URL=redis://redis:6379/0`.
4. Выбрать профиль RAM (п. 4.1 / 4.2).
5. `docker compose build`.
6. Поднять Redis: `docker compose up -d redis`.
7. Pull Ollama: `docker compose run --rm ollama ollama pull qwen2.5:3b-instruct` (или `./scripts/pull-summary-model.sh` на хосте в режиме B).
8. Первый STT прогреет Whisper cache (или pre-download в документации).
9. `docker compose up -d`.
10. `./scripts/deploy-check.sh` → exit 0.
11. Отправить тестовый файл в бот.

### 7.3. Скрипт `scripts/deploy-check.sh` (новый)

Проверяет:

- `docker compose ps` — все сервисы running/healthy;
- `docker compose exec bot python -m app health --skip-ollama`;
- `docker compose exec worker-summary python -m app health`;
- `redis-cli ping` внутри redis;
- опционально: наличие модели Ollama в tags.

Exit **0** / **1** для автоматизации.

### 7.4. Обслуживание

| Задача | Команда / периодичность |
|--------|-------------------------|
| Логи | `docker compose logs -f bot worker-transcript worker-summary` |
| Сброс зависших jobs | `docker compose exec bot python -m app jobs reset-stuck` |
| Очистка диска | cron: `docker compose exec bot python -m app jobs cleanup` |
| Обновление | `git pull && docker compose up -d --build` |
| Rollback | предыдущий image tag / `docker compose down` + backup `output/` |

---

## 8. Отличия Docker (Linux) vs локальный macOS

| Аспект | macOS (dev) | Docker Linux (prod) |
|--------|-------------|---------------------|
| RQ worker class | `SimpleWorker` | `Worker` (fork OK) |
| `MAX_STT_WORKERS_PER_JOB` | принудительно ≤ 1 | до 2–4 по CPU/RAM |
| `OBJC_DISABLE_INITIALIZE_FORK_SAFETY` | да | не нужен |
| Ollama | localhost | service `ollama` или host |
| Параллельный STT | выключен | включить на 8 GB |

**FR:** в Docker **не** полагаться на `scripts/start-stack.sh` (brew redis) — только Compose.

---

## 9. Функциональные требования (FR)

| ID | Требование |
|----|------------|
| FR-01 | `docker compose up -d --build` поднимает минимум redis + bot + 2 workers без ручных шагов после `.env` |
| FR-02 | Bot принимает файл и ставит job; worker-transcript завершает STT; пользователь получает `.txt` |
| FR-03 | Кнопка «Сделать тезисы»; worker-summary завершает job; тезисы в чат |
| FR-04 | URL в чате скачивается (yt-dlp в образе bot) |
| FR-05 | Рестарт контейнера **не** теряет Redis job metadata (`redis_data` volume) |
| FR-06 | Рестарт не удаляет готовые транскрипты в `./output` |
| FR-07 | Healthcheck failed → compose показывает unhealthy (restart policy) |
| FR-08 | Режим A: summary worker достучится до `ollama:11434` без `host.docker.internal` |
| FR-09 | Документированы 4 GB и 8 GB профили с ожидаемым поведением очереди |
| FR-10 | `deploy-check.sh` автоматизирует smoke после деплоя |

---

## 10. Нефункциональные требования (NFR)

| ID | Требование |
|----|------------|
| NFR-01 | Время cold start bot &lt; 30 s (без загрузки Whisper) |
| NFR-02 | Whisper грузится только в worker-transcript, не в bot |
| NFR-03 | Образ app не содержит токенов |
| NFR-04 | Логи в prod: `LOG_FORMAT=json` |
| NFR-05 | Один VPS 4 GB: пик RAM &lt; 90% при 1 STT + 0 summary |
| NFR-06 | Диск: документирован TTL cleanup (`JOB_CLEANUP_TTL_HOURS`) |
| NFR-07 | Egress только HTTPS (Telegram, HF, Ollama, yt-dlp CDN) |

---

## 11. Безопасность

| # | Мера |
|---|------|
| 1 | Redis без publish на `0.0.0.0` |
| 2 | Ollama без publish наружу (только internal network) |
| 3 | `TELEGRAM_ALLOWED_USER_IDS` обязателен в prod |
| 4 | Non-root user в контейнере app |
| 5 | Read-only mount для cookies и access file |
| 6 | Регулярные обновления base image (`python:3.12-slim`) |

---

## 12. CI/CD (v1.1, описание в ТЗ)

| Шаг | Действие |
|-----|----------|
| 1 | `pytest -m 'not integration'` на push |
| 2 | `docker build -t video-to-text:${{ sha }}` |
| 3 | push в registry (GHCR) |
| 4 | на VPS: `docker compose pull && up -d` |

Не блокирует v1 приёмку на одном VPS.

---

## 13. План реализации (после согласования ТЗ)

| # | Задача | Файлы | Оценка |
|---|--------|-------|--------|
| 1 | `.dockerignore`, non-root в Dockerfile | `Dockerfile`, `.dockerignore` | 2 ч |
| 2 | Volume whisper_cache, правки health | `docker-compose.yml` | 2 ч |
| 3 | Сервис `ollama` + profile `with-ollama` | `docker-compose.yml` | 2 ч |
| 4 | `docker-compose.prod.yml`, `docker-compose.dev.yml` | `deploy/` | 2 ч |
| 5 | `.env.docker.example`, `deploy/env/*.env` | env templates | 1 ч |
| 6 | `scripts/deploy-check.sh`, `scripts/docker-pull-models.sh` | scripts | 2 ч |
| 7 | README: раздел «Деплой на VPS» | `README.md` | 2 ч |
| 8 | Приёмка на 4 GB VPS (или Docker Desktop с лимитом) | — | 4 ч |
| 9 | Опционально: cron doc + `jobs cleanup` в compose | docs | 1 ч |
| | **Итого** | | **~18 ч** |

**Порядок:** 1 → 2 → 3 → 5 → 6 → 4 → 7 → 8.

---

## 14. Критерии приёмки

### 14.1. Docker

- [ ] `docker compose config` без ошибок (с profile и без).
- [ ] `docker compose up -d --build` — все сервисы `running`, health `healthy` в течение 5 мин после pull моделей.
- [ ] `deploy-check.sh` → exit 0.

### 14.2. Функционал

- [ ] Файл 1–3 мин → транскрипт в чат.
- [ ] «Сделать тезисы» → тезисы в чат (qwen2.5:3b).
- [ ] Ссылка YouTube (короткая) → транскрипт (при рабочем yt-dlp).
- [ ] Рестарт `docker compose restart bot` — бот снова отвечает, очередь не «ломается».

### 14.3. Ресурсы

- [ ] Профиль 4 GB: без OOM при одной STT-задаче.
- [ ] Профиль 8 GB (режим A): STT + summary последовательно от двух пользователей — очередь работает.

### 14.4. Документация

- [ ] README ссылается на ТЗ-08.
- [ ] Runbook: первый деплой, обновление, rollback, cleanup.

---

## 15. Риски и митигация

| Риск | Митигация |
|------|-----------|
| OOM на 4 GB | профиль minimal; Ollama на хосте; `MAX_*=1` |
| Whisper долгая первая загрузка | volume `whisper_cache`; README |
| YouTube 403 | cookies volume; [ТЗ-06](TZ-06-url-download.md) |
| Зависший summary блокирует очередь | [reset-stuck](TZ-05-parallel-backend.md); код defer concurrency (уже в main) |
| Диск full | `jobs cleanup` + TTL |
| Telegram 409 (два bot) | один replica bot, документация |

---

## 16. Связь с другими ТЗ

| ТЗ | Связь |
|----|-------|
| [ТЗ-05](TZ-05-parallel-backend.md) | архитектура очереди, лимиты, compose-скелет |
| [ТЗ-04](TZ-04-telegram-bot.md) | bot process, секреты, UX |
| [ТЗ-06](TZ-06-url-download.md) | yt-dlp в образе bot |
| [ТЗ-03](TZ-03-summary.md) | Ollama, pull модели |
| [ТЗ-02](TZ-02-stt.md) | Whisper, RAM |
| [ТЗ-07](TZ-07-speed-profiles.md) | ENV-профили на VPS после реализации |

---

## 17. Открытые вопросы (на согласование)

| # | Вопрос | Варианты по умолчанию |
|---|--------|------------------------|
| 1 | Ollama в Compose или на хосте для v1? | 8 GB → в Compose; 4 GB → на хосте |
| 2 | Pre-pull Whisper в Dockerfile? | нет (volume при runtime) |
| 3 | Отдельный контейнер `worker-cleanup` cron? | v1.1; v1 — cron на хосте |
| 4 | Публиковать ли метрики (Prometheus)? | вне scope v1 |

---

**Статус:** v1 реализован для профиля **2 vCPU / 4 GB** (`deploy/env/minimal-4gb.env`, `docker-compose.prod.yml`, `scripts/deploy-check.sh`). Ollama — на хосте; profile `with-ollama` только для ≥8 GB.
