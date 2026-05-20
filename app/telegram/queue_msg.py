from __future__ import annotations

from app.jobs.store import JobStore
from app.queue.diagnostics import collect_queue_diagnostics
from app.telegram import messages as M


def format_queue_accept_message(store: JobStore) -> str:
    position = max(1, store.queued_transcript_count())
    processing = store.count_processing_transcripts()
    diag = collect_queue_diagnostics()

    if diag.transcript_workers == 0:
        return M.QUEUE_NO_WORKER

    processing_hint = ""
    if processing > 0 or diag.transcript_started > 0:
        processing_hint = M.QUEUE_PROCESSING_ACTIVE

    return M.QUEUE_POSITION.format(position=position, processing_hint=processing_hint)
