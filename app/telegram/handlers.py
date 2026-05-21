from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from telegram import Message, Update
from telegram.error import BadRequest, NetworkError, TimedOut
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
    URL_DOWNLOAD_MAX_BYTES,
    telegram_file_limit_mb,
)
from app.download.url import UrlDownloadError, download_media_url, extract_url
from app.jobs.models import JobStatus, JobType
from app.jobs.paths import ensure_job_dirs, job_inbox_dir
from app.jobs.store import JobStore
from app.queue.enqueue import cancel_rq_job, ensure_summary_queued, enqueue_transcript
from app.telegram import messages as M
from app.telegram.auth import MediaRateLimiter, is_allowed
from app.telegram.credentials import TelegramCredentials
from app.telegram.jobs import CALLBACK_THESES_PREFIX, parse_theses_callback
from app.telegram.idempotency import claim_inbound_message
from app.telegram.notify import (
    ensure_summary_delivery,
    mark_theses_button_processing,
    track_job,
    try_deliver_summary,
)
from app.telegram.queue_msg import format_queue_accept_message

logger = logging.getLogger(__name__)


class _StoryForwardFilter(filters.MessageFilter):
    def filter(self, message: Message) -> bool:
        return bool(message.story)


_STORY_FORWARD = _StoryForwardFilter(name="StoryForward")

ALLOWED_SUFFIXES = frozenset(
    {".mp4", ".mov", ".mkv", ".webm", ".m4a", ".wav", ".mp3", ".ogg", ".opus"}
)


def _file_suffix(name: str) -> str:
    return Path(name).suffix.lower()


def _suffix_allowed(name: str) -> bool:
    suf = _file_suffix(name)
    return bool(suf) and suf in ALLOWED_SUFFIXES


def _is_forwarded(message: Message) -> bool:
    return message.forward_origin is not None or message.forward_date is not None


def _document_allowed(doc, *, forwarded: bool = False) -> bool:
    name = doc.file_name or ""
    mime = (doc.mime_type or "").lower()
    if mime.startswith("video/") or mime.startswith("audio/"):
        suf = _file_suffix(name)
        if suf and suf not in ALLOWED_SUFFIXES and suf != ".bin":
            return False
        return True
    if _suffix_allowed(name):
        return True
    # Пересланные файлы часто без имени / с application/octet-stream
    if forwarded and mime in ("application/octet-stream", "binary/octet-stream", ""):
        return True
    return False


def _normalize_media_filename(fname: str, *, default: str) -> str:
    base = Path(fname).name or default
    stem = Path(base).stem or "media"
    suf = _file_suffix(base)
    if not suf:
        suf = _file_suffix(default)
    return f"{stem}{suf}" if suf else default


def pick_media(message: Message) -> tuple[str, int | None, str] | None:
    if message.video:
        v = message.video
        fn = _normalize_media_filename(v.file_name or "", default="video.mp4")
        return v.file_id, v.file_size, fn
    if message.video_note:
        vn = message.video_note
        return vn.file_id, vn.file_size, "video_note.mp4"
    if message.audio:
        a = message.audio
        fn = a.file_name or "audio.m4a"
        if Path(fn).suffix.lower() not in ALLOWED_SUFFIXES:
            fn = "audio.m4a"
        return a.file_id, a.file_size, fn
    if message.voice:
        vo = message.voice
        return vo.file_id, vo.file_size, "voice.ogg"
    if message.animation:
        anim = message.animation
        fn = _normalize_media_filename(anim.file_name or "", default="animation.mp4")
        return anim.file_id, anim.file_size, fn
    if message.document:
        d = message.document
        if not _document_allowed(d, forwarded=_is_forwarded(message)):
            return None
        default = "document.bin"
        mime = (d.mime_type or "").lower()
        if mime.startswith("video/"):
            default = "video.mp4"
        elif mime.startswith("audio/"):
            default = "audio.m4a"
        fn = _normalize_media_filename(d.file_name or "", default=default)
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
    if not await _guard_access(update, context):
        return
    msg = update.effective_message
    if msg:
        await msg.reply_text(M.START)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard_access(update, context):
        return
    msg = update.effective_message
    if msg:
        await msg.reply_text(M.HELP)


def _telegram_user(update: Update):
    if update.effective_user:
        return update.effective_user
    if update.callback_query and update.callback_query.from_user:
        return update.callback_query.from_user
    msg = update.effective_message
    if msg and msg.from_user:
        return msg.from_user
    return None


