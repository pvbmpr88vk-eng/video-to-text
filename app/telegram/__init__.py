"""Telegram bot (stage 4–5): interface to extract → STT → summarize."""

from __future__ import annotations

__all__ = ["run_bot"]


def __getattr__(name: str):
    if name == "run_bot":
        from app.telegram.bot import run_bot

        return run_bot
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
