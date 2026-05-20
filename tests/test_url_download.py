from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.download.url import UrlDownloadError, download_media_url, extract_url


def test_extract_url_from_text() -> None:
    assert extract_url("Смотри https://youtu.be/abc123?t=1") == "https://youtu.be/abc123?t=1"
    assert extract_url("https://example.com/video.mp4.") == "https://example.com/video.mp4"
    assert extract_url("без ссылки") is None


def test_download_media_url_success(tmp_path: Path) -> None:
    dest = tmp_path / "inbox"
    fake_file = dest / "vid.mp4"
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    fake_file.write_bytes(b"x" * 100)

    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = {"id": "vid", "ext": "mp4"}
    mock_ydl.prepare_filename.return_value = str(fake_file)

    mock_cls = MagicMock()
    mock_cls.return_value.__enter__.return_value = mock_ydl

    with patch("yt_dlp.YoutubeDL", mock_cls):
        path = download_media_url("https://youtu.be/x", dest, max_bytes=10_000)

    assert path == fake_file
    mock_ydl.extract_info.assert_called_once()


def test_download_media_url_too_large(tmp_path: Path) -> None:
    dest = tmp_path / "inbox"
    fake_file = dest / "big.mp4"
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    fake_file.write_bytes(b"x" * 200)

    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = {"id": "big", "ext": "mp4"}
    mock_ydl.prepare_filename.return_value = str(fake_file)

    mock_cls = MagicMock()
    mock_cls.return_value.__enter__.return_value = mock_ydl

    with patch("yt_dlp.YoutubeDL", mock_cls):
        with pytest.raises(UrlDownloadError, match="too large"):
            download_media_url("https://example.com/x", dest, max_bytes=100)

    assert not fake_file.exists()
