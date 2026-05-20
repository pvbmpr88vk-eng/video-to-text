from __future__ import annotations

from dataclasses import dataclass

from rq import Worker

from app.config import RQ_QUEUE_SUMMARY, RQ_QUEUE_TRANSCRIPT
from app.queue.rq_connection import get_redis, get_summary_queue, get_transcript_queue


@dataclass(frozen=True)
class QueueDiagnostics:
    transcript_workers: int
    summary_workers: int
    transcript_queued: int
    summary_queued: int
    transcript_started: int


def collect_queue_diagnostics() -> QueueDiagnostics:
    redis = get_redis()
    transcript_workers = 0
    summary_workers = 0
    for worker in Worker.all(connection=redis):
        names = worker.queue_names()
        if RQ_QUEUE_TRANSCRIPT in names:
            transcript_workers += 1
        if RQ_QUEUE_SUMMARY in names:
            summary_workers += 1

    tq = get_transcript_queue()
    sq = get_summary_queue()
    started = tq.started_job_registry.count

    return QueueDiagnostics(
        transcript_workers=transcript_workers,
        summary_workers=summary_workers,
        transcript_queued=tq.count,
        summary_queued=sq.count,
        transcript_started=started,
    )


def format_queue_status() -> str:
    d = collect_queue_diagnostics()
    lines = [
        f"Workers transcript: {d.transcript_workers}  |  summary: {d.summary_workers}",
        f"RQ очередь transcript: {d.transcript_queued} ожидают, {d.transcript_started} в работе",
        f"RQ очередь summary: {d.summary_queued}",
    ]
    if d.transcript_workers == 0:
        lines.append("⚠️  Запустите: python -m app worker transcript")
    if d.summary_workers == 0:
        lines.append("⚠️  Для тезисов: python -m app worker summary")
    return "\n".join(lines)
