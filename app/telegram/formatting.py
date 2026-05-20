from __future__ import annotations

from typing import Any

from app.config import TELEGRAM_MESSAGE_MAX_LEN


def split_telegram_message(text: str, limit: int = TELEGRAM_MESSAGE_MAX_LEN) -> list[str]:
    """
    Split for Telegram message length. Prefer paragraph breaks, then line breaks.
    Prefix (n/total) when multiple parts. UTF-8 safe (no surrogate split — Python str is fine).
    """
    if not text:
        return [""]
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            parts.append(remaining)
            break
        chunk = remaining[:limit]
        cut = chunk.rfind("\n\n")
        if cut < limit // 2:
            cut = chunk.rfind("\n")
        if cut < limit // 2:
            cut = limit
        piece = remaining[:cut].rstrip()
        if not piece:
            piece = remaining[:limit]
            cut = len(piece)
        parts.append(piece)
        remaining = remaining[cut:].lstrip()

    if len(parts) <= 1:
        return parts
    total = len(parts)
    out: list[str] = []
    for i, p in enumerate(parts, start=1):
        prefix = f"({i}/{total})\n" if total > 1 else ""
        body = p
        if len(prefix) + len(body) > limit:
            body = body[: max(0, limit - len(prefix))]
        out.append(prefix + body)
    return out


def format_summary_for_chat(payload: dict[str, Any]) -> str:
    """Plain-text summary for chat: пересказ и тезисы."""
    summary = (payload.get("summary") or "").strip()
    theses = payload.get("theses") or []
    if not isinstance(theses, list):
        theses = []

    lines: list[str] = ["📋 Краткий пересказ", "", summary, "", "📌 Тезисы", ""]
    n = 0
    for t in theses:
        t = str(t).strip()
        if t:
            n += 1
            lines.append(f"{n}. {t}")

    return "\n".join(lines).strip()
