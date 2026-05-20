from __future__ import annotations

import re
from typing import Any

_RU_STOP = frozenset(
    {
        "и",
        "в",
        "на",
        "с",
        "по",
        "для",
        "что",
        "это",
        "как",
        "но",
        "не",
        "то",
        "же",
        "из",
        "за",
        "от",
        "до",
        "при",
        "все",
        "был",
        "была",
        "было",
        "были",
        "есть",
        "а",
        "у",
        "о",
        "к",
        "я",
        "мы",
        "вы",
        "он",
        "она",
        "они",
    }
)

_MEETING_MARKERS = (
    "созвон",
    "участник",
    "повестк",
    "проект",
    "команда",
    "ресурс",
    "встреча",
    "координац",
    "отчет",
    "отчёт",
    "распредел",
    "бюджет",
)

_TASK_MARKERS = (
    "нужен",
    "нужно",
    "сделать",
    "задач",
    "поруч",
    "ответствен",
    "дедлайн",
    "до ",
    "к ",
)


def tokenize_for_grounding(text: str) -> list[str]:
    words = re.findall(r"[\wа-яёА-ЯЁ]+", text.lower())
    return [w for w in words if len(w) >= 2 and w not in _RU_STOP]


def _result_blob(result: dict[str, Any]) -> str:
    parts = [str(result.get("summary") or "")]
    theses = result.get("theses") or []
    if isinstance(theses, list):
        parts.extend(str(t) for t in theses)
    return " ".join(parts).lower()


def transcript_implies_meeting(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in _MEETING_MARKERS + _TASK_MARKERS)


def _min_token_matches(token_count: int) -> int:
    if token_count <= 15:
        return max(1, min(3, (token_count + 1) // 2))
    return max(2, int(token_count * 0.03))


def summary_grounded_in_transcript(transcript: str, result: dict[str, Any]) -> bool:
    tokens = tokenize_for_grounding(transcript)
    if not tokens:
        return True
    blob = _result_blob(result)
    matched = sum(1 for t in tokens if t in blob)
    return matched >= _min_token_matches(len(tokens))


def looks_hallucinated(transcript: str, result: dict[str, Any]) -> bool:
    if not summary_grounded_in_transcript(transcript, result):
        return True
    blob = _result_blob(result)
    if not transcript_implies_meeting(transcript) and any(m in blob for m in _MEETING_MARKERS):
        return True
    return False


def literal_fallback_summary(text: str) -> dict[str, Any]:
    preview = text.strip()
    if len(preview) > 500:
        preview = preview[:497] + "..."
    thesis = preview if len(preview) <= 240 else preview[:237] + "..."
    return {
        "summary": f"В записи сказано: {preview}",
        "theses": [thesis],
        "quotes": [],
    }
