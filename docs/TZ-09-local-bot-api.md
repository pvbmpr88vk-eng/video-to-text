# ТЗ-09: Local Bot API Server в Docker

**Проект:** video-to-text  
**Этап:** 9 (файлы >20 MB через Telegram)  
**Зависит от:** [ТЗ-04](TZ-04-telegram-bot.md), [ТЗ-08](TZ-08-docker-deploy.md)  
**Версия ТЗ:** 1.0  
**Дата:** 2026-05-21  

---

## 1. Цель

Поднять **Telegram Local Bot API Server** в **отдельном контейнере** рядом с прод-стеком, чтобы бот мог принимать файлы **>20 MB** (до лимита Telegram ~2 GB), и **не раздувать диск** за счёт автоматической очистки кэша API.

**Не в scope v1:**

- Local Bot API на Mac без Docker (опционально вручную).
- Kubernetes.
- Дедупликация с `output/jobs` (достаточно TTL на оба каталога).

---

## 2. Контекст

### 2.1. Проблема

| Канал | Лимит сейчас | Причина |
|-------|----------------|---------|
| Файл в чат (облачный `api.telegram.org`) | 20 MB | лимит Bot API |
| Ссылка (yt-dlp) | 500 MB (`URL_DOWNLOAD_MAX_BYTES`) | скачивание на сервер |

Пользователи шлют **большие файлы** и **пересылки**; без Local API файл >20 MB не скачивается, даже если в коде лимит 500 MB.

### 2.2. Решение

```
[User] → Telegram DC
              ↓
    telegram-bot-api (контейнер, TDLib)
              ↓ HTTP :8081
         bot (python-telegram-bot, local_mode=True)
              ↓
         output/jobs/...  (+ JOB_CLEANUP_TTL_HOURS)
```

Отдельный контейнер **`telegram-bot-api`** + sidecar **`telegram-bot-api-cleanup`** (почасовая очистка файлов старше TTL).

---

## 3. Архитектура Compose

### 3.1. Сервисы (profile `with-local-bot-api`)

| Сервис | Образ | RAM (лимит prod) | Диск |
|--------|-------|------------------|------|
| `telegram-bot-api` | `aiogram/telegram-bot-api:latest` | 512 MB | volume `telegram_bot_api_data` |
| `telegram-bot-api-cleanup` | `alpine:3.20` | 64 MB | тот же volume (rw) |
| `bot` (override) | build `.` | без изменений | `TELEGRAM_BOT_API_BASE_URL`, volume API `:ro`, `group_add: 101` |

**Порты наружу не публиковать** — только сеть Compose.

**Docker:** `TELEGRAM_LOCAL=1` на `telegram-bot-api`; бот монтирует `telegram_bot_api_data` в `/var/lib/telegram-bot-api` и копирует файл по `file_path` (`app/telegram/download.py`). Без общего тома PTB пытается скачать с `api.telegram.org` → `InvalidToken: Not Found`.

### 3.2. Секреты (обязательны для Local API)

