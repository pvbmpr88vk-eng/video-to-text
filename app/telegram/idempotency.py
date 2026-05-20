"""Prevent duplicate handling when several bot processes poll the same token."""

from __future__ import annotations

from redis import Redis

_INBOUND_PREFIX = "tg:inbound:"
_DEFAULT_TTL_SEC = 86400


def claim_inbound_message(redis: Redis, chat_id: int, message_id: int) -> bool:
    """Return True if this chat/message was not handled yet."""
    key = f"{_INBOUND_PREFIX}{chat_id}:{message_id}"
    return bool(redis.set(key, "1", nx=True, ex=_DEFAULT_TTL_SEC))
