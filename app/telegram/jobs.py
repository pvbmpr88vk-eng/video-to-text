from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TranscriptJob:
    json_path: Path
    txt_path: Path
    user_id: int
    language: str
    created_at: float


CALLBACK_THESES_PREFIX = "theses:"


def register_transcript_job(
    bot_data: dict,
    *,
    user_id: int,
    json_path: Path,
    txt_path: Path,
    language: str,
) -> str:
    job_id = secrets.token_hex(6)
    store: dict[str, TranscriptJob] = bot_data.setdefault("transcript_jobs", {})
    store[job_id] = TranscriptJob(
        json_path=json_path,
        txt_path=txt_path,
        user_id=user_id,
        language=language,
        created_at=time.monotonic(),
    )
    return job_id


def get_transcript_job(bot_data: dict, job_id: str) -> TranscriptJob | None:
    return bot_data.get("transcript_jobs", {}).get(job_id)


def parse_theses_callback(data: str) -> str | None:
    if not data.startswith(CALLBACK_THESES_PREFIX):
        return None
    job_id = data[len(CALLBACK_THESES_PREFIX) :].strip()
    return job_id or None
