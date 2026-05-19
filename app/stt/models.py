from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Segment:
    start: float
    end: float
    text: str


@dataclass
class ChunkResult:
    index: int
    segments: list[Segment]
    text: str
    language: str
    duration_sec: float
