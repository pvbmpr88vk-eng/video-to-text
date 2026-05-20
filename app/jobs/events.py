from __future__ import annotations

import json
from typing import Any

from redis import Redis

JOB_EVENTS_CHANNEL = "job:events"


def publish_job_event(redis_conn: Redis, *, job_id: str, event: str, extra: dict[str, Any] | None = None) -> None:
    payload = {"job_id": job_id, "event": event}
    if extra:
        payload.update(extra)
    redis_conn.publish(JOB_EVENTS_CHANNEL, json.dumps(payload, ensure_ascii=False))
