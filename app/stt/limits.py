"""Duration guards for STT on memory-constrained hosts."""

from __future__ import annotations

from pathlib import Path

from app.config import STT_MAX_AUDIO_DURATION_MINUTES
from app.stt.chunks import probe_audio_duration, read_duration_from_sidecar


def audio_duration_sec(audio_path: Path) -> float:
    duration = read_duration_from_sidecar(audio_path)
    if duration is None:
        duration = probe_audio_duration(audio_path)
    return float(duration or 0.0)


def audio_too_long_for_stt(audio_path: Path) -> tuple[bool, float]:
    """Return (too_long, duration_sec). No limit when STT_MAX_AUDIO_DURATION_MINUTES <= 0."""
    duration = audio_duration_sec(audio_path)
    limit_min = STT_MAX_AUDIO_DURATION_MINUTES
    if limit_min <= 0:
        return False, duration
    return duration > limit_min * 60.0, duration
