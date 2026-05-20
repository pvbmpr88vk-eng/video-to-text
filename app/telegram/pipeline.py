from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

from app.audio.extractor import extract_audio
from app.config import (
    DEFAULT_CHUNK_MINUTES,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SUMMARY_DIR,
    DEFAULT_TRANSCRIPT_DIR,
    OLLAMA_HOST,
    OLLAMA_MODEL_DEFAULT,
    WHISPER_MODEL_DEFAULT,
)
from app.stt.chunks import resolve_workers
from app.stt.transcriber import transcribe_audio
from app.summary.summarizer import summarize_transcript


class PipelineCancelled(Exception):
    """User requested /cancel between stages."""


@dataclass
class TranscriptResult:
    wav_path: Path
    transcript_txt: Path
    transcript_json: Path
    duration_sec: float
    processing_sec: float
    stt_model: str


@dataclass
class SummaryResult:
    summary_md: Path
    theses_json: Path
    llm_model: str
    processing_sec: float


def _check(cancel_event: threading.Event | None) -> None:
    if cancel_event and cancel_event.is_set():
        raise PipelineCancelled()


def run_transcript_pipeline(
    local_media_path: Path,
    *,
    audio_dir: Path | None = None,
    transcript_dir: Path | None = None,
    language: str = "ru",
    whisper_model: str = WHISPER_MODEL_DEFAULT,
    cancel_event: threading.Event | None = None,
) -> TranscriptResult:
    """Extract audio and transcribe only (no LLM)."""
    t0 = time.monotonic()
    audio_out = audio_dir or DEFAULT_OUTPUT_DIR
    tr_out = transcript_dir or DEFAULT_TRANSCRIPT_DIR

    _check(cancel_event)
    wav = extract_audio(local_media_path, output_dir=audio_out)

    _check(cancel_event)
    workers = resolve_workers(None)
    tr = transcribe_audio(
        wav,
        output_dir=tr_out,
        model_size=whisper_model,
        language=language,
        with_segments=True,
        parallel=True,
        chunk_minutes=DEFAULT_CHUNK_MINUTES,
        workers=workers,
        keep_chunks=False,
    )

    return TranscriptResult(
        wav_path=wav,
        transcript_txt=tr.txt_path,
        transcript_json=tr.json_path,
        duration_sec=tr.duration_sec,
        processing_sec=time.monotonic() - t0,
        stt_model=tr.model,
    )


def run_summarize_pipeline(
    transcript_json_path: Path,
    *,
    summary_dir: Path | None = None,
    language: str = "ru",
    ollama_model: str = OLLAMA_MODEL_DEFAULT,
    ollama_host: str = OLLAMA_HOST,
) -> SummaryResult:
    """Summarize an existing transcript JSON (Ollama)."""
    t0 = time.monotonic()
    summ = summarize_transcript(
        transcript_json_path,
        output_dir=summary_dir or DEFAULT_SUMMARY_DIR,
        language=language,
        with_quotes=False,
        model=ollama_model,
        ollama_host=ollama_host,
    )
    return SummaryResult(
        summary_md=summ.summary_path,
        theses_json=summ.theses_path,
        llm_model=summ.model,
        processing_sec=time.monotonic() - t0,
    )
