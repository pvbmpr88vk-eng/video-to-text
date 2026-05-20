from __future__ import annotations

import uuid

import fakeredis
import pytest

from app.config import MAX_QUEUE_SIZE
from app.jobs.models import JobStatus, JobType
from app.jobs.store import JobStore


@pytest.fixture
def redis_conn():
    return fakeredis.FakeRedis(decode_responses=False)


@pytest.fixture
def store(redis_conn):
    return JobStore(redis_conn)


def test_create_and_get_transcript_job(store: JobStore) -> None:
    job_id = str(uuid.uuid4())
    job = store.create(
        job_id=job_id,
        job_type=JobType.TRANSCRIPT,
        user_id=42,
        chat_id=100,
        inbox_path="/tmp/inbox/file.mp4",
    )
    assert job.status == JobStatus.QUEUED
    assert store.queued_transcript_count() == 1

    loaded = store.get(job_id)
    assert loaded is not None
    assert loaded.user_id == 42
    assert loaded.inbox_path == "/tmp/inbox/file.mp4"


def test_queue_counter_decrements_on_worker_start(store: JobStore) -> None:
    job_id = str(uuid.uuid4())
    store.create(
        job_id=job_id,
        job_type=JobType.TRANSCRIPT,
        user_id=1,
        chat_id=1,
    )
    assert store.queued_transcript_count() == 1

    store.update_status(job_id, JobStatus.DOWNLOADING)
    assert store.queued_transcript_count() == 1

    store.update_status(job_id, JobStatus.QUEUED)
    assert store.queued_transcript_count() == 1

    store.update_status(job_id, JobStatus.EXTRACT)
    assert store.queued_transcript_count() == 0


def test_queue_full(store: JobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.jobs.store.MAX_QUEUE_SIZE", 2)
    for i in range(2):
        store.create(
            job_id=str(uuid.uuid4()),
            job_type=JobType.TRANSCRIPT,
            user_id=i,
            chat_id=i,
        )
    assert store.queue_full() is True


def test_summary_job_does_not_affect_queue_counter(store: JobStore) -> None:
    job_id = str(uuid.uuid4())
    store.create(
        job_id=job_id,
        job_type=JobType.SUMMARY,
        user_id=1,
        chat_id=1,
        parent_job_id=str(uuid.uuid4()),
    )
    assert store.queued_transcript_count() == 0


def test_cancel_job(store: JobStore) -> None:
    job_id = str(uuid.uuid4())
    store.create(
        job_id=job_id,
        job_type=JobType.TRANSCRIPT,
        user_id=7,
        chat_id=7,
    )
    cancelled = store.cancel(job_id)
    assert cancelled is not None
    assert cancelled.status == JobStatus.CANCELLED


def test_queue_counter_decrements_on_download_failure(store: JobStore) -> None:
    job_id = str(uuid.uuid4())
    store.create(
        job_id=job_id,
        job_type=JobType.TRANSCRIPT,
        user_id=1,
        chat_id=1,
    )
    store.update_status(job_id, JobStatus.DOWNLOADING)
    store.update_status(job_id, JobStatus.FAILED, error="file_too_large")
    assert store.queued_transcript_count() == 0


def test_queue_three_users_position(store: JobStore) -> None:
    """DoD A: three users enqueue → counter shows 3 waiting."""
    for i in range(3):
        store.create(
            job_id=str(uuid.uuid4()),
            job_type=JobType.TRANSCRIPT,
            user_id=i,
            chat_id=i,
        )
    assert store.queued_transcript_count() == 3


def test_list_user_jobs(store: JobStore) -> None:
    uid = 99
    ids = [str(uuid.uuid4()) for _ in range(3)]
    for jid in ids:
        store.create(job_id=jid, job_type=JobType.TRANSCRIPT, user_id=uid, chat_id=1)
    jobs = store.list_user_jobs(uid, limit=10)
    assert len(jobs) == 3
