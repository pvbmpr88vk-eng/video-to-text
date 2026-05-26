from __future__ import annotations

import logging
import shutil
import sys

import httpx

from app.audio.ffmpeg import require_ffmpeg_tools
from app.config import (
    GPU_SHARING_API_KEY,
    GPU_SHARING_ENABLED,
    GPU_SHARING_STT_FALLBACK_CPU,
    OLLAMA_HOST,
    REDIS_URL,
    TELEGRAM_BOT_API_BASE_URL,
)
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

    if TELEGRAM_BOT_API_BASE_URL:
        ping_url = TELEGRAM_BOT_API_BASE_URL.rstrip("/")
        try:
            r = httpx.get(ping_url, timeout=5.0)
            if r.status_code < 500:
                logger.info("Local Bot API OK (%s)", ping_url)
            else:
                logger.error("Local Bot API HTTP %s at %s", r.status_code, ping_url)
                ok = False
        except Exception as exc:
            logger.error("Local Bot API unreachable at %s: %s", ping_url, exc)
            ok = False

    if GPU_SHARING_API_KEY and GPU_SHARING_ENABLED:
        try:
            from app.gpu_sharing.client import client_from_config

            client = client_from_config()
            if client is None:
                raise RuntimeError("GPU Sharing client not configured")
            client.request_timeout_sec = 5.0
            health = client.health()
            if health.get("status") != "ok":
                if GPU_SHARING_STT_FALLBACK_CPU:
                    logger.warning("GPU Sharing health unexpected: %s", health)
                else:
                    logger.error("GPU Sharing health unexpected: %s", health)
                    ok = False
            elif not client.has_online_node():
                if GPU_SHARING_STT_FALLBACK_CPU:
                    logger.warning("GPU Sharing: no online GPU nodes")
                else:
                    logger.error("GPU Sharing: no online GPU nodes")
                    ok = False
            else:
                logger.info("GPU Sharing OK (%s, online node)", client.base_url)
        except Exception as exc:
            if GPU_SHARING_STT_FALLBACK_CPU:
                logger.warning("GPU Sharing check failed (CPU fallback enabled): %s", exc)
            else:
                logger.error("GPU Sharing check failed: %s", exc)
                ok = False

    return 0 if ok else 1