def _allowed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    creds: TelegramCredentials = context.application.bot_data["creds"]
    u = _telegram_user(update)
    if not u:
        return False
    return is_allowed(u.id, creds.allowed_user_ids)


async def _guard_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Return True only for user ids listed in ALLOWED_USER_IDS."""
    if _allowed(update, context):
        return True
    u = _telegram_user(update)
    denied_text = M.ACCESS_DENIED.format(user_id=u.id if u else "?")
    logger.info("Access denied for user_id=%s", u.id if u else None)
    if update.callback_query:
        await update.callback_query.answer(M.ACCESS_DENIED_ALERT, show_alert=True)
    elif update.effective_message:
        await update.effective_message.reply_text(denied_text)
    return False


async def cmd_whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Always available — helps add the correct id to ALLOWED_USER_IDS."""
    u = _telegram_user(update)
    if not u or not update.effective_message:
        return
    await update.effective_message.reply_text(M.WHOAMI.format(user_id=u.id))


def _format_job_line(job) -> str:
    return f"• {job.job_id[:8]}… — {job.status.value} ({job.job_type.value})"


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard_access(update, context):
        return
    user = update.effective_user
    store = _store(context)
    jobs = store.list_user_jobs(user.id, limit=5)
    queued = store.queued_transcript_count()
    from app.queue.diagnostics import format_queue_status

    lines = [
        f"В очереди transcript: {queued} (лимит {MAX_QUEUE_SIZE})",
        f"Обрабатывается сейчас: {store.count_processing_transcripts()}",
        "",
        format_queue_status(),
    ]
    if jobs:
        lines.append("Ваши задачи:")
        lines.extend(_format_job_line(j) for j in jobs)
    else:
        lines.append("Активных задач нет.")
    await update.effective_message.reply_text("\n".join(lines))


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard_access(update, context):
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
    redis = context.application.bot_data["redis"]
    if not claim_inbound_message(redis, message.chat_id, message.message_id):
        logger.debug("Skip duplicate media message chat=%s msg=%s", message.chat_id, message.message_id)
        return

    rl: MediaRateLimiter = context.application.bot_data["rate_limiter"]
    store = _store(context)
    user = update.effective_user
    if not user:
        return

    if not await _guard_access(update, context):
        return
    if not rl.allow(user.id):
        await message.reply_text(M.RATE_LIMIT)
        return
    if store.queue_full():
        await message.reply_text(M.QUEUE_FULL.format(max_size=MAX_QUEUE_SIZE))
        return

    job_id: str | None = None
    try:
        if message.document and not _document_allowed(
            message.document, forwarded=_is_forwarded(message)
        ):
            logger.info(
                "Rejected document name=%r mime=%s forward=%s",
                message.document.file_name,
                message.document.mime_type,
                _is_forwarded(message),
            )
            await message.reply_text(M.UNSUPPORTED_DOCUMENT)
            return

        picked = pick_media(message)
        if not picked:
            if message.story:
                await message.reply_text(M.UNSUPPORTED_STORY)
            elif _is_forwarded(message):
                await message.reply_text(M.UNSUPPORTED_FORWARD)
            else:
                await message.reply_text(M.UNSUPPORTED_MEDIA)
            return

        file_id, file_size, fname = picked
        if file_size is not None and file_size > TELEGRAM_BOT_FILE_SIZE_LIMIT:
            await message.reply_text(
                M.FILE_TOO_LARGE.format(
                    size_mb=file_size / 1e6,
                    limit_mb=telegram_file_limit_mb(),
                )
            )
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
            await message.reply_text(
                M.FILE_TOO_LARGE.format(
                    size_mb=remote_size / 1e6,
                    limit_mb=telegram_file_limit_mb(),
                )
            )
            return

        await tg_file.download_to_drive(custom_path=str(dest))
        if not dest.is_file() or dest.stat().st_size == 0:
            raise OSError(f"download empty or missing: {dest}")

        store.update_status(job_id, JobStatus.QUEUED, publish=True)
        enqueue_transcript(store, job)
        await status_msg.edit_text(format_queue_accept_message(store))

        track_job(
            context.application,
            job_id=job_id,
            chat_id=message.chat_id,
            status_message_id=status_msg.message_id,
            reply_to_message_id=message.message_id,
        )
    except BadRequest as exc:
        logger.warning("Telegram API rejected file download: %s", exc)
        err = str(exc).lower()
        if job_id and store.get(job_id):
            code = "file_too_large" if "too big" in err or "file is too large" in err else "telegram_download"
            store.update_status(job_id, JobStatus.FAILED, error=code)
        if "too big" in err or "file is too large" in err:
            await message.reply_text(
                M.FILE_TOO_LARGE_HINT.format(limit_mb=telegram_file_limit_mb())
            )
        else:
            await message.reply_text(M.TELEGRAM_DOWNLOAD_FAILED)
    except (TimedOut, NetworkError) as exc:
        logger.warning("Telegram download network error: %s", exc)
        if job_id and store.get(job_id):
            store.update_status(job_id, JobStatus.FAILED, error="telegram_download")
        await message.reply_text(M.TELEGRAM_DOWNLOAD_FAILED)
    except OSError as exc:
        logger.exception("Failed to save downloaded file: %s", exc)
        if job_id and store.get(job_id):
            store.update_status(job_id, JobStatus.FAILED, error="telegram_download")
        await message.reply_text(M.TELEGRAM_DOWNLOAD_FAILED)
    except Exception:
        logger.exception("Failed to enqueue media job")
        if job_id and store.get(job_id):
            store.update_status(job_id, JobStatus.FAILED, error="telegram_download")
        await message.reply_text(M.TELEGRAM_DOWNLOAD_FAILED)


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

    if not await _guard_access(update, context):
        return

    store = _store(context)
    parent = store.get(parent_job_id)
    if not parent:
        await query.answer(M.SUMMARY_JOB_EXPIRED, show_alert=True)
        return
    if parent.user_id != user.id:
        await query.answer(M.ACCESS_DENIED_ALERT, show_alert=True)
        return
    if parent.status != JobStatus.DONE or not parent.transcript_json:
        await query.answer(M.SUMMARY_JOB_EXPIRED, show_alert=True)
        return
    if not Path(parent.transcript_json).is_file():
        await query.answer(M.SUMMARY_JOB_EXPIRED, show_alert=True)
        return

    redis = context.application.bot_data["redis"]
    chat_id = query.message.chat_id if query.message else user.id
    msg = query.message

    async def _hide_button_and_answer(toast: str, *, alert: bool = False) -> None:
        if msg:
            await mark_theses_button_processing(
                context.application,
                chat_id=chat_id,
                message_id=msg.message_id,
                parent_job_id=parent_job_id,
            )
        await query.answer(toast, show_alert=alert)

    existing = store.find_summary_for_parent(parent_job_id)
    if existing and existing.status == JobStatus.DONE:
        from app.jobs.delivery import was_telegram_delivered

        if was_telegram_delivered(redis, existing.job_id, "summary"):
            await query.answer("Тезисы уже отправлены в чат.", show_alert=True)
            return
        await _hide_button_and_answer("Отправляю тезисы…")
        if await try_deliver_summary(context.application, existing.job_id):
            return
        ensure_summary_delivery(context.application, existing.job_id)
        return

    if existing and existing.status in (JobStatus.QUEUED, JobStatus.SUMMARY, JobStatus.FAILED):
        await _hide_button_and_answer(M.THESES_ALREADY_PROCESSING)
        if existing.status == JobStatus.SUMMARY:
            store.update_status(existing.job_id, JobStatus.QUEUED, error=None)
        elif existing.status == JobStatus.FAILED:
            store.update_status(existing.job_id, JobStatus.QUEUED, error=None)
        parent_track = context.application.bot_data.get("tracked_jobs", {}).get(parent_job_id)
        track_job(
            context.application,
            job_id=existing.job_id,
            chat_id=chat_id,
            status_message_id=existing.status_message_id,
        )
        if parent_track and parent_track.theses_message_id:
            summary_track = context.application.bot_data["tracked_jobs"].get(existing.job_id)
            if summary_track:
                summary_track.theses_message_id = parent_track.theses_message_id
        job_row = store.get(existing.job_id) or existing
        ensure_summary_queued(store, job_row)
        ensure_summary_delivery(context.application, existing.job_id)
        return

    await _hide_button_and_answer("Готовлю тезисы…")

    summary_job_id = str(uuid.uuid4())
    ensure_job_dirs(summary_job_id)
    summary_job = store.create(
        job_id=summary_job_id,
        job_type=JobType.SUMMARY,
        user_id=user.id,
        chat_id=chat_id,
        language=parent.language,
        status_message_id=None,
        parent_job_id=parent_job_id,
    )

    parent_track = context.application.bot_data.get("tracked_jobs", {}).get(parent_job_id)
    track_job(
        context.application,
        job_id=summary_job_id,
        chat_id=chat_id,
        status_message_id=None,
    )
    if parent_track and parent_track.theses_message_id:
        summary_track = context.application.bot_data["tracked_jobs"].get(summary_job_id)
        if summary_track:
            summary_track.theses_message_id = parent_track.theses_message_id

    ensure_summary_queued(store, summary_job)
    ensure_summary_delivery(context.application, summary_job_id)
    await try_deliver_summary(context.application, summary_job_id)


