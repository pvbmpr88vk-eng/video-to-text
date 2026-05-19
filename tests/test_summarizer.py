from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.config import SUMMARY_CHUNK_CHAR_LIMIT, SUMMARY_CHUNK_OVERLAP
from app.summary.chunking import split_transcript_text
from app.summary.exceptions import EmptyTranscriptError, SummaryConfigError
from app.summary.ollama_client import OllamaClient
from app.summary.summarizer import summarize_transcript

FIXTURES = Path(__file__).parent / "fixtures"
TRANSCRIPTS_DIR = Path(__file__).resolve().parent.parent / "output" / "transcripts"
REFERENCE_JSON = TRANSCRIPTS_DIR / "111_20260519T142840Z_20260519T162054Z.json"
REFERENCE_TXT = TRANSCRIPTS_DIR / "111_20260519T142840Z_20260519T162054Z.txt"


@pytest.fixture(scope="session")
def reference_transcript() -> dict:
    if not REFERENCE_JSON.is_file():
        pytest.skip(f"Reference transcript missing: {REFERENCE_JSON}")
    return json.loads(REFERENCE_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def ollama_available() -> bool:
    try:
        response = httpx.get("http://127.0.0.1:11434/api/tags", timeout=3.0)
        if response.status_code != 200:
            return False
        names = {m.get("name", "") for m in response.json().get("models", [])}
        return any("qwen2.5" in n and "3b" in n for n in names)
    except httpx.HTTPError:
        return False


def test_split_by_segments_respects_limit():
    segments = [{"text": "а" * 100} for _ in range(100)]
    chunks = split_transcript_text(
        "x" * 10000,
        segments=segments,
        char_limit=500,
        overlap=50,
    )
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.text) <= 550


def test_chunking_reference_transcript(reference_transcript: dict):
    """Map-reduce plan for real 111 transcript (~42k chars, small STT)."""
    text = reference_transcript["text"]
    segments = reference_transcript.get("segments")
    chunks = split_transcript_text(
        text,
        segments=segments,
        char_limit=SUMMARY_CHUNK_CHAR_LIMIT,
        overlap=SUMMARY_CHUNK_OVERLAP,
    )
    assert len(text) > 30_000
    assert len(chunks) >= 5
    assert reference_transcript["language"] == "ru"
    assert reference_transcript["model"] == "small"


def test_reference_txt_matches_json_length(reference_transcript: dict):
    if not REFERENCE_TXT.is_file():
        pytest.skip("Reference txt missing")
    txt = REFERENCE_TXT.read_text(encoding="utf-8").strip()
    assert abs(len(txt) - len(reference_transcript["text"])) < 500


def test_summarize_empty_transcript(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text(json.dumps({"text": "  "}), encoding="utf-8")
    with pytest.raises(EmptyTranscriptError):
        summarize_transcript(path, output_dir=tmp_path / "out")


@patch("app.summary.summarizer.OllamaClient")
def test_summarize_short_fixture(mock_client_cls, tmp_path):
    mock_client = MagicMock()
    mock_client.host = "http://127.0.0.1:11434"
    mock_client_cls.return_value = mock_client
    mock_client.ensure_ready.return_value = None
    mock_client.chat_json.return_value = {
        "summary": "Краткий итог созвона.",
        "theses": ["Тезис один", "Тезис два"],
        "action_items": [],
        "quotes": [],
    }

    source = FIXTURES / "short_transcript.json"
    result = summarize_transcript(
        source, output_dir=tmp_path / "summaries", model="qwen2.5:3b-instruct"
    )
    assert result.summary_path.exists()
    payload = json.loads(result.theses_path.read_text(encoding="utf-8"))
    assert len(payload["theses"]) >= 2


@patch("app.summary.summarizer.OllamaClient")
def test_summarize_reference_transcript_mock(
    mock_client_cls, reference_transcript: dict, tmp_path
):
    """Full pipeline on real output/transcripts JSON with mocked Ollama."""
    mock_client = MagicMock()
    mock_client.host = "http://127.0.0.1:11434"
    mock_client_cls.return_value = mock_client
    mock_client.ensure_ready.return_value = None

    def fake_chat(*, system: str, user: str, model: str | None = None) -> dict:
        if "partial" in system.lower() or "фрагмент" in user.lower():
            return {
                "partial_summary": "Обсуждали Dashboard, ДДС и выход из антикризиса.",
                "partial_theses": ["Заключительный созвон", "Обратная связь по проекту"],
            }
        return {
            "summary": "Созвон с обратной связью по финансам клиники, Dashboard и антикризису.",
            "theses": [
                "Внедрён ДДС",
                "Нужен понятный трек выхода из антикризиса",
                "Dashboard обсудят с Кристиной",
                "Вопрос прозрачности личного дохода",
                "ABC-анализ сложно применять к разнородным услугам",
            ],
            "action_items": [
                {"text": "Созвон по Dashboard с Кристиной", "assignee": None, "due": None}
            ],
            "quotes": [],
        }

    mock_client.chat_json.side_effect = fake_chat

    out_dir = tmp_path / "summaries"
    result = summarize_transcript(
        REFERENCE_JSON,
        output_dir=out_dir,
        language="ru",
        model="qwen2.5:3b-instruct",
    )
    assert result.summary_path.exists()
    payload = json.loads(result.theses_path.read_text(encoding="utf-8"))
    assert len(payload["theses"]) >= 5
    assert "summary" in payload
    meta = json.loads(result.meta_path.read_text(encoding="utf-8"))
    assert meta["input_char_count"] > 30_000
    assert meta["chunk_count"] >= 5
    assert mock_client.chat_json.call_count >= 2


@patch("app.summary.ollama_client.httpx.get")
def test_ollama_not_running(mock_get):
    mock_get.side_effect = httpx.ConnectError("connection refused")
    client = OllamaClient(model="qwen2.5:3b-instruct")
    with pytest.raises(SummaryConfigError, match="not reachable"):
        client.ensure_ready()


@pytest.mark.integration
def test_summarize_reference_transcript_live(reference_transcript: dict, ollama_available: bool):
    """Real Ollama run on 111 small transcript (slow, needs ollama + model)."""
    if not ollama_available:
        pytest.skip("Ollama not running or qwen2.5:3b not pulled")

    out_dir = TRANSCRIPTS_DIR.parent / "summaries"
    result = summarize_transcript(
        REFERENCE_JSON,
        output_dir=out_dir,
        language="ru",
        model="qwen2.5:3b-instruct",
    )
    payload = json.loads(result.theses_path.read_text(encoding="utf-8"))
    assert len(payload["theses"]) >= 5
    assert len(payload["summary"]) > 100
