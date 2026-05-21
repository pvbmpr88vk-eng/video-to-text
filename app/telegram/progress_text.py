"""Format progress + ETA for Telegram status messages."""

from __future__ import annotations

from app.jobs.models import Job, JobStatus
from app.jobs.store import JobStore
from app.telegram import messages as M
from app.telegram.queue_msg import format_queue_accept_message


def format_eta(sec: float | None) -> str | None:
    if sec is None or sec <= 0:
        return None
    sec = int(sec)
    if sec < 60:
        return f"~{sec} сек"
    if sec < 3600:
        return f"~{sec // 60} мин"
    hours = sec // 3600
    minutes = (sec % 3600) // 60
    if minutes:
        return f"~{hours} ч {minutes} мин"
    return f"~{hours} ч"


def _base_status_text(job: Job, store: JobStore | None) -> str:
    if job.status == JobStatus.QUEUED and store is not None:
        return format_queue_accept_message(store)
    mapping = {
        JobStatus.DOWNLOADING: M.DOWNLOADING,
        JobStatus.EXTRACT: "Извлекаю аудио…",
        JobStatus.STT: "Распознавание",
        JobStatus.SUMMARY: "Тезисы",
    }
    return mapping.get(job.status, "Обработка…")


def format_job_status_message(job: Job, store: JobStore | None = None) -> str:
    base = _base_status_text(job, store)
    if job.progress_pct is None:
        return base
    title = base
    if job.status in (JobStatus.STT, JobStatus.SUMMARY) and job.progress_label:
        title = job.progress_label
    parts = [title, f"Прогресс: {job.progress_pct:.0f}%"]
    eta = format_eta(job.progress_eta_sec)
    if eta and (job.progress_pct or 0) < 99:
        parts.append(f"Осталось: {eta}")
    return "\n".join(parts)


def format_theses_caption_progress(job: Job) -> str:
    base = M.TRANSCRIPT_CAPTION
    if job.progress_pct is None:
        return f"{base}\n⏳ Тезисы"
    parts = [base, f"⏳ Тезисы: {job.progress_pct:.0f}%"]
    eta = format_eta(job.progress_eta_sec)
    if eta and (job.progress_pct or 0) < 99:
        parts.append(f"Осталось: {eta}")
    return "\n".join(parts)
