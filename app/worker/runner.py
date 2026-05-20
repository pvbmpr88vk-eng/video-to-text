from __future__ import annotations

import logging
import signal
import sys
import threading

from app.darwin import configure_fork_safety

configure_fork_safety()

from rq import SimpleWorker, Worker

from app.config import RQ_QUEUE_SUMMARY, RQ_QUEUE_TRANSCRIPT
from app.queue.rq_connection import get_redis
from app.queue.scheduled import promote_scheduled_jobs

logger = logging.getLogger(__name__)

_SCHEDULER_POLL_SEC = 15


def _start_scheduled_promoter(queue_names: list[str], stop: threading.Event) -> threading.Thread:
    """RQ's built-in scheduler forks on macOS → ObjC SIGABRT; poll in-process instead."""

    def _loop() -> None:
        conn = get_redis()
        while not stop.wait(_SCHEDULER_POLL_SEC):
            for name in queue_names:
                try:
                    promote_scheduled_jobs(name, conn)
                except Exception:
                    logger.debug("scheduled promote failed for %s", name, exc_info=True)

    thread = threading.Thread(target=_loop, name="rq-scheduled-promoter", daemon=True)
    thread.start()
    return thread


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

    for name in queue_names:
        promote_scheduled_jobs(name, conn)
    if kind == "summary":
        from app.jobs.store import JobStore
        from app.queue.tasks import SUMMARY_INFLIGHT_KEY

        JobStore(conn).reconcile_queue_counter()
        conn.set(SUMMARY_INFLIGHT_KEY, 0)

    # fork() + ML/Ollama/ObjC → SIGABRT on macOS; run jobs in-process locally.
    worker_cls = SimpleWorker if sys.platform == "darwin" else Worker
    worker = worker_cls(queue_names, connection=conn)
    logger.info(
        "Starting RQ worker for queues: %s (class=%s, scheduler=%s)",
        queue_names,
        worker_cls.__name__,
        "in-process" if sys.platform == "darwin" else "rq",
    )

    stop_promoter = threading.Event()
    promoter: threading.Thread | None = None
    if sys.platform == "darwin":
        promoter = _start_scheduled_promoter(queue_names, stop_promoter)

    def _handle_sigterm(signum, frame) -> None:  # noqa: ARG001
        logger.info("Received signal %s, shutting down worker", signum)
        stop_promoter.set()
        worker.request_stop()

    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)
    try:
        # with_scheduler=True spawns ForkProcess on macOS — crashes after ML libs load.
        worker.work(with_scheduler=sys.platform != "darwin")
    finally:
        stop_promoter.set()
        if promoter is not None:
            promoter.join(timeout=2)
