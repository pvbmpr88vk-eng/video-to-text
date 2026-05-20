from __future__ import annotations

import logging

from rq.job import Job as RQJob

from app.jobs.models import JobStatus, JobType
from app.jobs.store import JobStore
from app.queue.rq_connection import get_redis, get_summary_queue, get_transcript_queue
from app.queue.scheduled import promote_scheduled_jobs
from app.queue.tasks import SUMMARY_INFLIGHT_KEY

logger = logging.getLogger(__name__)


def reset_stuck_jobs(store: JobStore | None = None) -> dict[str, int]:
    """
    Recover from zombie EXTRACT/STT jobs and drifted queue counter.
    Does not stop a running worker process — restart worker transcript after this.
    """
    redis = get_redis()
    store = store or JobStore(redis)
    stats = {
        "processing_failed": 0,
        "waiting_failed": 0,
        "rq_canceled": 0,
        "summary_requeued": 0,
    }

    for key in redis.scan_iter(match="job:*"):
        raw = redis.get(key)
        if not raw:
            continue
        if isinstance(raw, bytes):
            raw = raw.decode()
        try:
            import json
            from app.jobs.models import Job

            job = Job.from_dict(json.loads(raw))
        except Exception:
            continue
        if job.job_type == JobType.SUMMARY and job.status == JobStatus.SUMMARY:
            store.update_status(
                job.job_id,
                JobStatus.QUEUED,
                error=None,
            )
            stats["summary_requeued"] += 1
            continue
        if job.job_type != JobType.TRANSCRIPT:
            continue
        if job.status in (JobStatus.EXTRACT, JobStatus.STT):
            store.update_status(
                job.job_id,
                JobStatus.FAILED,
                error="stuck: сброс (перезапустите worker transcript и отправьте файл снова)",
            )
            stats["processing_failed"] += 1
        elif job.status in (JobStatus.QUEUED, JobStatus.DOWNLOADING):
            store.update_status(
                job.job_id,
                JobStatus.FAILED,
                error="stuck: задача в очереди сброшена",
            )
            stats["waiting_failed"] += 1

    tq = get_transcript_queue()
    for registry in (
        tq.started_job_registry,
        tq.deferred_job_registry,
        tq.scheduled_job_registry,
    ):
        for rq_id in registry.get_job_ids():
            try:
                rj = RQJob.fetch(rq_id, connection=redis)
                rj.cancel()
                stats["rq_canceled"] += 1
            except Exception:
                logger.debug("Could not cancel RQ job %s", rq_id, exc_info=True)

    for rq_id in tq.job_ids:
        try:
            RQJob.fetch(rq_id, connection=redis).cancel()
            stats["rq_canceled"] += 1
        except Exception:
            logger.debug("Could not cancel queued RQ job %s", rq_id, exc_info=True)

    waiting = store.reconcile_queue_counter()
    stats["queue_waiting"] = waiting
    redis.set(SUMMARY_INFLIGHT_KEY, 0)
    stats["scheduled_promoted"] = 0
    for q in (get_transcript_queue(), get_summary_queue()):
        stats["scheduled_promoted"] += promote_scheduled_jobs(q.name, redis)

    from app.queue.enqueue import enqueue_summary

    for key in redis.scan_iter(match="job:*"):
        raw = redis.get(key)
        if not raw:
            continue
        if isinstance(raw, bytes):
            raw = raw.decode()
        try:
            import json
            from app.jobs.models import Job

            job = Job.from_dict(json.loads(raw))
        except Exception:
            continue
        if job.job_type == JobType.SUMMARY and job.status == JobStatus.QUEUED:
            try:
                enqueue_summary(store, job)
                stats["summary_requeued"] += 1
            except Exception:
                logger.debug("Could not re-enqueue summary %s", job.job_id, exc_info=True)

    return stats
