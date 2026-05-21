from __future__ import annotations

import logging
import os
import sys

import httpx

from app.config import JOB_QUEUE_ENABLED, OLLAMA_HOST
from app.jobs.store import JobStore
from app.queue.rq_connection import get_redis
from app.telegram.auth import MediaRateLimiter
from app.telegram.credentials import CredentialsError, load_credentials
from app.telegram.handlers import register_handlers
from app.telegram.notify import start_notify_listener, stop_notify_listener

logger = logging.getLogger(__name__)


def _ollama_reachable() -> bool:
    try:
        r = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=5.0)
        return r.status_code == 200
    except Exception:
        return False


async def _post_init(application) -> None:
    try:
        me = await application.bot.get_me()
        access = os.environ.get("TELEGRAM_ACCESS_FILE", "telegram-bot.access.txt")
        logger.info(
            "Telegram bot ready: @%s (id=%s), credentials=%s, APP_ENV=%s",
            me.username,
            me.id,
            access,
            os.environ.get("APP_ENV", "default"),
        )
    except Exception:
        logger.debug("get_me failed at startup", exc_info=True)

    if JOB_QUEUE_ENABLED:
        store: JobStore = application.bot_data["job_store"]
        stale = store.fail_stale_waiting_jobs(max_age_sec=3600)
        waiting = store.reconcile_queue_counter()
        if stale:
            logger.warning("Marked %s stale transcript job(s) as failed", stale)
        logger.info("Queue reconciled: %s transcript job(s) waiting", waiting)
        from app.queue.diagnostics import collect_queue_diagnostics

        diag = collect_queue_diagnostics()
        if diag.transcript_workers == 0:
            logger.warning(
                "No transcript RQ workers registered — start: python -m app worker transcript"
            )
        else:
            logger.info(
                "RQ workers: transcript=%s summary=%s (queued=%s started=%s)",
                diag.transcript_workers,
                diag.summary_workers,
                diag.transcript_queued,
                diag.transcript_started,
            )
        await start_notify_listener(application)


async def _post_shutdown(application) -> None:
    if JOB_QUEUE_ENABLED:
        await stop_notify_listener(application)


def run_bot(*, verbose: bool = False) -> None:
    from app.logging_setup import configure_logging

    configure_logging(verbose=verbose)

    try:
        creds = load_credentials()
    except CredentialsError as exc:
        print(
            f"Error: {exc}\n"
            "Создайте telegram-bot.access.txt (прод) или telegram-bot.access.test.txt (локальный тест) "
            "или задайте TELEGRAM_BOT_TOKEN + TELEGRAM_ACCESS_FILE.",
            file=sys.stderr,
        )
        raise SystemExit(7) from exc

    if not JOB_QUEUE_ENABLED:
        print("Error: JOB_QUEUE_ENABLED=false is no longer supported (TZ-05).", file=sys.stderr)
        raise SystemExit(7)

    try:
        redis = get_redis()
        redis.ping()
    except Exception as exc:
        print(f"Error: Redis unavailable ({exc}). Start Redis before running the bot.", file=sys.stderr)
        raise SystemExit(7) from exc

    if not _ollama_reachable():
        logger.warning(
            "Ollama не отвечает на %s — кнопка «Сделать тезисы» не сработает, пока сервис не запущен.",
            OLLAMA_HOST,
        )

    from telegram.ext import Application

    application = (
        Application.builder()
        .token(creds.bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    application.bot_data["creds"] = creds
    application.bot_data["rate_limiter"] = MediaRateLimiter()
    application.bot_data["redis"] = redis
    application.bot_data["job_store"] = JobStore(redis)

    register_handlers(application)

    bot_lock_key = "bot:telegram:polling"
    if not redis.set(bot_lock_key, str(os.getpid()), nx=True, ex=86400):
        holder = redis.get(bot_lock_key)
        if isinstance(holder, bytes):
            holder = holder.decode()
        print(
            f"Error: another Telegram bot is already running (lock holder pid={holder}).\n"
            "Остановите второй процесс: pkill -f 'python -m app bot'",
            file=sys.stderr,
        )
        raise SystemExit(7)

    logger.info(
        "Starting Telegram bot (queue=%s, allowed user ids: %s)",
        JOB_QUEUE_ENABLED,
        sorted(creds.allowed_user_ids) if creds.allowed_user_ids else "none",
    )
    try:
        application.run_polling()
    finally:
        redis.delete(bot_lock_key)
