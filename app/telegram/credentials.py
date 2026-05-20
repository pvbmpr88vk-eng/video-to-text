from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from app.config import PROJECT_ROOT


class CredentialsError(Exception):
    """Missing or invalid Telegram credentials."""


@dataclass(frozen=True)
class TelegramCredentials:
    bot_token: str
    allowed_user_ids: frozenset[int]
    bot_username: str | None = None
    bot_link: str | None = None


def _default_access_path() -> Path:
    custom = os.environ.get("TELEGRAM_ACCESS_FILE", "").strip()
    if custom:
        return Path(custom).expanduser().resolve()
    return (PROJECT_ROOT / "telegram-bot.access.txt").resolve()


def _parse_kv_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        k = key.strip().upper()
        data[k] = val.strip()
    return data


def _parse_user_ids(s: str) -> frozenset[int]:
    if not s.strip():
        return frozenset()
    out: set[int] = set()
    for part in re.split(r"[\s,;]+", s.strip()):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise CredentialsError(f"Invalid user id (must be digits): {part!r}")
        out.add(int(part))
    return frozenset(out)


def _validate_token(token: str) -> None:
    if not token:
        raise CredentialsError("BOT_TOKEN / TELEGRAM_BOT_TOKEN is empty")
    if ":" not in token:
        raise CredentialsError("Invalid bot token format (expected '12345:AA...')")


def load_credentials() -> TelegramCredentials:
    """
    Load from telegram-bot.access.txt (or TELEGRAM_ACCESS_FILE), then override
    with TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_USER_IDS if set in environment.
    """
    path = _default_access_path()
    file_data = _parse_kv_file(path)

    token = file_data.get("BOT_TOKEN", "")
    allowed_raw = file_data.get("ALLOWED_USER_IDS", "")
    username = file_data.get("BOT_USERNAME") or None
    link = file_data.get("BOT_LINK") or None

    env_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if env_token:
        token = env_token

    env_ids = os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").strip()
    if env_ids:
        allowed_raw = env_ids

    _validate_token(token)

    try:
        allowed = _parse_user_ids(allowed_raw)
    except CredentialsError:
        raise
    except Exception as exc:
        raise CredentialsError(f"Invalid ALLOWED_USER_IDS: {exc}") from exc

    return TelegramCredentials(
        bot_token=token,
        allowed_user_ids=allowed,
        bot_username=username,
        bot_link=link,
    )
