# video-to-text

Извлечение аудио из видео и транскрипция в текст (монолит на Python).

## Этап 1: извлечение аудио

Модуль приводит звуковую дорожку к формату, готовому для STT (Whisper и аналоги):

| Параметр | WAV (по умолчанию) | MP3 |
|----------|-------------------|-----|
| Sample rate | 16 kHz | 16 kHz |
| Каналы | mono | mono |
| Кодек | PCM 16-bit | MP3 96 kbps |

### Требования

- Python **3.11+**
- **FFmpeg** и **ffprobe** в `PATH`

#### Установка FFmpeg (macOS)

**Вариант A — без Homebrew (в папку проекта `.local/bin/`):**

```bash
./scripts/install-ffmpeg-local.sh
```

После этого приложение **само** подхватывает `ffmpeg` из проекта — `export PATH` не обязателен.

**Вариант B — Homebrew** (нужен пароль администратора в Терминале):

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install ffmpeg
```

Проверка:

```bash
ffmpeg -version
ffprobe -version
```

### Установка зависимостей Python

Требуется **Python 3.11+** (см. `pyproject.toml`).

**Рекомендуется** (Homebrew + скрипт проекта):

```bash
brew install python@3.12   # один раз, если ещё нет
cd "/Users/aleksejlassal/Desktop/project/video to text"
./scripts/setup-venv.sh
source .venv/bin/activate
```

Вручную:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Запуск

```bash
python -m app extract-audio /path/to/video.mp4
```

Опции:

```bash
python -m app extract-audio INPUT \
  --format wav|mp3 \
  --output-dir output/audio \
  --audio-track-index 0 \
  --max-duration 120 \
  -v
```

Результат:

- аудиофайл в `output/audio/` (имя: `{имя}_{timestamp}.wav`);
- метаданные: `{файл}.wav.meta.json` (duration, sample_rate, source_path и т.д.).

Коды выхода: `0` успех, `1` файл не найден, `2` нет аудио, `3` ошибка FFmpeg, `4` неверные аргументы.

### Тесты

```bash
pytest tests/ -v
```

Интеграционные тесты пропускаются, если FFmpeg не установлен.

## Этап 2: распознавание речи (STT)

Локально на **CPU** через [faster-whisper](https://github.com/SYSTRAN/faster-whisper), модель по умолчанию `small`.

```bash
pip install -r requirements.txt
python -m app transcribe output/audio/ваш_файл.wav --language ru
```

Опции:

- `--model small|base|medium|tiny`
- `--output-dir output/transcripts`
- `--no-segments`
- `--parallel` — нарезка на чанки и транскрипция в несколько процессов (ускорение ~2–4× на CPU)
- `--chunk-minutes 10` — длина чанка (по умолчанию 10)
- `--workers 4` — число процессов (по умолчанию `min(4, cpu_count-1)`)

Результат:

- `output/transcripts/{имя}.txt` — текст;
- `output/transcripts/{имя}.json` — текст, язык, сегменты с таймкодами.

При первом запуске модель скачивается (~500 МБ для `small`).

### Полный пайплайн (этап 1 + 2)

```bash
python -m app process /path/to/video.mp4 --language ru
```

Или по шагам:

```bash
AUDIO=$(python -m app extract-audio /path/to/video.mp4)
python -m app transcribe "$AUDIO" --language ru --parallel --workers 4
```

Для длинных файлов (~48 мин) с ускорением:

```bash
python -m app transcribe output/audio/111_*.wav --language ru --parallel --chunk-minutes 10 --workers 4
```

Код выхода STT: `5` — ошибка модели или транскрипции.

## Этап 3: саммари (локальная LLM, Ollama)

По умолчанию модель **`qwen2.5:3b-instruct`** — рассчитана на **8 GB RAM**. Сначала завершите STT, затем саммари (не параллельно).

### Ollama

```bash
brew install ollama
ollama serve   # если не запущен как служба
./scripts/pull-summary-model.sh
```

Скрипт скачивает **одну** модель (`qwen2.5:3b-instruct`). Модель `7b` — только вручную при ≥16 GB RAM (см. ТЗ-03).

Опционально скопируйте `.env.example` → `.env`.

### Запуск

```bash
python -m app summarize output/transcripts/ваш_файл.json --language ru -v
```

Полный пайплайн с саммари:

```bash
python -m app process /path/to/video.mp4 --language ru --summarize
```

Результат в `output/summaries/`:

- `{имя}.summary.md` — пересказ и тезисы;
- `{имя}.theses.json` — структурированный JSON.

Код выхода саммари: `6` — Ollama недоступна, модель не установлена, пустой текст.

## Этап 4: Telegram-бот

Локальный бот принимает видео/аудио (до **20 MB**), делает **транскрипт** (.txt) и предлагает кнопку **«Сделать тезисы»** — саммари через Ollama по запросу.

### Настройка

1. Создайте бота в [@BotFather](https://t.me/BotFather), узнайте свой `user_id` (например [@userinfobot](https://t.me/userinfobot)).
2. Скопируйте шаблон и заполните токен и id (файл в `.gitignore`):

```bash
cp telegram-bot.access.example.txt telegram-bot.access.txt
```

Опционально: переменные `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_IDS`, `TELEGRAM_ACCESS_FILE` в окружении перекрывают файл.

3. Нужны **FFmpeg**; для кнопки «Сделать тезисы» — запущенная **Ollama** с моделью из этапа 3.

### Запуск

```bash
python -m app bot -v
```

Код выхода **`7`** — нет токена / неверные credentials, или нет FFmpeg.

Подробнее: [ТЗ-04: Telegram-бот](docs/TZ-04-telegram-bot.md).

### Документация

- [ТЗ-01: извлечение аудио](docs/TZ-01-audio-extraction.md)
- [ТЗ-02: STT](docs/TZ-02-stt.md)
- [ТЗ-03: саммари (локальная LLM / Ollama)](docs/TZ-03-summary.md)
- [ТЗ-04: Telegram-бот](docs/TZ-04-telegram-bot.md)
