from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from app.darwin import configure_fork_safety

configure_fork_safety()

from app.audio.exceptions import FFmpegError, FFmpegNotFoundError, NoAudioStreamError
from app.audio.extractor import extract_audio
from app.config import (
    DEFAULT_CHUNK_MINUTES,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SUMMARY_DIR,
    DEFAULT_TRANSCRIPT_DIR,
    OLLAMA_HOST,
    OLLAMA_MODEL_DEFAULT,
    WHISPER_MODEL_DEFAULT,
)
from app.stt.exceptions import ModelNotAvailableError, TranscriptionError
from app.stt.transcriber import transcribe_audio
from app.summary.exceptions import (
    EmptyTranscriptError,
    SummaryAPIError,
    SummaryConfigError,
    SummaryError,
)
from app.summary.summarizer import summarize_transcript

EXIT_SUCCESS = 0
EXIT_FILE_NOT_FOUND = 1
EXIT_NO_AUDIO = 2
EXIT_FFMPEG = 3
EXIT_INVALID_ARGS = 4
EXIT_STT = 5
EXIT_SUMMARY = 6
EXIT_BOT = 7


def _configure_logging(verbose: bool) -> None:
    from app.logging_setup import configure_logging

    configure_logging(verbose=verbose)


def _add_transcribe_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--model",
        default=WHISPER_MODEL_DEFAULT,
        help=f"Whisper model size (default: {WHISPER_MODEL_DEFAULT})",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Language code, e.g. ru, en (default: auto-detect)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_TRANSCRIPT_DIR,
        help=f"Transcript output directory (default: {DEFAULT_TRANSCRIPT_DIR})",
    )
    parser.add_argument(
        "--no-segments",
        action="store_true",
        help="Do not include timed segments in JSON output",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Split audio into chunks and transcribe in parallel (CPU)",
    )
    parser.add_argument(
        "--chunk-minutes",
        type=float,
        default=DEFAULT_CHUNK_MINUTES,
        help=f"Chunk length in minutes for --parallel (default: {DEFAULT_CHUNK_MINUTES})",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Parallel worker processes (default: min(4, cpu_count-1))",
    )
    parser.add_argument(
        "--keep-chunks",
        action="store_true",
        help="Keep temporary chunk WAV files after parallel transcribe",
    )


