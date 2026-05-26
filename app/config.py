import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCAL_BIN_DIR = PROJECT_ROOT / ".local" / "bin"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output" / "audio"
DEFAULT_TRANSCRIPT_DIR = PROJECT_ROOT / "output" / "transcripts"
DEFAULT_SUMMARY_DIR = PROJECT_ROOT / "output" / "summaries"
DEFAULT_TELEGRAM_INBOX_DIR = PROJECT_ROOT / "output" / "telegram" / "inbox"

TELEGRAM_ACCESS_FILE = os.environ.get("TELEGRAM_ACCESS_FILE", "").strip()
TELEGRAM_RATE_LIMIT_PER_HOUR = int(os.environ.get("TELEGRAM_RATE_LIMIT_PER_HOUR", "10"))
TELEGRAM_DEFAULT_LANGUAGE = os.environ.get("TELEGRAM_DEFAULT_LANGUAGE", "ru").strip() or "ru"
TELEGRAM_ENABLE_SUMMARY = os.environ.get("TELEGRAM_ENABLE_SUMMARY", "true").lower() in (
    "1",
    "true",
    "yes",
)
TELEGRAM_MESSAGE_MAX_LEN = 4096
_APP_ENV = os.environ.get("APP_ENV", "").strip().lower()
TELEGRAM_BOT_API_BASE_URL = os.environ.get("TELEGRAM_BOT_API_BASE_URL", "").strip().rstrip("/")
TELEGRAM_BOT_API_CACHE_TTL_HOURS = int(os.environ.get("TELEGRAM_BOT_API_CACHE_TTL_HOURS", "6"))
_USE_LOCAL_BOT_API = bool(TELEGRAM_BOT_API_BASE_URL)
# Прод cloud API: 20 MB. Local Bot API или APP_ENV=test: 500 MB.
_DEFAULT_TELEGRAM_FILE_LIMIT = 20_000_000
if _USE_LOCAL_BOT_API or _APP_ENV == "test":
    _DEFAULT_TELEGRAM_FILE_LIMIT = 500 * 1024 * 1024
TELEGRAM_BOT_FILE_SIZE_LIMIT = int(
    os.environ.get("TELEGRAM_BOT_FILE_SIZE_LIMIT", str(_DEFAULT_TELEGRAM_FILE_LIMIT))
)
TELEGRAM_STATUS_EDIT_MIN_SEC = 30.0
# Min interval between Telegram progress edits (worker publishes; bot throttles edits too).
TELEGRAM_PROGRESS_MIN_INTERVAL_SEC = float(
    os.environ.get("TELEGRAM_PROGRESS_MIN_INTERVAL_SEC", str(TELEGRAM_STATUS_EDIT_MIN_SEC))
)
# PTB default read timeout is 5s — too short for 200+ MB via Local Bot API.
_DEFAULT_TELEGRAM_HTTP_READ_TIMEOUT = 30.0
if _USE_LOCAL_BOT_API:
    _DEFAULT_TELEGRAM_HTTP_READ_TIMEOUT = 3600.0
TELEGRAM_HTTP_READ_TIMEOUT_SEC = float(
    os.environ.get("TELEGRAM_HTTP_READ_TIMEOUT_SEC", str(_DEFAULT_TELEGRAM_HTTP_READ_TIMEOUT))
)
TELEGRAM_HTTP_WRITE_TIMEOUT_SEC = float(
    os.environ.get("TELEGRAM_HTTP_WRITE_TIMEOUT_SEC", str(TELEGRAM_HTTP_READ_TIMEOUT_SEC))
)


def telegram_file_limit_mb() -> float:
    """Лимит размера файла из Telegram для сообщений пользователю (как в handlers: /1e6)."""
    return TELEGRAM_BOT_FILE_SIZE_LIMIT / 1_000_000

# URL download (TZ-06, yt-dlp) — larger than Telegram 20 MB limit
URL_DOWNLOAD_MAX_BYTES = int(os.environ.get("URL_DOWNLOAD_MAX_BYTES", str(500 * 1024 * 1024)))
URL_DOWNLOAD_TIMEOUT_SEC = int(os.environ.get("URL_DOWNLOAD_TIMEOUT_SEC", "600"))

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL_DEFAULT = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b-instruct")
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))
SUMMARY_CHUNK_CHAR_LIMIT = int(os.environ.get("SUMMARY_CHUNK_CHAR_LIMIT", "6000"))
SUMMARY_CHUNK_OVERLAP = int(os.environ.get("SUMMARY_CHUNK_OVERLAP", "300"))
SUMMARY_TEMPERATURE = float(os.environ.get("SUMMARY_TEMPERATURE", "0.2"))
SUMMARY_NUM_PREDICT = int(os.environ.get("SUMMARY_NUM_PREDICT", "2048"))
SUMMARY_REQUEST_TIMEOUT_SEC = float(os.environ.get("SUMMARY_REQUEST_TIMEOUT_SEC", "300"))

WHISPER_MODEL_DEFAULT = os.environ.get("WHISPER_MODEL", "small")
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"