async def on_text_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard_access(update, context):
        return
    msg = update.effective_message
    if not msg or not msg.text:
        return
    redis = context.application.bot_data["redis"]
    if not claim_inbound_message(redis, msg.chat_id, msg.message_id):
        logger.debug("Skip duplicate URL message chat=%s msg=%s", msg.chat_id, msg.message_id)
        return
    url = extract_url(msg.text)
    if not url:
        return

    rl: MediaRateLimiter = context.application.bot_data["rate_limiter"]
    store = _store(context)
    user = update.effective_user
    if not user:
        return
    if not rl.allow(user.id):
        await msg.reply_text(M.RATE_LIMIT)
        return
    if store.queue_full():
        await msg.reply_text(M.QUEUE_FULL.format(max_size=MAX_QUEUE_SIZE))
        return

    job_id = str(uuid.uuid4())
    ensure_job_dirs(job_id)
    inbox_dir = job_inbox_dir(job_id)
    status_msg = None

    try:
        status_msg = await msg.reply_text(M.URL_DOWNLOADING)
        job = store.create(
            job_id=job_id,
            job_type=JobType.TRANSCRIPT,
            user_id=user.id,
            chat_id=msg.chat_id,
            language=TELEGRAM_DEFAULT_LANGUAGE,
            message_id=msg.message_id,
            status_message_id=status_msg.message_id,
        )
        store.update_status(job_id, JobStatus.DOWNLOADING, publish=True)

        path = await asyncio.to_thread(
            download_media_url,
            url,
            inbox_dir,
            max_bytes=URL_DOWNLOAD_MAX_BYTES,
        )

        store.update_status(job_id, JobStatus.QUEUED, inbox_path=str(path), publish=True)
        job = store.get(job_id)
        if job:
            enqueue_transcript(store, job)
        await status_msg.edit_text(format_queue_accept_message(store))
        track_job(
            context.application,
            job_id=job_id,
            chat_id=msg.chat_id,
            status_message_id=status_msg.message_id,
            reply_to_message_id=msg.message_id,
        )
    except UrlDownloadError as exc:
        logger.warning("URL download failed for %s: %s", url[:80], exc)
        if store.get(job_id):
            store.update_status(job_id, JobStatus.FAILED, error=f"url_download: {exc}")
        # Сообщение в чат — только через notify (без дубля edit + send)
    except Exception:
        logger.exception("Failed to enqueue URL job")
        if store.get(job_id):
            store.update_status(job_id, JobStatus.FAILED, error="url_download: internal")


async def on_story_forward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Пересланная сторис — в API нет file_id, скачать нельзя."""
    message = update.effective_message
    if not message or not message.story:
        return
    if not await _guard_access(update, context):
        return
    await message.reply_text(M.UNSUPPORTED_STORY)


async def on_unsupported_visual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard_access(update, context):
        return
    await update.effective_message.reply_text(M.UNSUPPORTED_MEDIA)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update", exc_info=context.error)


def register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("whoami", cmd_whoami))
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("cancel", cmd_cancel))
    application.add_handler(CallbackQueryHandler(on_theses_callback, pattern=f"^{CALLBACK_THESES_PREFIX}"))

    application.add_handler(
        MessageHandler(
            filters.VIDEO
            | filters.VIDEO_NOTE
            | filters.ANIMATION
            | filters.AUDIO
            | filters.VOICE
            | filters.Document.ALL,
            on_media,
        )
    )
    application.add_handler(MessageHandler(_STORY_FORWARD, on_story_forward))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text_url))
    application.add_handler(MessageHandler(filters.PHOTO | filters.Sticker.ALL, on_unsupported_visual))
    application.add_error_handler(on_error)
