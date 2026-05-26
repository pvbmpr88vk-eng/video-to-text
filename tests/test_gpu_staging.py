from __future__ import annotations

from pathlib import Path

from app.gpu_sharing.staging import publish_file_to_staging


def test_publish_file_to_staging(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    src = tmp_path / "clip.wav"
    src.write_bytes(b"RIFF")
    url = publish_file_to_staging(
        src,
        staging_dir=staging,
        publish_host="10.0.0.1",
        http_port=18888,
    )
    copied = next(staging.iterdir())
    assert copied.read_bytes() == b"RIFF"
    assert url == f"http://10.0.0.1:18888/{copied.name}"
