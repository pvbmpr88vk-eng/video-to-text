from __future__ import annotations

import json
import logging

import pytest

from app.logging_setup import JsonFormatter, configure_logging


def test_json_formatter_includes_extra_fields() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="app.worker.transcript",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Transcript job done",
        args=(),
        exc_info=None,
    )
    record.job_id = "abc-123"
    record.user_id = 42
    record.status = "done"
    record.duration_ms = 1500

    payload = json.loads(formatter.format(record))
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.worker.transcript"
    assert payload["msg"] == "Transcript job done"
    assert payload["job_id"] == "abc-123"
    assert payload["user_id"] == 42
    assert payload["status"] == "done"
    assert payload["duration_ms"] == 1500
    assert "ts" in payload


def test_configure_logging_json(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("LOG_FORMAT", "json")
    monkeypatch.setenv("LOG_LEVEL", "INFO")

    import importlib

    import app.config
    import app.logging_setup

    importlib.reload(app.config)
    importlib.reload(app.logging_setup)

    configure_logging(verbose=False)
    logging.getLogger("test.logger").info("hello json")

    err = capsys.readouterr().err
    line = err.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["msg"] == "hello json"
