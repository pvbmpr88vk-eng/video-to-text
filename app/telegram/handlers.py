from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from telegram import Message, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.config import (
    MAX_QUEUE_SIZE,
    TELEGRAM_BOT_FILE_SIZE_LIMIT,
    TELEGRAM_DEFAULT_LANGUAGE,
)
from app.jobs.models import JobStatus, JobType
from app.jobs.paths import ensure_job_dirs, job_inbox_dir
from app.jobs.store import JobStore
from app.queue.enqueue import cancel_rq_job, enqueue_summary, enqueue_transcript
from app.telegram import messages as M
from app.telegram.auth import MediaRateLimiter, is_allowed
from app.telegram.credentials import TelegramCredentials
from app.telegram.jobs import CALLBACK_THESES_PREFIX, parse_theses_callback
from app.telegram.notify import track_job, track_theses_message

logger = logging.getLogger(__name__)

ALLOWED_SUFFIXES = frozenset(
    {".mp4", ".mov", ".mkv", ".webm", ".m4a", ".wav", ".mp3", ".ogg", ".opus"}
)
URL_RE = re.compile(r"https?://", re.I)


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


def _inbox_filename(chat_id: int, fname: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = Path(fname).name
    safe = re.sub(r"[^\w\.\-]", "_", base).strip("._") or "media"
    safe = safe[:120]
    return f"{chat_id}_{ts}_{safe}"


def _store(context: ContextTypes.DEFAULT_TYPE) -> JobStore:
    return context.application.bot_data["job_store"]


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


def _format_job_line(job) -> str:
    return f"• {job.job_id[:8]}… — {job.status.value} ({job.job_type.value})"


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update, context):
        await update.effective_message.reply_text(M.ACCESS_DENIED)
        return
    user = update.effective_user
    store = _store(context)
    jobs = store.list_user_jobs(user.id, limit=5)
    queued = store.queued_transcript_count()
    lines = [f"В очереди transcript: {queued} (лимит {MAX_QUEUE_SIZE})"]
    if jobs:
        lines.append("Ваши задачи:")
        lines.extend(_format_job_line(j) for j in jobs)
    else:
        lines.append("Активных задач нет.")
    await update.effective_message.reply_text("\n".join(lines))


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update, context):
        await update.effective_message.reply_text(M.ACCESS_DENIED)
        return
    user = update.effective_user
    store = _store(context)
    jobs = store.list_user_jobs(user.id, limit=10)
    cancelled = 0
    for job in jobs:
        if job.status not in (JobStatus.QUEUED, JobStatus.DOWNLOADING, JobStatus.EXTRACT, JobStatus.STT, JobStatus.SUMMARY):
            continue
        store.cancel(job.job_id)
        cancel_rq_job(job.rq_job_id)
        cancelled += 1
    if cancelled:
        await update.effective_message.reply_text(M.CANCEL_ACK)
    else:
        await update.effective_message.reply_text("Нет задач для отмены.")


async def on_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return

    creds: TelegramCredentials = context.application.bot_data["creds"]
    rl: MediaRateLimiter = context.application.bot_data["rate_limiter"]
    store = _store(context)
    user = update.effective_user
    if not user:
        return

    if not creds.allowed_user_ids:
        await message.reply_text(M.NO_IDS_CONFIGURED)
        return
    if not is_allowed(user.id, creds.allowed_user_ids):
        await message.reply_text(M.ACCESS_DENIED)
        return
    if not rl.allow(user.id):
        await message.reply_text(M.RATE_LIMIT)
        return
    if store.queue_full():
        await message.reply_text(M.QUEUE_FULL.format(max_size=MAX_QUEUE_SIZE))
        return

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

        job_id = str(uuid.uuid4())
        ensure_job_dirs(job_id)
        dest = job_inbox_dir(job_id) / _inbox_filename(message.chat_id, fname)

        status_msg = await message.reply_text(M.DOWNLOADING)
        job = store.create(
            job_id=job_id,
            job_type=JobType.TRANSCRIPT,
            user_id=user.id,
            chat_id=message.chat_id,
            language=TELEGRAM_DEFAULT_LANGUAGE,
            message_id=message.message_id,
            status_message_id=status_msg.message_id,
            inbox_path=str(dest),
        )
        store.update_status(job_id, JobStatus.DOWNLOADING, publish=True)

        tg_file = await context.bot.get_file(file_id)
        remote_size = getattr(tg_file, "file_size", None) or file_size
        if remote_size is not None and remote_size > TELEGRAM_BOT_FILE_SIZE_LIMIT:
            store.update_status(job_id, JobStatus.FAILED, error="file_too_large")
            await message.reply_text(M.FILE_TOO_LARGE.format(size_mb=remote_size / 1e6))
            return

        await tg_file.download_to_drive(custom_path=str(dest))

        position = store.queued_transcript_count()
        store.update_status(job_id, JobStatus.QUEUED, publish=True)
        enqueue_transcript(store, job)
        await status_msg.edit_text(M.QUEUE_POSITION.format(position=max(1, position)))

        track_job(
            context.application,
            job_id=job_id,
            chat_id=message.chat_id,
            status_message_id=status_msg.message_id,
            reply_to_message_id=message.message_id,
        )
    except Exception:
        logger.exception("Failed to enqueue media job")
        await message.reply_text("Не удалось принять файл. Попробуйте позже.")


async def on_theses_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    parent_job_id = parse_theses_callback(query.data)
    if not parent_job_id:
        return

    user = query.from_user
    if not user:
        return

    creds: TelegramCredentials = context.application.bot_data["creds"]
    if not creds.allowed_user_ids or not is_allowed(user.id, creds.allowed_user_ids):
        await query.answer(M.ACCESS_DENIED, show_alert=True)
        return

    store = _store(context)
    parent = store.get(parent_job_id)
    if not parent:
        await query.answer(M.SUMMARY_JOB_EXPIRED, show_alert=True)
        return
    if parent.user_id != user.id:
        await query.answer(M.ACCESS_DENIED, show_alert=True)
        return
    if parent.status != JobStatus.DONE or not parent.transcript_json:
        await query.answer(M.SUMMARY_JOB_EXPIRED, show_alert=True)
        return
    if not Path(parent.transcript_json).is_file():
        await query.answer(M.SUMMARY_JOB_EXPIRED, show_alert=True)
        return

    await query.answer(M.SUMMARY_STARTED)
    chat_id = query.message.chat_id if query.message else user.id
    status_msg = await context.bot.send_message(chat_id, M.SUMMARY_STARTED)

    summary_job_id = str(uuid.uuid4())
    ensure_job_dirs(summary_job_id)
    summary_job = store.create(
        job_id=summary_job_id,
        job_type=JobType.SUMMARY,
        user_id=user.id,
        chat_id=chat_id,
        language=parent.language,
        status_message_id=status_msg.message_id,
        parent_job_id=parent_job_id,
    )
    enqueue_summary(store, summary_job)

    if query.message:
        track_theses_message(context.application, parent_job_id, query.message.message_id)

    parent_track = context.application.bot_data.get("tracked_jobs", {}).get(parent_job_id)
    track_job(
        context.application,
        job_id=summary_job_id,
        chat_id=chat_id,
        status_message_id=status_msg.message_id,
    )
    if parent_track and parent_track.theses_message_id:
        summary_track = context.application.bot_data["tracked_jobs"].get(summary_job_id)
        if summary_track:
            summary_track.theses_message_id = parent_track.theses_message_id


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
