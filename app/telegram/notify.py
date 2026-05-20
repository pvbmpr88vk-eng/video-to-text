from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application

from app.config import MAX_QUEUE_SIZE, TELEGRAM_STATUS_EDIT_MIN_SEC
from app.jobs.delivery import claim_telegram_delivery
from app.jobs.events import JOB_EVENTS_CHANNEL
from app.jobs.models import Job, JobStatus, JobType
from app.jobs.store import JobStore
from app.telegram import messages as M
from app.telegram.formatting import format_summary_for_chat, split_telegram_message
from app.telegram.jobs import CALLBACK_THESES_PREFIX
from app.telegram.queue_msg import format_queue_accept_message

logger = logging.getLogger(__name__)

STATUS_TEXT = {
    JobStatus.QUEUED: "В очереди…",
    JobStatus.DOWNLOADING: "Скачиваю файл…",
    JobStatus.EXTRACT: "Извлекаю аудио…",
    JobStatus.STT: "Распознаю речь (CPU, может занять долго)…",
    JobStatus.SUMMARY: M.SUMMARY_STARTED,
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
    if code == "no_audio":
        return M.ERR_NO_AUDIO
    if code == "ffmpeg_missing":
        return M.ERR_FFMPEG_MISSING
    if code == "stt_model":
        return M.ERR_STT_MODEL
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
    if not track and job.parent_job_id:
        track = tracked.get(job.parent_job_id)

    if job.status in (JobStatus.QUEUED, JobStatus.DOWNLOADING, JobStatus.EXTRACT, JobStatus.STT, JobStatus.SUMMARY):
        await _maybe_edit_status(app, job, track)
        return

    if job.status == JobStatus.DONE:
        if job.job_type == JobType.TRANSCRIPT:
            await _deliver_transcript(app, job, track)
        elif job.job_type == JobType.SUMMARY:
            await _deliver_summary(app, job, track)
        _untrack(app, job_id)
        if job.parent_job_id:
            _untrack(app, job.parent_job_id)
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
    text = STATUS_TEXT.get(job.status, "Обработка…")
    if job.status == JobStatus.QUEUED:
        store: JobStore = app.bot_data["job_store"]
        text = format_queue_accept_message(store)
    try:
        await app.bot.edit_message_text(
            chat_id=track.chat_id,
            message_id=track.status_message_id,
            text=text,
        )
        track.last_edit_at = now
    except Exception:
        logger.debug("status edit failed for job %s", job.job_id, exc_info=True)


async def _deliver_transcript(app: Application, job: Job, track: TrackedJob | None) -> None:
    redis = app.bot_data["redis"]
    if not claim_telegram_delivery(redis, job.job_id, "transcript"):
        logger.info("Skip duplicate transcript delivery for job %s", job.job_id)
        return
    chat_id = track.chat_id if track else job.chat_id
    if track and track.status_message_id:
        try:
            await app.bot.delete_message(chat_id=chat_id, message_id=track.status_message_id)
        except Exception:
            logger.debug("Could not delete status message", exc_info=True)

    txt_path = Path(job.transcript_txt) if job.transcript_txt else None
    if txt_path and txt_path.is_file():
        await app.bot.send_document(
            chat_id=chat_id,
            document=str(txt_path.resolve()),
            caption="Транскрипт (.txt)",
            reply_to_message_id=track.reply_to_message_id if track else job.message_id,
        )
        mins = job.duration_sec / 60.0 if job.duration_sec else 0.0
        stats = M.TRANSCRIPT_CAPTION.format(
            mins=mins,
            model=job.stt_model or "whisper",
            proc_min=job.processing_sec / 60.0,
        )
        msg = await app.bot.send_message(chat_id, stats, reply_markup=_theses_keyboard(job.job_id))
        track_theses_message(app, job.job_id, msg.message_id)
    else:
        await app.bot.send_message(chat_id, "Транскрипт не найден на диске.")


async def _deliver_summary(app: Application, job: Job, track: TrackedJob | None) -> None:
    redis = app.bot_data["redis"]
    if not claim_telegram_delivery(redis, job.job_id, "summary"):
        logger.info("Skip duplicate summary delivery for job %s", job.job_id)
        return
    chat_id = track.chat_id if track else job.chat_id
    parent_id = job.parent_job_id or job.job_id
    tracked: dict[str, TrackedJob] = app.bot_data.get("tracked_jobs", {})
    parent_track = tracked.get(parent_id, track)

    if parent_track and parent_track.theses_message_id:
        try:
            await app.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=parent_track.theses_message_id,
                reply_markup=None,
            )
        except Exception:
            logger.debug("Could not remove inline keyboard", exc_info=True)

    theses_path = Path(job.theses_json) if job.theses_json else None
    if theses_path and theses_path.is_file():
        payload = json.loads(theses_path.read_text(encoding="utf-8"))
        body = format_summary_for_chat(payload)
        for part in split_telegram_message(body):
            await app.bot.send_message(chat_id, part)
        await app.bot.send_message(
            chat_id,
            M.SUMMARY_DONE.format(
                proc_min=job.processing_sec / 60.0,
                model=job.llm_model or "ollama",
            ),
        )
    else:
        await app.bot.send_message(chat_id, M.ERR_SUMMARY.format(detail="theses file missing"))


async def _deliver_failure(app: Application, job: Job, track: TrackedJob | None) -> None:
    redis = app.bot_data["redis"]
    if not claim_telegram_delivery(redis, job.job_id, "failure"):
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
            return
        except Exception:
            logger.debug("Could not edit failure status", exc_info=True)
    await app.bot.send_message(chat_id, text)