DEFAULT_CHUNK_MINUTES = float(os.environ.get("STT_CHUNK_MINUTES", "10"))
DEFAULT_MAX_WORKERS = 4
LONG_AUDIO_WARN_MINUTES = 30.0
# Above this length: split into chunks and transcribe sequentially (fits 4 GB VPS).
STT_CHUNK_WHEN_ABOVE_MINUTES = float(os.environ.get("STT_CHUNK_WHEN_ABOVE_MINUTES", "12"))
# Hard reject before STT (0 = no limit).
STT_MAX_AUDIO_DURATION_MINUTES = float(os.environ.get("STT_MAX_AUDIO_DURATION_MINUTES", "55"))
WHISPER_BEAM_SIZE = int(os.environ.get("WHISPER_BEAM_SIZE", "1"))
STT_PROGRESS_SEGMENT_INTERVAL = 50

SAMPLE_RATE = 16_000
CHANNELS = 1
MP3_BITRATE = "96k"

WAV_CODEC = "pcm_s16le"
MP3_CODEC = "libmp3lame"

FFMPEG_STDERR_LOG_LIMIT = 2048

# --- Job queue (TZ-05) ---
REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0").strip()
JOB_QUEUE_ENABLED = os.environ.get("JOB_QUEUE_ENABLED", "true").lower() in ("1", "true", "yes")

MAX_CONCURRENT_JOBS = int(os.environ.get("MAX_CONCURRENT_JOBS", "1"))
MAX_STT_WORKERS_PER_JOB = int(os.environ.get("MAX_STT_WORKERS_PER_JOB", "1"))
if sys.platform == "darwin":
    # ProcessPool/fork + ObjC is unsafe on macOS; keep STT in-process for workers.
    MAX_STT_WORKERS_PER_JOB = min(MAX_STT_WORKERS_PER_JOB, 1)
MAX_CONCURRENT_SUMMARIES = int(os.environ.get("MAX_CONCURRENT_SUMMARIES", "1"))
MAX_QUEUE_SIZE = int(os.environ.get("MAX_QUEUE_SIZE", "5"))

JOB_TRANSCRIPT_TIMEOUT_SEC = int(os.environ.get("JOB_TRANSCRIPT_TIMEOUT_SEC", "7200"))
JOB_SUMMARY_TIMEOUT_SEC = int(os.environ.get("JOB_SUMMARY_TIMEOUT_SEC", "1800"))
JOB_MAX_RETRIES = int(os.environ.get("JOB_MAX_RETRIES", "2"))
JOB_RETRY_DELAY_SEC = int(os.environ.get("JOB_RETRY_DELAY_SEC", "60"))
JOB_CLEANUP_TTL_HOURS = int(os.environ.get("JOB_CLEANUP_TTL_HOURS", "24"))

JOBS_BASE_DIR = PROJECT_ROOT / "output" / "jobs"

RQ_QUEUE_TRANSCRIPT = "transcript"
RQ_QUEUE_SUMMARY = "summary"

LOG_FORMAT = os.environ.get("LOG_FORMAT", "text").strip().lower()
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").strip().upper()

# GPU Sharing (remote GPU jobs) — key only in .env, never commit
GPU_SHARING_URL = os.environ.get("GPU_SHARING_URL", "http://85.198.66.114:8082").strip().rstrip("/")
GPU_SHARING_API_KEY = os.environ.get("GPU_SHARING_API_KEY", "").strip()
GPU_SHARING_ENABLED = os.environ.get("GPU_SHARING_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
)
# API v3: ONNX invoke runtime (see tenant handoff).
GPU_SHARING_RUNTIME = os.environ.get("GPU_SHARING_RUNTIME", "onnx_cuda").strip()
# Public HTTPS/HTTP URL to ONNX model for smoke test (no redirects; VPS staging OK).
GPU_SHARING_TEST_MODEL_URL = os.environ.get("GPU_SHARING_TEST_MODEL_URL", "").strip()
# Legacy v1/v2 Docker jobs STT — disabled by default (API v3 does not support image/command).
GPU_SHARING_TRANSCRIPT = os.environ.get("GPU_SHARING_TRANSCRIPT", "").lower() in (
    "1",
    "true",
    "yes",
)
GPU_SHARING_STT_IMAGE = os.environ.get("GPU_SHARING_STT_IMAGE", "python:3.11-slim").strip()
GPU_SHARING_STT_MODEL = os.environ.get("GPU_SHARING_STT_MODEL", "tiny").strip()
GPU_SHARING_STT_TIMEOUT_SEC = int(os.environ.get("GPU_SHARING_STT_TIMEOUT_SEC", "1800"))
GPU_SHARING_STT_PUBLISH_HOST = os.environ.get("GPU_SHARING_STT_PUBLISH_HOST", "").strip()
GPU_SHARING_STT_PUBLISH_PORT = int(os.environ.get("GPU_SHARING_STT_PUBLISH_PORT", "18888"))
# Local dir served by host http.server (prod worker volume); empty = SSH publish (dev/Mac).
GPU_SHARING_STT_STAGING_DIR = os.environ.get("GPU_SHARING_STT_STAGING_DIR", "").strip()
# When GPU path fails (v3 jobs off / ONNX not ready), use faster-whisper on VPS.
GPU_SHARING_STT_FALLBACK_CPU = os.environ.get("GPU_SHARING_STT_FALLBACK_CPU", "true").lower() in (
    "1",
    "true",
    "yes",
)
