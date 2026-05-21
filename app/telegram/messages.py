"""RU user-facing strings for the Telegram bot."""

from app.config import telegram_file_limit_mb

README_STAGE4 = "https://github.com/pvbmpr88vk-eng/video-to-text#readme"

_LIMIT_MB = f"{telegram_file_limit_mb():.0f}"

START = (
    "Привет! Отправьте видео, аудио или ссылку (YouTube и др.) — получите транскрипт (.txt).\n\n"
    "После готовности нажмите кнопку «Сделать тезисы», чтобы получить краткое саммари (локальная Ollama).\n\n"
    f"Лимит файла: {_LIMIT_MB} MB. Длинные ролики — ссылка или CLI.\n\n"
    "Команды: /help, /status, /cancel, /whoami"
)

HELP = (
    f"1. Отправьте видео, аудио, голосовое (до {_LIMIT_MB} MB) или ссылку (YouTube и др.).\n"
    "2. Дождитесь .txt с транскриптом.\n"
    "3. Нажмите «Сделать тезисы» под файлом — саммари через Ollama (нужен запущенный ollama serve).\n\n"
    "Форматы: mp4, mov, mkv, webm, m4a, wav, mp3, ogg; кружочки, GIF; файл как документ.\n"
    "Пересланные сторис не поддерживаются — сохраните видео или пришлите ссылку.\n"
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
    "Файл {size_mb:.1f} MB — лимит для этого бота {limit_mb:.0f} MB. "
    "Отправьте ссылку (YouTube и др.) или сожмите файл / отправьте аудио."
)
FILE_TOO_LARGE_HINT = (
    "Telegram не отдал файл боту"
    "{size_hint} (лимит скачивания до {limit_mb:.0f} MB).\n"
    "Отправьте ссылку на видео или сожмите файл."
)
TELEGRAM_FILE_TOO_BIG_API = (
    "Telegram не отдал файл (~{size_mb:.0f} MB в приложении — "
    "для бота действует лимит 20 MB, не размер в чате). "
    "Пришлите ссылку на видео или файл до 20 MB."
)
TELEGRAM_DOWNLOAD_FAILED = (
    "Не удалось скачать файл из Telegram. Попробуйте ещё раз, "
    "другой формат (mp4/mov как документ) или ссылку."
)
TELEGRAM_DOWNLOAD_TIMEOUT = (
    "Скачивание прервалось по таймауту (файл большой — нужно больше времени). "
    "Подождите минуту и отправьте файл снова или пришлите ссылку."
)

URL_DOWNLOADING = "Скачиваю по ссылке (может занять несколько минут)…"
URL_DOWNLOAD_FAILED = "Не удалось скачать по ссылке: {detail}"

UNSUPPORTED_MEDIA = "Этот тип сообщения не поддерживается. Отправьте видео, аудио или документ из списка в /help."

UNSUPPORTED_DOCUMENT = "Формат документа не поддерживается. Используйте видео/аудио или расширения из /help."

UNSUPPORTED_STORY = (
    "Пересланная сторис — бот не может скачать её (ограничение Telegram Bot API).\n\n"
    "Что сработает:\n"
    "• обычное видео из галереи (не сторис);\n"
    "• файл mp4/mov как «документ»;\n"
    "• ссылка на YouTube и др."
)

UNSUPPORTED_FORWARD = (
    "Не удалось взять файл из пересланного сообщения.\n\n"
    "Попробуйте:\n"
    "• «Сохранить в галерею» и отправить видео заново;\n"
    "• отправить как документ (mp4/mov);\n"
    "• прислать ссылку на ролик."
)

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
ERR_AUDIO_TOO_LONG = (
    "Аудио слишком длинное (~{minutes:.0f} мин). На этом сервере лимит ~{limit_min:.0f} мин. "
    "Отправьте более короткий фрагмент или ссылку на часть записи."
)
ERR_SUMMARY = "Не удалось сделать тезисы: {detail}"
SUMMARY_BUSY = "Сейчас идёт другая задача. Попробуйте через минуту."
SUMMARY_STARTED = "Готовлю тезисы… (локальная LLM, может занять несколько минут)"
SUMMARY_JOB_EXPIRED = "Эта транскрипция устарела. Отправьте файл заново."
TRANSCRIPT_CAPTION = "Транскрипт (.txt)"
TRANSCRIPT_SEND_FAILED = (
    "Транскрипт готов на сервере, но не удалось отправить файл в Telegram. "
    "Напишите /status — попробуем снова."
)
TRANSCRIPT_THESES_PROCESSING = "Транскрипт (.txt)\n⏳ Готовлю тезисы…"
THESES_ALREADY_PROCESSING = "Уже готовлю тезисы…"
