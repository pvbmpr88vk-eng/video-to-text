"""Run faster-whisper on GPU Sharing (remote Docker job)."""

from __future__ import annotations

import logging
import re
import subprocess
import uuid
from pathlib import Path

from app.gpu_sharing.client import GPUSharingClient, GPUSharingError, client_from_config

logger = logging.getLogger(__name__)

_TRANSCRIPT_MARKERS = ("---TRANSCRIPT---",)


def _build_transcribe_script(*, audio_url: str, model: str) -> str:
    return f"""set -e
pip install -q faster-whisper
python3 -c "
import urllib.request
urllib.request.urlretrieve({audio_url!r}, '/tmp/in.wav')
from faster_whisper import WhisperModel
for dev, ct in [('cuda', 'float16'), ('cpu', 'int8')]:
    try:
        m = WhisperModel({model!r}, device=dev, compute_type=ct)
        segs, info = m.transcribe('/tmp/in.wav')
        print('DEVICE', dev)
        print('---TRANSCRIPT---')
        print(''.join(s.text for s in segs))
        print('---LANG---', info.language)
        break
    except Exception as e:
        print('try', dev, 'failed', e)
"
"""


def parse_transcript_from_logs(logs: str) -> tuple[str, str | None]:
    """Return (text, device_or_none)."""
    if _TRANSCRIPT_MARKERS[0] not in logs:
        raise GPUSharingError("no transcript marker in remote logs")
    part = logs.split(_TRANSCRIPT_MARKERS[0], 1)[1]
    if "---LANG---" in part:
        text, rest = part.split("---LANG---", 1)
        lang = rest.strip().splitlines()[0].strip() if rest.strip() else None
        return text.strip(), lang
    return part.strip(), None


def extract_device_from_logs(logs: str) -> str | None:
    m = re.search(r"^DEVICE\s+(\S+)", logs, re.MULTILINE)
    return m.group(1) if m else None


def run_remote_transcribe(
    audio_url: str,
    *,
    model: str = "tiny",
    image: str = "python:3.11-slim",
    timeout_sec: int = 1800,
    client: GPUSharingClient | None = None,
) -> dict[str, str]:
    """
    Submit STT job to GPU Sharing. Returns dict with keys: text, language, device, job_id, logs.
    """
    from app.config import GPU_SHARING_STT_IMAGE

    c = client or client_from_config()
    if c is None:
        raise GPUSharingError("GPU_SHARING_API_KEY not configured")

    job_image = image or GPU_SHARING_STT_IMAGE
    script = _build_transcribe_script(audio_url=audio_url, model=model)
    job_id = c.create_job(
        image=job_image,
        command=["bash", "-lc", script],
        env={"AUDIO_URL": audio_url},
        timeout_sec=timeout_sec,
    )
    logger.info("GPU Sharing STT job %s queued for %s", job_id, audio_url[:80])
    job = c.wait_job(job_id, timeout_sec=float(timeout_sec) + 120)
    logs = c.get_logs(job_id)
    if job.get("status") != "done":
        raise GPUSharingError(f"remote STT job {job_id} {job.get('status')}: {logs[-2000:]}")
    text, lang = parse_transcript_from_logs(logs)
    return {
        "text": text,
        "language": lang or "",
        "device": extract_device_from_logs(logs) or "",
        "job_id": job_id,
        "logs": logs,
    }


def publish_audio_for_gpu(
    local_path: Path,
    *,
    deploy_host: str | None = None,
    deploy_user: str = "root",
    ssh_key: Path | None = None,
    remote_dir: str = "/tmp/vtt-gpu-audio",
    http_port: int | None = None,
) -> str:
    """Copy audio to HTTP staging and return URL reachable by the GPU worker."""
    from app.config import (
        GPU_SHARING_STT_PUBLISH_HOST,
        GPU_SHARING_STT_PUBLISH_PORT,
        GPU_SHARING_STT_STAGING_DIR,
    )
    from app.gpu_sharing.staging import publish_file_to_staging

    local_path = local_path.resolve()
    if not local_path.is_file():
        raise FileNotFoundError(local_path)

    host = (deploy_host or GPU_SHARING_STT_PUBLISH_HOST).strip()
    if not host:
        raise GPUSharingError("Set GPU_SHARING_STT_PUBLISH_HOST (VPS IP for audio HTTP staging)")
    port = http_port if http_port is not None else GPU_SHARING_STT_PUBLISH_PORT

    if GPU_SHARING_STT_STAGING_DIR:
        return publish_file_to_staging(
            local_path,
            staging_dir=Path(GPU_SHARING_STT_STAGING_DIR),
            publish_host=host,
            http_port=port,
        )

    if ssh_key is None:
        raise GPUSharingError(
            "GPU_SHARING_STT_STAGING_DIR not set and no SSH key for remote publish"
        )

    name = f"{uuid.uuid4().hex[:12]}{local_path.suffix or '.wav'}"
    remote_path = f"{remote_dir}/{name}"
    ssh_base = ["ssh", "-i", str(ssh_key), "-o", "StrictHostKeyChecking=accept-new", f"{deploy_user}@{deploy_host}"]
    scp_base = ["scp", "-i", str(ssh_key), "-o", "StrictHostKeyChecking=accept-new", str(local_path), f"{deploy_user}@{deploy_host}:{remote_path}"]

    subprocess.run(ssh_base + [f"mkdir -p {remote_dir}"], check=True, timeout=30)
    subprocess.run(scp_base, check=True, timeout=120)
    # Serve only that directory; start if not listening yet.
    subprocess.run(
        ssh_base
        + [
            f"mkdir -p {remote_dir} && "
            f"ss -tln | grep -q ':{http_port} ' || "
            f"(cd {remote_dir} && nohup python3 -m http.server {http_port} "
            f">/tmp/vtt-http-{http_port}.log 2>&1 </dev/null & sleep 1)"
        ],
        check=True,
        timeout=30,
    )
    probe = subprocess.run(
        ssh_base + [f"curl -sf -o /dev/null http://127.0.0.1:{http_port}/"],
        timeout=15,
    )
    if probe.returncode != 0:
        raise GPUSharingError(
            f"HTTP staging on {deploy_host}:{http_port} not reachable after start "
            f"(check ufw allow {http_port}/tcp)"
        )
    return f"http://{deploy_host}:{http_port}/{name}"


