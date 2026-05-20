from __future__ import annotations

from unittest.mock import patch

from app.worker.health import run_health_check


def test_health_fails_without_ytdlp(monkeypatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "yt_dlp" or name.startswith("yt_dlp."):
            raise ImportError("no yt_dlp")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        with patch("app.worker.health.get_redis") as mock_redis:
            mock_redis.return_value.ping.return_value = True
            with patch("app.worker.health.require_ffmpeg_tools"):
                with patch("app.worker.health.shutil.which", return_value="/usr/bin/ffmpeg"):
                    code = run_health_check(check_ollama=False)

    assert code == 1
