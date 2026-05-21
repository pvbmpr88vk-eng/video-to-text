from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app.jobs.models import Job, JobStatus, JobType
from app.jobs.reconcile import sync_rq_failed_jobs
from app.jobs.store import JOB_KEY_PREFIX


def test_sync_rq_failed_jobs_updates_stuck_stt() -> None:
    job = Job(
        job_id="j1",
        job_type=JobType.TRANSCRIPT,
        status=JobStatus.STT,
        user_id=1,
        chat_id=1,
        rq_job_id="j1",
    )
    redis = MagicMock()
    redis.scan_iter.return_value = [f"{JOB_KEY_PREFIX}j1".encode()]
    redis.get.return_value = json.dumps(job.to_dict()).encode()

    rq_job = MagicMock()
    rq_job.get_status.return_value = "failed"
    rq_job.exc_info = "Work-horse terminated unexpectedly; waitpid returned 9 (signal 9)"

    store = MagicMock()
    store._redis = redis
    store.get.return_value = job

    with patch("app.jobs.reconcile.RQJob.fetch", return_value=rq_job):
        fixed = sync_rq_failed_jobs(store)

    assert fixed == 1
    store.update_status.assert_called_once()
    args, kwargs = store.update_status.call_args
    assert args[1] == JobStatus.FAILED
    assert "памяти" in kwargs["error"]
