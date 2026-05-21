from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections.abc import Callable
from pathlib import Path
from typing import Any

ProgressCallback = Callable[[float, str], None]

from app.config import (
    DEFAULT_CHUNK_MINUTES,
    DEFAULT_TRANSCRIPT_DIR,
    LONG_AUDIO_WARN_MINUTES,
    STT_CHUNK_WHEN_ABOVE_MINUTES,
    STT_PROGRESS_SEGMENT_INTERVAL,
    WHISPER_BEAM_SIZE,
    WHISPER_COMPUTE_TYPE,
    WHISPER_DEVICE,
    WHISPER_MODEL_DEFAULT,
)
from app.stt.chunks import (
    chunk_work_dir,
    cleanup_chunk_dir,
    merge_chunk_results,
    probe_audio_duration,
    read_duration_from_sidecar,
    resolve_workers,
    split_audio_into_chunks,
    transcribe_chunks_parallel,
)
from app.stt.exceptions import ModelNotAvailableError, TranscriptionError
from app.stt.models import ChunkResult, Segment
from app.utils.paths import build_output_basename, ensure_dir

logger = logging.getLogger(__name__)

SUPPORTED_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".ogg"}


@dataclass
class TranscriptionResult:
    text: str
    txt_path: Path
    json_path: Path
    language: str
    duration_sec: float
    segments: list[Segment] = field(default_factory=list)
    model: str = WHISPER_MODEL_DEFAULT
    source_path: str = ""
    parallel: bool = False
    workers: int = 1


