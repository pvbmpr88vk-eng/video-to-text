"""Throttled job progress for Telegram status (low Redis/Telegram load)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from app.config import TELEGRAM_PROGRESS_MIN_INTERVAL_SEC

if TYPE_CHECKING:
    from app.jobs.store import JobStore


class ProgressReporter:
    """Publish progress at most once per min_interval seconds."""

    def __init__(
        self,
        store: JobStore,
        job_id: str,
        *,
        min_interval: float | None = None,
    ) -> None:
        self._store = store
        self._job_id = job_id
        self._min_interval = (
            TELEGRAM_PROGRESS_MIN_INTERVAL_SEC
            if min_interval is None
            else min_interval
        )
        self._t0 = time.monotonic()
        self._last_publish = 0.0

    def report(
        self,
        pct: float,
        label: str,
        *,
        force: bool = False,
    ) -> None:
        pct = max(0.0, min(100.0, float(pct)))
        now = time.monotonic()
        if not force and (now - self._last_publish) < self._min_interval:
            return

        eta_sec: float | None = None
        if pct >= 5.0:
            elapsed = now - self._t0
            eta_sec = max(0.0, elapsed / (pct / 100.0) - elapsed)

        self._store.update_progress(
            self._job_id,
            pct=pct,
            label=label,
            eta_sec=eta_sec,
            publish=True,
        )
        self._last_publish = now
