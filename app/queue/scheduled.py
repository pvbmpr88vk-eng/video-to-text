"""Promote due RQ scheduled jobs without a forked scheduler subprocess (macOS-safe)."""

from __future__ import annotations

import logging

from redis import Redis
from rq import Queue
from rq.job import Job
from rq.registry import ScheduledJobRegistry
from rq.utils import current_timestamp

logger = logging.getLogger(__name__)


def promote_scheduled_jobs(queue_name: str, connection: Redis) -> int:
    """Move jobs whose scheduled time has passed into the queue. Returns count promoted."""
    registry = ScheduledJobRegistry(queue_name, connection=connection)
    job_ids = registry.get_jobs_to_schedule(current_timestamp())
    if not job_ids:
        return 0

    queue = Queue(queue_name, connection=connection)
    promoted = 0
    with connection.pipeline() as pipeline:
        jobs = Job.fetch_many(job_ids, connection=connection)
        for job in jobs:
            if job is not None:
                queue._enqueue_job(job, pipeline=pipeline, at_front=job.should_enqueue_at_front())
                promoted += 1
        for job_id in job_ids:
            registry.remove(job_id, pipeline=pipeline)
        pipeline.execute()
    if promoted:
        logger.info("Promoted %s scheduled job(s) on queue %s", promoted, queue_name)
    return promoted
