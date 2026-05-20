from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import fakeredis
import pytest

from app.jobs.models import JobType
from app.jobs.store import JobStore
from app.queue.enqueue import cancel_rq_job, enqueue_summary, enqueue_transcript


@pytest.fixture
def redis_conn():
    return fakeredis.FakeRedis(decode_responses=False)


@pytest.fixture
def store(redis_conn):
    return JobStore(redis_conn)


def test_enqueue_transcript_attaches_rq_id(store: JobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_queue = MagicMock()
    fake_rq_job = MagicMock()
    fake_rq_job.id = "rq-transcript-1"
    fake_queue.enqueue.return_value = fake_rq_job
    monkeypatch.setattr("app.queue.enqueue.get_transcript_queue", lambda: fake_queue)

    job_id = str(uuid.uuid4())
    job = store.create(
        job_id=job_id,
        job_type=JobType.TRANSCRIPT,
        user_id=1,
        chat_id=100,
    )
    rq_job = enqueue_transcript(store, job)

    assert rq_job.id == "rq-transcript-1"
    fake_queue.enqueue.assert_called_once()
    updated = store.get(job_id)
    assert updated is not None
    assert updated.rq_job_id == "rq-transcript-1"


def test_enqueue_summary_attaches_rq_id(store: JobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_queue = MagicMock()
    fake_rq_job = MagicMock()
    fake_rq_job.id = "rq-summary-1"
    fake_queue.enqueue.return_value = fake_rq_job
    monkeypatch.setattr("app.queue.enqueue.get_summary_queue", lambda: fake_queue)

    job_id = str(uuid.uuid4())
    job = store.create(
        job_id=job_id,
        job_type=JobType.SUMMARY,
        user_id=2,
        chat_id=200,
        parent_job_id=str(uuid.uuid4()),
    )
    rq_job = enqueue_summary(store, job)

    assert rq_job.id == "rq-summary-1"
    updated = store.get(job_id)
    assert updated is not None
    assert updated.rq_job_id == "rq-summary-1"


def test_cancel_rq_job_no_id() -> None:
    assert cancel_rq_job(None) is False


def test_cancel_rq_job_fetches_and_cancels(store: JobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_rq_job = MagicMock()
    monkeypatch.setattr("app.queue.enqueue.RQJob.fetch", lambda _id, connection: fake_rq_job)

    assert cancel_rq_job("rq-999") is True
    fake_rq_job.cancel.assert_called_once()
