from __future__ import annotations

import importlib

import pytest


def _reload_config(monkeypatch: pytest.MonkeyPatch, **env: str | None) -> object:
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    import app.config as cfg

    return importlib.reload(cfg)


def test_cloud_api_default_20mb(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _reload_config(
        monkeypatch,
        TELEGRAM_BOT_API_BASE_URL=None,
        APP_ENV=None,
        TELEGRAM_BOT_FILE_SIZE_LIMIT=None,
    )
    assert cfg.TELEGRAM_BOT_FILE_SIZE_LIMIT == 20_000_000
    assert cfg._USE_LOCAL_BOT_API is False
    assert cfg.TELEGRAM_HTTP_READ_TIMEOUT_SEC == 30.0


def test_local_bot_api_raises_limit_to_500mb(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _reload_config(
        monkeypatch,
        TELEGRAM_BOT_API_BASE_URL="http://telegram-bot-api:8081",
        APP_ENV=None,
        TELEGRAM_BOT_FILE_SIZE_LIMIT=None,
    )
    assert cfg.TELEGRAM_BOT_FILE_SIZE_LIMIT == 500 * 1024 * 1024
    assert cfg._USE_LOCAL_BOT_API is True
    assert cfg.TELEGRAM_HTTP_READ_TIMEOUT_SEC == 3600.0


def test_app_env_test_500mb_without_local_api(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _reload_config(
        monkeypatch,
        TELEGRAM_BOT_API_BASE_URL=None,
        APP_ENV="test",
        TELEGRAM_BOT_FILE_SIZE_LIMIT=None,
    )
    assert cfg.TELEGRAM_BOT_FILE_SIZE_LIMIT == 500 * 1024 * 1024
