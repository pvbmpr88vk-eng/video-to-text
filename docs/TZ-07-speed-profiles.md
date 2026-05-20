# ТЗ-07: Профили скорости (лёгкие модели STT и тезисов)

**Проект:** video-to-text  
**Этап:** 7 (оптимизация производительности)  
**Архитектура:** монолит (Python) + Redis/RQ ([ТЗ-05](TZ-05-parallel-backend.md))  
**Зависит от:** [ТЗ-02](TZ-02-stt.md), [ТЗ-03](TZ-03-summary.md), [ТЗ-04](TZ-04-telegram-bot.md)  
**Версия ТЗ:** 1.0  
**Дата:** 2026-05-21  

---

## 1. Цель этапа

Ускорить **транскрипцию** и **создание тезисов** на слабых серверах (CPU, 8 GB RAM, без дискретной GPU) за счёт:

- смены моделей на более лёгкие;
- настраиваемых **профилей скорости** (`turbo` / `fast` / `quality`);
- упрощения пайплайна LLM для коротких транскриптов.

Качество в профиле `turbo` **ниже**, чем у текущих дефолтов; пользователь выбирает профиль осознанно.

**Не в scope:** облачный STT/LLM, GPU/CUDA, смена движка STT (остаётся faster-whisper).

---

## 2. Контекст

### 2.1. Текущие дефолты в коде

| Этап | Компонент | Значение |
|------|-----------|----------|
| STT | faster-whisper | `small`, CPU, `int8`, `beam_size=5`, VAD |
| Тезисы | Ollama | `qwen2.5:3b-instruct`, `num_ctx=8192`, map-reduce |

Ускорение: профили `turbo` / `fast` в п. 4.1 (`tiny`, `llama3.2:1b` и т.д.).

Ориентиры из [ТЗ-02](TZ-02-stt.md) / [ТЗ-03](TZ-03-summary.md): ~25–50 мин STT + ~8–20 мин тезисы на референсе **48 мин** аудио на MacBook Air 8 GB.

### 2.2. Целевая аудитория профилей

| Сценарий | Приоритет |
|----------|-----------|
| Голосовые 30 с – 5 мин | скорость |
| YouTube / ссылки до ~15 мин | скорость + приемлемый RU |
| Длинные созвоны 30–60+ мин | качество (`quality` или `fast`) |

### 2.3. Цепочка (без изменений архитектуры)

```
[Медиа] → [ТЗ-01 extract] → [ТЗ-02 STT] → .txt/.json → [кнопка] → [ТЗ-03 summarize] → чат
```

ТЗ-07 меняет только **параметры моделей и inference**, не контракт job/очереди ([ТЗ-05](TZ-05-parallel-backend.md)).

---

## 3. Границы scope

### В scope (v1)

| # | Требование |
|---|------------|
| 1 | Переменная `SPEED_PROFILE` с значениями `turbo`, `fast`, `quality` |
| 2 | Таблица пресетов: Whisper-модель, Ollama-модель, `num_ctx`, размер чанка summary, `beam_size` |
| 3 | Профиль **`fast`** — рекомендуемый дефолт для слабого сервера (см. п. 5) |
| 4 | Профиль **`quality`** — текущее поведение (`small` + `qwen2.5:3b-instruct`) |
| 5 | Разрешение env: явные `WHISPER_MODEL` / `OLLAMA_MODEL` **перекрывают** пресет профиля |
| 6 | Один проход LLM (без map-reduce) для короткого транскрипта (&lt; порога символов) |
| 7 | `TELEGRAM_DEFAULT_LANGUAGE=ru` по умолчанию в боте (быстрее и стабильнее auto) |
| 8 | Документация: README, `.env.example`, этот ТЗ |
| 9 | Скрипт `scripts/pull-models.sh` (или расширение `pull-summary-model.sh`) — список моделей по профилю |
| 10 | Unit-тесты: резолв профиля в `config`, порог single-pass summary |

### Вне scope (v1)

| # | Исключение | Когда |
|---|------------|--------|
| 1 | Автовыбор профиля по `duration_sec` в боте | v1.1 (`turbo` если &lt; 5 мин) |
| 2 | Metal/CUDA для Whisper | отдельное исследование |
| 3 | Облачные API (OpenAI Whisper, GPT) | v2 |
| 4 | Замена faster-whisper на другой движок | v2 |
| 5 | Параллельный STT + Ollama одновременно | запрещено (как в ТЗ-03) |