def _add_summarize_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--model",
        default=OLLAMA_MODEL_DEFAULT,
        help=f"Ollama model tag (default: {OLLAMA_MODEL_DEFAULT})",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Summary language, e.g. ru (default: from transcript or ru)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_SUMMARY_DIR,
        help=f"Summary output directory (default: {DEFAULT_SUMMARY_DIR})",
    )
    parser.add_argument(
        "--ollama-host",
        default=OLLAMA_HOST,
        help=f"Ollama API base URL (default: {OLLAMA_HOST})",
    )
    parser.add_argument(
        "--with-quotes",
        action="store_true",
        help="Include timestamped quotes when transcript has segments",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app",
        description="video-to-text: extract audio and transcribe speech",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract = subparsers.add_parser(
        "extract-audio",
        help="Extract audio track to WAV (16 kHz mono) or MP3",
    )
    extract.add_argument("input_path", type=Path, help="Path to video or audio file")
    extract.add_argument(
        "--format",
        choices=("wav", "mp3"),
        default="wav",
        help="Output format (default: wav)",
    )
    extract.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    extract.add_argument(
        "--audio-track-index",
        type=int,
        default=0,
        help="Zero-based audio stream index (default: 0)",
    )
    extract.add_argument(
        "--max-duration",
        type=float,
        default=None,
        metavar="SEC",
        help="Limit output duration in seconds",
    )
    extract.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Debug logging",
    )

    transcribe = subparsers.add_parser(
        "transcribe",
        help="Transcribe audio to text (faster-whisper, CPU)",
    )
    transcribe.add_argument("audio_path", type=Path, help="Path to WAV/MP3 audio file")
    _add_transcribe_args(transcribe)
    transcribe.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Debug logging",
    )

    process = subparsers.add_parser(
        "process",
        help="Extract audio from video then transcribe (full pipeline)",
    )
    process.add_argument("input_path", type=Path, help="Path to video or audio file")
    process.add_argument(
        "--audio-format",
        choices=("wav", "mp3"),
        default="wav",
        help="Extracted audio format (default: wav)",
    )
    process.add_argument(
        "--audio-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Audio output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    _add_transcribe_args(process)
    process.add_argument(
        "--summarize",
        action="store_true",
        help="After transcribe, run local LLM summary (Ollama)",
    )
    process.add_argument(
        "--summary-model",
        default=OLLAMA_MODEL_DEFAULT,
        help=f"Ollama model for --summarize (default: {OLLAMA_MODEL_DEFAULT})",
    )
    process.add_argument(
        "--summary-dir",
        type=Path,
        default=DEFAULT_SUMMARY_DIR,
        help=f"Summary output directory (default: {DEFAULT_SUMMARY_DIR})",
    )
    process.add_argument(
        "--ollama-host",
        default=OLLAMA_HOST,
        help=f"Ollama API URL for --summarize (default: {OLLAMA_HOST})",
    )
    process.add_argument(
        "--with-quotes",
        action="store_true",
        help="Include timestamped quotes in summary",
    )
    process.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Debug logging",
    )

    summarize = subparsers.add_parser(
        "summarize",
        help="Summarize transcript via local Ollama LLM",
    )
    summarize.add_argument(
        "transcript_path",
        type=Path,
        help="Path to transcript .json or .txt from transcribe",
    )
    _add_summarize_args(summarize)
    summarize.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Debug logging",
    )

    bot = subparsers.add_parser(
        "bot",
        help="Run Telegram bot (long polling; see docs/TZ-04-telegram-bot.md)",
    )
    bot.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Debug logging",
    )

    worker = subparsers.add_parser("worker", help="Run RQ worker (transcript or summary)")
    worker.add_argument("kind", choices=("transcript", "summary"), help="Worker queue type")
    worker.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    health = subparsers.add_parser("health", help="Check Redis, FFmpeg, Ollama")
    health.add_argument(
        "--skip-ollama",
        action="store_true",
        help="Do not check Ollama (for transcript-only workers)",
    )

    gpu_check = subparsers.add_parser(
        "gpu-sharing-check",
        help="Smoke test GPU Sharing API v3 (health, nodes, ONNX invoke)",
    )
    gpu_check.add_argument(
        "--skip-invoke",
        action="store_true",
        help="Only check /health, nodes, runtimes (no ONNX invoke)",
    )
    gpu_check.add_argument(
        "--model-url",
        default=None,
        help="ONNX model URL for invoke test (default: GPU_SHARING_TEST_MODEL_URL)",
    )

    gpu_stt = subparsers.add_parser(
        "gpu-sharing-transcribe",
        help="[deprecated v1/v2] Docker jobs STT — use ONNX v3 instead (docs/gpu-sharing.md)",
    )
    gpu_stt.add_argument(
        "--audio-url",
        default=None,
        help="Public HTTP(S) URL to WAV/MP3 for remote worker",
    )
    gpu_stt.add_argument(
        "--audio-path",
        type=Path,
        default=None,
        help="Local file — upload to GPU_SHARING_STT_PUBLISH_HOST then transcribe",
    )
    gpu_stt.add_argument(
        "--model",
        default=None,
        help="Whisper model on remote worker (default: GPU_SHARING_STT_MODEL)",
    )

    queue = subparsers.add_parser("queue", help="Redis/RQ queue diagnostics")
    queue_sub = queue.add_subparsers(dest="queue_command", required=True)
    queue_sub.add_parser("status", help="Show workers and queue depth")
    queue_sub.add_parser("prune-workers", help="Unregister dead RQ workers from Redis")

    jobs = subparsers.add_parser("jobs", help="Job maintenance")
    jobs_sub = jobs.add_subparsers(dest="jobs_command", required=True)
    cleanup = jobs_sub.add_parser("cleanup", help="Remove old job directories")
    cleanup.add_argument(
        "--ttl-hours",
        type=int,
        default=None,
        help="TTL in hours (default: JOB_CLEANUP_TTL_HOURS)",
    )
    cleanup.add_argument("--dry-run", action="store_true", help="List dirs without deleting")
    reset_stuck = jobs_sub.add_parser(
        "reset-stuck",
        help="Fail zombie jobs in extract/stt and reconcile queue (restart worker after)",
    )

    return parser


