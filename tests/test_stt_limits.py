from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.stt.limits import audio_too_long_for_stt
from app.stt.transcriber import _should_chunk_sequential


def test_audio_too_long_when_above_limit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STT_MAX_AUDIO_DURATION_MINUTES", "30")
    import importlib

    import app.config as cfg
    import app.stt.limits as lim

    importlib.reload(cfg)
    lim = importlib.reload(lim)
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    with patch.object(lim, "audio_duration_sec", return_value=48 * 60):
        too_long, duration = lim.audio_too_long_for_stt(wav)
    assert too_long is True
    assert duration == 48 * 60


def test_should_chunk_sequential_for_long_audio(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STT_CHUNK_WHEN_ABOVE_MINUTES", "12")
    import importlib

    import app.config as cfg
    import app.stt.transcriber as tr

    importlib.reload(cfg)
    tr = importlib.reload(tr)
    wav = tmp_path / "long.wav"
    wav.write_bytes(b"x")
    with patch.object(tr, "_audio_duration_sec", return_value=20 * 60):
        assert tr._should_chunk_sequential(wav) is True
    with patch.object(tr, "_audio_duration_sec", return_value=5 * 60):
        assert tr._should_chunk_sequential(wav) is False