---

## 4. Профили скорости

### 4.1. Сводная таблица

| Параметр | `turbo` | `fast` (дефолт ТЗ-07) | `quality` |
|----------|---------|----------------------|-----------|
| **WHISPER_MODEL** | `tiny` | `base` | `small` |
| **WHISPER_BEAM_SIZE** | `1` | `3` | `5` |
| **OLLAMA_MODEL** | `qwen2.5:1.5b-instruct` | `qwen2.5:3b-instruct` | `qwen2.5:3b-instruct` |
| **OLLAMA_NUM_CTX** | `4096` | `6144` | `8192` |
| **SUMMARY_CHUNK_CHAR_LIMIT** | `8000` | `6000` | `6000` |
| **SUMMARY_SINGLE_PASS_MAX_CHARS** | `4000` | `6000` | `8000` |
| RAM (ориентир, пик) | ~3–4 GB | ~5–6 GB | ~6–8 GB |
| Качество RU STT | низкое | среднее | хорошее |
| Качество тезисов | черновик | хорошо | лучше на длинных текстах |

### 4.2. Ориентиры wall-time (CPU int8, 1 vCPU worker, без GPU)

Оценки для планирования; фактическое время зависит от CPU и фоновой нагрузки.

| Аудио | `turbo` STT + тезисы | `fast` STT + тезисы | `quality` STT + тезисы |
|-------|----------------------|---------------------|------------------------|
| 30 с | ~20–40 с | ~30–60 с | ~40–90 с |
| 5 мин | ~2–4 мин | ~3–6 мин | ~5–10 мин |
| 10 мин | ~4–8 мин | ~6–12 мин | ~10–18 мин |
| 48 мин | ~12–25 мин + ~3–8 мин | ~15–30 мин + ~5–12 мин | ~25–50 мин + ~8–20 мин |

> **Важно:** «мгновенная» обработка длинного видео на CPU без GPU **недостижима**; профиль `turbo` даёт ускорение, а не магию.

### 4.3. Когда какой профиль

| Профиль | Рекомендация |
|---------|--------------|
| **turbo** | тесты, черновик, короткие голосовые; пользователь предупреждён о качестве |
| **fast** | **основной режим бота** на VPS / Mac 8 GB |
| **quality** | длинные созвоны, важные записи, машина ≥8 GB с запасом RAM |

---

## 5. STT (faster-whisper)

### 5.1. Модели Whisper (без смены движка)

| Модель | RAM | Качество RU | Относительная скорость |
|--------|-----|-------------|------------------------|
| `tiny` | ~1 GB | низкое | ~3–5× быстрее `small` |
| `base` | ~1.5 GB | среднее | ~2× быстрее `small` |
| `small` | ~2 GB | хорошее | 1× (текущий дефолт) |
| `medium` | ~5 GB | очень хорошее | медленнее; только `quality`+ при ≥16 GB |

### 5.2. Параметры inference

| Параметр | `turbo` | `fast` | `quality` |
|----------|---------|--------|-----------|
| `device` | `cpu` | `cpu` | `cpu` |
| `compute_type` | `int8` | `int8` | `int8` |
| `beam_size` | `1` | `3` | `5` |
| `vad_filter` | `true` | `true` | `true` |
| `language` (бот) | `ru` | `ru` | `ru` |

`beam_size=1` (greedy) даёт ~20–30% ускорения decode при потере точности на шумных записях.

### 5.3. Параллельные чанки STT

Поведение [ТЗ-02](TZ-02-stt.md) **сохраняется** (`--parallel`, `chunk-minutes`, `workers`).

На macOS worker STT ограничен **1 процессом** ([ТЗ-05](TZ-05-parallel-backend.md)); на Linux VPS с 4 vCPU параллельный режим даёт ускорение ~2–4× на длинных файлах.

---

## 6. Тезисы (Ollama)

### 6.1. Кандидаты моделей

| Модель | Диск (Q4) | RAM inference | Скорость | Русский / JSON |
|--------|-----------|---------------|----------|----------------|
| `qwen2.5:1.5b-instruct` | ~1.0 GB | ~1.5–2.5 GB | быстрее 3B | слабее на длинных текстах |
| **`qwen2.5:3b-instruct`** | ~2.0 GB | ~2.5–3.5 GB | база | проверен в проекте |
| `gemma2:2b-instruct` | ~1.5 GB | ~2–3 GB | быстро | короткие саммари ок |
| `llama3.2:3b-instruct` | ~2.0 GB | ~2.5–3.5 GB | сопоставимо с Qwen 3B | нейтрально |
| `qwen2.5:7b-instruct` | ~4.7 GB | ~5–6 GB | медленно | только ручной override, ≥16 GB |

