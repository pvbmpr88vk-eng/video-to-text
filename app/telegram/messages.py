"""RU user-facing strings for the Telegram bot."""

README_STAGE4 = "https://github.com/pvbmpr88vk-eng/video-to-text#readme"

START = (
    "Привет! Отправьте видео, аудио или ссылку (YouTube и др.) — получите транскрипт (.txt).\n\n"
    "После готовности нажмите кнопку «Сделать тезисы», чтобы получить краткое саммари (локальная Ollama).\n\n"
    "Лимит файла: 20 MB (Telegram Bot API). Длинные ролики — через CLI.\n\n"
    "Команды: /help, /status, /cancel, /whoami"
)

HELP = (
    "1. Отправьте видео, аудио, голосовое (до 20 MB) или ссылку (YouTube и др.).\n"
    "2. Дождитесь .txt с транскриптом.\n"
    "3. Нажмите «Сделать тезисы» под файлом — саммари через Ollama (нужен запущенный ollama serve).\n\n"
    "Форматы: mp4, mov, mkv, webm, m4a, wav, mp3, ogg.\n"
    "STT: faster-whisper (CPU), модель small.\n\n"
    "Команды:\n"
    "/start — кратко о боте\n"
    "/help — это сообщение\n"
    "/status — этап обработки\n"
    "/cancel — отмена (best-effort)\n\n"
    f"Документация: {README_STAGE4}"
)

ACCESS_DENIED = (
    "У вас нет доступа к этому боту.\n"
    "Ваш Telegram user id: {user_id}\n"
    "Добавьте его в ALLOWED_USER_IDS в telegram-bot.access.txt и перезапустите бота.\n"
    "Команда /whoami — показать id."
)
ACCESS_DENIED_ALERT = "Нет доступа к этому боту."
WHOAMI = "Ваш Telegram user id: {user_id}\n\nЕсли бот пишет «нет доступа» — добавьте это число в ALLOWED_USER_IDS."
RATE_LIMIT = "Слишком много файлов за час. Подождите и попробуйте позже."
BUSY = "Уже идёт обработка. Дождитесь окончания или /status."
QUEUE_FULL = "Очередь переполнена ({max_size} задач). Попробуйте позже."
QUEUE_POSITION = (
    "Файл принят. В очереди: №{position}.\n"
    "{processing_hint}"
    "Распознавание на CPU может занять 10–60+ мин. /status — проверить этап."
)
QUEUE_PROCESSING_ACTIVE = "Сейчас обрабатывается другая задача — ваша начнётся после неё.\n"
QUEUE_NO_WORKER = (
    "⚠️ Worker transcript не запущен — задача не обработается.\n"
    "В отдельном терминале: python -m app worker transcript"
)
DOWNLOADING = "Скачиваю файл…"
FILE_TOO_LARGE = (
    "Файл {size_mb:.1f} MB — лимит Telegram для ботов 20 MB. "
    "Сожмите видео, отправьте аудио или используйте CLI. Загрузка по ссылке — в следующем обновлении."
)

URL_DOWNLOADING = "Скачиваю по ссылке (может занять несколько минут)…"
URL_DOWNLOAD_FAILED = "Не удалось скачать по ссылке: {detail}"

UNSUPPORTED_MEDIA = "Этот тип сообщения не поддерживается. Отправьте видео, аудио или документ из списка в /help."

UNSUPPORTED_DOCUMENT = "Формат документа не поддерживается. Используйте видео/аудио или расширения из /help."

CANCEL_ACK = (
    "Запрос на отмену принят.\n"
    "Если в worker transcript уже идёт STT — остановите его (Ctrl+C), "
    "выполните: python -m app jobs reset-stuck\n"
    "и запустите worker снова. Затем отправьте файл заново."
)

PIPELINE_CANCELLED = "Обработка отменена."
ERR_FFMPEG_MISSING = "На сервере не установлен FFmpeg. Установите ffmpeg и перезапустите бота."
ERR_NO_AUDIO = "В файле нет звуковой дорожки."
ERR_STT_MODEL = "Модель распознавания не загружена. Проверьте установку faster-whisper."
ERR_STT = "Ошибка распознавания. Попробуйте позже или другой файл."
ERR_SUMMARY = "Не удалось сделать тезисы: {detail}"
SUMMARY_BUSY = "Сейчас идёт другая задача. Попробуйте через минуту."
SUMMARY_STARTED = "Готовлю тезисы… (локальная LLM, может занять несколько минут)"
SUMMARY_JOB_EXPIRED = "Эта транскрипция устарела. Отправьте файл заново."
TRANSCRIPT_CAPTION = (
    "Транскрипт готов (файл выше).\n"
    "Длительность: ~{mins:.1f} мин · STT: {model} · Время: {proc_min:.1f} мин.\n"
    "Нажмите «Сделать тезисы», когда будете готовы."
)
SUMMARY_DONE = "Тезисы готовы за {proc_min:.1f} мин (модель {model})."
