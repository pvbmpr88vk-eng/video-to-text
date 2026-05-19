from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import (
    DEFAULT_SUMMARY_DIR,
    OLLAMA_HOST,
    OLLAMA_MODEL_DEFAULT,
    SUMMARY_CHUNK_CHAR_LIMIT,
    SUMMARY_CHUNK_OVERLAP,
)
from app.summary.chunking import split_transcript_text
from app.summary.exceptions import EmptyTranscriptError, SummaryAPIError
from app.summary.ollama_client import OllamaClient
from app.summary.prompts import (
    MAP_SYSTEM_RU,
    REDUCE_SYSTEM_RU,
    map_user_message,
    reduce_user_message,
)
from app.utils.paths import build_output_basename, ensure_dir

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".json", ".txt"}


@dataclass
class SummaryResult:
    summary_path: Path
    theses_path: Path
    meta_path: Path
    model: str


def _load_transcript(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Transcript JSON must be an object")
        return payload
    text = path.read_text(encoding="utf-8").strip()
    return {"text": text, "language": "ru", "segments": [], "source_path": str(path)}


def _format_summary_md(payload: dict[str, Any]) -> str:
    lines = ["# Краткий пересказ", "", payload.get("summary", "").strip(), "", "# Основные тезисы", ""]
    for item in payload.get("theses") or []:
        if str(item).strip():
            lines.append(f"- {str(item).strip()}")
    actions = payload.get("action_items") or []
    if actions:
        lines.extend(["", "# Действия (если есть)", ""])
        for action in actions:
            if isinstance(action, dict):
                text = (action.get("text") or "").strip()
            else:
                text = str(action).strip()
            if text:
                lines.append(f"- [ ] {text}")
    lines.append("")
    return "\n".join(lines)


def _run_map_reduce(
    client: OllamaClient,
    *,
    text: str,
    segments: list[dict] | None,
    model: str,
) -> dict[str, Any]:
    chunks = split_transcript_text(
        text,
        segments=segments,
        char_limit=SUMMARY_CHUNK_CHAR_LIMIT,
        overlap=SUMMARY_CHUNK_OVERLAP,
    )
    total = len(chunks)
    logger.info("Summary map-reduce: %d chunk(s), model=%s", total, model)

    if total == 1:
        data = client.chat_json(
            system=REDUCE_SYSTEM_RU,
            user=f"Полный транскрипт:\n\n{chunks[0].text}",
            model=model,
        )
        return _normalize_final(data)

    partials: list[str] = []
    for chunk in chunks:
        logger.info("Map chunk %d/%d", chunk.index + 1, total)
        part = client.chat_json(
            system=MAP_SYSTEM_RU,
            user=map_user_message(chunk.text, chunk.index + 1, total),
            model=model,
        )
        partials.append(
            json.dumps(
                {
                    "partial_summary": part.get("partial_summary", ""),
                    "partial_theses": part.get("partial_theses", []),
                },
                ensure_ascii=False,
            )
        )

    logger.info("Reduce step")
    final = client.chat_json(
        system=REDUCE_SYSTEM_RU,
        user=reduce_user_message("\n\n".join(partials)),
        model=model,
    )
    return _normalize_final(final)


def _normalize_final(data: dict[str, Any]) -> dict[str, Any]:
    theses = data.get("theses") or data.get("partial_theses") or []
    if not isinstance(theses, list):
        theses = [str(theses)]
    summary = data.get("summary") or data.get("partial_summary") or ""
    return {
        "summary": str(summary).strip(),
        "theses": [str(t).strip() for t in theses if str(t).strip()],
        "action_items": data.get("action_items") or [],
        "quotes": data.get("quotes") or [],
    }


def summarize_transcript(
    transcript_path: str | Path,
    *,
    output_dir: Path | None = None,
    language: str | None = None,
    with_quotes: bool = False,
    model: str | None = None,
    ollama_host: str | None = None,
) -> SummaryResult:
    source = Path(transcript_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Transcript not found: {source}")
    if source.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(
            f"Unsupported transcript format: {source.suffix}. Use .json or .txt"
        )

    payload = _load_transcript(source)
    text = (payload.get("text") or "").strip()
    if not text:
        raise EmptyTranscriptError("Transcript text is empty")

    model_name = model or OLLAMA_MODEL_DEFAULT
    client = OllamaClient(host=ollama_host or OLLAMA_HOST, model=model_name)

    print(
        f"Loading summary model '{model_name}' via Ollama (local, {client.host})...",
        flush=True,
    )
    client.ensure_ready(model_name)

    started = time.monotonic()
    segments = payload.get("segments") if isinstance(payload.get("segments"), list) else None
    final = _run_map_reduce(client, text=text, segments=segments, model=model_name)
    if not with_quotes:
        final["quotes"] = []

    out_dir = ensure_dir(output_dir or DEFAULT_SUMMARY_DIR)
    basename = build_output_basename(source)
    summary_path = out_dir / f"{basename}.summary.md"
    theses_path = out_dir / f"{basename}.theses.json"
    meta_path = out_dir / f"{basename}.meta.json"

    lang = language or payload.get("language") or "ru"
    theses_payload = {
        "summary": final["summary"],
        "theses": final["theses"],
        "action_items": final["action_items"],
        "quotes": final["quotes"],
        "language": lang,
        "source_transcript": str(source),
        "llm_model": model_name,
        "llm_provider": "ollama",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    summary_path.write_text(_format_summary_md(theses_payload), encoding="utf-8")
    theses_path.write_text(
        json.dumps(theses_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    meta = {
        "duration_sec": payload.get("duration_sec"),
        "input_char_count": len(text),
        "chunk_count": len(
            split_transcript_text(
                text,
                segments=segments,
                char_limit=SUMMARY_CHUNK_CHAR_LIMIT,
                overlap=SUMMARY_CHUNK_OVERLAP,
            )
        ),
        "ollama_host": client.host,
        "llm_model": model_name,
        "stt_model": payload.get("model"),
        "processing_time_sec": round(time.monotonic() - started, 2),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote %s and %s", summary_path, theses_path)
    return SummaryResult(
        summary_path=summary_path,
        theses_path=theses_path,
        meta_path=meta_path,
        model=model_name,
    )
