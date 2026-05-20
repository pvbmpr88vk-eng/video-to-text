# ТЗ-03: Саммари и тезисы по транскрипту (локальная LLM)

**Проект:** video-to-text  
**Этап:** 3 из 6  
**Архитектура:** монолит (Python)  
**Зависит от:** [ТЗ-02](TZ-02-stt.md) (`.txt` / `.json` транскрипта)  
**Версия ТЗ:** 2.0 (локальная LLM)  
**Дата:** 2026-05-19  

---

## 1. Цель этапа

Принять **текстовую транскрипцию** (результат этапа 2) и сформировать **структурированное саммари**: краткий пересказ, тезисы, опционально — действия и цитаты с таймкодами.

Обработка выполняется **локально** через **[Ollama](https://ollama.com)** и квантизованную instruct-модель — в одной линии с этапом 2 (STT на CPU / Apple Silicon без отдельной видеокарты): **данные не уходят в облако**, нет API-ключей и поминутной оплаты.

Этап **не включает:** Telegram-бот (ТЗ-04), загрузку по URL (ТЗ-05), повторное распознавание речи.

---

## 2. Контекст в общей цепочке

```
[Видео] → [ТЗ-01] → [WAV/MP3] → [ТЗ-02] → [.txt + .json] → [ТЗ-03: summarize] → [.summary.*]
                                                                              ↓
                                                                    [ТЗ-04: Telegram-бот]
```

**Входной контракт от ТЗ-02** (файл `.json`, приоритетный вход):

| Поле | Обязательно | Использование в ТЗ-03 |
|------|-------------|------------------------|
| `text` | да | основной вход для LLM |
| `language` | да | выбор языка промпта (`ru` / `en`) |
| `duration_sec` | да | предупреждение о длине, оценка времени |
| `segments[]` | желательно | разбиение на чанки, цитаты с таймкодами |
| `source_path` | да | трассировка в метаданных |
| `model` | да | в sidecar (модель STT) |
| `created_at` | да | lineage |

**Альтернативный вход:** только `.txt` (UTF-8).

**Референс-кейс:** `111_*.json` (~48 мин, **~42k символов**, `language=ru`) — осмысленное саммари на русском после map-reduce.

---

## 3. Границы scope

### В scope (v1)

- Локальный файл: `.json` или `.txt` из `output/transcripts/`.
- Рантайм: **Ollama** (демон на `localhost:11434`, HTTP API).
- Модель по умолчанию проекта: **`qwen2.5:3b-instruct`** (целевая машина **8 GB RAM**, см. п. 4.3).
- Скрипт `pull-summary-model.sh` скачивает **только эту одну** модель; запасные теги не тянутся автоматически.
- Конфигурация: `.env` / `config.py` (`OLLAMA_HOST`, `OLLAMA_MODEL`, `OLLAMA_NUM_CTX`, размер чанка).
- Промпты на **русском** (`language=ru`).
- Выход: `.summary.md`, `.theses.json`, `.meta.json` в `output/summaries/`.
- **Map-reduce** для длинных транскриптов (п. 4.4).
- CLI `summarize`, API `summarize_transcript()`.
- Проверка при старте: Ollama доступен, модель скачана (`ollama pull`).
- Скрипт `scripts/pull-summary-model.sh`.
- Тесты с **mock** HTTP-клиента Ollama (без реальной модели в CI).

### Вне scope (v2+)

- Облачный LLM (OpenAI и т.д.) — опциональный backend позже (`SUMMARY_PROVIDER=openai`).
- Telegram (ТЗ-04), URL (ТЗ-05), веб-UI, БД, очередь.
- Fine-tuning / LoRA под домен.
- Диаризация и разделение спикеров.
- Отдельная «вычитка» транскрипта без саммари.

### В scope v1.1

- `python -m app process VIDEO --summarize` (цепочка 1→2→3).
- Флаг `--style meeting|interview|lecture`.
- Кэш ответов по хэшу входного текста.
- Документация альтернатив (`7b`, Saiga) — только ручной `ollama pull` при ≥16 GB RAM, **не** в скриптах проекта.

---

## 4. Выбор локальной LLM (решение для проекта)

### 4.1. Критерии отбора

| Критерий | Вес | Комментарий |
|----------|-----|-------------|
| Качество **русского** саммари | высокий | созвоны, финансы, деловая лексика |
| Работа на **Mac без дискретной GPU** | высокий | Ollama + Metal на Apple Silicon |
| RAM **8–16 GB** | высокий | тот же класс машин, что и STT |
| **Instruct** + следование JSON | высокий | структурированный выход |
| Размер дистрибутива | средний | первый `ollama pull` |
| Скорость на длинном тексте | средний | компенсируется map-reduce |

### 4.2. Рантайм: Ollama

| Параметр | Значение |
|----------|----------|
| Установка macOS | `brew install ollama` или установщик с [ollama.com](https://ollama.com) |
| API | `POST {OLLAMA_HOST}/api/chat` (stream опционально v1.1) |
| Квантизация | Q4_K_M (баланс качество/RAM) — выбирает Ollama в теге модели |
| Apple Silicon | ускорение через **Metal** (не CUDA); отдельная видеокарта не нужна |
| Офлайн | да, после `ollama pull` |

**Почему не llama.cpp напрямую в v1:** Ollama уже решает загрузку моделей, Metal и версии GGUF; меньше кода в монолите.

### 4.3. Модель по умолчанию проекта: `qwen2.5:3b-instruct` (8 GB RAM)

**Рекомендация для целевой машины заказчика (MacBook Air 8 GB):**

```bash
./scripts/pull-summary-model.sh
# эквивалент: ollama pull qwen2.5:3b-instruct
```

| Параметр | Ориентир |
|----------|----------|
| Параметры | 3B |
| Диск после pull | ~2.0 GB |
| RAM при inference | ~2.5–3.5 GB |
| Русский саммари | хорошо для тезисов и пересказа созвонов |
| Время на референс `111` | **8–20 мин** (map-reduce) |

**Правило эксплуатации на 8 GB:** сначала завершить STT (`transcribe`), закрыть лишние приложения, затем `summarize`. **Не** запускать STT и summarize одновременно.

**Почему Qwen2.5 3B:** баланс качества русского и RAM; после `faster-whisper small` на 8 GB 7B-модель часто вызывает OOM.

Значение по умолчанию в коде и `.env.example`: `OLLAMA_MODEL=qwen2.5:3b-instruct`.

### 4.4. Усиленный профиль (только вручную, ≥16 GB RAM): `qwen2.5:7b-instruct`

Для машин с **16 GB RAM и более** — лучшее качество саммари. **Не** входит в `pull-summary-model.sh`; установка только вручную:

```bash
ollama pull qwen2.5:7b-instruct
export OLLAMA_MODEL=qwen2.5:7b-instruct
```

| Параметр | Ориентир |
|----------|----------|
| Диск | ~4.7 GB |
| RAM | ~5–6 GB |
| Время на референс `111` | **15–40 мин** |

### 4.5. Прочие альтернативы (только документация, без скриптов проекта)

| Модель | Когда | Установка |
|--------|-------|-----------|
| `bambucha/saiga-llama3:8b` | нужен «максимально русский» стиль, ≥16 GB | ручной `ollama pull` |
| облако (OpenAI и т.д.) | скорость важнее приватности | v2, не v1 |

**Итог для ТЗ:** v1 в коде и скриптах — **только `qwen2.5:3b-instruct`**; 7B и Saiga — опционально, **самостоятельно** пользователем.

### 4.6. Параметры inference (Ollama)

| Параметр | Значение v1 | Описание |
|----------|-------------|----------|
| `temperature` | `0.2` | меньше выдумок |
| `top_p` | `0.9` | |
| `num_predict` | `2048` | лимит токенов ответа на шаг |
| **`num_ctx`** | **`8192`** | контекст одного запроса (обязательно в API; дефолт Ollama 2048 мал) |
| `format` | `json` | Ollama JSON mode для map/reduce |

Перед длинным прогоном **не запускать** параллельно второй `transcribe --parallel` и `summarize` — конкуренция за RAM.

### 4.7. Длинные транскрипты: map-reduce

**~42 000 символов** не помещаются в один вызов с запасом под промпт и ответ.

Алгоритм v1:

1. Размер чанка: **`SUMMARY_CHUNK_CHAR_LIMIT=6000`** (консервативно для `num_ctx=8192` и русского текста).
2. Разбиение: по границам **`segments[]`** (предпочтительно); иначе по символам с overlap **300** символов.
3. **Map:** для каждого чанка — запрос «выдели факты и тезисы» → JSON `{ "partial_theses": [], "partial_summary": "" }`.
4. **Reduce:** один запрос — объединить partial в финальный `summary`, `theses`, `action_items`.
5. Запись в `output/summaries/`.

Запросы **последовательно**; в логе `Map chunk 2/8`.

Ориентир времени на референс `111` (7B, M-серия):

| Модель | Map+reduce (~8 чанков) |
|--------|-------------------------|
| `qwen2.5:7b-instruct` | **15–40 мин** |
| `qwen2.5:3b-instruct` | **8–20 мин** |

### 4.8. Сравнение с облаком (информативно)

| | Локально (Qwen 7B) | Облако (GPT-4o-mini) |
|--|-------------------|----------------------|
| Приватность | полная | данные у провайдера |
| Стоимость | $0 | платно за токены |
| Время на 48 мин | 15–40 мин | 1–5 мин |
| Качество RU | хорошее | очень хорошее |
| Офлайн | да | нет |

Облако остаётся запасным путём в **v2**, не в v1.

---

## 5. Требования к входным данным

### 5.1. Форматы

| Файл | Описание |
|------|----------|
| `.json` | транскрипт ТЗ-02 (приоритет) |
| `.txt` | только текст |

### 5.2. Валидация

- Файл существует, UTF-8.
- JSON: поле `text` непустое.
- `language` отсутствует → `ru`.
- Пустой текст → `EmptyTranscriptError`, exit **6**.

### 5.3. Ограничения v1

| Параметр | Лимит | Поведение |
|----------|-------|-----------|
| Длина текста | до **200 000** символов | map-reduce + предупреждение |
| Таймаут одного запроса Ollama | **300 с** | retry 1 раз |
| Одновременные `summarize` | 1 | документировать |
| RAM | не STT + summarize одновременно на 8 GB | предупреждение в логе |

---

## 6. Требования к выходным данным

### 6.1. Каталог

`output/summaries/` (gitignored).

Пример:

```
output/summaries/111_20260519T142840Z_20260519T162054Z_20260520T120000Z.summary.md
output/summaries/111_20260519T142840Z_20260519T162054Z_20260520T120000Z.theses.json
output/summaries/111_20260519T142840Z_20260519T162054Z_20260520T120000Z.meta.json
```

### 6.2. `.summary.md`

```markdown
# Краткий пересказ
…

# Основные тезисы
- …

# Действия (если есть)
- [ ] …
```

### 6.3. `.theses.json`

```json
{
  "summary": "…",
  "theses": ["…"],
  "action_items": [{ "text": "…", "assignee": null, "due": null }],
  "quotes": [{ "start": 0.0, "end": 1.0, "text": "…", "note": "…" }],
  "language": "ru",
  "source_transcript": "/path/to/transcript.json",
  "llm_model": "qwen2.5:3b-instruct",
  "llm_provider": "ollama",
  "created_at": "2026-05-20T12:00:00+00:00"
}
```

### 6.4. `.meta.json`

- `duration_sec`, `input_char_count`, `chunk_count`, `map_calls`, `ollama_host`, `num_ctx`, `processing_time_sec`, `stt_model` (из входного JSON).

Поле `estimated_cost_usd` — **не используется** (локальный режим).

---

## 7. Функциональные требования

### FR-01. Саммаризация

- Вход: путь к `.json` / `.txt`.
- Выход: `SummaryResult` (пути к `.summary.md`, `.theses.json`).

### FR-02. CLI

```bash
python -m app summarize TRANSCRIPT_PATH \
  [--output-dir DIR] \
  [--language ru|en] \
  [--model qwen2.5:3b-instruct] \
  [--ollama-host http://127.0.0.1:11434] \
  [--with-quotes] \
  [-v]
```

| Код | Смысл |
|-----|--------|
| 0 | Успех |
| 1 | Файл не найден |
| 4 | Некорректные аргументы / JSON |
| **6** | Ollama недоступен, модель не найдена, пустой текст, сбой LLM, OOM |

### FR-03. API

```python
def summarize_transcript(
    transcript_path: str | Path,
    *,
    output_dir: Path | None = None,
    language: str | None = None,
    style: str = "meeting",
    with_quotes: bool = False,
    model: str | None = None,
    ollama_host: str | None = None,
) -> SummaryResult:
    ...
```

### FR-04. Конфигурация

`.env.example` (без секретов):

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | URL демона |
| `OLLAMA_MODEL` | `qwen2.5:3b-instruct` | тег модели (единственный в `pull-summary-model.sh`) |
| `OLLAMA_NUM_CTX` | `8192` | размер контекста |
| `SUMMARY_CHUNK_CHAR_LIMIT` | `6000` | символов на map-чанк |
| `SUMMARY_TEMPERATURE` | `0.2` | |

При старте:

1. `GET /api/tags` — Ollama жива.
2. Модель есть в списке; иначе сообщение: `ollama pull {OLLAMA_MODEL}`.

### FR-05. Промпты (RU)

- Системный: аналитик созвонов; ответ **только JSON**; не выдумывать; язык `ru`.
- Пользовательский: фрагмент транскрипта.
- Reduce: объединить partial JSON.

`format: "json"` в теле запроса Ollama.

### FR-06. Установка окружения

```bash
brew install ollama          # или с сайта
ollama serve                 # если не запущен как служба
./scripts/pull-summary-model.sh
```

Скрипт тянет **только** модель из `OLLAMA_MODEL` (по умолчанию `qwen2.5:3b-instruct`). Другие теги проект **не скачивает**.

### FR-07. Связка 1→2→3 (v1.1)

```bash
python -m app process VIDEO --language ru --summarize
```

---

## 8. Нефункциональные требования

| ID | Требование |
|----|------------|
| NFR-01 | Данные транскрипта **не покидают машину** |
| NFR-02 | Без NVIDIA GPU; Ollama + Metal на Apple Silicon |
| NFR-03 | Референс `111` (~42k символов) завершается без OOM на **8 GB RAM** (модель **3B**) |
| NFR-04 | 7B — только при ручной смене `OLLAMA_MODEL` и ≥16 GB RAM |
| NFR-05 | Таймаут запроса **300 с**; 1 retry при сетевом сбое к localhost |
| NFR-06 | Логи INFO: чанк i/N, модель, `num_ctx`; не логировать полный транскрипт на DEBUG в проде |
| NFR-07 | Python **≥ 3.11**; HTTP-клиент `httpx` (без тяжёлого SDK OpenAI в v1) |
| NFR-08 | Не параллелить STT и summarize на одной машине v1 |

---

## 9. Структура в монолите

```
video-to-text/
├── app/
│   ├── summary/
│   │   ├── __init__.py
│   │   ├── summarizer.py
│   │   ├── chunking.py
│   │   ├── prompts.py
│   │   ├── ollama_client.py    # HTTP /api/chat, format=json
│   │   └── exceptions.py
│   ├── config.py
│   └── __main__.py
├── output/summaries/
├── scripts/
│   └── pull-summary-model.sh
├── tests/test_summarizer.py
├── .env.example
└── docs/TZ-03-summary.md
```

---

## 10. Обработка ошибок

| Ситуация | Поведение |
|----------|-----------|
| Ollama не запущен | `SummaryConfigError`: «запустите ollama serve» / exit 6 |
| Модель не скачана | подсказка `ollama pull …` / exit 6 |
| OOM / модель killed | лог + совет перейти на `3b` / exit 6 |
| Невалидный JSON от модели | 1 повтор с уточнением промпта; иначе exit 6 |
| Пустой `text` | exit 6 |
| Ctrl+C | без частичного сохранения (v1) |

---

## 11. Критерии приёмки (DoD)

- [ ] Установлен Ollama, выполнен `./scripts/pull-summary-model.sh` (`qwen2.5:3b-instruct`).
- [ ] CLI `summarize` на `111_*.json` создаёт `.summary.md` и `.theses.json`.
- [ ] Саммари на **русском** отражает темы созвона (обратная связь, финансы, Dashboard, антикризис).
- [ ] ≥ **5** тезисов в `.theses.json` для референса.
- [ ] При остановленном Ollama — понятная ошибка, exit **6**.
- [ ] Тесты с mock Ollama API проходят.
- [ ] `output/summaries/` в `.gitignore`.
- [ ] README: этап 3, Ollama, 3B по умолчанию, `pull-summary-model.sh` (одна модель).
- [ ] `.env.example` без API-ключей.

---

## 12. Сценарии проверки

### A — проверка Ollama

```bash
ollama run qwen2.5:3b-instruct "Сожми в 3 тезиса: созвон о финансах клиники и Dashboard."
```

### B — короткий транскрипт (тест / mock)

```bash
python -m app summarize tests/fixtures/short_transcript.json --language ru
```

### C — боевой файл

```bash
ollama serve   # в отдельном терминале, если нужно
./scripts/pull-summary-model.sh
python -m app summarize \
  "output/transcripts/111_20260519T142840Z_20260519T162054Z.json" \
  --language ru -v
```

Ожидание: map-reduce, **8–20 мин** на 3B; осмысленный результат.

### D — машина ≥16 GB (вручную, вне скриптов проекта)

```bash
ollama pull qwen2.5:7b-instruct
OLLAMA_MODEL=qwen2.5:7b-instruct python -m app summarize "output/transcripts/111_....json" --language ru
```

### E — полный пайплайн (v1.1)

```bash
python -m app process "111.mp4" --language ru --summarize
```

---

## 13. Зависимости для ТЗ-04

- `summary` + `theses[]` — сообщения боту (разбивка &gt;4096 символов в ТЗ-04).
- `.summary.md` — отправка файлом.
- Локальный режим: бот на том же сервере, что Ollama.

---

## 14. Риски и ограничения

| Риск | Митигация |
|------|-----------|
| OOM (STT + LLM) | не параллелить; 3b; закрыть лишние приложения |
| Медленно на CPU Intel | предпочесть Apple Silicon; уменьшить модель |
| Галлюцинации | temperature 0.2, JSON-only, промпт «только из текста» |
| Плохой STT | перезапуск ТЗ-02 с `small` |
| JSON ломается | Ollama `format: json`; retry; укоротить чанк |
| `num_ctx` по умолчанию 2048 | явно передавать **8192** в каждом запросе |

---

## 15. Оценка трудозатрат

| Задача | Оценка |
|--------|--------|
| Переписать ТЗ-03 под Ollama | 2 ч |
| `ollama_client.py` + map-reduce | 6 ч |
| `summarizer.py`, CLI, config | 4 ч |
| `pull-summary-model.sh`, README | 1 ч |
| Тесты mock | 3 ч |
| Приёмка на `111_*.json` (7B, ручной прогон) | 1 ч wall time |
| `process --summarize` (v1.1) | 2 ч |
| **Итого v1** | **~19 ч** |

---

## 16. Следующий шаг

**ТЗ-04:** [Telegram-бот](TZ-04-telegram-bot.md); пайплайн 1→2→3 на сервере с Ollama.

**Опционально v2:** backend `openai` за флагом `--provider openai` для тех, кому важнее скорость, чем приватность.

---

## Согласование

| Роль | Статус |
|------|--------|
| Заказчик | |
| Исполнитель | Черновик v2.0 — локальная LLM |
