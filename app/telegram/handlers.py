from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.audio.exceptions import FFmpegError, FFmpegNotFoundError, NoAudioStreamError
from app.config import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SUMMARY_DIR,
    DEFAULT_TRANSCRIPT_DIR,
    TELEGRAM_BOT_FILE_SIZE_LIMIT,
    TELEGRAM_DEFAULT_LANGUAGE,
    TELEGRAM_STATUS_EDIT_MIN_SEC,
)
from app.stt.exceptions import ModelNotAvailableError, TranscriptionError
from app.summary.exceptions import (
    EmptyTranscriptError,
    SummaryAPIError,
    SummaryConfigError,
    SummaryError,
)
from app.telegram import messages as M
from app.telegram.auth import MediaRateLimiter, is_allowed
from app.telegram.credentials import TelegramCredentials
from app.telegram.formatting import format_summary_for_chat, split_telegram_message
from app.telegram.jobs import (
    CALLBACK_THESES_PREFIX,
    get_transcript_job,
    parse_theses_callback,
    register_transcript_job,
)
from app.telegram.pipeline import PipelineCancelled, run_summarize_pipeline, run_transcript_pipeline
from app.telegram.queue import JobCoordinator, JobPhase

logger = logging.getLogger(__name__)

ALLOWED_SUFFIXES = frozenset(
    {".mp4", ".mov", ".mkv", ".webm", ".m4a", ".wav", ".mp3", ".ogg", ".opus"}
)
URL_RE = re.compile(r"https?://", re.I)


def _theses_keyboard(job_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("📌 Сделать тезисы", callback_data=f"{CALLBACK_THESES_PREFIX}{job_id}")]]
    )


def _document_allowed(doc) -> bool:
    name = (doc.file_name or "").lower()
    mime = (doc.mime_type or "").lower()
    if mime.startswith("video/") or mime.startswith("audio/"):
        suf = Path(name).suffix if name else ""
        if suf and suf not in ALLOWED_SUFFIXES and suf != ".bin":
            return False
        return True
    suf = Path(name).suffix if name else ""
    return suf in ALLOWED_SUFFIXES


def pick_media(message: Message) -> tuple[str, int | None, str] | None:
    if message.video:
        v = message.video
        fn = v.file_name or "video.mp4"
        return v.file_id, v.file_size, fn
    if message.audio:
        a = message.audio
        fn = a.file_name or "audio.m4a"
        if Path(fn).suffix.lower() not in ALLOWED_SUFFIXES:
            fn = "audio.m4a"
        return a.file_id, a.file_size, fn
    if message.voice:
        vo = message.voice
        return vo.file_id, vo.file_size, "voice.ogg"
    if message.document:
        d = message.document
        if not _document_allowed(d):
            return None
        fn = d.file_name or "document.bin"
        return d.file_id, d.file_size, fn
    return None


def _inbox_path(inbox: Path, chat_id: int, fname: str) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = Path(fname).name
    safe = re.sub(r"[^\w\.\-]", "_", base).strip("._") or "media"
    safe = safe[:120]
    return inbox / f"{chat_id}_{ts}_{safe}"


async def _edit_status(
    coord: JobCoordinator,
    status_msg: Message | None,
    text: str,
) -> Message | None:
    if not status_msg:
        return None
    if not coord.can_edit_status(TELEGRAM_STATUS_EDIT_MIN_SEC):
        return status_msg
    try:
        await status_msg.edit_text(text)
    except Exception:
        logger.debug("edit_text failed", exc_info=True)
    return status_msg


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    creds: TelegramCredentials = context.application.bot_data["creds"]
    text = M.START
    if not creds.allowed_user_ids:
        text += "\n\n" + M.NO_IDS_CONFIGURED
    await update.effective_message.reply_text(text)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(M.HELP)


