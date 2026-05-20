from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from redis import Redis

from app.config import MAX_QUEUE_SIZE
from app.jobs.events import publish_job_event
from app.jobs.models import Job, JobStatus, JobType

_TRANSCRIPT_LEFT_QUEUE = frozenset(
    {
        JobStatus.EXTRACT,
        JobStatus.STT,
        JobStatus.DONE,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
        JobStatus.TIMEOUT,
    }
)
_TRANSCRIPT_WAITING = frozenset({JobStatus.QUEUED, JobStatus.DOWNLOADING})
_TRANSCRIPT_PROCESSING = frozenset({JobStatus.EXTRACT, JobStatus.STT})
JOB_KEY_PREFIX = "job:"
USER_JOBS_PREFIX = "user_jobs:"
QUEUE_COUNTER_KEY = "queue:transcript:queued_count"


class JobStore:
    def __init__(self, redis_conn: Redis) -> None:
        self._redis = redis_conn

    def _key(self, job_id: str) -> str:
        return f"{JOB_KEY_PREFIX}{job_id}"

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def save(self, job: Job, *, publish: bool = True) -> None:
        job.updated_at = self._now()
        self._redis.set(self._key(job.job_id), json.dumps(job.to_dict(), ensure_ascii=False))
        self._redis.sadd(f"{USER_JOBS_PREFIX}{job.user_id}", job.job_id)
        if publish:
            publish_job_event(
                self._redis,
                job_id=job.job_id,
                event="status_changed",
                extra={"status": job.status.value},
            )

    def create(
        self,
        *,
        job_id: str,
        job_type: JobType,
        user_id: int,
        chat_id: int,
        language: str = "ru",
        message_id: int | None = None,
        status_message_id: int | None = None,
        parent_job_id: str | None = None,
        inbox_path: str | None = None,
    ) -> Job:
        now = self._now()
        job = Job(
            job_id=job_id,
            job_type=job_type,
            status=JobStatus.QUEUED,
            user_id=user_id,
            chat_id=chat_id,
            language=language,
            message_id=message_id,
            status_message_id=status_message_id,
            parent_job_id=parent_job_id,
            inbox_path=inbox_path,
            created_at=now,
            updated_at=now,
        )
        self.save(job)
        if job_type == JobType.TRANSCRIPT:
            self._redis.incr(QUEUE_COUNTER_KEY)
        return job

    def get(self, job_id: str) -> Job | None:
        raw = self._redis.get(self._key(job_id))
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        data = json.loads(raw)
        return Job.from_dict(data)

    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error: str | None = None,
        publish: bool = True,
        **fields: Any,
    ) -> Job | None:
        job = self.get(job_id)
        if not job:
            return None
        prev = job.status
        job.status = status
        if error is not None:
            job.error = error
        for k, v in fields.items():
            if hasattr(job, k):
                setattr(job, k, v)
        self.save(job, publish=publish)
        if (
            prev in _TRANSCRIPT_WAITING
            and status in _TRANSCRIPT_LEFT_QUEUE
            and job.job_type == JobType.TRANSCRIPT
        ):
            self._redis.decr(QUEUE_COUNTER_KEY)
        return job

    def set_rq_job_id(self, job_id: str, rq_job_id: str) -> None:
        job = self.get(job_id)
        if not job:
            return
        job.rq_job_id = rq_job_id
        self.save(job, publish=False)

    def list_user_jobs(self, user_id: int, limit: int = 10) -> list[Job]:
        ids = list(self._redis.smembers(f"{USER_JOBS_PREFIX}{user_id}"))[-limit:]
        out: list[Job] = []
        for raw_id in ids:
            jid = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
            job = self.get(jid)
            if job:
                out.append(job)
        return out

    def queued_transcript_count(self) -> int:
        val = self._redis.get(QUEUE_COUNTER_KEY)
        return max(0, int(val or 0))

    def count_active_summaries(self) -> int:
        """Jobs currently in SUMMARY status (replaces drift-prone Redis inflight counter)."""
        count = 0
        for key in self._redis.scan_iter(match=f"{JOB_KEY_PREFIX}*"):
            raw = self._redis.get(key)
            if not raw:
                continue
            if isinstance(raw, bytes):
                raw = raw.decode()
            try:
                job = Job.from_dict(json.loads(raw))
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
            if job.job_type == JobType.SUMMARY and job.status == JobStatus.SUMMARY:
                count += 1
        return count

    def count_processing_transcripts(self) -> int:
        count = 0
        for key in self._redis.scan_iter(match=f"{JOB_KEY_PREFIX}*"):
            raw = self._redis.get(key)
            if not raw:
                continue
            if isinstance(raw, bytes):
                raw = raw.decode()
            try:
                job = Job.from_dict(json.loads(raw))
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
            if job.job_type == JobType.TRANSCRIPT and job.status in _TRANSCRIPT_PROCESSING:
                count += 1
        return count

    def reconcile_queue_counter(self) -> int:
        """Recount waiting transcript jobs; fixes counter drift after crashes."""
        waiting = 0
        for key in self._redis.scan_iter(match=f"{JOB_KEY_PREFIX}*"):
            raw = self._redis.get(key)
            if not raw:
                continue
            try:
                job = Job.from_dict(json.loads(raw))
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
            if job.job_type == JobType.TRANSCRIPT and job.status in _TRANSCRIPT_WAITING:
                waiting += 1
        self._redis.set(QUEUE_COUNTER_KEY, waiting)
        return waiting

    def fail_stale_waiting_jobs(self, *, max_age_sec: int = 7200) -> int:
        """Mark old queued/downloading jobs as failed (bot restarted mid-download)."""
        from datetime import datetime, timezone

        cutoff = datetime.now(timezone.utc).timestamp() - max_age_sec
        failed = 0
        for key in self._redis.scan_iter(match=f"{JOB_KEY_PREFIX}*"):
            raw = self._redis.get(key)
            if not raw:
                continue
            try:
                job = Job.from_dict(json.loads(raw))
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
            if job.job_type != JobType.TRANSCRIPT or job.status not in _TRANSCRIPT_WAITING:
                continue
            if not job.updated_at:
                continue
            try:
                updated = datetime.fromisoformat(job.updated_at.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
            if updated < cutoff:
                self.update_status(
                    job.job_id,
                    JobStatus.FAILED,
                    error="stale: bot or worker was restarted",
                )
                failed += 1
        if failed:
            self.reconcile_queue_counter()
        return failed

    def queue_full(self) -> bool:
        return self.queued_transcript_count() >= MAX_QUEUE_SIZE

    def cancel(self, job_id: str) -> Job | None:
        job = self.get(job_id)
        if not job:
            return None
        if job.status in (JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.TIMEOUT):
            return job
        return self.update_status(job_id, JobStatus.CANCELLED)

    def is_cancelled(self, job_id: str) -> bool:
        job = self.get(job_id)
        return job is not None and job.status == JobStatus.CANCELLED

    def find_summary_for_parent(self, parent_job_id: str) -> Job | None:
        """Latest summary child job for a transcript (any status)."""
        parent = self.get(parent_job_id)
        if not parent:
            return None
        candidates: list[Job] = []
        for raw_id in self._redis.smembers(f"{USER_JOBS_PREFIX}{parent.user_id}"):
            jid = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
            job = self.get(jid)
            if (
                job
                and job.job_type == JobType.SUMMARY
                and job.parent_job_id == parent_job_id
            ):
                candidates.append(job)
        if not candidates:
            return None
        return max(candidates, key=lambda j: j.created_at or "")
