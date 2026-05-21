"""Download Telegram media when using Local Bot API in Docker."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from telegram import File as TgFile

from app.config import TELEGRAM_BOT_API_BASE_URL

logger = logging.getLogger(__name__)


async def save_telegram_file(tg_file: TgFile, dest: Path) -> None:
    """
    Save a file from getFile to dest.

    With Local Bot API (--local), file_path is an absolute path on the API server.
    In Docker we mount that tree read-only; copy instead of HTTP (PTB would hit
    api.telegram.org and fail with InvalidToken).
    """
    if not tg_file.file_path:
        raise OSError("Telegram file has no file_path")

    src = Path(tg_file.file_path)
    if TELEGRAM_BOT_API_BASE_URL and src.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        logger.info(
            "Copied Local Bot API file %s -> %s (%s bytes)",
            src,
            dest,
            dest.stat().st_size,
        )
        return

    await tg_file.download_to_drive(custom_path=str(dest))
