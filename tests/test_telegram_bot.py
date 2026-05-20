from __future__ import annotations

from pathlib import Path

import pytest

from app.telegram.auth import MediaRateLimiter, is_allowed
from app.telegram.credentials import CredentialsError, load_credentials
from app.telegram.formatting import format_summary_for_chat, split_telegram_message
from app.config import TELEGRAM_MESSAGE_MAX_LEN


def test_is_allowed() -> None:
    assert is_allowed(1, frozenset({1, 2}))
    assert not is_allowed(3, frozenset({1, 2}))
    assert not is_allowed(1, frozenset())


def test_rate_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    rl = MediaRateLimiter(max_per_hour=2)
    t = 0.0

    def fake_monotonic() -> float:
        return t

    monkeypatch.setattr("app.telegram.auth.time.monotonic", fake_monotonic)
    assert rl.allow(100)
    assert rl.allow(100)
    assert not rl.allow(100)
    t += 3601.0
    assert rl.allow(100)


def test_split_telegram_message_short() -> None:
    assert split_telegram_message("hello") == ["hello"]


def test_split_telegram_message_parts_prefix() -> None:
    limit = 50
    body = "a" * 30 + "\n\n" + "b" * 30
    parts = split_telegram_message(body, limit=limit)
    assert len(parts) >= 2
    assert "(1/" in parts[0]


def test_split_telegram_message_exact_limit() -> None:
    s = "x" * TELEGRAM_MESSAGE_MAX_LEN
    out = split_telegram_message(s)
    assert len(out) == 1
    assert len(out[0]) == TELEGRAM_MESSAGE_MAX_LEN


def test_format_summary_for_chat_all_theses() -> None:
    payload = {
        "summary": "Кратко.",
        "theses": [f"Тезис {i}" for i in range(20)],
    }
    text = format_summary_for_chat(payload)
    assert "… ещё" not in text
    assert "summary.md" not in text
    assert "20. Тезис 19" in text
    assert "1. Тезис 0" in text
    assert "Действия" not in text


def test_format_summary_ignores_legacy_action_items() -> None:
    text = format_summary_for_chat(
        {
            "summary": "Кратко.",
            "theses": ["Один"],
            "action_items": [{"text": "Сделать X"}],
        }
    )
    assert "Действия" not in text
    assert "Сделать X" not in text


def test_load_credentials_from_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "access.txt"
    p.write_text(
        "BOT_TOKEN=123456:AA-abc\nALLOWED_USER_IDS=1, 2\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    monkeypatch.setenv("TELEGRAM_ACCESS_FILE", str(p))
    c = load_credentials()
    assert c.bot_token == "123456:AA-abc"
    assert c.allowed_user_ids == frozenset({1, 2})


def test_load_credentials_env_overrides_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "access.txt"
    p.write_text("BOT_TOKEN=1:old\nALLOWED_USER_IDS=1\n", encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_ACCESS_FILE", str(p))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "999:fromenv")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "5")
    c = load_credentials()
    assert c.bot_token == "999:fromenv"
    assert c.allowed_user_ids == frozenset({5})


def test_load_credentials_bad_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "access.txt"
    p.write_text("BOT_TOKEN=nocolon\nALLOWED_USER_IDS=1\n", encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_ACCESS_FILE", str(p))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(CredentialsError):
        load_credentials()


def test_load_credentials_empty_user_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "access.txt"
    p.write_text("BOT_TOKEN=123456:AA-abc\nALLOWED_USER_IDS=\n", encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_ACCESS_FILE", str(p))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    with pytest.raises(CredentialsError, match="ALLOWED_USER_IDS is empty"):
        load_credentials()


def test_load_credentials_bad_user_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "access.txt"
    p.write_text("BOT_TOKEN=1:a\nALLOWED_USER_IDS=abc\n", encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_ACCESS_FILE", str(p))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    with pytest.raises(CredentialsError):
        load_credentials()


def test_parse_theses_callback() -> None:
    from app.telegram.jobs import parse_theses_callback

    job_id = "550e8400-e29b-41d4-a716-446655440000"
    assert parse_theses_callback(f"theses:{job_id}") == job_id
    assert parse_theses_callback("other") is None
    assert parse_theses_callback("theses:") is None