Из [my.telegram.org](https://my.telegram.org/apps):

| Переменная | Назначение |
|------------|------------|
| `TELEGRAM_API_ID` | numeric app id |
| `TELEGRAM_API_HASH` | app api hash |
| `TELEGRAM_BOT_TOKEN` | как сейчас (бот подключается к локальному API) |

В git **не коммитить** — только `.env` / `deploy/env/local-bot-api.env.example`.

### 3.3. Переменные приложения

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `TELEGRAM_BOT_API_BASE_URL` | пусто → облачный API | `http://telegram-bot-api:8081` в Docker |
| `TELEGRAM_LOCAL_MODE` | `true` если задан BASE_URL | `local_mode` в PTB |
| `TELEGRAM_BOT_FILE_SIZE_LIMIT` | 500 MB при Local API, иначе 20 MB | проверка до скачивания |
| `TELEGRAM_BOT_API_CACHE_TTL_HOURS` | `6` | возраст файлов в volume API до удаления |

### 3.4. Очистка диска (обязательно)

1. **Sidecar** `telegram-bot-api-cleanup`: каждый час  
   `find /data -type f -mmin +TTL*60 -delete` + пустые каталоги.
2. **`output/jobs`**: существующий `JOB_CLEANUP_TTL_HOURS` (24 h).
3. **Логи** compose: `max-size: 10m`, `max-file: 2` на сервисе API.
4. **Ручной прогон:** `./scripts/telegram-bot-api-cleanup.sh [hours]`.

**Ожидание по диску:** при TTL 6 h и 1 job ~300 MB — пик кэша API ~300–600 MB, не накопление месяцами.

### 3.5. Ресурсы VPS 4 GB

| Компонент | RAM |
|-----------|-----|
| Ollama qwen2.5 3b (хост) | ~2–3 GB |
| worker-transcript + Whisper | до 2.8 GB limit |
| telegram-bot-api | до 512 MB |
| bot + redis + summary | ~1 GB |

**Риск OOM** при одновременно: большой файл + STT + тезисы.  
**Митигация:** `MAX_CONCURRENT_JOBS=1` (уже есть), не качать второй файл пока идёт job.

**Рекомендация:** включать Local API на **6–8 GB** VPS или держать Ollama с урезанным `OLLAMA_NUM_CTX`.

---

## 4. Изменения в коде

| Файл | Изменение |
|------|-----------|
| `app/config.py` | `TELEGRAM_BOT_API_BASE_URL`, лимит файла при Local API |
| `app/telegram/bot.py` | `base_url` + `local_mode(True)` |
| `app/worker/health.py` | ping Local API если URL задан |
| `docker-compose.local-bot-api.yml` | сервисы + override bot |
| `scripts/telegram-bot-api-cleanup.sh` | ручная очистка volume |
| `scripts/deploy-check.sh` | проверка API при `TELEGRAM_BOT_API_BASE_URL` |

---

## 5. Запуск

### 5.1. Prod (VPS) — только после согласования деплоя

```bash
cp deploy/env/local-bot-api.env.example .env.local-bot-api
# дописать TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_BOT_TOKEN

set -a && source .env && source .env.local-bot-api && set +a

docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  -f docker-compose.local-bot-api.yml \
  --profile with-local-bot-api \
  up -d --build

./scripts/deploy-check.sh
```

### 5.2. Без Local API (как сейчас)

Не передавать overlay и profile — бот на `api.telegram.org`, лимит 20 MB.

### 5.3. Отключение

```bash
docker compose --profile with-local-bot-api down
# убрать TELEGRAM_BOT_API_BASE_URL из .env, restart bot
```

Опционально: `docker volume rm video-to-text_telegram_bot_api_data` — освободить диск.

---

## 6. Приёмка

| # | Критерий |
|---|----------|
| 1 | `telegram-bot-api` healthy, не в `ports:` на 0.0.0.0 |
| 2 | `bot` логирует `Using Local Bot API: http://telegram-bot-api:8081/bot` |
| 3 | Файл 25–50 MB (документ) → «Скачиваю файл…» → job в очереди |
| 4 | Через 7+ h в volume API нет файлов старше TTL (проверка `du` / find) |
| 5 | `python -m app health` в bot: Local Bot API OK |
| 6 | Без profile стек поднимается как TZ-08 |

---

## 7. Runbook

```bash
# Размер кэша API
docker compose ... exec telegram-bot-api du -sh /var/lib/telegram-bot-api

# Ручная очистка
./scripts/telegram-bot-api-cleanup.sh 6

# Логи
docker compose ... logs telegram-bot-api --tail 100
docker compose ... logs telegram-bot-api-cleanup --tail 20
```

---

## 8. Оценка

| Задача | Часы |
|--------|------|
| Compose + cleanup sidecar | 2 |
| Код bot + config + health | 1 |
| Документация + deploy-check | 1 |
| Приёмка на VPS | 1 |
| **Итого** | **~5** |

---

## 9. Кэш и нагрузка на сервер (варианты)

### 9.1. Как сейчас

| Место | Что хранится | Очистка |
|-------|----------------|---------|
| `telegram_bot_api_data` | Копия файла с DC Telegram (~255 MB) | Sidecar раз в **1 ч**, TTL **6 ч** |
| `output/jobs/<id>/inbox/` | Копия для воркера (та же сущность) | `JOB_CLEANUP_TTL_HOURS` **24 ч** |

Пик диска на один большой файл: **~2× размер** (кэш API + inbox), до **6 ч** на API-томе.  
CPU/RAM API: в основном пока TDLib качает файл с Telegram; после копирования в inbox сервис почти простаивает.

### 9.2. Варианты ускорить очистку кэша

| # | Подход | Плюсы | Риски / минусы |
|---|--------|-------|----------------|
| **A** | **Удалять файл в кэше сразу после успешного `copy` в inbox** | Минимум диска; безопасно при `MAX_CONCURRENT_JOBS=1`; не ждём час | Нужен **rw**-mount тома в `bot`; удалять только если `dest.stat().st_size == src` |
| **B** | Sidecar чаще: `sleep 900`, TTL **0.5–1 ч** | Только правка compose/env | Пик диска всё ещё 2× на время job; «осиротевшие» файлы до 1 ч |
| **C** | TTL **15–30 мин** + раз в 15 мин | Просто | При сбое до копирования повторная отправка — API снова качает с DC (нормально) |
| **D** | Ручной `./scripts/telegram-bot-api-cleanup.sh 0` | Экстренно освободить диск | Не автоматизация; можно снести файл **активного** job, если TTL=0 без проверки |
| **E** | Inbox на том же volume + **hardlink** вместо copy | Один физический файл на диске | Разные FS сейчас (`output` vs volume); смена layout |
| **F** | Только ссылки (yt-dlp), без Local API | Нет API-тома | Файлы в чат >20 MB снова недоступны |

**Не ломает**, если соблюдать порядок: **сначала** проверка размера inbox, **потом** `unlink` кэша; sidecar оставить как страховку для сбоев (не дошли до `QUEUED`).

### 9.3. Облегчить нагрузку от `telegram-bot-api`

| Мера | Эффект | Комментарий |
|------|--------|-------------|
| **A (удаление после copy)** | −диск, −дублирование I/O | Главный выигрыш на 4 GB VPS |
| `TELEGRAM_VERBOSITY=1` | Меньше логов на диск | Env в compose API |
| Лимит RAM **256–384 MB** (вместо 512) | Меньше давления на OOM | Следить после смены; при нехватке вернуть 512 |
| `MAX_CONCURRENT_JOBS=1` | Уже есть | Не качаем 2×255 MB параллельно |
| Не публиковать `:8081` наружу | Уже есть | Меньше поверхность атаки и случайного трафика |
| Короткий TTL + частый sidecar | Только диск | CPU API почти не снижает |
| Отключить profile без больших файлов | Нет контейнера API | Лимит 20 MB в чат |

Whisper + Ollama на VPS **тяжелее**, чем Bot API; оптимизация кэша — про **диск** и пики при приёме файла.

### 9.4. Рекомендуемый набор (prod 4 GB)

1. **Вариант A** — `unlink` кэша в `app/telegram/download.py` после успешного copy (mount `:rw`).
2. **Sidecar** — TTL **1 ч**, интервал **15 мин** (страховка «осиротевших» файлов).
3. **`TELEGRAM_VERBOSITY=1`** на `telegram-bot-api`.
4. **`JOB_CLEANUP_TTL_HOURS=24`** не трогать (inbox нужен воркеру).

Ожидаемый пик API-тома: **~0** после постановки job в очередь (вместо 255 MB × часы).

### 9.5. Пример env (после внедрения A)

```bash
TELEGRAM_BOT_API_CACHE_TTL_HOURS=1
TELEGRAM_VERBOSITY=1
# опционально в compose cleanup: sleep 900 вместо 3600
```

### 9.6. Проверка, что ничего не сломалось

```bash
du -sh /var/lib/telegram-bot-api   # в контейнере API
du -sh output/jobs                  # inbox
# после успешного приёма 255 MB: API-том ≈ десятки MB, inbox ≈ 255 MB
```

---

## 10. Статус реализации

| Артефакт | Статус |
|----------|--------|
| `docker-compose.local-bot-api.yml` | готово |
| `scripts/telegram-bot-api-cleanup.sh` | готово |
| `scripts/up-with-local-bot-api.sh` | готово |
| `scripts/lib/compose-args.sh` | готово |
| `deploy/env/local-bot-api.env.example` | готово |
| Код `bot.py` / `config.py` / `health.py` | готово |
| `tests/test_local_bot_api_config.py` | готово |
| `deploy-remote.sh` + `ENABLE_LOCAL_BOT_API=1` | готово |
| Деплой на VPS | **по запросу** (см. правило deploy-and-environments) |
| Удаление кэша сразу после copy (§9.4) | **не сделано** (рекомендация) |