def transcribe_local_file_via_gpu(
    audio_path: Path,
    *,
    model: str | None = None,
    publish_host: str | None = None,
    ssh_key: Path | None = None,
) -> dict[str, str]:
    """Upload local WAV to staging host, run STT on GPU Sharing, return transcript dict."""
    from app.config import (
        GPU_SHARING_STT_MODEL,
        GPU_SHARING_STT_PUBLISH_HOST,
        GPU_SHARING_STT_PUBLISH_PORT,
    )

    from app.config import GPU_SHARING_STT_STAGING_DIR

    host = publish_host or GPU_SHARING_STT_PUBLISH_HOST
    key = ssh_key
    if not GPU_SHARING_STT_STAGING_DIR:
        if key is None:
            for candidate in (
                Path("/app/ssh-keys/id_ed25519"),
                Path(__file__).resolve().parents[2] / "ssh-keys" / "id_ed25519",
            ):
                if candidate.is_file():
                    key = candidate
                    break
            else:
                key = Path(__file__).resolve().parents[2] / "ssh-keys" / "id_ed25519"
        if not key.is_file():
            raise GPUSharingError(f"SSH key not found: {key}")

    url = publish_audio_for_gpu(
        audio_path,
        deploy_host=host,
        ssh_key=key,
        http_port=GPU_SHARING_STT_PUBLISH_PORT,
    )
    logger.info("Published audio for GPU STT: %s", url)
    return run_remote_transcribe(url, model=model or GPU_SHARING_STT_MODEL)


def transcribe_wav_via_gpu(
    wav_path: Path,
    *,
    output_dir: Path,
    language: str | None = None,
    progress_callback=None,
) -> "TranscriptionResult":
    """GPU Sharing STT + write .txt/.json like local transcribe_audio."""
    from datetime import datetime, timezone

    import json

    from app.config import GPU_SHARING_STT_MODEL
    from app.stt.chunks import probe_audio_duration, read_duration_from_sidecar
    from app.stt.transcriber import TranscriptionResult
    from app.utils.paths import build_output_basename, ensure_dir

    if progress_callback:
        progress_callback(15.0, "Распознавание (GPU)…")

    remote = transcribe_local_file_via_gpu(wav_path, model=GPU_SHARING_STT_MODEL)
    if progress_callback:
        progress_callback(85.0, "Распознавание (GPU)…")

    duration = read_duration_from_sidecar(wav_path)
    if duration is None:
        try:
            duration = probe_audio_duration(wav_path)
        except Exception:
            duration = 0.0

    lang = remote.get("language") or language or "unknown"
    basename = build_output_basename(wav_path)
    out_dir = ensure_dir(output_dir)
    txt_path = out_dir / f"{basename}.txt"
    json_path = out_dir / f"{basename}.json"
    text = remote["text"]
    txt_path.write_text(text + "\n", encoding="utf-8")
    payload = {
        "text": text,
        "language": lang,
        "duration_sec": float(duration or 0),
        "model": GPU_SHARING_STT_MODEL,
        "source_path": str(wav_path.resolve()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "parallel": False,
        "workers": 1,
        "gpu_sharing": True,
        "gpu_sharing_job_id": remote.get("job_id", ""),
        "gpu_device": remote.get("device", ""),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "GPU Sharing transcript done job=%s device=%s",
        remote.get("job_id"),
        remote.get("device"),
    )
    return TranscriptionResult(
        text=text,
        txt_path=txt_path,
        json_path=json_path,
        language=lang,
        duration_sec=float(duration or 0),
        segments=[],
        model=GPU_SHARING_STT_MODEL,
        source_path=str(wav_path.resolve()),
        parallel=False,
        workers=1,
    )
