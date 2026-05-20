from __future__ import annotations

CALLBACK_THESES_PREFIX = "theses:"


def parse_theses_callback(data: str) -> str | None:
    if not data.startswith(CALLBACK_THESES_PREFIX):
        return None
    job_id = data[len(CALLBACK_THESES_PREFIX) :].strip()
    return job_id or None
