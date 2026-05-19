from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.stt.exceptions import ModelNotAvailableError
from app.stt.models import Segment
from app.stt.transcriber import transcribe_audio


def test_transcribe_audio_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        transcribe_audio(tmp_path / "missing.wav", output_dir=tmp_path / "out")


def test_transcribe_unsupported_format(tmp_path):
    bad = tmp_path / "clip.xyz"
    bad.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported"):
        transcribe_audio(bad, output_dir=tmp_path / "out")


@patch("app.stt.transcriber._log_duration_hint", return_value=1.5)
@patch("app.stt.transcriber._load_whisper_model")
def test_transcribe_writes_txt_and_json(mock_load, _mock_duration, tmp_path):
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"\x00\x00")
    out_dir = tmp_path / "transcripts"

    mock_segment = SimpleNamespace(start=0.0, end=1.5, text=" Привет мир ")
    mock_info = SimpleNamespace(language="ru", duration=1.5)
    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([mock_segment], mock_info)
    mock_load.return_value = mock_model

    with patch(
        "app.stt.transcriber.build_output_basename",
        return_value="sample_20260101T000000Z",
    ):
        result = transcribe_audio(audio, output_dir=out_dir, language="ru")

    assert result.text == "Привет мир"
    assert result.language == "ru"
    assert result.txt_path.exists()
    assert result.json_path.exists()
    assert result.txt_path.read_text(encoding="utf-8").strip() == "Привет мир"

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["language"] == "ru"
    assert len(payload["segments"]) == 1
    assert payload["segments"][0]["text"] == "Привет мир"


@patch("app.stt.transcriber._transcribe_parallel")
@patch("app.stt.transcriber._load_whisper_model")
def test_transcribe_parallel_path(mock_load, mock_parallel, tmp_path):
    audio = tmp_path / "long.wav"
    audio.write_bytes(b"x")
    mock_parallel.return_value = (
        [Segment(start=0.0, end=1.0, text="ok")],
        "ok",
        "ru",
        600.0,
    )
    result = transcribe_audio(
        audio,
        output_dir=tmp_path / "out",
        parallel=True,
        workers=2,
    )
    assert result.parallel is True
    assert result.workers == 2
    mock_parallel.assert_called_once()
    mock_load.assert_not_called()


@patch("app.stt.transcriber._log_duration_hint", return_value=1.0)
@patch("app.stt.transcriber._load_whisper_model")
def test_model_not_available(mock_load, _mock_duration, tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    mock_load.side_effect = ModelNotAvailableError("pip install -r requirements.txt")
    with pytest.raises(ModelNotAvailableError):
        transcribe_audio(audio, output_dir=tmp_path / "out")
