from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application

from app.config import MAX_QUEUE_SIZE, TELEGRAM_STATUS_EDIT_MIN_SEC, telegram_file_limit_mb
from app.jobs.delivery import (
    claim_telegram_delivery,
    clear_telegram_delivery,
    mark_telegram_delivered,
    was_telegram_delivered,
)
from app.jobs.events import JOB_EVENTS_CHANNEL
from app.jobs.models import Job, JobStatus, JobType
from app.jobs.store import JobStore
from app.telegram import messages as M
from app.telegram.files import document_upload_file
from app.telegram.formatting import format_summary_for_chat, split_telegram_message
from app.telegram.jobs import CALLBACK_THESES_PREFIX
from app.telegram.progress_text import format_job_status_message, format_theses_caption_progress
from app.telegram.queue_msg import format_queue_accept_message

logger = logging.getLogger(__name__)

STATUS_TEXT = {
    JobStatus.QUEUED: "В очереди…",
    JobStatus.DOWNLOADING: "Скачиваю файл…",
    JobStatus.EXTRACT: "Извлекаю аудио…",
    JobStatus.STT: "Распознавание",
    JobStatus.SUMMARY: "Тезисы",
}


@dataclass
class TrackedJob:
    job_id: str
    chat_id: int
    status_message_id: int | None = None
    reply_to_message_id: int | None = None
    theses_message_id: int | None = None
    last_edit_at: float = 0.0


def _theses_keyboard(job_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("📌 Сделать тезисы", callback_data=f"{CALLBACK_THESES_PREFIX}{job_id}")]]
    )


def _error_message(code: str) -> str:
    if code.startswith("url_download:"):
        return M.URL_DOWNLOAD_FAILED.format(detail=code.removeprefix("url_download:").strip())
    if code == "file_too_large":
        return M.FILE_TOO_LARGE_HINT.format(limit_mb=telegram_file_limit_mb())
    if code == "telegram_download_timeout":
        return M.TELEGRAM_DOWNLOAD_TIMEOUT
    if code == "telegram_download":
        return M.TELEGRAM_DOWNLOAD_FAILED
    if code == "no_audio":
        return M.ERR_NO_AUDIO
    if code == "ffmpeg_missing":
        return M.ERR_FFMPEG_MISSING
    if code == "stt_model":
        return M.ERR_STT_MODEL
    if code.startswith("audio_too_long:"):
        try:
            minutes = float(code.split(":", 1)[1])
        except ValueError:
            minutes = 0.0
        from app.config import STT_MAX_AUDIO_DURATION_MINUTES

        return M.ERR_AUDIO_TOO_LONG.format(
            minutes=minutes,
            limit_min=STT_MAX_AUDIO_DURATION_MINUTES,
        )
    if code.startswith("stt:"):
        return f"{M.ERR_STT} ({code[4:]})"
    if code.startswith("ffmpeg:"):
        return f"Ошибка FFmpeg: {code[7:]}"
    return M.ERR_SUMMARY.format(detail=code)


def track_job(
    app: Application,
    *,
    job_id: str,
    chat_id: int,
    status_message_id: int | None = None,
    reply_to_message_id: int | None = None,
) -> None:
    tracked: dict[str, TrackedJob] = app.bot_data.setdefault("tracked_jobs", {})
    tracked[job_id] = TrackedJob(
        job_id=job_id,
        chat_id=chat_id,
        status_message_id=status_message_id,
        reply_to_message_id=reply_to_message_id,
    )


def track_theses_message(app: Application, transcript_job_id: str, message_id: int) -> None:
    tracked: dict[str, TrackedJob] = app.bot_data.get("tracked_jobs", {})
    t = tracked.get(transcript_job_id)
    if t:
        t.theses_message_id = message_id


async def reset_theses_processing_caption(
    app: Application, *, chat_id: int, message_id: int
) -> None:
    try:
        await app.bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=M.TRANSCRIPT_CAPTION,
        )
    except Exception:
        logger.debug("Could not reset transcript caption", exc_info=True)


async def notify_summary_failed(
    app: Application, job: Job, *, detail: str
) -> None:
    chat_id = job.chat_id
    tracked: dict[str, TrackedJob] = app.bot_data.get("tracked_jobs", {})
    parent_id = job.parent_job_id or job.job_id
    parent_track = tracked.get(parent_id)
    if parent_track and parent_track.theses_message_id:
        await reset_theses_processing_caption(
            app,
            chat_id=chat_id,
            message_id=parent_track.theses_message_id,
        )
    await app.bot.send_message(chat_id, M.ERR_SUMMARY.format(detail=detail))


