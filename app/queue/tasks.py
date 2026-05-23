from __future__ import annotations

import logging
import time
from pathlib import Path

from app.darwin import configure_fork_safety

configure_fork_safety()

from app.audio.exceptions import FFmpegError, FFmpegNotFoundError, NoAudioStreamError
from app.audio.extractor import extract_audio
from app.config import (
    DEFAULT_CHUNK_MINUTES,
    GPU_SHARING_TRANSCRIPT,
    MAX_CONCURRENT_SUMMARIES,
    MAX_STT_WORKERS_PER_JOB,
    OLLAMA_HOST,
    OLLAMA_MODEL_DEFAULT,
    WHISPER_MODEL_DEFAULT,
)
from app.jobs.models import JobStatus
from app.jobs.paths import ensure_job_dirs
from app.jobs.progress import ProgressReporter
from app.jobs.store import JobStore
from app.queue.rq_connection import get_redis
from app.stt.chunks import resolve_workers
from app.stt.exceptions import ModelNotAvailableError, TranscriptionError
from app.stt.limits import audio_too_long_for_stt
from app.stt.transcriber import transcribe_audio
from app.summary.exceptions import SummaryError
from app.summary.summarizer import summarize_transcript

logger = logging.getLogger(__name__)

SUMMARY_INFLIGHT_KEY = "summary:inflight"  # legacy; reconciled in reset_stuck / worker start


def _store() -> JobStore:
    return JobStore(get_redis())


def _fail(store: JobStore, job_id: str, error: str) -> None:
    logger.error("Job %s failed: %s", job_id, error)
    store.update_status(job_id, JobStatus.FAILED, error=error)


def run_transcript_job(job_id: str) -> None:
    store = _store()
    job = store.get(job_id)
    if not job:
        logger.warning("Transcript job %s not found", job_id)
        return
    if store.is_cancelled(job_id):
        logger.info("Transcript job %s cancelled before start", job_id)
        return

    t0 = time.monotonic()
    progress = ProgressReporter(store, job_id)
    try:
        if not job.inbox_path:
            _fail(store, job_id, "inbox_path missing")
            return
        inbox = Path(job.inbox_path)
        if not inbox.is_file():
            _fail(store, job_id, f"Input file not found: {inbox}")
            return

        _, work_dir, out_dir = ensure_job_dirs(job_id)

        store.update_status(job_id, JobStatus.EXTRACT)
        progress.report(8.0, "Извлекаю аудио…", force=True)
        if store.is_cancelled(job_id):
            return

        wav = extract_audio(inbox, output_dir=work_dir)
        store.update_status(job_id, JobStatus.STT, wav_path=str(wav))
        progress.report(12.0, "Распознаю речь…", force=True)
        if store.is_cancelled(job_id):
            return

        too_long, duration_sec = audio_too_long_for_stt(wav)
        if too_long:
            _fail(
                store,
                job_id,
                f"audio_too_long:{duration_sec / 60:.0f}",
            )
            return

        if store.is_cancelled(job_id):
            logger.info("Transcript job %s cancelled before STT", job_id)
            return

        if GPU_SHARING_TRANSCRIPT:
            raise TranscriptionError(
                "GPU_SHARING_TRANSCRIPT: Docker jobs API (v1/v2) отключён. "
                "v3 — ONNX на VPS + /v1/gpu/invoke. См. docs/gpu-sharing.md"
            )
        else:
            workers = resolve_workers(None, default=MAX_STT_WORKERS_PER_JOB)
            tr = transcribe_audio(
                wav,
                output_dir=out_dir,
                model_size=WHISPER_MODEL_DEFAULT,
                language=job.language,
                with_segments=True,
                parallel=workers > 1,
                chunk_minutes=DEFAULT_CHUNK_MINUTES,
                workers=workers,
                keep_chunks=False,
                progress_callback=lambda pct, label: progress.report(pct, label),
            )
        progress.report(100.0, "Готово", force=True)

        if store.is_cancelled(job_id):
            logger.info("Transcript job %s was cancelled; skipping DONE", job_id)
            return

        store.update_status(
            job_id,
            JobStatus.DONE,
            wav_path=str(wav),
            transcript_txt=str(tr.txt_path),
            transcript_json=str(tr.json_path),
            duration_sec=tr.duration_sec,
            processing_sec=time.monotonic() - t0,
            stt_model=tr.model,
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "Transcript job done in %.1fs",
            time.monotonic() - t0,
            extra={"job_id": job_id, "user_id": job.user_id, "status": "done", "duration_ms": elapsed_ms},
        )
    except NoAudioStreamError:
        _fail(store, job_id, "no_audio")
    except FFmpegNotFoundError:
        _fail(store, job_id, "ffmpeg_missing")
    except FFmpegError as exc:
        _fail(store, job_id, f"ffmpeg: {exc}")
    except ModelNotAvailableError:
        _fail(store, job_id, "stt_model")
    except TranscriptionError as exc:
        _fail(store, job_id, f"stt: {exc}")
    except FileNotFoundError as exc:
        _fail(store, job_id, f"file_not_found: {exc}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error in transcript job %s", job_id)
        _fail(store, job_id, str(exc))


def run_summary_job(job_id: str) -> None:
    store = _store()
    job = store.get(job_id)
    if not job:
        logger.warning("Summary job %s not found", job_id)
        return
    if store.is_cancelled(job_id):
        logger.info("Summary job %s cancelled before start", job_id)
        return
    if not job.parent_job_id:
        _fail(store, job_id, "parent_job_id missing")
        return

    parent = store.get(job.parent_job_id)
    if not parent or not parent.transcript_json:
        _fail(store, job_id, "parent transcript missing")
        return

    json_path = Path(parent.transcript_json)
    if not json_path.is_file():
        _fail(store, job_id, "transcript file not found")
        return

    active = store.count_active_summaries()
    job = store.get(job_id)
    if job and job.status != JobStatus.SUMMARY and active >= MAX_CONCURRENT_SUMMARIES:
        logger.info(
            "Summary job %s deferred: concurrency limit (%s active)",
            job_id,
            active,
        )
        return
    t0 = time.monotonic()
    progress = ProgressReporter(store, job_id)
    try:
        store.update_status(job_id, JobStatus.SUMMARY)
        progress.report(5.0, "Готовлю тезисы…", force=True)
        if store.is_cancelled(job_id):
            return

        _, _, out_dir = ensure_job_dirs(job_id)
        summ = summarize_transcript(
            json_path,
            output_dir=out_dir,
            language=job.language or parent.language,
            with_quotes=False,
            model=OLLAMA_MODEL_DEFAULT,
            ollama_host=OLLAMA_HOST,
            progress_callback=lambda pct, label: progress.report(pct, label),
        )
        progress.report(100.0, "Тезисы готовы", force=True)
        store.update_status(
            job_id,
            JobStatus.DONE,
            error=None,
            summary_md=str(summ.summary_path),
            theses_json=str(summ.theses_path),
            llm_model=summ.model,
            processing_sec=time.monotonic() - t0,
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "Summary job done in %.1fs",
            time.monotonic() - t0,
            extra={"job_id": job_id, "user_id": job.user_id, "status": "done", "duration_ms": elapsed_ms},
        )
    except SummaryError as exc:
        _fail(store, job_id, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error in summary job %s", job_id)
        _fail(store, job_id, str(exc))


def transcript_task(job_id: str) -> None:
    """RQ entrypoint for transcript queue."""
    run_transcript_job(job_id)


def summary_task(job_id: str) -> None:
    """RQ entrypoint for summary queue."""
    run_summary_job(job_id)
