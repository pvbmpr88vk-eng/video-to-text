from __future__ import annotations

import logging
import os
import signal
import sys

# Before any ML/ObjC libs load (macOS + RQ fork → SIGABRT in work horse)
if sys.platform == "darwin":
    os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")

from rq import SimpleWorker, Worker

from app.config import RQ_QUEUE_SUMMARY, RQ_QUEUE_TRANSCRIPT
from app.queue.rq_connection import get_redis

logger = logging.getLogger(__name__)


def run_worker(kind: str, *, verbose: bool = False) -> None:
    from app.logging_setup import configure_logging

    configure_logging(verbose=verbose)

    if kind == "transcript":
        queue_names = [RQ_QUEUE_TRANSCRIPT]
    elif kind == "summary":
        queue_names = [RQ_QUEUE_SUMMARY]
    else:
        print(f"Unknown worker kind: {kind}", file=sys.stderr)
        raise SystemExit(1)

    conn = get_redis()
    try:
        conn.ping()
    except Exception as exc:
        print(f"Redis unavailable: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    # fork() + ML/Ollama/ObjC → SIGABRT on macOS; run jobs in-process locally.
    worker_cls = SimpleWorker if sys.platform == "darwin" else Worker
    worker = worker_cls(queue_names, connection=conn)
    logger.info("Starting RQ worker for queues: %s", queue_names)

    def _handle_sigterm(signum, frame) -> None:  # noqa: ARG001
        logger.info("Received signal %s, shutting down worker", signum)
        worker.request_stop()

    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)
    # Retries land in ScheduledJobRegistry — scheduler required on macOS after SIGABRT retries.
    worker.work(with_scheduler=True)
