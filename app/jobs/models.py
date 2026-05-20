from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class JobType(str, enum.Enum):
    TRANSCRIPT = "transcript"
    SUMMARY = "summary"


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    EXTRACT = "extract"
    STT = "stt"
    SUMMARY = "summary"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class Job:
    job_id: str
    job_type: JobType
    status: JobStatus
    user_id: int
    chat_id: int
    language: str = "ru"
    message_id: int | None = None
    status_message_id: int | None = None
    parent_job_id: str | None = None
    rq_job_id: str | None = None
    inbox_path: str | None = None
    wav_path: str | None = None
    transcript_txt: str | None = None
    transcript_json: str | None = None
    summary_md: str | None = None
    theses_json: str | None = None
    error: str | None = None
    retry_count: int = 0
    duration_sec: float = 0.0
    processing_sec: float = 0.0
    stt_model: str | None = None
    llm_model: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type.value,
            "status": self.status.value,
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "language": self.language,
            "message_id": self.message_id,
            "status_message_id": self.status_message_id,
            "parent_job_id": self.parent_job_id,
            "rq_job_id": self.rq_job_id,
            "inbox_path": self.inbox_path,
            "wav_path": self.wav_path,
            "transcript_txt": self.transcript_txt,
            "transcript_json": self.transcript_json,
            "summary_md": self.summary_md,
            "theses_json": self.theses_json,
            "error": self.error,
            "retry_count": self.retry_count,
            "duration_sec": self.duration_sec,
            "processing_sec": self.processing_sec,
            "stt_model": self.stt_model,
            "llm_model": self.llm_model,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Job:
        return cls(
            job_id=data["job_id"],
            job_type=JobType(data["job_type"]),
            status=JobStatus(data["status"]),
            user_id=int(data["user_id"]),
            chat_id=int(data["chat_id"]),
            language=data.get("language") or "ru",
            message_id=_optional_int(data.get("message_id")),
            status_message_id=_optional_int(data.get("status_message_id")),
            parent_job_id=data.get("parent_job_id"),
            rq_job_id=data.get("rq_job_id"),
            inbox_path=data.get("inbox_path"),
            wav_path=data.get("wav_path"),
            transcript_txt=data.get("transcript_txt"),
            transcript_json=data.get("transcript_json"),
            summary_md=data.get("summary_md"),
            theses_json=data.get("theses_json"),
            error=data.get("error"),
            retry_count=int(data.get("retry_count") or 0),
            duration_sec=float(data.get("duration_sec") or 0),
            processing_sec=float(data.get("processing_sec") or 0),
            stt_model=data.get("stt_model"),
            llm_model=data.get("llm_model"),
            created_at=data.get("created_at") or "",
            updated_at=data.get("updated_at") or "",
        )


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)