def _allowed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    creds: TelegramCredentials = context.application.bot_data["creds"]
    u = update.effective_user
    if not u:
        return False
    return bool(creds.allowed_user_ids) and is_allowed(u.id, creds.allowed_user_ids)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update, context):
        await update.effective_message.reply_text(M.ACCESS_DENIED)
        return
    coord: JobCoordinator = context.application.bot_data["coord"]
    await update.effective_message.reply_text(f"Состояние: {coord.phase}")


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update, context):
        await update.effective_message.reply_text(M.ACCESS_DENIED)
        return
    coord: JobCoordinator = context.application.bot_data["coord"]
    coord.request_cancel()
    await update.effective_message.reply_text(M.CANCEL_ACK)


async def on_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return

    creds: TelegramCredentials = context.application.bot_data["creds"]
    coord: JobCoordinator = context.application.bot_data["coord"]
    rl: MediaRateLimiter = context.application.bot_data["rate_limiter"]
    user = update.effective_user
    if not user:
        return

    if not creds.allowed_user_ids:
        await message.reply_text(M.NO_IDS_CONFIGURED)
        return
    if not is_allowed(user.id, creds.allowed_user_ids):
        await message.reply_text(M.ACCESS_DENIED)
        return

    if not await coord.try_begin():
        await message.reply_text(M.BUSY)
        return

    if not rl.allow(user.id):
        await coord.end()
        await message.reply_text(M.RATE_LIMIT)
        return

    inbox = Path(context.application.bot_data["inbox_dir"])
    inbox.mkdir(parents=True, exist_ok=True)

    status_msg: Message | None = None
    try:
        if message.document and not _document_allowed(message.document):
            await message.reply_text(M.UNSUPPORTED_DOCUMENT)
            return

        picked = pick_media(message)
        if not picked:
            await message.reply_text(M.UNSUPPORTED_MEDIA)
            return

        file_id, file_size, fname = picked
        if file_size is not None and file_size > TELEGRAM_BOT_FILE_SIZE_LIMIT:
            await message.reply_text(M.FILE_TOO_LARGE.format(size_mb=file_size / 1e6))
            return

        dest = _inbox_path(inbox, message.chat_id, fname)
        status_msg = await message.reply_text("Файл принят. Скачиваю…")
        coord.set_phase(JobPhase.DOWNLOADING)

        tg_file = await context.bot.get_file(file_id)
        remote_size = getattr(tg_file, "file_size", None) or file_size
        if remote_size is not None and remote_size > TELEGRAM_BOT_FILE_SIZE_LIMIT:
            await message.reply_text(M.FILE_TOO_LARGE.format(size_mb=remote_size / 1e6))
            return

        await tg_file.download_to_drive(custom_path=str(dest))

        coord.set_phase(JobPhase.EXTRACT)
        status_msg = await _edit_status(
            coord,
            status_msg,
            "Скачано. Извлечение аудио и распознавание речи на CPU (долго на длинных файлах)…",
        ) or status_msg

        language = TELEGRAM_DEFAULT_LANGUAGE

        try:
            result = await asyncio.to_thread(
                run_transcript_pipeline,
                dest,
                audio_dir=DEFAULT_OUTPUT_DIR,
                transcript_dir=DEFAULT_TRANSCRIPT_DIR,
                language=language,
                cancel_event=coord.cancel_event(),
            )
        except PipelineCancelled:
            await message.reply_text(M.PIPELINE_CANCELLED)
            return
        except NoAudioStreamError:
            await message.reply_text(M.ERR_NO_AUDIO)
            return
        except FFmpegNotFoundError:
            await message.reply_text(M.ERR_FFMPEG_MISSING)
            return
        except FFmpegError as exc:
            await message.reply_text(f"Ошибка FFmpeg: {exc}")
            return
        except ModelNotAvailableError:
            await message.reply_text(M.ERR_STT_MODEL)
            return
        except TranscriptionError as exc:
            await message.reply_text(f"{M.ERR_STT} ({exc})")
            return
        except FileNotFoundError as exc:
            await message.reply_text(f"Файл не найден: {exc}")
            return
        except ValueError as exc:
            await message.reply_text(f"Ошибка: {exc}")
            return

        job_id = register_transcript_job(
            context.application.bot_data,
            user_id=user.id,
            json_path=result.transcript_json,
            txt_path=result.transcript_txt,
            language=language,
        )

        mins = result.duration_sec / 60.0 if result.duration_sec else 0.0
        stats = M.TRANSCRIPT_CAPTION.format(
            mins=mins,
            model=result.stt_model,
            proc_min=result.processing_sec / 60.0,
        )

        if result.transcript_txt.is_file():
            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    logger.debug("Could not delete status message", exc_info=True)

            # 1) Сначала только файл транскрипта (без саммари)
            logger.info("Sending transcript file: %s", result.transcript_txt)
            await message.reply_document(
                document=str(result.transcript_txt.resolve()),
                caption="Транскрипт (.txt)",
            )
            # 2) Статистика и кнопка тезисов — отдельным сообщением
            await message.reply_text(stats, reply_markup=_theses_keyboard(job_id))
        else:
            await message.reply_text("Транскрипт не найден на диске.")

        coord.set_phase(JobPhase.IDLE)
    finally:
        await coord.end()