def _summary_queued_age_sec(job: Job) -> float:
    ts = job.updated_at or job.created_at
    if not ts:
        return 0.0
    try:
        anchor = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return max(0.0, datetime.now(timezone.utc).timestamp() - anchor.timestamp())


def _summary_queue_stuck(job: Job, *, timeout_sec: float = 600.0) -> bool:
    """True when summary stays queued with no RQ worker picking it up."""
    if job.status != JobStatus.QUEUED:
        return False
    if _summary_queued_age_sec(job) <= timeout_sec:
        return False
    if job.rq_job_id:
        from app.queue.enqueue import _rq_job_alive

        if _rq_job_alive(job.rq_job_id):
            return False
    return True


async def mark_theses_button_processing(
    app: Application,
    *,
    chat_id: int,
    message_id: int,
    parent_job_id: str,
) -> None:
    """Hide inline button and show in-caption progress on the transcript file."""
    track_theses_message(app, parent_job_id, message_id)
    try:
        await app.bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=None,
        )
    except Exception:
        logger.debug("Could not remove theses button", exc_info=True)
    try:
        caption = f"{M.TRANSCRIPT_CAPTION}\n⏳ Тезисы"
        await app.bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=caption,
        )
    except Exception:
        logger.debug("Could not set theses processing caption", exc_info=True)


async def start_notify_listener(app: Application) -> None:
    if app.bot_data.get("notify_task"):
        logger.warning("Notify listener already running — skip duplicate start")
        return
    redis = app.bot_data["redis"]
    pubsub = redis.pubsub()
    pubsub.subscribe(JOB_EVENTS_CHANNEL)
    app.bot_data["notify_pubsub"] = pubsub
    app.bot_data["notify_task"] = asyncio.create_task(_listen_loop(app, pubsub))


async def stop_notify_listener(app: Application) -> None:
    task: asyncio.Task | None = app.bot_data.pop("notify_task", None)
    pubsub = app.bot_data.pop("notify_pubsub", None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    if pubsub is not None:
        try:
            pubsub.unsubscribe(JOB_EVENTS_CHANNEL)
            pubsub.close()
        except Exception:
            logger.debug("pubsub close failed", exc_info=True)


async def _listen_loop(app: Application, pubsub) -> None:
    loop = asyncio.get_running_loop()
    while True:
        try:
            message = await loop.run_in_executor(None, pubsub.get_message, True, 1.0)
        except Exception:
            logger.debug("pubsub get_message failed", exc_info=True)
            await asyncio.sleep(1.0)
            continue
        if not message or message.get("type") != "message":
            continue
        raw = message.get("data")
        if isinstance(raw, bytes):
            raw = raw.decode()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        job_id = payload.get("job_id")
        if not job_id:
            continue
        try:
            await _handle_job_event(app, job_id)
        except Exception:
            logger.exception("notify handler failed for job %s", job_id)


async def _handle_job_event(app: Application, job_id: str) -> None:
    store: JobStore = app.bot_data["job_store"]
    job = store.get(job_id)
    if not job:
        return

    tracked: dict[str, TrackedJob] = app.bot_data.get("tracked_jobs", {})
    track = tracked.get(job_id)
    if not track and job.parent_job_id and job.job_type != JobType.SUMMARY:
        track = tracked.get(job.parent_job_id)

    if job.status in (JobStatus.QUEUED, JobStatus.DOWNLOADING, JobStatus.EXTRACT, JobStatus.STT, JobStatus.SUMMARY):
        if job.job_type == JobType.SUMMARY:
            await _maybe_edit_summary_progress(app, job, track)
        else:
            await _maybe_edit_status(app, job, track)
        return

    if job.status == JobStatus.DONE:
        if job.job_type == JobType.TRANSCRIPT:
            await _deliver_transcript(app, job, track)
        elif job.job_type == JobType.SUMMARY:
            await try_deliver_summary(app, job.job_id)
        return

    if job.status in (JobStatus.FAILED, JobStatus.TIMEOUT, JobStatus.CANCELLED):
        await _deliver_failure(app, job, track)
        _untrack(app, job_id)


def _untrack(app: Application, job_id: str) -> None:
    app.bot_data.get("tracked_jobs", {}).pop(job_id, None)


async def _maybe_edit_status(app: Application, job: Job, track: TrackedJob | None) -> None:
    if not track or not track.status_message_id:
        return
    now = time.monotonic()
    if now - track.last_edit_at < TELEGRAM_STATUS_EDIT_MIN_SEC:
        return
    store: JobStore = app.bot_data["job_store"]
    text = format_job_status_message(job, store)
    try:
        await app.bot.edit_message_text(
            chat_id=track.chat_id,
            message_id=track.status_message_id,
            text=text,
        )
        track.last_edit_at = now
    except Exception:
        logger.debug("status edit failed for job %s", job.job_id, exc_info=True)


async def _maybe_edit_summary_progress(
    app: Application, job: Job, track: TrackedJob | None
) -> None:
    parent_id = job.parent_job_id or job.job_id
    tracked: dict[str, TrackedJob] = app.bot_data.get("tracked_jobs", {})
    parent_track = tracked.get(parent_id) or track
    if not parent_track or not parent_track.theses_message_id:
        return
    now = time.monotonic()
    if now - parent_track.last_edit_at < TELEGRAM_STATUS_EDIT_MIN_SEC:
        return
    caption = format_theses_caption_progress(job)
    try:
        await app.bot.edit_message_caption(
            chat_id=parent_track.chat_id,
            message_id=parent_track.theses_message_id,
            caption=caption,
        )
        parent_track.last_edit_at = now
    except Exception:
        logger.debug("summary caption edit failed for job %s", job.job_id, exc_info=True)


async def _deliver_transcript(app: Application, job: Job, track: TrackedJob | None) -> None:
    redis = app.bot_data["redis"]
    if was_telegram_delivered(redis, job.job_id, "transcript"):
        logger.info("Skip duplicate transcript delivery for job %s", job.job_id)
        return
    chat_id = track.chat_id if track else job.chat_id
    reply_to = track.reply_to_message_id if track else job.message_id

    txt_path = Path(job.transcript_txt) if job.transcript_txt else None
    if not txt_path or not txt_path.is_file():
        await app.bot.send_message(chat_id, "Транскрипт не найден на диске.")
        mark_telegram_delivered(redis, job.job_id, "transcript")
        return

    try:
        doc = await app.bot.send_document(
            chat_id=chat_id,
            document=document_upload_file(txt_path),
            caption=M.TRANSCRIPT_CAPTION,
            reply_markup=_theses_keyboard(job.job_id),
            reply_to_message_id=reply_to,
        )
    except Exception:
        logger.exception("Failed to send transcript for job %s", job.job_id)
        if track and track.status_message_id:
            try:
                await app.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=track.status_message_id,
                    text=M.TRANSCRIPT_SEND_FAILED,
                )
            except Exception:
                await app.bot.send_message(chat_id, M.TRANSCRIPT_SEND_FAILED, reply_to_message_id=reply_to)
        else:
            await app.bot.send_message(chat_id, M.TRANSCRIPT_SEND_FAILED, reply_to_message_id=reply_to)
        return

    if track and track.status_message_id:
        try:
            await app.bot.delete_message(chat_id=chat_id, message_id=track.status_message_id)
        except Exception:
            logger.debug("Could not delete status message", exc_info=True)

    track_theses_message(app, job.job_id, doc.message_id)
    mark_telegram_delivered(redis, job.job_id, "transcript")


