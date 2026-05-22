"""Download Telegram media when using Local Bot API in Docker."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from telegram import File as TgFile

from app.config import TELEGRAM_BOT_API_BASE_URL

logger = logging.getLogger(__name__)

# Paths where Local Bot API (TDLib) stores downloaded files — safe to unlink after copy.
_LOCAL_API_CACHE_ROOTS = (Path("/var/lib/telegram-bot-api"),)


def _is_under_api_cache(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in _LOCAL_API_CACHE_ROOTS:
        try:
            root_resolved = root.resolve()
        except OSError:
            continue
        if resolved == root_resolved or root_resolved in resolved.parents:
            return True
    return False


def _copy_from_local_api_cache(src: Path, dest: Path) -> None:
    """Copy from Local Bot API volume; drop cache file after verified copy (TZ-09 §9.4 A)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    src_size = src.stat().st_size
    dest_size = dest.stat().st_size
    if src_size != dest_size:
        raise OSError(f"copy size mismatch: {src} ({src_size}) -> {dest} ({dest_size})")

    if _is_under_api_cache(src):
        try:
            src.unlink()
            logger.info("Removed Local Bot API cache after copy: %s", src)
        except OSError as exc:
            logger.warning("Could not remove API cache file %s: %s", src, exc)

    logger.info(
        "Copied Local Bot API file %s -> %s (%s bytes)",
        src,
        dest,
        dest_size,
    )


async def save_telegram_file(tg_file: TgFile, dest: Path) -> None:
    """
    Save a file from getFile to dest.

    With Local Bot API (--local), file_path is an absolute path on the API server.
    In Docker we mount that tree read-write; copy instead of HTTP (PTB would hit
    api.telegram.org and fail with InvalidToken), then unlink cache (§9.4 A).
    """
    if not tg_file.file_path:
        raise OSError("Telegram file has no file_path")

    src = Path(tg_file.file_path)
    if TELEGRAM_BOT_API_BASE_URL and src.is_file():
        _copy_from_local_api_cache(src, dest)
        return

    await tg_file.download_to_drive(custom_path=str(dest))
