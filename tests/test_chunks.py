from __future__ import annotations

from pathlib import Path

import pytest

from app.stt.chunks import (
    merge_chunk_results,
    plan_chunks,
    read_duration_from_sidecar,
    resolve_workers,
)
from app.stt.models import ChunkResult, Segment


def test_plan_chunks_48_minutes():
    plans = plan_chunks(48 * 60, 10 * 60)
    assert len(plans) == 5
    assert plans[0] == (0.0, 600.0)
    assert plans[-1][0] == 2400.0
    assert plans[-1][1] == 480.0


def test_merge_chunk_results_offsets_and_order():
    results = [
        ChunkResult(
            index=1,
            segments=[Segment(start=10.0, end=12.0, text="вторая")],
            text="вторая",
            language="ru",
            duration_sec=120.0,
        ),
        ChunkResult(
            index=0,
            segments=[Segment(start=0.0, end=2.0, text="первая")],
            text="первая",
            language="ru",
            duration_sec=600.0,
        ),
    ]
    segments, text, language = merge_chunk_results(results, total_duration_sec=2880.0)
    assert language == "ru"
    assert text == "первая вторая"
    assert [s.start for s in segments] == [0.0, 10.0]
    assert segments[0].text == "первая"


def test_merge_timestamps_monotonic():
    results = [
        ChunkResult(
            index=0,
            segments=[
                Segment(start=0.0, end=1.0, text="a"),
                Segment(start=5.0, end=6.0, text="b"),
            ],
            text="a b",
            language="ru",
            duration_sec=600.0,
        ),
        ChunkResult(
            index=1,
            segments=[Segment(start=600.0, end=601.0, text="c")],
            text="c",
            language="ru",
            duration_sec=600.0,
        ),
    ]
    segments, _, _ = merge_chunk_results(results, total_duration_sec=1200.0)
    starts = [s.start for s in segments]
    assert starts == sorted(starts)
    assert all(s.end >= s.start for s in segments)


def test_resolve_workers_default():
    workers = resolve_workers(None)
    assert workers >= 1


def test_resolve_workers_explicit():
    assert resolve_workers(2) == 2


def test_read_duration_from_sidecar(tmp_path):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"x")
    sidecar = Path(str(audio) + ".meta.json")
    sidecar.write_text('{"duration_sec": 123.5}', encoding="utf-8")
    assert read_duration_from_sidecar(audio) == 123.5