def _summary_track(app: Application, job: Job, track: TrackedJob | None) -> TrackedJob | None:
    if track:
        return track
    tracked: dict[str, TrackedJob] = app.bot_data.get("tracked_jobs", {})
    if job.parent_job_id:
        return tracked.get(job.parent_job_id)
    return None


async def _send_summary_messages(
    app: Application, job: Job, track: TrackedJob | None
) -> None:
    chat_id = track.chat_id if track else job.chat_id
    parent_id = job.parent_job_id or job.job_id
    tracked: dict[str, TrackedJob] = app.bot_data.get("tracked_jobs", {})
    parent_track = tracked.get(parent_id, track)

    status_message_id = (track.status_message_id if track else None) or job.status_message_id
    if status_message_id:
        try:
            await app.bot.delete_message(chat_id=chat_id, message_id=status_message_id)
        except Exception:
            logger.debug("Could not delete summary status message", exc_info=True)

    if parent_track and parent_track.theses_message_id:
        try:
            await app.bot.edit_message_caption(
                chat_id=chat_id,
                message_id=parent_track.theses_message_id,
                caption=M.TRANSCRIPT_CAPTION,
            )
        except Exception:
            logger.debug("Could not reset transcript caption", exc_info=True)

    theses_path = Path(job.theses_json) if job.theses_json else None
    if not theses_path or not theses_path.is_file():
        raise FileNotFoundError("theses file missing")

    payload = json.loads(theses_path.read_text(encoding="utf-8"))
    body = format_summary_for_chat(payload)
    reply_to = parent_track.theses_message_id if parent_track else None
    for i, part in enumerate(split_telegram_message(body)):
        await app.bot.send_message(
            chat_id,
            part,
            reply_to_message_id=reply_to if i == 0 else None,
        )


