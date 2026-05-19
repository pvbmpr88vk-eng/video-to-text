from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from app.audio.exceptions import FFmpegNotFoundError, NoAudioStreamError
from app.audio.extractor import extract_audio
from app.audio import ffmpeg as ffmpeg_tools
from app.config import CHANNELS, SAMPLE_RATE
from tests.conftest import PROJECT_ROOT


def test_require_ffmpeg_raises_when_missing(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _: None)
    monkeypatch.setattr(ffmpeg_tools, "_project_local_tools", lambda: None)
    with pytest.raises(FFmpegNotFoundError, match="PATH|not found"):
        ffmpeg_tools.require_ffmpeg_tools()


def test_extract_audio_file_not_found(tmp_path):
    missing = tmp_path / "missing.mp4"
    with pytest.raises(FileNotFoundError):
        extract_audio(missing, output_dir=tmp_path / "out")


@patch("app.audio.extractor.ffmpeg_tools.extract_audio_file")
@patch("app.audio.extractor.ffmpeg_tools.probe_output_audio")
@patch("app.audio.extractor.ffmpeg_tools.require_ffmpeg_tools")
def test_extract_audio_writes_metadata(
    mock_require,
    mock_probe,
    mock_extract,
    tmp_path,
):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fake")
    out_dir = tmp_path / "out"
    output = out_dir / "clip_20260101T000000Z.wav"
    mock_extract.return_value = None
    mock_probe.return_value = {
        "duration_sec": 1.0,
        "sample_rate": SAMPLE_RATE,
        "channels": CHANNELS,
        "codec_name": "pcm_s16le",
    }

    with patch(
        "app.audio.extractor.build_output_basename",
        return_value="clip_20260101T000000Z",
    ):
        result = extract_audio(source, output_dir=out_dir, format="wav")

    assert result == output
    sidecar = Path(str(output) + ".meta.json")
    assert sidecar.exists()
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    assert meta["duration_sec"] == 1.0
    assert meta["sample_rate"] == SAMPLE_RATE
    assert meta["channels"] == CHANNELS
    assert meta["format"] == "wav"
    assert meta["source_path"] == str(source.resolve())


def test_no_audio_stream_error_from_ffmpeg_layer(tmp_path):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"x")
    with patch(
        "app.audio.ffmpeg.probe_audio_streams",
        return_value=[],
    ), patch(
        "app.audio.ffmpeg.require_ffmpeg_tools",
        return_value=("ffmpeg", "ffprobe"),
    ):
        with pytest.raises(NoAudioStreamError):
            ffmpeg_tools.extract_audio_file(
                source,
                tmp_path / "out.wav",
                audio_format="wav",
            )


@pytest.mark.integration
def test_extract_wav_from_sample(sample_wav, tmp_path, ffmpeg_available):
    if not ffmpeg_available:
        pytest.skip("ffmpeg not installed")

    out_dir = tmp_path / "audio"
    result = extract_audio(sample_wav, output_dir=out_dir, format="wav")
    assert result.exists()
    assert result.suffix == ".wav"

    probed = ffmpeg_tools.probe_output_audio(result)
    assert probed["sample_rate"] == SAMPLE_RATE
    assert probed["channels"] == CHANNELS
    assert probed["codec_name"] == "pcm_s16le"
    assert probed["duration_sec"] == pytest.approx(1.0, abs=0.5)

    sidecar = Path(str(result) + ".meta.json")
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    assert meta["duration_sec"] == pytest.approx(1.0, abs=0.5)


@pytest.mark.integration
def test_cli_extract_audio_no_audio_exits_2(video_no_audio, tmp_path, ffmpeg_available):
    if not ffmpeg_available:
        pytest.skip("ffmpeg not installed")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app",
            "extract-audio",
            str(video_no_audio),
            "--output-dir",
            str(tmp_path / "out"),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "No audio stream" in result.stderr


@pytest.mark.integration
def test_extract_mp3_from_sample(sample_wav, tmp_path, ffmpeg_available):
    if not ffmpeg_available:
        pytest.skip("ffmpeg not installed")

    result = extract_audio(sample_wav, output_dir=tmp_path / "out", format="mp3")
    assert result.suffix == ".mp3"
    probed = ffmpeg_tools.probe_output_audio(result)
    assert probed["sample_rate"] == SAMPLE_RATE
    assert probed["channels"] == CHANNELS
