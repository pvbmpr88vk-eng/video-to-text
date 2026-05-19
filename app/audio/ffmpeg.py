from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.audio.exceptions import FFmpegError, FFmpegNotFoundError, NoAudioStreamError
from app.config import (
    CHANNELS,
    FFMPEG_STDERR_LOG_LIMIT,
    LOCAL_BIN_DIR,
    MP3_BITRATE,
    MP3_CODEC,
    SAMPLE_RATE,
    WAV_CODEC,
)

logger = logging.getLogger(__name__)

FFMPEG_INSTALL_HINT = (
    "Install FFmpeg: macOS — `brew install ffmpeg`; "
    "or see https://ffmpeg.org/download.html"
)


def _project_local_tools() -> tuple[str, str] | None:
    """Binaries from ./scripts/install-ffmpeg-local.sh → .local/bin/."""
    ffmpeg = LOCAL_BIN_DIR / "ffmpeg"
    ffprobe = LOCAL_BIN_DIR / "ffprobe"
    if ffmpeg.is_file() and ffprobe.is_file():
        return str(ffmpeg), str(ffprobe)
    return None


def require_ffmpeg_tools() -> tuple[str, str]:
    local = _project_local_tools()
    if local:
        return local

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise FFmpegNotFoundError(
            f"ffmpeg and ffprobe not found. Run ./scripts/install-ffmpeg-local.sh "
            f"or add FFmpeg to PATH. {FFMPEG_INSTALL_HINT}"
        )
    return ffmpeg, ffprobe


def _run(
    args: list[str],
    *,
    tool: str,
) -> subprocess.CompletedProcess[str]:
    logger.info("Running %s", " ".join(args))
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "")[:FFMPEG_STDERR_LOG_LIMIT]
        logger.error("%s failed (code %s): %s", tool, result.returncode, stderr)
        raise FFmpegError(f"{tool} failed with code {result.returncode}", stderr=stderr)
    return result


def probe_audio_streams(input_path: Path) -> list[dict[str, Any]]:
    _, ffprobe = require_ffmpeg_tools()
    args = [
        ffprobe,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        "-select_streams",
        "a",
        str(input_path),
    ]
    result = _run(args, tool="ffprobe")
    payload = json.loads(result.stdout or "{}")
    streams = payload.get("streams", [])
    if not isinstance(streams, list):
        return []
    return streams


def count_audio_streams(input_path: Path) -> int:
    return len(probe_audio_streams(input_path))


def probe_file(input_path: Path) -> dict[str, Any]:
    _, ffprobe = require_ffmpeg_tools()
    args = [
        ffprobe,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(input_path),
    ]
    result = _run(args, tool="ffprobe")
    return json.loads(result.stdout or "{}")


def probe_output_audio(output_path: Path) -> dict[str, Any]:
    data = probe_file(output_path)
    audio_streams = [
        s for s in data.get("streams", []) if s.get("codec_type") == "audio"
    ]
    fmt = data.get("format", {})
    stream = audio_streams[0] if audio_streams else {}
    duration = stream.get("duration") or fmt.get("duration")
    return {
        "duration_sec": float(duration) if duration is not None else 0.0,
        "sample_rate": int(stream.get("sample_rate", 0) or 0),
        "channels": int(stream.get("channels", 0) or 0),
        "codec_name": stream.get("codec_name", ""),
    }


def extract_audio_file(
    input_path: Path,
    output_path: Path,
    *,
    audio_format: str,
    audio_track_index: int = 0,
    max_duration_sec: float | None = None,
) -> None:
    ffmpeg, _ = require_ffmpeg_tools()
    streams = probe_audio_streams(input_path)
    if not streams:
        raise NoAudioStreamError(f"No audio stream in file: {input_path}")
    if audio_track_index < 0 or audio_track_index >= len(streams):
        raise NoAudioStreamError(
            f"Audio track index {audio_track_index} out of range "
            f"(available: {len(streams)})"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    args: list[str] = [
        ffmpeg,
        "-y",
        "-i",
        str(input_path),
        "-map",
        f"0:a:{audio_track_index}",
        "-vn",
    ]
    if max_duration_sec is not None:
        args.extend(["-t", str(max_duration_sec)])

    if audio_format == "wav":
        args.extend(
            [
                "-acodec",
                WAV_CODEC,
                "-ar",
                str(SAMPLE_RATE),
                "-ac",
                str(CHANNELS),
                str(output_path),
            ]
        )
    elif audio_format == "mp3":
        args.extend(
            [
                "-acodec",
                MP3_CODEC,
                "-ar",
                str(SAMPLE_RATE),
                "-ac",
                str(CHANNELS),
                "-b:a",
                MP3_BITRATE,
                str(output_path),
            ]
        )
    else:
        raise ValueError(f"Unsupported format: {audio_format}")

    _run(args, tool="ffmpeg")