async def try_deliver_summary(app: Application, job_id: str) -> bool:
    """Deliver summary to chat once. Returns True if already sent or sent now."""
    redis = app.bot_data["redis"]
    if was_telegram_delivered(redis, job_id, "summary"):
        return True

    store: JobStore = app.bot_data["job_store"]
    job = store.get(job_id)
    if not job or job.job_type != JobType.SUMMARY or job.status != JobStatus.DONE:
        return False

    if not claim_telegram_delivery(redis, job_id, "summary"):
        return was_telegram_delivered(redis, job_id, "summary")

    tracked: dict[str, TrackedJob] = app.bot_data.get("tracked_jobs", {})
    track = tracked.get(job_id) or _summary_track(app, job, None)
    try:
        await _send_summary_messages(app, job, track)
    except Exception:
        clear_telegram_delivery(redis, job_id, "summary")
        logger.exception("Summary delivery failed for job %s", job_id)
        chat_id = track.chat_id if track else job.chat_id
        try:
            await app.bot.send_message(
                chat_id,
                M.ERR_SUMMARY.format(detail="не удалось отправить тезисы"),
            )
        except Exception:
            logger.debug("Could not send summary delivery error", exc_info=True)
        return False

    mark_telegram_delivered(redis, job_id, "summary")
    _untrack(app, job_id)
    if job.parent_job_id:
        _untrack(app, job.parent_job_id)
    return True


async def schedule_summary_delivery(app: Application, job_id: str) -> None:
    """Poll until summary is ready and deliver (covers missed pubsub events)."""
    from app.queue.enqueue import ensure_summary_queued

    store: JobStore = app.bot_data["job_store"]
    for _ in range(600):
        if was_telegram_delivered(app.bot_data["redis"], job_id, "summary"):
            return
        job = store.get(job_id)
        if not job:
            return
        if job.status == JobStatus.QUEUED:
            ensure_summary_queued(store, job)
            job = store.get(job_id) or job
            if _summary_queue_stuck(job):
                active = store.count_active_summaries()
                if active > 0:
                    detail = (
                        "другая задача тезисов зависла. Нажмите «Сделать тезисы» ещё раз "
                        "или перезапустите worker summary."
                    )
                else:
                    detail = "задача не попала в очередь. Нажмите «Сделать тезисы» ещё раз."
                store.update_status(job_id, JobStatus.FAILED, error="summary_queue_timeout")
                await notify_summary_failed(app, job, detail=detail)
                return
        if job.status == JobStatus.DONE:
            if await try_deliver_summary(app, job_id):
                return
        elif job.status in (JobStatus.FAILED, JobStatus.TIMEOUT, JobStatus.CANCELLED):
            await _handle_job_event(app, job_id)
            fresh = store.get(job_id)
            if fresh and fresh.status in (
                JobStatus.FAILED,
                JobStatus.TIMEOUT,
                JobStatus.CANCELLED,
            ):
                if not was_telegram_delivered(app.bot_data["redis"], job_id, "failure"):
                    await notify_summary_failed(
                        app,
                        fresh,
                        detail=fresh.error or fresh.status.value,
                    )
                    mark_telegram_delivered(app.bot_data["redis"], job_id, "failure")
            return
        await asyncio.sleep(1)


def ensure_summary_delivery(app: Application, job_id: str) -> None:
    """Start background watcher after user requests theses."""
    app.bot_data.setdefault("summary_delivery_tasks", {})
    tasks: dict[str, asyncio.Task] = app.bot_data["summary_delivery_tasks"]
    old = tasks.pop(job_id, None)
    if old and not old.done():
        old.cancel()
    tasks[job_id] = asyncio.create_task(schedule_summary_delivery(app, job_id))


async def _deliver_failure(app: Application, job: Job, track: TrackedJob | None) -> None:
    redis = app.bot_data["redis"]
    if was_telegram_delivered(redis, job.job_id, "failure"):
        logger.info("Skip duplicate failure delivery for job %s", job.job_id)
        return
    chat_id = track.chat_id if track else job.chat_id
    detail = job.error or job.status.value
    text = _error_message(detail) if job.job_type == JobType.TRANSCRIPT else M.ERR_SUMMARY.format(detail=detail)
    status_message_id = (track.status_message_id if track else None) or job.status_message_id
    if status_message_id:
        try:
            await app.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message_id,
                text=text,
            )
            mark_telegram_delivered(redis, job.job_id, "failure")
            return
        except Exception:
            logger.debug("Could not edit failure status", exc_info=True)
    await app.bot.send_message(chat_id, text)
    mark_telegram_delivered(redis, job.job_id, "failure")
