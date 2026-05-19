import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve_ffmpeg() -> tuple[str, str] | None:
    local = PROJECT_ROOT / ".local" / "bin"
    for directory in (local, Path("/opt/homebrew/bin"), Path("/usr/local/bin")):
        ffmpeg = directory / "ffmpeg"
        ffprobe = directory / "ffprobe"
        if ffmpeg.is_file() and ffprobe.is_file():
            return str(ffmpeg), str(ffprobe)
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg and ffprobe:
        return ffmpeg, ffprobe
    return None


@pytest.fixture(scope="session")
def ffmpeg_tools() -> tuple[str, str] | None:
    return _resolve_ffmpeg()


@pytest.fixture(scope="session")
def ffmpeg_available(ffmpeg_tools) -> bool:
    return ffmpeg_tools is not None


@pytest.fixture(scope="session")
def sample_wav(tmp_path_factory, ffmpeg_tools):
    """Short mono WAV generated via ffmpeg for integration tests."""
    if not ffmpeg_tools:
        pytest.skip("ffmpeg not installed")

    ffmpeg, _ = ffmpeg_tools
    path = tmp_path_factory.mktemp("fixtures") / "sample.wav"

    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-ar",
            "44100",
            "-ac",
            "1",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


@pytest.fixture(scope="session")
def video_no_audio(tmp_path_factory, ffmpeg_tools):
    """MP4 with video track only (no audio) for CLI exit-code tests."""
    if not ffmpeg_tools:
        pytest.skip("ffmpeg not installed")

    ffmpeg, _ = ffmpeg_tools
    path = tmp_path_factory.mktemp("fixtures") / "video_no_audio.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:d=0.5",
            "-an",
            "-c:v",
            "libx264",
            "-t",
            "0.5",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path
