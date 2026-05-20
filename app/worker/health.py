from __future__ import annotations

import logging
import shutil
import sys

import httpx

from app.audio.ffmpeg import require_ffmpeg_tools
from app.config import OLLAMA_HOST, REDIS_URL
from app.queue.rq_connection import get_redis

logger = logging.getLogger(__name__)


def run_health_check(*, check_ollama: bool = True) -> int:
    ok = True

    try:
        redis = get_redis()
        if not redis.ping():
            logger.error("Redis PING failed")
            ok = False
        else:
            logger.info("Redis OK (%s)", REDIS_URL)
    except Exception as exc:
        logger.error("Redis unavailable: %s", exc)
        ok = False

    if shutil.which("ffmpeg") is None:
        logger.error("ffmpeg not found in PATH")
        ok = False
    else:
        try:
            require_ffmpeg_tools()
            logger.info("FFmpeg OK")
        except Exception as exc:
            logger.error("FFmpeg check failed: %s", exc)
            ok = False

    if check_ollama:
        try:
            r = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=5.0)
            if r.status_code == 200:
                logger.info("Ollama OK (%s)", OLLAMA_HOST)
            else:
                logger.warning("Ollama returned HTTP %s", r.status_code)
        except Exception as exc:
            logger.warning("Ollama unreachable: %s", exc)

    try:
        import yt_dlp  # noqa: F401

        logger.info("yt-dlp OK")
    except ImportError:
        logger.error("yt-dlp not installed (required for URL download in bot)")
        ok = False

    return 0 if ok else 1
