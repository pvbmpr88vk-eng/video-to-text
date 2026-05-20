from __future__ import annotations

from pathlib import Path

from app.config import JOBS_BASE_DIR


def job_root(job_id: str) -> Path:
    return JOBS_BASE_DIR / job_id


def job_inbox_dir(job_id: str) -> Path:
    return job_root(job_id) / "inbox"


def job_work_dir(job_id: str) -> Path:
    return job_root(job_id) / "work"


def job_out_dir(job_id: str) -> Path:
    return job_root(job_id) / "out"


def ensure_job_dirs(job_id: str) -> tuple[Path, Path, Path]:
    inbox = job_inbox_dir(job_id)
    work = job_work_dir(job_id)
    out = job_out_dir(job_id)
    for d in (inbox, work, out):
        d.mkdir(parents=True, exist_ok=True)
    return inbox, work, out
