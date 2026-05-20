from __future__ import annotations

import logging
import sys

import httpx

from app.audio.ffmpeg import require_ffmpeg_tools
from app.config import (
    DEFAULT_TELEGRAM_INBOX_DIR,
    OLLAMA_HOST,
)
from app.telegram.auth import MediaRateLimiter
from app.telegram.credentials import CredentialsError, load_credentials
from app.telegram.handlers import register_handlers
from app.telegram.queue import JobCoordinator

logger = logging.getLogger(__name__)


def _ollama_reachable() -> bool:
    try:
        r = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=5.0)
        return r.status_code == 200
    except Exception:
        return False


def run_bot(*, verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        creds = load_credentials()
    except CredentialsError as exc:
        print(
            f"Error: {exc}\n"
            "Создайте telegram-bot.access.txt из telegram-bot.access.example.txt "
            "или задайте TELEGRAM_BOT_TOKEN в окружении.",
            file=sys.stderr,
        )
        raise SystemExit(7) from exc

    try:
        require_ffmpeg_tools()
    except Exception as exc:
        print(f"Error: FFmpeg required for the bot: {exc}", file=sys.stderr)
        raise SystemExit(7) from exc

    if not _ollama_reachable():
        logger.warning(
            "Ollama не отвечает на %s — кнопка «Сделать тезисы» не сработает, пока сервис не запущен.",
            OLLAMA_HOST,
        )

    from telegram.ext import Application

    application = Application.builder().token(creds.bot_token).build()
    application.bot_data["creds"] = creds
    application.bot_data["coord"] = JobCoordinator()
    application.bot_data["rate_limiter"] = MediaRateLimiter()
    application.bot_data["inbox_dir"] = DEFAULT_TELEGRAM_INBOX_DIR
    application.bot_data["transcript_jobs"] = {}

    register_handlers(application)

    logger.info(
        "Starting Telegram bot (allowed user ids: %s)",
        sorted(creds.allowed_user_ids) if creds.allowed_user_ids else "none",
    )
    application.run_polling()