**ТЗ-07 v1 в пресетах:** только `1.5b` (turbo) и `3b` (fast/quality). Остальные — документация для ручной подстановки через `OLLAMA_MODEL`.

### 6.2. Map-reduce и single-pass

| Режим | Условие | Поведение |
|-------|---------|-----------|
| **single-pass** | `len(text) ≤ SUMMARY_SINGLE_PASS_MAX_CHARS` | один запрос к LLM, без map |
| **map-reduce** | длиннее порога | как [ТЗ-03](TZ-03-summary.md) |

Порог по профилю — см. п. 4.1. Это сокращает время на коротких записях (голос, Shorts).

### 6.3. Проверка grounding

Логика [ТЗ-03](TZ-03-summary.md) (anti-hallucination, literal fallback) **обязательна для всех профилей**, включая `turbo` и `1.5b`.

---

## 7. Конфигурация (ENV)

### 7.1. Новые и изменённые переменные

| Переменная | По умолчанию (после ТЗ-07) | Описание |
|------------|----------------------------|----------|
| `SPEED_PROFILE` | `fast` | `turbo` \| `fast` \| `quality` |
| `WHISPER_MODEL` | *(из профиля)* | явное значение перекрывает профиль |
| `WHISPER_BEAM_SIZE` | *(из профиля)* | `1` / `3` / `5` |
| `OLLAMA_MODEL` | *(из профиля)* | явное значение перекрывает профиль |
| `OLLAMA_NUM_CTX` | *(из профиля)* | |
| `SUMMARY_CHUNK_CHAR_LIMIT` | *(из профиля)* | |
| `SUMMARY_SINGLE_PASS_MAX_CHARS` | *(из профиля)* | порог одного прохода LLM |
| `TELEGRAM_DEFAULT_LANGUAGE` | `ru` | язык STT в боте |

### 7.2. Пример `.env.example`

```bash
# Профиль скорости: turbo | fast | quality
SPEED_PROFILE=fast

# Опционально перекрыть пресет:
# WHISPER_MODEL=base
# WHISPER_BEAM_SIZE=3
# OLLAMA_MODEL=qwen2.5:3b-instruct
# OLLAMA_NUM_CTX=6144

OLLAMA_HOST=http://127.0.0.1:11434
TELEGRAM_DEFAULT_LANGUAGE=ru
```

### 7.3. Резолв в коде (`app/config.py`)

Псевдологика (FR для реализации):

```python
_PROFILES = {
    "turbo": {...},
    "fast": {...},
    "quality": {...},
}

def resolve_speed_settings() -> SpeedSettings:
    base = _PROFILES[os.getenv("SPEED_PROFILE", "fast")]
    return base.with_overrides(
        whisper_model=os.getenv("WHISPER_MODEL"),
        whisper_beam_size=os.getenv("WHISPER_BEAM_SIZE"),
        ollama_model=os.getenv("OLLAMA_MODEL"),
        ...
    )
```

Все точки входа (worker STT, worker summary, CLI) читают **один** резолв, не дублируют дефолты.

---

## 8. Функциональные требования

### FR-01. Пресеты профилей

- Модуль: `app/config.py` (или `app/profiles/speed.py`).
- Три профиля по таблице п. 4.1.
- Невалидный `SPEED_PROFILE` → warning в лог + fallback `fast`.

### FR-02. STT использует профиль

- `app/stt/transcriber.py`: `beam_size` из конфига, не захардкожен `5`.
- `app/queue/tasks.py` / worker: модель Whisper из резолва профиля.
- CLI `transcribe`: флаги `--model` / `--beam-size` перекрывают профиль (как сейчас `--model`).

### FR-03. Summary использует профиль

- `app/queue/tasks.py`, `summarize_transcript`: `OLLAMA_MODEL`, `OLLAMA_NUM_CTX`, chunk limits из профиля.
- Single-pass если `input_char_count ≤ SUMMARY_SINGLE_PASS_MAX_CHARS` (уже частично есть для 1 chunk; формализовать порог из конфига).

### FR-04. Скрипт загрузки моделей

