from __future__ import annotations

import logging

from rq.job import Job as RQJob

from app.jobs.models import Job, JobStatus, JobType
from app.jobs.store import JobStore
from app.queue.rq_connection import (
    DEFAULT_RETRY,
    get_redis,
    get_summary_queue,
    get_transcript_queue,
)
from app.queue.tasks import summary_task, transcript_task

logger = logging.getLogger(__name__)


def _attach_rq_id(store: JobStore, job: Job, rq_job: RQJob) -> None:
    store.set_rq_job_id(job.job_id, rq_job.id)


def _drop_stale_rq_job(job_id: str) -> None:
    """Remove finished/scheduled RQ job so enqueue with same job_id works."""
    redis = get_redis()
    try:
        rq_job = RQJob.fetch(job_id, connection=redis)
    except Exception:
        return
    try:
        rq_job.cancel()
    except Exception:
        pass
    try:
        rq_job.delete()
    except Exception:
        logger.debug("Could not delete stale RQ job %s", job_id, exc_info=True)


def enqueue_transcript(store: JobStore, job: Job) -> RQJob:
    _drop_stale_rq_job(job.job_id)
    queue = get_transcript_queue()
    rq_job = queue.enqueue(
        transcript_task,
        job.job_id,
        job_id=job.job_id,
        retry=DEFAULT_RETRY,
        meta={"job_id": job.job_id, "user_id": job.user_id},
    )
    _attach_rq_id(store, job, rq_job)
    logger.info("Enqueued transcript job %s as RQ %s", job.job_id, rq_job.id)
    return rq_job


def _rq_job_alive(rq_job_id: str) -> bool:
    try:
        rq_job = RQJob.fetch(rq_job_id, connection=get_redis())
    except Exception:
        return False
    return rq_job.get_status() in ("queued", "scheduled", "started", "deferred")


def ensure_summary_queued(store: JobStore, job: Job | str) -> RQJob | None:
    """
    Ensure a summary job is registered in the RQ summary queue.
    Fixes jobs stuck in Redis as queued without rq_job_id (e.g. after bot restart).
    """
    resolved = store.get(job.job_id) if isinstance(job, Job) else store.get(job)
    if not resolved or resolved.job_type != JobType.SUMMARY:
        return None
    if resolved.status in (JobStatus.DONE, JobStatus.CANCELLED):
        return None
    if resolved.status == JobStatus.FAILED:
        store.update_status(resolved.job_id, JobStatus.QUEUED, error=None)
        resolved = store.get(resolved.job_id) or resolved
    if resolved.status == JobStatus.SUMMARY:
        return None
    if resolved.status != JobStatus.QUEUED:
        return None

    if resolved.rq_job_id and _rq_job_alive(resolved.rq_job_id):
        return None

    _drop_stale_rq_job(resolved.job_id)
    rq_job = enqueue_summary(store, resolved)
    logger.info("Re-queued summary job %s as RQ %s", resolved.job_id, rq_job.id)
    return rq_job


def enqueue_summary(store: JobStore, job: Job) -> RQJob:
    _drop_stale_rq_job(job.job_id)
    queue = get_summary_queue()
    rq_job = queue.enqueue(
        summary_task,
        job.job_id,
        job_id=job.job_id,
        retry=DEFAULT_RETRY,
        meta={"job_id": job.job_id, "user_id": job.user_id, "parent": job.parent_job_id},
    )
    _attach_rq_id(store, job, rq_job)
    logger.info("Enqueued summary job %s as RQ %s", job.job_id, rq_job.id)
    return rq_job


def cancel_rq_job(rq_job_id: str | None) -> bool:
    if not rq_job_id:
        return False
    try:
        redis = get_redis()
        rq_job = RQJob.fetch(rq_job_id, connection=redis)
        status = rq_job.get_status()
        rq_job.cancel()
        if status in ("started", "deferred"):
            try:
                from rq.command import send_stop_job_command

                if rq_job.worker_name:
                    send_stop_job_command(redis, rq_job.worker_name)
            except Exception:
                logger.debug("send_stop_job_command failed", exc_info=True)
        return True
    except Exception:
        logger.debug("Could not cancel RQ job %s", rq_job_id, exc_info=True)
        return False
