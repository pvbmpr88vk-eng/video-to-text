"""Publish artifacts to HTTP staging for GPU Sharing (direct URLs, no redirects)."""

from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

from app.gpu_sharing.client import GPUSharingError

logger = logging.getLogger(__name__)


def publish_file_to_staging(
    local_path: Path,
    *,
    staging_dir: Path,
    publish_host: str,
    http_port: int = 18888,
) -> str:
    """Copy file into staging_dir and return URL reachable by the GPU worker."""
    local_path = local_path.resolve()
    if not local_path.is_file():
        raise FileNotFoundError(local_path)

    staging_dir = staging_dir.resolve()
    staging_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex[:12]}{local_path.suffix or '.bin'}"
    dest = staging_dir / name
    shutil.copy2(local_path, dest)
    url = f"http://{publish_host}:{http_port}/{name}"
    logger.info("Published staging artifact %s (%d bytes)", url, dest.stat().st_size)
    return url
