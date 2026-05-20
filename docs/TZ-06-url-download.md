# ТЗ-06: Загрузка медиа по URL (Telegram + yt-dlp)

**Проект:** video-to-text  
**Этап:** 6 из 7  
**Архитектура:** монолит (Python) + Redis/RQ ([ТЗ-05](TZ-05-parallel-backend.md))  
**Зависит от:** [ТЗ-04](TZ-04-telegram-bot.md), [ТЗ-05](TZ-05-parallel-backend.md)  
**Версия ТЗ:** 1.0  
**Дата:** 2026-05-20  

---

## 1. Цель

Разрешить пользователю отправить в Telegram-бот **текст со ссылкой** на видео/аудио (YouTube и другие источники, поддерживаемые [yt-dlp](https://github.com/yt-dlp/yt-dlp)), обойти лимит **20 MB** Bot API и получить тот же результат, что при загрузке файла:

```
[Ссылка в чате] → скачивание (бот) → [ТЗ-05 очередь] → extract → STT → .txt → [кнопка «Сделать тезисы»]
```

Скачивание выполняется **в процессе бота** (`asyncio.to_thread`), далее — существующий `transcript` job в Redis/RQ без изменений worker-логики.

---

## 2. Контекст

### 2.1. До ТЗ-06 (ТЗ-04 v2)

- Текст с `https://…` → сообщение «Ссылки не поддерживаются».
- Файлы только до 20 MB (лимит Telegram Bot API).

### 2.2. После ТЗ-06

```
Пользователь → on_text_url → extract_url()
                    │
                    ▼
            download_media_url()  (yt-dlp, в thread)
                    │
                    ▼
         output/jobs/{uuid}/inbox/{id}.ext
                    │
                    ▼
         enqueue_transcript() → worker (ТЗ-05)
```

---

## 3. Границы scope

### В scope (v1)

| # | Требование |
|---|------------|
| 1 | Распознавание первой `http(s)` ссылки в текстовом сообщении |
| 2 | Скачивание через **yt-dlp** в `output/jobs/{job_id}/inbox/` |
| 3 | Лимит размера на сервере: `URL_DOWNLOAD_MAX_BYTES` (по умолчанию **500 MB**) |
| 4 | Таймаут сокета yt-dlp: `URL_DOWNLOAD_TIMEOUT_SEC` (по умолчанию **600 с**) |
| 5 | `noplaylist: true` — только одно видео, не весь плейлист |
| 6 | Те же проверки, что для файла: whitelist, rate limit, `MAX_QUEUE_SIZE` |
| 7 | Статусы job: `downloading` → `queued` → worker (`extract` → `stt` → `done`) |
| 8 | Ошибки скачивания → `failed`, сообщение пользователю |
| 9 | Зависимость `yt-dlp` в `requirements.txt` |
| 10 | Unit-тесты: `extract_url`, mock `YoutubeDL` |
| 11 | README + `.env.example` |

### Вне scope (v1)

| # | Исключение | Когда |
|---|------------|--------|
| 1 | Google Drive (приватные ссылки, OAuth) | v1.1 |
| 2 | Отдельная очередь RQ только для URL | не требуется |
| 3 | Прогресс % скачивания yt-dlp в чат | v1.1 |
| 4 | Поддержка нескольких ссылок в одном сообщении | только **первая** |
| 5 | Скачивание URL в CLI | только Telegram |

### Поддерживаемые источники (best-effort)

Всё, что поддерживает установленная версия **yt-dlp** (YouTube, Vimeo, прямые `.mp4`/`.m3u8` и т.д.). Гарантия только для **публичных** ссылок без DRM.

---

## 4. Конфигурация (ENV)

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `URL_DOWNLOAD_MAX_BYTES` | `524288000` (500 MB) | Макс. размер файла после скачивания |
| `URL_DOWNLOAD_TIMEOUT_SEC` | `600` | Таймаут сокета yt-dlp |

Файл: `app/config.py`. Пример: `.env.example`.

**Не путать** с `TELEGRAM_BOT_FILE_SIZE_LIMIT` (20 MB) — он только для файлов из Telegram.

---

## 5. Функциональные требования

### FR-01. Извлечение URL

- Модуль: `app/download/url.py`, функция `extract_url(text)`.
- Regex: `https?://[^\s<>"']+`, обрезка хвостовой пунктуации `.,);]}`.
- Нет URL → handler молчит (не спамит пользователя обычным текстом).

### FR-02. Скачивание

- Функция `download_media_url(url, dest_dir, *, max_bytes, timeout_sec) → Path`.
- Формат yt-dlp: `bestaudio/best/b` (аудио приоритетно, иначе лучший поток).
- После скачивания — проверка размера на диске; при превышении — удалить файл и `UrlDownloadError`.
- Исключение `UrlDownloadError` — единый тип для handler.

### FR-03. Handler `on_text_url`

- Файл: `app/telegram/handlers.py`.
- Порядок проверок: `_guard_access` → rate limit → `queue_full` → create job → `DOWNLOADING` → `asyncio.to_thread(download)` → `QUEUED` + `inbox_path` → `enqueue_transcript`.
- Сообщения: `M.URL_DOWNLOADING`, `M.QUEUE_POSITION`, `M.URL_DOWNLOAD_FAILED`.
- При ошибке — обновить status message (не оставлять «Скачиваю…»).

### FR-04. Интеграция с ТЗ-05

- Контракт worker **не меняется**: `inbox_path` указывает на скачанный файл в `output/jobs/{uuid}/inbox/`.
- Pub/sub notify — ошибки `url_download:…` в `notify._error_message`.

### FR-05. Зависимости и health

- `pip install yt-dlp` (диапазон в `requirements.txt`).
- `python -m app health` — проверка импорта `yt_dlp` (предупреждение/ошибка если нет).

### FR-06. Документация

- README: раздел «Этап 6».
- `/help` и `/start`: упоминание ссылок.

---

## 6. Структура кода

```
app/download/
  __init__.py
  url.py              # extract_url, download_media_url, UrlDownloadError

app/telegram/handlers.py   # on_text_url
app/telegram/messages.py   # URL_DOWNLOADING, URL_DOWNLOAD_FAILED
app/telegram/notify.py     # _error_message: url_download:

tests/test_url_download.py
```

---

## 7. Сообщения пользователю (RU)

| Ситуация | Текст |
|----------|--------|
| Начало скачивания | «Скачиваю по ссылке (может занять несколько минут)…» |
| Успех | «В очереди (позиция N)…» (как для файла) |
| Ошибка yt-dlp | «Не удалось скачать по ссылке: {detail}» |
| Нет доступа / очередь / rate limit | как в ТЗ-04 |

---

## 8. Обработка ошибок

| Код / префикс | Причина |
|---------------|---------|
| `url_download:…` | yt-dlp, сеть, лимит размера, нет файла |
| `file_too_large` | только Telegram upload (20 MB) |
| `no_audio` | worker: нет звука в скачанном файле |

Job status: `failed`, `error` в Redis.

---

## 9. Тестирование

| Тест | Файл |
|------|------|
| `extract_url` — youtube, trim punctuation, no url | `tests/test_url_download.py` |
| `download_media_url` — mock YoutubeDL success | там же |
| `download_media_url` — file too large, удаление | там же |
| Регрессия telegram auth/credentials | `tests/test_telegram_bot.py` |

CI: без сети и без реального yt-dlp download.

---

## 10. Критерии приёмки (DoD)

### A — функциональность

- [x] Текст с YouTube-ссылкой создаёт transcript job и ставит в очередь.
- [x] Скачанный файл лежит в `output/jobs/{uuid}/inbox/`.
- [x] Worker выполняет extract → STT → `.txt` в чат (как для файла).
- [x] Кнопка «Сделать тезисы» работает после transcript job.
- [ ] Ручная проверка: реальная YouTube-ссылка на коротком ролике (<5 мин).

### B — лимиты и безопасность

- [x] Whitelist `ALLOWED_USER_IDS` применяется к URL-сообщениям.
- [x] Rate limit 10 медиа/час учитывает URL как медиа-запрос.
- [x] `MAX_QUEUE_SIZE` — отказ до скачивания.
- [x] Файл > `URL_DOWNLOAD_MAX_BYTES` → ошибка, файл удаляется.
- [x] `noplaylist` — не качает весь плейлист.

### C — ошибки

- [x] Нет yt-dlp → понятная ошибка при скачивании.
- [x] Сбой yt-dlp → `failed` + сообщение в чат.
- [x] Status message обновляется при ошибке (не зависает на «Скачиваю…»).

### D — регрессия

- [x] Загрузка файла ≤20 MB в Telegram — без изменений.
- [x] `pytest tests/test_url_download.py` — зелёный.
- [x] CLI `extract-audio`, `transcribe`, `summarize` — без изменений.

### E — документация

- [x] `docs/TZ-06-url-download.md` (этот файл).
- [x] README: этап 6, yt-dlp, ENV.
- [x] `.env.example`: `URL_DOWNLOAD_*`.

---

## 11. Риски

| Риск | Митигация |
|------|-----------|
| YouTube меняет разметку | обновление yt-dlp |
| Долгое скачивание блокирует thread pool бота | один URL на пользователя; rate limit |
| OOM на 4 GB VPS при 500 MB файле | снизить `URL_DOWNLOAD_MAX_BYTES` |
| DRM / приватное видео | сообщение об ошибке yt-dlp |

---

## 12. Следующий шаг

**ТЗ-07:** деплой без Docker (systemd/launchd, `install.sh`, healthcheck на VPS).

---

## Согласование

| Роль | Статус |
|------|--------|
| Заказчик | |
| Исполнитель | Реализация v1.0 в `main` (коммит TZ-06) |
