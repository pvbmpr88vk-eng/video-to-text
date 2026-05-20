from __future__ import annotations

from typing import Any

from app.config import TELEGRAM_MAX_THESIS_LINES_IN_CHAT, TELEGRAM_MESSAGE_MAX_LEN


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
    """Plain-text summary for chat: summary + up to N theses + action lines."""
    summary = (payload.get("summary") or "").strip()
    theses = payload.get("theses") or []
    if not isinstance(theses, list):
        theses = []
    actions = payload.get("action_items") or []

    lines: list[str] = ["📋 Краткий пересказ", "", summary, "", "📌 Тезисы", ""]
    for i, t in enumerate(theses[:TELEGRAM_MAX_THESIS_LINES_IN_CHAT], start=1):
        t = str(t).strip()
        if t:
            lines.append(f"{i}. {t}")
    if len(theses) > TELEGRAM_MAX_THESIS_LINES_IN_CHAT:
        lines.append(
            f"… ещё {len(theses) - TELEGRAM_MAX_THESIS_LINES_IN_CHAT} тезисов — см. файл .summary.md"
        )

    if actions:
        lines.extend(["", "✅ Действия", ""])
        for a in actions:
            if isinstance(a, dict):
                txt = (a.get("text") or "").strip()
            else:
                txt = str(a).strip()
            if txt:
                lines.append(f"• [ ] {txt}")

    return "\n".join(lines).strip()
