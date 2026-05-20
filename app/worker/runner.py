from __future__ import annotations

import logging
import signal
import sys

from rq import Worker

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

    worker = Worker(queue_names, connection=conn)
    logger.info("Starting RQ worker for queues: %s", queue_names)

    def _handle_sigterm(signum, frame) -> None:  # noqa: ARG001
        logger.info("Received signal %s, shutting down worker", signum)
        worker.request_stop()

    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)
    worker.work(with_scheduler=False)