async def on_theses_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    job_id = parse_theses_callback(query.data)
    if not job_id:
        return

    user = query.from_user
    if not user:
        return

    creds: TelegramCredentials = context.application.bot_data["creds"]
    if not creds.allowed_user_ids or not is_allowed(user.id, creds.allowed_user_ids):
        await query.answer(M.ACCESS_DENIED, show_alert=True)
        return

    job = get_transcript_job(context.application.bot_data, job_id)
    if not job:
        await query.answer(M.SUMMARY_JOB_EXPIRED, show_alert=True)
        return
    if job.user_id != user.id:
        await query.answer(M.ACCESS_DENIED, show_alert=True)
        return
    if not job.json_path.is_file():
        await query.answer(M.SUMMARY_JOB_EXPIRED, show_alert=True)
        return

    coord: JobCoordinator = context.application.bot_data["coord"]
    if not await coord.try_begin():
        await query.answer(M.SUMMARY_BUSY, show_alert=True)
        return

    await query.answer(M.SUMMARY_STARTED)

    chat_id = query.message.chat_id if query.message else user.id
    status_msg = await context.bot.send_message(chat_id, M.SUMMARY_STARTED)
    coord.set_phase(JobPhase.SUMMARY)

    try:
        summary = await asyncio.to_thread(
            run_summarize_pipeline,
            job.json_path,
            summary_dir=DEFAULT_SUMMARY_DIR,
            language=job.language,
        )

        payload = json.loads(summary.theses_json.read_text(encoding="utf-8"))
        body = format_summary_for_chat(payload)
        for part in split_telegram_message(body):
            await context.bot.send_message(chat_id, part)

        await context.bot.send_message(
            chat_id,
            M.SUMMARY_DONE.format(
                proc_min=summary.processing_sec / 60.0,
                model=summary.llm_model,
            ),
        )

        if query.message:
            try:
                await query.message.edit_reply_markup(reply_markup=None)
            except Exception:
                logger.debug("Could not remove inline keyboard", exc_info=True)

        await status_msg.delete()
    except (
        EmptyTranscriptError,
        SummaryConfigError,
        SummaryAPIError,
        SummaryError,
    ) as exc:
        await status_msg.edit_text(M.ERR_SUMMARY.format(detail=exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Summary failed for job %s", job_id)
        await status_msg.edit_text(M.ERR_SUMMARY.format(detail=exc))
    finally:
        coord.set_phase(JobPhase.IDLE)
        await coord.end()


async def on_text_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if not msg or not msg.text:
        return
    if URL_RE.search(msg.text):
        await msg.reply_text(M.URL_NOT_SUPPORTED)


async def on_unsupported_visual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(M.UNSUPPORTED_MEDIA)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update", exc_info=context.error)


def register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("cancel", cmd_cancel))
    application.add_handler(CallbackQueryHandler(on_theses_callback, pattern=f"^{CALLBACK_THESES_PREFIX}"))

    application.add_handler(
        MessageHandler(
            filters.VIDEO | filters.AUDIO | filters.VOICE | filters.Document.ALL,
            on_media,
        )
    )
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_url))
    application.add_handler(MessageHandler(filters.PHOTO | filters.Sticker.ALL, on_unsupported_visual))
    application.add_error_handler(on_error)