def _load_whisper_model(model_size: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise ModelNotAvailableError(
            "Install STT dependencies: pip install -r requirements.txt"
        ) from exc

    logger.info(
        "Loading Whisper model %s (device=%s, compute_type=%s)",
        model_size,
        WHISPER_DEVICE,
        WHISPER_COMPUTE_TYPE,
    )
    print(
        f"Loading Whisper model '{model_size}' "
        "(first run downloads from Hugging Face — can take several minutes)...",
        flush=True,
    )
    try:
        return WhisperModel(
            model_size,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
        )
    except Exception as exc:
        raise ModelNotAvailableError(f"Failed to load model {model_size}: {exc}") from exc


def _run_transcription(
    model,
    audio_path: Path,
    *,
    language: str | None,
) -> tuple[list[Segment], str, float, str]:
    segments_iter, info = model.transcribe(
        str(audio_path),
        language=language,
        beam_size=WHISPER_BEAM_SIZE,
        vad_filter=True,
    )
    segments: list[Segment] = []
    parts: list[str] = []
    count = 0
    for seg in segments_iter:
        text = (seg.text or "").strip()
        if not text:
            continue
        segments.append(Segment(start=seg.start, end=seg.end, text=text))
        parts.append(text)
        count += 1
        if count % STT_PROGRESS_SEGMENT_INTERVAL == 0:
            logger.info(
                "Transcribed %d segments (last %.1fs – %.1fs)",
                count,
                segments[-1].start,
                segments[-1].end,
            )

    if count and count % STT_PROGRESS_SEGMENT_INTERVAL != 0:
        logger.info("Transcribed %d segments total", count)

    full_text = " ".join(parts).strip()
    detected_language = info.language or language or "unknown"
    duration = float(info.duration or 0.0)
    return segments, full_text, duration, detected_language


def _log_duration_hint(audio_path: Path) -> float:
    duration = read_duration_from_sidecar(audio_path)
    if duration is None:
        try:
            duration = probe_audio_duration(audio_path)
        except Exception:
            duration = 0.0
    if duration > LONG_AUDIO_WARN_MINUTES * 60:
        logger.warning(
            "Long audio (%.0f min). STT on CPU may take a while.",
            duration / 60,
        )
    else:
        logger.info("Audio duration: %.0f min", duration / 60)
    return duration


def _write_outputs(
    *,
    basename: str,
    output_dir: Path,
    result: TranscriptionResult,
    with_segments: bool,
) -> tuple[Path, Path]:
    txt_path = output_dir / f"{basename}.txt"
    json_path = output_dir / f"{basename}.json"

    txt_path.write_text(result.text + "\n", encoding="utf-8")

    payload: dict[str, Any] = {
        "text": result.text,
        "language": result.language,
        "duration_sec": result.duration_sec,
        "model": result.model,
        "source_path": result.source_path,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "parallel": result.parallel,
        "workers": result.workers,
    }
    if with_segments:
        payload["segments"] = [
            {"start": s.start, "end": s.end, "text": s.text} for s in result.segments
        ]

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return txt_path, json_path


def _audio_duration_sec(source: Path) -> float:
    duration = read_duration_from_sidecar(source)
    if duration is None:
        try:
            duration = probe_audio_duration(source)
        except Exception:
            duration = 0.0
    return float(duration or 0.0)


def _should_chunk_sequential(source: Path) -> bool:
    limit_sec = STT_CHUNK_WHEN_ABOVE_MINUTES * 60.0
    if limit_sec <= 0:
        return False
    return _audio_duration_sec(source) > limit_sec


def _transcribe_sequential_chunks(
    source: Path,
    *,
    out_dir: Path,
    basename: str,
    model_size: str,
    language: str | None,
    chunk_minutes: float,
    keep_chunks: bool,
    progress_callback: ProgressCallback | None = None,
) -> tuple[list[Segment], str, str, float]:
    """One Whisper model, chunks one-by-one — low RAM for long files on small VPS."""
    chunk_duration_sec = chunk_minutes * 60.0
    total_duration = _log_duration_hint(source)
    work_dir = chunk_work_dir(out_dir, basename)
    try:
        chunk_specs = split_audio_into_chunks(
            source,
            work_dir,
            chunk_duration_sec=chunk_duration_sec,
        )
        model = _load_whisper_model(model_size)
        chunk_results: list[ChunkResult] = []
        total_chunks = len(chunk_specs)
        for spec in chunk_specs:
            if progress_callback:
                pct = 12.0 + 78.0 * (spec.index / max(total_chunks, 1))
                progress_callback(pct, "Распознавание")
            segments, text, _duration, detected_lang = _run_transcription(
                model,
                spec.path,
                language=language,
            )
            for segment in segments:
                segment.start += spec.start_sec
                segment.end += spec.start_sec
            chunk_results.append(
                ChunkResult(
                    index=spec.index,
                    segments=segments,
                    text=text,
                    language=detected_lang,
                    duration_sec=spec.duration_sec,
                )
            )
            if progress_callback:
                pct = 12.0 + 78.0 * ((spec.index + 1) / max(total_chunks, 1))
                progress_callback(pct, "Распознавание")
            logger.info(
                "Sequential chunk %d/%d done (%s)",
                spec.index + 1,
                total_chunks,
                spec.path.name,
            )
        if progress_callback:
            progress_callback(92.0, "Сохраняю транскрипт…")
        segments, text, detected_lang = merge_chunk_results(
            chunk_results,
            total_duration_sec=total_duration,
        )
        return segments, text, detected_lang, total_duration
    finally:
        if not keep_chunks:
            cleanup_chunk_dir(work_dir)


def _transcribe_parallel(
    source: Path,
    *,
    out_dir: Path,
    basename: str,
    model_size: str,
    language: str | None,
    chunk_minutes: float,
    workers: int | None,
    keep_chunks: bool,
) -> tuple[list[Segment], str, str, float]:
    chunk_duration_sec = chunk_minutes * 60.0
    total_duration = _log_duration_hint(source)
    work_dir = chunk_work_dir(out_dir, basename)
    worker_count = resolve_workers(workers)

    try:
        chunk_specs = split_audio_into_chunks(
            source,
            work_dir,
            chunk_duration_sec=chunk_duration_sec,
        )
        chunk_results = transcribe_chunks_parallel(
            chunk_specs,
            model_size=model_size,
            language=language,
            workers=worker_count,
        )
        segments, text, detected_lang = merge_chunk_results(
            chunk_results,
            total_duration_sec=total_duration,
        )
        return segments, text, detected_lang, total_duration
    finally:
        if not keep_chunks:
            cleanup_chunk_dir(work_dir)


def transcribe_audio(
    audio_path: str | Path,
    *,
    output_dir: Path | None = None,
    model_size: str = WHISPER_MODEL_DEFAULT,
    language: str | None = None,
    with_segments: bool = True,
    parallel: bool = False,
    chunk_minutes: float = DEFAULT_CHUNK_MINUTES,
    workers: int | None = None,
    keep_chunks: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> TranscriptionResult:
    """
    Transcribe audio to text using faster-whisper on CPU.

    Writes .txt and .json to output_dir.
    """
    source = Path(audio_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Audio file not found: {source}")

    if source.suffix.lower() not in SUPPORTED_AUDIO_SUFFIXES:
        raise ValueError(
            f"Unsupported audio format: {source.suffix}. "
            f"Use one of: {', '.join(sorted(SUPPORTED_AUDIO_SUFFIXES))}"
        )

    out_dir = ensure_dir(output_dir or DEFAULT_TRANSCRIPT_DIR)
    basename = build_output_basename(source)
    worker_count = resolve_workers(workers) if parallel else 1

    use_parallel = parallel and worker_count > 1
    use_sequential_chunks = _should_chunk_sequential(source)
    logger.info(
        "Transcribing %s (parallel=%s, sequential_chunks=%s, workers=%s)",
        source,
        use_parallel,
        use_sequential_chunks and not use_parallel,
        worker_count,
    )

    try:
        if use_parallel:
            segments, text, detected_lang, duration = _transcribe_parallel(
                source,
                out_dir=out_dir,
                basename=basename,
                model_size=model_size,
                language=language,
                chunk_minutes=chunk_minutes,
                workers=workers,
                keep_chunks=keep_chunks,
            )
        elif use_sequential_chunks:
            segments, text, detected_lang, duration = _transcribe_sequential_chunks(
                source,
                out_dir=out_dir,
                basename=basename,
                model_size=model_size,
                language=language,
                chunk_minutes=chunk_minutes,
                keep_chunks=keep_chunks,
                progress_callback=progress_callback,
            )
        else:
            if progress_callback:
                progress_callback(20.0, "Распознавание")
            _log_duration_hint(source)
            model = _load_whisper_model(model_size)
            segments, text, duration, detected_lang = _run_transcription(
                model,
                source,
                language=language,
            )
    except ModelNotAvailableError:
        raise
    except Exception as exc:
        raise TranscriptionError(f"Transcription failed: {exc}") from exc

    result = TranscriptionResult(
        text=text,
        txt_path=out_dir / f"{basename}.txt",
        json_path=out_dir / f"{basename}.json",
        language=detected_lang,
        duration_sec=duration,
        segments=segments,
        model=model_size,
        source_path=str(source),
        parallel=use_parallel,
        workers=worker_count,
    )
    result.txt_path, result.json_path = _write_outputs(
        basename=basename,
        output_dir=out_dir,
        result=result,
        with_segments=with_segments,
    )
    logger.info("Wrote %s and %s", result.txt_path, result.json_path)
    return result
