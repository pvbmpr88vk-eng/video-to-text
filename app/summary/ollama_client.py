from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.config import (
    OLLAMA_HOST,
    OLLAMA_NUM_CTX,
    SUMMARY_NUM_PREDICT,
    SUMMARY_REQUEST_TIMEOUT_SEC,
    SUMMARY_TEMPERATURE,
)
from app.summary.exceptions import SummaryAPIError, SummaryConfigError

logger = logging.getLogger(__name__)


class OllamaClient:
    def __init__(
        self,
        host: str = OLLAMA_HOST,
        model: str = "",
        *,
        timeout_sec: float = SUMMARY_REQUEST_TIMEOUT_SEC,
    ) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.timeout_sec = timeout_sec

    def ensure_ready(self, model: str | None = None) -> None:
        model_name = model or self.model
        try:
            response = httpx.get(f"{self.host}/api/tags", timeout=10.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SummaryConfigError(
                f"Ollama is not reachable at {self.host}. "
                "Start it with: ollama serve"
            ) from exc

        names = {item.get("name", "") for item in response.json().get("models", [])}
        if not any(
            n == model_name
            or n.startswith(f"{model_name}:")
            or model_name in n
            or n.split(":")[0] == model_name.split(":")[0]
            for n in names
        ):
            raise SummaryConfigError(
                f"Model '{model_name}' is not installed. Run: ollama pull {model_name}"
            )

    def chat_json(
        self,
        *,
        system: str,
        user: str,
        model: str | None = None,
    ) -> dict[str, Any]:
        model_name = model or self.model
        payload = {
            "model": model_name,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {
                "temperature": SUMMARY_TEMPERATURE,
                "num_ctx": OLLAMA_NUM_CTX,
                "num_predict": SUMMARY_NUM_PREDICT,
            },
        }
        try:
            response = httpx.post(
                f"{self.host}/api/chat",
                json=payload,
                timeout=self.timeout_sec,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SummaryAPIError(f"Ollama request failed: {exc}") from exc

        data = response.json()
        content = (data.get("message") or {}).get("content") or ""
        return _parse_json_content(content)


def _parse_json_content(content: str) -> dict[str, Any]:
    text = content.strip()
    if not text:
        raise SummaryAPIError("Ollama returned empty response")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError as exc:
                raise SummaryAPIError(f"Invalid JSON from Ollama: {text[:500]}") from exc
        raise SummaryAPIError(f"Invalid JSON from Ollama: {text[:500]}")
