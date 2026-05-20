from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

from app.config import JOB_CLEANUP_TTL_HOURS, JOBS_BASE_DIR

logger = logging.getLogger(__name__)


def cleanup_old_jobs(*, ttl_hours: int | None = None, dry_run: bool = False) -> int:
    ttl = ttl_hours if ttl_hours is not None else JOB_CLEANUP_TTL_HOURS
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl)
    removed = 0

    if not JOBS_BASE_DIR.is_dir():
        logger.info("Jobs base dir does not exist: %s", JOBS_BASE_DIR)
        return 0

    for path in JOBS_BASE_DIR.iterdir():
        if not path.is_dir():
            continue
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if mtime >= cutoff:
            continue
        if dry_run:
            logger.info("Would remove %s (mtime %s)", path, mtime.isoformat())
        else:
            shutil.rmtree(path)
            logger.info("Removed %s", path)
        removed += 1

    return removed
