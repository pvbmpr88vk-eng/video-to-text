"""Idempotent Telegram delivery markers (one transcript/summary per job)."""

from __future__ import annotations

from redis import Redis

_DELIVERED_PREFIX = "job:telegram_delivered:"
_DEFAULT_TTL_SEC = 7 * 86400


def _key(job_id: str, kind: str) -> str:
    return f"{_DELIVERED_PREFIX}{job_id}:{kind}"


def was_telegram_delivered(redis: Redis, job_id: str, kind: str) -> bool:
    return bool(redis.get(_key(job_id, kind)))


def clear_telegram_delivery(redis: Redis, job_id: str, kind: str) -> None:
    redis.delete(_key(job_id, kind))


def mark_telegram_delivered(
    redis: Redis,
    job_id: str,
    kind: str,
    *,
    ttl_sec: int = _DEFAULT_TTL_SEC,
) -> None:
    """Call only after the user-visible Telegram send succeeded."""
    redis.set(_key(job_id, kind), "1", ex=ttl_sec)


def claim_telegram_delivery(
    redis: Redis,
    job_id: str,
    kind: str,
    *,
    ttl_sec: int = _DEFAULT_TTL_SEC,
) -> bool:
    """Return True if this process may deliver (first claimant wins)."""
    return bool(redis.set(_key(job_id, kind), "1", nx=True, ex=ttl_sec))
