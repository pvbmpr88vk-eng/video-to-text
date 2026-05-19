from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from app.audio import ffmpeg as ffmpeg_tools
from app.config import CHANNELS, DEFAULT_OUTPUT_DIR, SAMPLE_RATE
from app.utils.paths import build_output_basename, ensure_dir

logger = logging.getLogger(__name__)

AudioFormat = Literal["wav", "mp3"]


def _write_metadata(sidecar_path: Path, metadata: dict[str, Any]) -> None:
    sidecar_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def extract_audio(
    input_path: str | Path,
    *,
    output_dir: Path | None = None,
    format: AudioFormat = "wav",
    audio_track_index: int = 0,
    max_duration_sec: float | None = None,
) -> Path:
    """
    Extract and normalize audio from a video or audio file.

    Returns path to the created audio file. Writes {stem}.meta.json sidecar.
    """
    source = Path(input_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Input file not found: {source}")

    ffmpeg_tools.require_ffmpeg_tools()

    out_dir = ensure_dir(output_dir or DEFAULT_OUTPUT_DIR)
    basename = build_output_basename(source)
    extension = f".{format}"
    output_path = out_dir / f"{basename}{extension}"

    logger.info("Extracting audio from %s -> %s", source, output_path)
    ffmpeg_tools.extract_audio_file(
        source,
        output_path,
        audio_format=format,
        audio_track_index=audio_track_index,
        max_duration_sec=max_duration_sec,
    )

    probed = ffmpeg_tools.probe_output_audio(output_path)
    created_at = datetime.now(timezone.utc).isoformat()
    metadata: dict[str, Any] = {
        "duration_sec": probed["duration_sec"],
        "sample_rate": probed["sample_rate"] or SAMPLE_RATE,
        "channels": probed["channels"] or CHANNELS,
        "format": format,
        "codec": probed["codec_name"],
        "source_path": str(source),
        "output_path": str(output_path),
        "created_at": created_at,
        "audio_track_index": audio_track_index,
    }
    if max_duration_sec is not None:
        metadata["max_duration_sec"] = max_duration_sec

    sidecar = output_path.with_suffix(output_path.suffix + ".meta.json")
    _write_metadata(sidecar, metadata)
    logger.info("Wrote metadata %s", sidecar)
    return output_path
