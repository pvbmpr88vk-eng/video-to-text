from __future__ import annotations

from app.jobs.models import Job, JobStatus, JobType
from app.telegram.progress_text import format_eta, format_job_status_message


def test_format_eta() -> None:
    assert format_eta(45) == "~45 сек"
    assert format_eta(120) == "~2 мин"
    assert format_eta(3700) == "~1 ч 1 мин"


def test_format_job_status_message_with_progress() -> None:
    job = Job(
        job_id="x",
        job_type=JobType.TRANSCRIPT,
        status=JobStatus.STT,
        user_id=1,
        chat_id=1,
        progress_pct=42.0,
        progress_label="Распознавание",
        progress_eta_sec=600.0,
    )
    text = format_job_status_message(job)
    assert "Распознавание" in text
    assert "42%" in text
    assert "чанк" not in text
    assert "10 мин" in text
