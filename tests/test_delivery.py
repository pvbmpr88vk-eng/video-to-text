from __future__ import annotations

import fakeredis

from app.jobs.delivery import claim_telegram_delivery
from app.jobs.models import JobStatus, JobType
from app.jobs.store import JobStore


def test_claim_telegram_delivery_once():
    redis = fakeredis.FakeRedis(decode_responses=False)
    assert claim_telegram_delivery(redis, "j1", "transcript") is True
    assert claim_telegram_delivery(redis, "j1", "transcript") is False


def test_find_summary_for_parent():
    redis = fakeredis.FakeRedis(decode_responses=False)
    store = JobStore(redis)
    parent = store.create(
        job_id="p1",
        job_type=JobType.TRANSCRIPT,
        user_id=1,
        chat_id=1,
    )
    store.update_status(parent.job_id, JobStatus.DONE, publish=False)
    child = store.create(
        job_id="s1",
        job_type=JobType.SUMMARY,
        user_id=1,
        chat_id=1,
        parent_job_id=parent.job_id,
    )
    found = store.find_summary_for_parent("p1")
    assert found is not None
    assert found.job_id == child.job_id
