from __future__ import annotations

import logging
import os
import shutil
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from app.audio.ffmpeg import probe_file, require_ffmpeg_tools
from app.config import CHANNELS, DEFAULT_MAX_WORKERS, SAMPLE_RATE, WAV_CODEC
from app.stt.models import ChunkResult, Segment

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChunkSpec:
    index: int
    path: Path
    start_sec: float
    duration_sec: float


def resolve_workers(workers: int | None, *, default: int | None = None) -> int:
    if workers is not None:
        return max(1, workers)
    if default is not None:
        return max(1, default)
    cpu = os.cpu_count() or 2
    fallback = min(DEFAULT_MAX_WORKERS, max(1, cpu - 1))
    return max(1, fallback)


def probe_audio_duration(audio_path: Path) -> float:
    data = probe_file(audio_path)
    fmt = data.get("format", {})
    duration = fmt.get("duration")
    if duration is not None:
        return float(duration)
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "audio" and stream.get("duration"):
            return float(stream["duration"])
    return 0.0


def read_duration_from_sidecar(audio_path: Path) -> float | None:
    sidecar = Path(str(audio_path) + ".meta.json")
    if not sidecar.is_file():
        return None
    import json

    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        value = payload.get("duration_sec")
        return float(value) if value is not None else None
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def plan_chunks(total_duration_sec: float, chunk_duration_sec: float) -> list[tuple[float, float]]:
    if total_duration_sec <= 0:
        return [(0.0, chunk_duration_sec)]
    specs: list[tuple[float, float]] = []
    start = 0.0
    while start < total_duration_sec:
        duration = min(chunk_duration_sec, total_duration_sec - start)
        specs.append((start, duration))
        start += chunk_duration_sec
    return specs


def split_audio_into_chunks(
    audio_path: Path,
    chunk_dir: Path,
    *,
    chunk_duration_sec: float,
) -> list[ChunkSpec]:
    ffmpeg, _ = require_ffmpeg_tools()
    chunk_dir.mkdir(parents=True, exist_ok=True)
    total = probe_audio_duration(audio_path)
    plans = plan_chunks(total, chunk_duration_sec)
    specs: list[ChunkSpec] = []

    for index, (start_sec, duration_sec) in enumerate(plans):
        chunk_path = chunk_dir / f"chunk_{index:03d}.wav"
        args = [
            ffmpeg,
            "-y",
            "-i",
            str(audio_path),
            "-ss",
            str(start_sec),
            "-t",
            str(duration_sec),
            "-acodec",
            WAV_CODEC,
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            str(CHANNELS),
            str(chunk_path),
        ]
        logger.info(
            "Splitting chunk %s: start=%.1fs duration=%.1fs",
            chunk_path.name,
            start_sec,
            duration_sec,
        )
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            stderr = (result.stderr or "")[:2048]
            raise RuntimeError(f"ffmpeg chunk split failed: {stderr}")
        specs.append(
            ChunkSpec(
                index=index,
                path=chunk_path,
                start_sec=start_sec,
                duration_sec=duration_sec,
            )
        )
    return specs


def _transcribe_chunk_task(
    chunk_path: str,
    model_size: str,
    language: str | None,
    time_offset_sec: float,
) -> ChunkResult:
    """Top-level worker for ProcessPoolExecutor (must be picklable)."""
    from app.stt.transcriber import _load_whisper_model, _run_transcription

    path = Path(chunk_path)
    model = _load_whisper_model(model_size)
    segments, text, duration, detected_lang = _run_transcription(
        model, path, language=language
    )
    for segment in segments:
        segment.start += time_offset_sec
        segment.end += time_offset_sec
    return ChunkResult(
        index=-1,
        segments=segments,
        text=text,
        language=detected_lang,
        duration_sec=duration,
    )


def transcribe_chunks_parallel(
    chunk_specs: list[ChunkSpec],
    *,
    model_size: str,
    language: str | None,
    workers: int,
) -> list[ChunkResult]:
    if not chunk_specs:
        return []

    if workers <= 1 or len(chunk_specs) == 1:
        spec = chunk_specs[0]
        one = _transcribe_chunk_task(
            str(spec.path), model_size, language, spec.start_sec
        )
        one.index = spec.index
        return [one]

    results: list[ChunkResult] = []
    logger.info(
        "Parallel transcription: %d chunks, %d workers",
        len(chunk_specs),
        workers,
    )

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _transcribe_chunk_task,
                str(spec.path),
                model_size,
                language,
                spec.start_sec,
            ): spec
            for spec in chunk_specs
        }
        for future in as_completed(futures):
            spec = futures[future]
            result = future.result()
            result.index = spec.index
            results.append(result)
            logger.info(
                "Completed chunk %d/%d",
                spec.index + 1,
                len(chunk_specs),
            )
    return results


def merge_chunk_results(
    chunk_results: list[ChunkResult],
    *,
    total_duration_sec: float,
) -> tuple[list[Segment], str, str]:
    ordered = sorted(chunk_results, key=lambda item: item.index)
    segments: list[Segment] = []
    text_parts: list[str] = []
    languages: list[str] = []

    for chunk in ordered:
        segments.extend(chunk.segments)
        if chunk.text:
            text_parts.append(chunk.text)
        if chunk.language:
            languages.append(chunk.language)

    segments.sort(key=lambda seg: seg.start)
    language = languages[0] if languages else "unknown"
    full_text = " ".join(text_parts).strip()
    return segments, full_text, language


def cleanup_chunk_dir(chunk_dir: Path) -> None:
    if chunk_dir.is_dir():
        shutil.rmtree(chunk_dir)
        logger.info("Removed chunk directory %s", chunk_dir)


def chunk_work_dir(output_dir: Path, basename: str) -> Path:
    return output_dir / ".chunks" / basename
