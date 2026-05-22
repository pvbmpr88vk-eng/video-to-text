from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.telegram import download as dl


@pytest.fixture
def api_cache_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    cache_root = tmp_path / "telegram-bot-api"
    cache_root.mkdir()
    src = cache_root / "bot123" / "video.mp4"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"local-api-cache-payload")
    dest = tmp_path / "inbox" / "video.mp4"

    monkeypatch.setattr(dl, "TELEGRAM_BOT_API_BASE_URL", "http://telegram-bot-api:8081")
    monkeypatch.setattr(dl, "_LOCAL_API_CACHE_ROOTS", (cache_root,))
    return src, dest


def test_copy_unlinks_api_cache_after_success(api_cache_tree: tuple[Path, Path]) -> None:
    src, dest = api_cache_tree
    dl._copy_from_local_api_cache(src, dest)
    assert dest.read_bytes() == b"local-api-cache-payload"
    assert not src.exists()


def test_copy_keeps_cache_if_not_under_api_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "other" / "file.bin"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"x")
    dest = tmp_path / "dest.bin"
    monkeypatch.setattr(dl, "_LOCAL_API_CACHE_ROOTS", (tmp_path / "telegram-bot-api",))

    dl._copy_from_local_api_cache(src, dest)
    assert src.exists()
    assert dest.read_bytes() == b"x"


def test_save_telegram_file_local_copy_and_unlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_root = tmp_path / "telegram-bot-api"
    cache_root.mkdir()
    src = cache_root / "cached.mp4"
    src.write_bytes(b"payload")
    dest = tmp_path / "job" / "inbox" / "cached.mp4"

    monkeypatch.setattr(dl, "TELEGRAM_BOT_API_BASE_URL", "http://telegram-bot-api:8081")
    monkeypatch.setattr(dl, "_LOCAL_API_CACHE_ROOTS", (cache_root,))

    tg_file = MagicMock()
    tg_file.file_path = str(src)
    asyncio.run(dl.save_telegram_file(tg_file, dest))

    assert dest.read_bytes() == b"payload"
    assert not src.exists()
