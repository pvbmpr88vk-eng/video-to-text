from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.gpu_sharing.client import GPUSharingError
from app.stt.exceptions import TranscriptionError


def test_transcribe_wav_for_prod_falls_back_on_gpu_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GPU_SHARING_TRANSCRIPT", "1")
    monkeypatch.setenv("GPU_SHARING_STT_FALLBACK_CPU", "1")
    monkeypatch.setenv("GPU_SHARING_API_KEY", "gpu_sk_test")

    import importlib

    import app.config as config
    import app.gpu_sharing.prod_stt as prod_stt

    importlib.reload(config)
    importlib.reload(prod_stt)

    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    out_dir = tmp_path / "out"
    expected = MagicMock()

    with (
        patch.object(prod_stt, "gpu_stt_ready", return_value=True),
        patch(
            "app.gpu_sharing.remote_stt.transcribe_wav_via_gpu",
            side_effect=GPUSharingError("HTTP 404 /v1/jobs"),
        ),
        patch.object(prod_stt, "transcribe_audio", return_value=expected) as local,
    ):
        result = prod_stt.transcribe_wav_for_prod(
            wav,
            output_dir=out_dir,
            model_size="small",
            language="ru",
            with_segments=True,
            parallel=False,
            chunk_minutes=12,
            workers=1,
            keep_chunks=False,
        )

    assert result is expected
    local.assert_called_once()


def test_transcribe_wav_for_prod_no_fallback_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GPU_SHARING_TRANSCRIPT", "1")
    monkeypatch.setenv("GPU_SHARING_STT_FALLBACK_CPU", "0")
    monkeypatch.setenv("GPU_SHARING_API_KEY", "gpu_sk_test")

    import importlib

    import app.config as config
    import app.gpu_sharing.prod_stt as prod_stt

    importlib.reload(config)
    importlib.reload(prod_stt)

    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")

    with (
        patch.object(prod_stt, "gpu_stt_ready", return_value=False),
        pytest.raises(TranscriptionError, match="no online GPU"),
    ):
        prod_stt.transcribe_wav_for_prod(
            wav,
            output_dir=tmp_path / "out",
            model_size="small",
            language=None,
            with_segments=False,
            parallel=False,
            chunk_minutes=12,
            workers=1,
            keep_chunks=False,
        )
