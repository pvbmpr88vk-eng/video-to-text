"""Production STT: GPU Sharing first, local Whisper fallback."""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import GPU_SHARING_STT_FALLBACK_CPU, GPU_SHARING_TRANSCRIPT
from app.gpu_sharing.client import GPUSharingError, client_from_config
from app.gpu_sharing.remote_stt import transcribe_wav_via_gpu
from app.stt.exceptions import TranscriptionError
from app.stt.transcriber import TranscriptionResult, transcribe_audio

logger = logging.getLogger(__name__)


def gpu_transcript_enabled() -> bool:
    return bool(GPU_SHARING_TRANSCRIPT)


def gpu_stt_ready() -> bool:
    if not GPU_SHARING_TRANSCRIPT:
        return False
    client = client_from_config()
    return client is not None and client.has_online_node()


def transcribe_wav_for_prod(
    wav_path: Path,
    *,
    output_dir: Path,
    model_size: str,
    language: str | None,
    with_segments: bool,
    parallel: bool,
    chunk_minutes: int,
    workers: int,
    keep_chunks: bool,
    progress_callback=None,
) -> TranscriptionResult:
    """
    Try GPU Sharing STT when configured; fall back to local faster-whisper on VPS.
    """
    if not GPU_SHARING_TRANSCRIPT:
        return transcribe_audio(
            wav_path,
            output_dir=output_dir,
            model_size=model_size,
            language=language,
            with_segments=with_segments,
            parallel=parallel,
            chunk_minutes=chunk_minutes,
            workers=workers,
            keep_chunks=keep_chunks,
            progress_callback=progress_callback,
        )

    if not gpu_stt_ready():
        if GPU_SHARING_STT_FALLBACK_CPU:
            logger.warning("GPU Sharing offline — local Whisper on VPS")
            return _local_transcribe(
                wav_path,
                output_dir=output_dir,
                model_size=model_size,
                language=language,
                with_segments=with_segments,
                parallel=parallel,
                chunk_minutes=chunk_minutes,
                workers=workers,
                keep_chunks=keep_chunks,
                progress_callback=progress_callback,
            )
        raise TranscriptionError("GPU Sharing: no online GPU node")

    try:
        return transcribe_wav_via_gpu(
            wav_path,
            output_dir=output_dir,
            language=language,
            progress_callback=progress_callback,
        )
    except GPUSharingError as exc:
        logger.warning("GPU Sharing STT (legacy jobs) failed: %s", exc)
        if not GPU_SHARING_STT_FALLBACK_CPU:
            raise TranscriptionError(str(exc)) from exc

    logger.info(
        "GPU STT unavailable (v3 needs GPU_SHARING_STT_ONNX_MODEL_URL); "
        "using local Whisper on VPS"
    )
    return _local_transcribe(
        wav_path,
        output_dir=output_dir,
        model_size=model_size,
        language=language,
        with_segments=with_segments,
        parallel=parallel,
        chunk_minutes=chunk_minutes,
        workers=workers,
        keep_chunks=keep_chunks,
        progress_callback=progress_callback,
    )


def _local_transcribe(
    wav_path: Path,
    *,
    output_dir: Path,
    model_size: str,
    language: str | None,
    with_segments: bool,
    parallel: bool,
    chunk_minutes: int,
    workers: int,
    keep_chunks: bool,
    progress_callback=None,
) -> TranscriptionResult:
    return transcribe_audio(
        wav_path,
        output_dir=output_dir,
        model_size=model_size,
        language=language,
        with_segments=with_segments,
        parallel=parallel,
        chunk_minutes=chunk_minutes,
        workers=workers,
        keep_chunks=keep_chunks,
        progress_callback=progress_callback,
    )
