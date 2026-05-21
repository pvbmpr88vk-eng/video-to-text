from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app.jobs.models import Job, JobStatus, JobType
from app.jobs.store import JOB_KEY_PREFIX, JobStore


def test_fail_stale_downloading_jobs() -> None:
    old = Job(
        job_id="old-dl",
        job_type=JobType.TRANSCRIPT,
        status=JobStatus.DOWNLOADING,
        user_id=1,
        chat_id=1,
        updated_at=(datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat(),
    )
    fresh = Job(
        job_id="fresh-dl",
        job_type=JobType.TRANSCRIPT,
        status=JobStatus.DOWNLOADING,
        user_id=1,
        chat_id=1,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    redis = MagicMock()
    redis.scan_iter.return_value = [
        f"{JOB_KEY_PREFIX}old-dl".encode(),
        f"{JOB_KEY_PREFIX}fresh-dl".encode(),
    ]

    def fake_get(key):
        if key.endswith(b"old-dl"):
            return json.dumps(old.to_dict()).encode()
        if key.endswith(b"fresh-dl"):
            return json.dumps(fresh.to_dict()).encode()
        return None

    redis.get.side_effect = fake_get
    store = JobStore(redis)
    store.update_status = MagicMock(side_effect=lambda jid, status, **kw: None)  # type: ignore[method-assign]
    store.reconcile_queue_counter = MagicMock(return_value=0)  # type: ignore[method-assign]

    failed = store.fail_stale_downloading_jobs(max_age_sec=600)
    assert failed == 1
    store.update_status.assert_called_once()
    assert store.update_status.call_args[0][0] == "old-dl"
