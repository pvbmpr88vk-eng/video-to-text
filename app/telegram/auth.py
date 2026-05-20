from __future__ import annotations

import time
from collections import defaultdict

from app.config import TELEGRAM_RATE_LIMIT_PER_HOUR


def is_allowed(user_id: int, allowed: frozenset[int]) -> bool:
    return user_id in allowed if allowed else False


class MediaRateLimiter:
    """At most N media messages per user_id per rolling hour (in-memory)."""

    def __init__(self, max_per_hour: int = TELEGRAM_RATE_LIMIT_PER_HOUR) -> None:
        self._max = max(1, max_per_hour)
        self._hits: dict[int, list[float]] = defaultdict(list)

    def allow(self, user_id: int) -> bool:
        now = time.monotonic()
        window_start = now - 3600.0
        hits = [t for t in self._hits[user_id] if t >= window_start]
        self._hits[user_id] = hits
        if len(hits) >= self._max:
            return False
        hits.append(now)
        self._hits[user_id] = hits
        return True
