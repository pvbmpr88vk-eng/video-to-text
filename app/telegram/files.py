"""Upload paths for Telegram (cloud vs Local Bot API)."""

from __future__ import annotations

import io
from pathlib import Path

from telegram import InputFile

from app.config import TELEGRAM_BOT_API_BASE_URL


def document_upload_file(path: Path) -> InputFile:
    """
    Build document payload for send_document.

    Local Bot API (--local) cannot read arbitrary paths on the bot container
    (\"Can't find real file path\"); stream bytes instead.
    """
    data = path.read_bytes()
    return InputFile(io.BytesIO(data), filename=path.name)


def document_upload_uri(path: Path) -> str | InputFile:
    """Prefer streaming upload on Local API; cloud may use path string."""
    if TELEGRAM_BOT_API_BASE_URL:
        return document_upload_file(path)
    return str(path.resolve())
