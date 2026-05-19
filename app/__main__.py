from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from app.audio.exceptions import FFmpegError, FFmpegNotFoundError, NoAudioStreamError
from app.audio.extractor import extract_audio
from app.config import (
    DEFAULT_CHUNK_MINUTES,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_TRANSCRIPT_DIR,
    WHISPER_MODEL_DEFAULT,
)
from app.stt.exceptions import ModelNotAvailableError, TranscriptionError
from app.stt.transcriber import transcribe_audio

EXIT_SUCCESS = 0
EXIT_FILE_NOT_FOUND = 1
EXIT_NO_AUDIO = 2
EXIT_FFMPEG = 3
EXIT_INVALID_ARGS = 4
EXIT_STT = 5


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )


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
        "-v",
        "--verbose",
        action="store_true",
        help="Debug logging",
    )

    return parser


def _run_transcribe_args(args: argparse.Namespace, audio_path: Path) -> int:
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
        return EXIT_FILE_NOT_FOUND
    except (ModelNotAvailableError, TranscriptionError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_STT
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_INVALID_ARGS

    print(result.txt_path)
    return EXIT_SUCCESS


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
    return _run_transcribe_args(args, args.audio_path)


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
    return _run_transcribe_args(args, audio_path)


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

    parser.error(f"Unknown command: {args.command}")
    return EXIT_INVALID_ARGS


if __name__ == "__main__":
    raise SystemExit(main())
