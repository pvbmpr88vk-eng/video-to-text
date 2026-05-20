from __future__ import annotations

import logging
import re
from pathlib import Path

from app.config import URL_DOWNLOAD_MAX_BYTES, URL_DOWNLOAD_TIMEOUT_SEC

logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)


class UrlDownloadError(Exception):
    """Failed to download media from URL."""


def extract_url(text: str) -> str | None:
    match = URL_RE.search(text.strip())
    if not match:
        return None
    return match.group(0).rstrip(".,);]}")


def download_media_url(
    url: str,
    dest_dir: Path,
    *,
    max_bytes: int | None = None,
    timeout_sec: int | None = None,
) -> Path:
    """
    Download best available audio/video via yt-dlp into dest_dir.
    Returns path to the downloaded file.
    """
    try:
        import yt_dlp
    except ImportError as exc:
        raise UrlDownloadError("yt-dlp not installed") from exc

    limit = max_bytes if max_bytes is not None else URL_DOWNLOAD_MAX_BYTES
    timeout = timeout_sec if timeout_sec is not None else URL_DOWNLOAD_TIMEOUT_SEC
    dest_dir.mkdir(parents=True, exist_ok=True)
    outtmpl = str(dest_dir / "%(id)s.%(ext)s")

    ydl_opts: dict = {
        "format": "bestaudio/best/b",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "max_filesize": limit,
        "socket_timeout": timeout,
        "quiet": True,
        "no_warnings": True,
    }

    logger.info("Downloading URL via yt-dlp: %s", url[:120])
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                raise UrlDownloadError("no media info returned")
            path = Path(ydl.prepare_filename(info))
    except UrlDownloadError:
        raise
    except Exception as exc:
        raise UrlDownloadError(str(exc)) from exc

    if not path.is_file():
        raise UrlDownloadError(f"file not found after download: {path}")

    size = path.stat().st_size
    if size > limit:
        path.unlink(missing_ok=True)
        raise UrlDownloadError(f"file too large ({size / 1e6:.1f} MB, limit {limit / 1e6:.0f} MB)")

    return path
