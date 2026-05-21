"""Sync Redis job records with finished RQ jobs (e.g. OOM kill without Python exception)."""

from __future__ import annotations

import json
import logging

from rq.job import Job as RQJob

from app.jobs.models import Job, JobStatus, JobType
from app.jobs.store import JOB_KEY_PREFIX, JobStore

logger = logging.getLogger(__name__)

_STUCK_STATUSES = frozenset({JobStatus.EXTRACT, JobStatus.STT})


def _rq_failure_message(rq_job: RQJob) -> str:
    exc = (rq_job.exc_info or "").strip()
    if "signal 9" in exc.lower() or "sigkill" in exc.lower() or "out of memory" in exc.lower():
        return "stt:нехватка памяти — ролик слишком длинный для сервера (попробуйте до 45 мин или ссылку)"
    if exc:
        line = exc.splitlines()[-1][:240]
        return f"stt:worker failed ({line})"
    return "stt:worker failed (process killed or crashed)"


def sync_rq_failed_jobs(store: JobStore) -> int:
    """Mark store jobs failed when RQ already failed (OOM, SIGKILL, etc.)."""
    fixed = 0
    for key in store._redis.scan_iter(match=f"{JOB_KEY_PREFIX}*"):
        raw = store._redis.get(key)
        if not raw:
            continue
        try:
            job = Job.from_dict(json.loads(raw))
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
        if job.job_type != JobType.TRANSCRIPT:
            continue
        if job.status not in _STUCK_STATUSES or not job.rq_job_id:
            continue
        try:
            rq_job = RQJob.fetch(job.rq_job_id, connection=store._redis)
        except Exception:
            continue
        if rq_job.get_status() != "failed":
            continue
        store.update_status(
            job.job_id,
            JobStatus.FAILED,
            error=_rq_failure_message(rq_job),
            publish=True,
        )
        fixed += 1
        logger.warning("Synced failed RQ job %s -> store failed", job.job_id)
    if fixed:
        store.reconcile_queue_counter()
    return fixed
