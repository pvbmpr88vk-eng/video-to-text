from __future__ import annotations

from functools import lru_cache

from redis import Redis
from rq import Queue

from app.config import (
    JOB_MAX_RETRIES,
    JOB_RETRY_DELAY_SEC,
    JOB_SUMMARY_TIMEOUT_SEC,
    JOB_TRANSCRIPT_TIMEOUT_SEC,
    REDIS_URL,
    RQ_QUEUE_SUMMARY,
    RQ_QUEUE_TRANSCRIPT,
)
from rq import Retry

DEFAULT_RETRY = Retry(max=JOB_MAX_RETRIES, interval=JOB_RETRY_DELAY_SEC)


@lru_cache(maxsize=1)
def get_redis() -> Redis:
    return Redis.from_url(REDIS_URL, decode_responses=False)


def get_transcript_queue() -> Queue:
    return Queue(
        RQ_QUEUE_TRANSCRIPT,
        connection=get_redis(),
        default_timeout=JOB_TRANSCRIPT_TIMEOUT_SEC,
    )


def get_summary_queue() -> Queue:
    return Queue(
        RQ_QUEUE_SUMMARY,
        connection=get_redis(),
        default_timeout=JOB_SUMMARY_TIMEOUT_SEC,
    )