- `scripts/pull-models.sh`:
  - для `SPEED_PROFILE=fast`: `ollama pull qwen2.5:3b-instruct` + напоминание про кэш Whisper `base`;
  - для `turbo`: + `qwen2.5:1.5b-instruct`;
  - для `quality`: без изменений (3b + small).

Whisper качается при первом `transcribe` (Hugging Face Hub); в скрипте — опциональный warmup CLI.

### FR-05. Telegram / UX

- В `/help` или `/start`: одна строка «Профиль скорости: fast (base + qwen 3B)».
- При `SPEED_PROFILE=turbo`: опционально предупреждение в `SUMMARY_STARTED` toast: «черновик, низкое качество» (v1.1).

### FR-06. Эксплуатация RAM

- На 8 GB: **не** запускать STT worker и summary worker на тяжёлых моделях одновременно на одном файле (как сейчас).
- Профиль `turbo` не должен требовать &gt;4 GB свободной RAM в пике.

---

## 9. Нефункциональные требования

| ID | Требование |
|----|------------|
| NFR-01 | Переключение профиля — только через `.env` + перезапуск workers/bot |
| NFR-02 | Обратная совместимость: `SPEED_PROFILE=quality` ≈ поведение до ТЗ-07 |
| NFR-03 | Явные `WHISPER_MODEL` / `OLLAMA_MODEL` в env всегда сильнее пресета |
| NFR-04 | Логи при старте worker/bot: `Speed profile: fast (whisper=base, ollama=qwen2.5:3b-instruct)` |

---

## 10. Критерии приёмки (DoD)

- [ ] `SPEED_PROFILE=fast` в `.env` → worker STT грузит `base`, summary — `qwen2.5:3b-instruct`.
- [ ] `SPEED_PROFILE=turbo` → `tiny` + `1.5b`, `beam_size=1`.
- [ ] `SPEED_PROFILE=quality` → `small` + `3b`, `beam_size=5` (как до изменений).
- [ ] Транскрипт 2 мин (референс-короткий sample): wall-time STT+тезисы на `turbo` **&lt; 90 с** на целевой машине заказчика.
- [ ] Тот же sample на `fast`: **&lt; 3 мин**.
- [ ] Транскрипт &lt; `SUMMARY_SINGLE_PASS_MAX_CHARS` → один вызов Ollama (проверка логом `Summary map-reduce: 1 chunk`).
- [ ] Grounding / anti-hallucination из ТЗ-03 работает на всех профилях.
- [ ] `.env.example`, README, `pull-models.sh` обновлены.
- [ ] Unit-тесты резолва профиля и override env.

---

## 11. Риски и митигация

| Риск | Митигация |
|------|-----------|
| `tiny` плохо на именах и терминах | профиль `fast` по умолчанию, не `turbo` |
| `1.5b` выдумывает тезисы | grounding + retry + literal fallback (уже в коде) |
| OOM 8 GB при `quality` + параллель STT | не менять правило «STT потом summary» |
| Пользователь не знает о профиле | строка в `/help`, README |
| Долгий первый запуск (скачивание `base`) | сообщение при первом job (как сейчас для Whisper) |

---

## 12. План реализации (оценка)

| Задача | Оценка |
|--------|--------|
| `SpeedSettings` + резолв в `config.py` | 2 ч |
| STT: `beam_size` из конфига | 1 ч |
| Summary: порог single-pass из конфига | 1 ч |
| `pull-models.sh`, `.env.example`, README | 1 ч |
| Тесты | 2 ч |
| Правки TZ-02/TZ-03 (ссылки на ТЗ-07) | 0.5 ч |
| **Итого** | **~7.5 ч** |

---

## 13. Связь с другими ТЗ

| ТЗ | Изменение |
|----|-----------|
| [ТЗ-02](TZ-02-stt.md) | дефолт модели: `small` → в профиле `quality`; рекомендация сервера: `fast` |
| [ТЗ-03](TZ-03-summary.md) | дефолт Ollama остаётся 3B; turbo — 1.5B в отдельном профиле |
| [ТЗ-04](TZ-04-telegram-bot.md) | строка про профиль в help; `language=ru` |
| [ТЗ-05](TZ-05-parallel-backend.md) | без изменений контракта job |

---

## 14. Согласование

| Роль | Статус |
|------|--------|
| Заказчик | |
| Исполнитель | Черновик ТЗ готов |