def _run_transcribe_args(
    args: argparse.Namespace, audio_path: Path
) -> tuple[int, Path | None]:
    print(
        f"Starting transcription: {audio_path} "
        f"(model={args.model}, parallel={args.parallel})",
        flush=True,
    )
    try:
        result = transcribe_audio(
            audio_path,
            output_dir=args.output_dir,
            model_size=args.model,
            language=args.language,
            with_segments=not args.no_segments,
            parallel=args.parallel,
            chunk_minutes=args.chunk_minutes,
            workers=args.workers,
            keep_chunks=args.keep_chunks,
        )
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_FILE_NOT_FOUND, None
    except (ModelNotAvailableError, TranscriptionError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_STT, None
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_INVALID_ARGS, None

    print(result.txt_path)
    return EXIT_SUCCESS, result.json_path


def _cmd_extract_audio(args: argparse.Namespace) -> int:
    try:
        output = extract_audio(
            args.input_path,
            output_dir=args.output_dir,
            format=args.format,
            audio_track_index=args.audio_track_index,
            max_duration_sec=args.max_duration,
        )
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_FILE_NOT_FOUND
    except NoAudioStreamError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_NO_AUDIO
    except FFmpegNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_FFMPEG
    except FFmpegError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if exc.stderr:
            print(exc.stderr, file=sys.stderr)
        return EXIT_FFMPEG
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_INVALID_ARGS

    print(output)
    return EXIT_SUCCESS


def _cmd_transcribe(args: argparse.Namespace) -> int:
    code, _ = _run_transcribe_args(args, args.audio_path)
    return code


def _cmd_process(args: argparse.Namespace) -> int:
    try:
        audio_path = extract_audio(
            args.input_path,
            output_dir=args.audio_dir,
            format=args.audio_format,
        )
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_FILE_NOT_FOUND
    except NoAudioStreamError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_NO_AUDIO
    except FFmpegNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_FFMPEG
    except FFmpegError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if exc.stderr:
            print(exc.stderr, file=sys.stderr)
        return EXIT_FFMPEG
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_INVALID_ARGS

    print(f"Audio: {audio_path}")
    code, json_path = _run_transcribe_args(args, audio_path)
    if code != EXIT_SUCCESS or not args.summarize:
        return code
    if json_path is None:
        print("Error: transcript path missing after transcribe", file=sys.stderr)
        return EXIT_SUMMARY
    return _run_summarize_args(
        args,
        json_path,
        output_dir=args.summary_dir,
        model=args.summary_model,
        ollama_host=args.ollama_host,
        with_quotes=args.with_quotes,
    )


def _run_summarize_args(
    args: argparse.Namespace,
    transcript_path: Path,
    *,
    output_dir: Path | None = None,
    model: str | None = None,
    ollama_host: str | None = None,
    with_quotes: bool | None = None,
) -> int:
    summary_model = model or getattr(args, "model", OLLAMA_MODEL_DEFAULT)
    print(f"Starting summary: {transcript_path} (model={summary_model})", flush=True)
    try:
        result = summarize_transcript(
            transcript_path,
            output_dir=output_dir or args.output_dir,
            language=getattr(args, "language", None),
            with_quotes=(
                with_quotes
                if with_quotes is not None
                else getattr(args, "with_quotes", False)
            ),
            model=summary_model,
            ollama_host=ollama_host or getattr(args, "ollama_host", OLLAMA_HOST),
        )
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_FILE_NOT_FOUND
    except EmptyTranscriptError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_SUMMARY
    except (SummaryConfigError, SummaryAPIError, SummaryError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_SUMMARY
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_INVALID_ARGS

    print(result.summary_path)
    return EXIT_SUCCESS


def _cmd_summarize(args: argparse.Namespace) -> int:
    return _run_summarize_args(args, args.transcript_path)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _configure_logging(getattr(args, "verbose", False))

    if args.command == "extract-audio":
        return _cmd_extract_audio(args)
    if args.command == "transcribe":
        return _cmd_transcribe(args)
    if args.command == "process":
        return _cmd_process(args)
    if args.command == "summarize":
        return _cmd_summarize(args)
    if args.command == "bot":
        from app.telegram.bot import run_bot

        run_bot(verbose=args.verbose)
        return EXIT_SUCCESS
    if args.command == "worker":
        from app.worker.runner import run_worker

        run_worker(args.kind, verbose=args.verbose)
        return EXIT_SUCCESS
    if args.command == "health":
        from app.worker.health import run_health_check

        return run_health_check(check_ollama=not args.skip_ollama)
    if args.command == "gpu-sharing-check":
        from app.config import GPU_SHARING_RUNTIME, GPU_SHARING_TEST_MODEL_URL
        from app.gpu_sharing.client import GPUSharingError, client_from_config

        client = client_from_config()
        if client is None:
            print("Error: set GPU_SHARING_API_KEY in .env", file=sys.stderr)
            return EXIT_INVALID_ARGS
        try:
            health = client.health()
            print(f"health: {health}")
            nodes = client.list_nodes()
            online = sum(1 for n in nodes if n.get("status") == "online")
            print(f"nodes: {len(nodes)} total, {online} online")
            runtimes = client.list_runtimes()
            print(f"runtimes: {[r.get('runtime_id') for r in runtimes]}")
            if online == 0:
                print("Error: no online GPU node", file=sys.stderr)
                return EXIT_INVALID_ARGS
            if args.skip_invoke:
                return EXIT_SUCCESS
            model_url = args.model_url or GPU_SHARING_TEST_MODEL_URL
            if not model_url:
                print(
                    "Error: set GPU_SHARING_TEST_MODEL_URL or pass --model-url "
                    "(direct URL, no redirects)",
                    file=sys.stderr,
                )
                return EXIT_INVALID_ARGS
            out = client.run_invoke(
                runtime=GPU_SHARING_RUNTIME,
                model_url=model_url,
                timeout_sec=600,
            )
            inv = out["invoke"]
            device = client.invoke_device(inv)
            print(f"invoke: {inv.get('status')} device={device}")
            if device != "cuda":
                print("Warning: expected device=cuda", file=sys.stderr)
            return EXIT_SUCCESS if inv.get("status") == "done" else EXIT_STT
        except GPUSharingError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return EXIT_STT
    if args.command == "gpu-sharing-transcribe":
        from app.config import GPU_SHARING_STT_MODEL
        from app.gpu_sharing.client import GPUSharingError
        from app.gpu_sharing.remote_stt import (
            run_remote_transcribe,
            transcribe_local_file_via_gpu,
        )

        model = args.model or GPU_SHARING_STT_MODEL
        try:
            if args.audio_url:
                out = run_remote_transcribe(args.audio_url, model=model)
            elif args.audio_path:
                out = transcribe_local_file_via_gpu(args.audio_path, model=model)
            else:
                print("Error: pass --audio-url or --audio-path", file=sys.stderr)
                return EXIT_INVALID_ARGS
            print("job_id:", out.get("job_id"))
            print("device:", out.get("device"))
            print("language:", out.get("language"))
            print("--- transcript ---")
            print(out.get("text", ""))
            return EXIT_SUCCESS
        except GPUSharingError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return EXIT_STT
    if args.command == "queue":
        if args.queue_command == "status":
            from app.queue.diagnostics import format_queue_status

            print(format_queue_status())
            return EXIT_SUCCESS
        if args.queue_command == "prune-workers":
            from app.queue.workers_cleanup import prune_dead_workers

            print(f"Removed {prune_dead_workers()} dead worker registration(s)")
            return EXIT_SUCCESS

    if args.command == "jobs":
        if args.jobs_command == "cleanup":
            from app.jobs.cleanup import cleanup_old_jobs

            removed = cleanup_old_jobs(ttl_hours=args.ttl_hours, dry_run=args.dry_run)
            print(f"Removed {removed} job director{'y' if removed == 1 else 'ies'}")
            return EXIT_SUCCESS
        if args.jobs_command == "reset-stuck":
            from app.jobs.reset import reset_stuck_jobs

            stats = reset_stuck_jobs()
            print(
                "Reset: processing_failed={processing_failed}, waiting_failed={waiting_failed}, "
                "rq_canceled={rq_canceled}, queue_waiting={queue_waiting}, "
                "scheduled_promoted={scheduled_promoted}, summary_requeued={summary_requeued}".format(
                    **stats
                )
            )
            print("Перезапустите: python -m app worker transcript")
            return EXIT_SUCCESS

    parser.error(f"Unknown command: {args.command}")
    return EXIT_INVALID_ARGS


if __name__ == "__main__":
    raise SystemExit(main())
