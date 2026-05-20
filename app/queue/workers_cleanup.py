"""Remove dead RQ worker registrations from Redis."""

from __future__ import annotations

import logging
import os

from rq import Worker

from app.queue.rq_connection import get_redis

logger = logging.getLogger(__name__)


def prune_dead_workers() -> int:
    """Unregister workers whose PID no longer exists. Returns count removed."""
    redis = get_redis()
    removed = 0
    for worker in Worker.all(connection=redis):
        pid = getattr(worker, "pid", None)
        if pid is None:
            continue
        try:
            os.kill(int(pid), 0)
        except (OSError, ProcessLookupError, ValueError):
            try:
                worker.register_death()
                removed += 1
                logger.info("Unregistered dead RQ worker %s (pid=%s)", worker.name, pid)
            except Exception:
                logger.debug("Could not unregister worker %s", worker.name, exc_info=True)
    return removed
