from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    index: int
    text: str


def _split_plain_text(text: str, char_limit: int, overlap: int) -> list[str]:
    if len(text) <= char_limit:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + char_limit, len(text))
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def split_transcript_text(
    text: str,
    *,
    segments: list[dict] | None,
    char_limit: int,
    overlap: int,
) -> list[TextChunk]:
    if len(text) <= char_limit:
        return [TextChunk(index=0, text=text)]

    if segments:
        return _split_by_segments(segments, char_limit, overlap)

    parts = _split_plain_text(text, char_limit, overlap)
    return [TextChunk(index=i, text=part) for i, part in enumerate(parts)]


def _split_by_segments(
    segments: list[dict],
    char_limit: int,
    overlap: int,
) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    current_parts: list[str] = []
    current_len = 0
    index = 0

    def flush() -> None:
        nonlocal index, current_parts, current_len
        if not current_parts:
            return
        chunks.append(TextChunk(index=index, text=" ".join(current_parts).strip()))
        index += 1
        if overlap > 0 and chunks[-1].text:
            tail = chunks[-1].text[-overlap:]
            current_parts = [tail] if tail.strip() else []
            current_len = len(tail)
        else:
            current_parts = []
            current_len = 0

    for seg in segments:
        piece = (seg.get("text") or "").strip()
        if not piece:
            continue
        addition = len(piece) + (1 if current_parts else 0)
        if current_parts and current_len + addition > char_limit:
            flush()
        current_parts.append(piece)
        current_len += addition

    flush()
    if not chunks:
        return [TextChunk(index=0, text="")]
    return chunks
