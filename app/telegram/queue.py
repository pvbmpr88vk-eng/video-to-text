from __future__ import annotations

import asyncio
import enum
import threading
import time


class JobPhase(enum.StrEnum):
    IDLE = "idle"
    DOWNLOADING = "downloading"
    EXTRACT = "extract"
    STT = "stt"
    SUMMARY = "summary"
    ERROR = "error"


class JobCoordinator:
    """At most one active media job; cancel flag for best-effort stop between stages."""

    def __init__(self) -> None:
        self._guard = asyncio.Lock()
        self.phase = JobPhase.IDLE
        self._cancel_event = threading.Event()
        self._last_status_edit = 0.0
        self._active = False

    def cancel_event(self) -> threading.Event:
        return self._cancel_event

    def request_cancel(self) -> None:
        self._cancel_event.set()

    async def try_begin(self) -> bool:
        async with self._guard:
            if self._active:
                return False
            self._active = True
            self._cancel_event.clear()
            self.phase = JobPhase.IDLE
            return True

    async def end(self) -> None:
        async with self._guard:
            self._active = False
            self.phase = JobPhase.IDLE

    def set_phase(self, phase: JobPhase) -> None:
        self.phase = phase

    def can_edit_status(self, min_interval_sec: float) -> bool:
        now = time.monotonic()
        if now - self._last_status_edit >= min_interval_sec:
            self._last_status_edit = now
            return True
        return False
