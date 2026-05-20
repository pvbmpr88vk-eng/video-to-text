from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from app.jobs.cleanup import cleanup_old_jobs


def test_cleanup_removes_old_job_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.jobs.cleanup.JOBS_BASE_DIR", tmp_path)

    old_id = str(uuid.uuid4())
    new_id = str(uuid.uuid4())
    old_dir = tmp_path / old_id
    new_dir = tmp_path / new_id
    old_dir.mkdir()
    new_dir.mkdir()
    (old_dir / "inbox").mkdir()

    old_ts = (datetime.now(timezone.utc) - timedelta(hours=48)).timestamp()
    new_ts = datetime.now(timezone.utc).timestamp()
    import os

    os.utime(old_dir, (old_ts, old_ts))
    os.utime(new_dir, (new_ts, new_ts))

    removed = cleanup_old_jobs(ttl_hours=24, dry_run=False)
    assert removed == 1
    assert not old_dir.exists()
    assert new_dir.exists()


def test_cleanup_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.jobs.cleanup.JOBS_BASE_DIR", tmp_path)

    job_dir = tmp_path / str(uuid.uuid4())
    job_dir.mkdir()
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=48)).timestamp()
    import os

    os.utime(job_dir, (old_ts, old_ts))

    removed = cleanup_old_jobs(ttl_hours=24, dry_run=True)
    assert removed == 1
    assert job_dir.exists()


def test_cleanup_missing_base_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = tmp_path / "no-such-jobs"
    monkeypatch.setattr("app.jobs.cleanup.JOBS_BASE_DIR", missing)
    assert cleanup_old_jobs() == 0
