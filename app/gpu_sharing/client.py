"""HTTP client for GPU Sharing API v3 (ONNX invoke on remote CUDA)."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class GPUSharingError(Exception):
    """GPU Sharing API or job failure."""


class GPUSharingClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        poll_interval_sec: float = 5.0,
        request_timeout_sec: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.poll_interval_sec = poll_interval_sec
        self.request_timeout_sec = request_timeout_sec
        if not self.base_url:
            raise GPUSharingError("GPU_SHARING_URL is empty")
        if not self.api_key:
            raise GPUSharingError("GPU_SHARING_API_KEY is empty")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        url = f"{self.base_url}{path}"
        try:
            r = httpx.request(
                method,
                url,
                headers=self._headers(),
                json=json,
                timeout=timeout or self.request_timeout_sec,
            )
        except httpx.HTTPError as exc:
            raise GPUSharingError(f"HTTP error {method} {path}: {exc}") from exc
        if r.status_code == 401:
            raise GPUSharingError("invalid api key (401)")
        if r.status_code >= 400:
            detail = r.text[:500]
            raise GPUSharingError(f"HTTP {r.status_code} {path}: {detail}")
        return r

    def health(self) -> dict[str, Any]:
        r = self._request("GET", "/health")
        return r.json()

    def list_nodes(self) -> list[dict[str, Any]]:
        r = self._request("GET", "/v1/nodes")
        data = r.json()
        if isinstance(data, list):
            return data
        return list(data.get("nodes") or [])

    def has_online_node(self) -> bool:
        try:
            return any(n.get("status") == "online" for n in self.list_nodes())
        except GPUSharingError as exc:
            logger.warning("GPU node list unavailable, falling back to runtimes: %s", exc)
            return self.has_enabled_runtime()

    def list_runtimes(self) -> list[dict[str, Any]]:
        r = self._request("GET", "/v1/gpu/runtimes")
        data = r.json()
        if isinstance(data, list):
            return data
        return list(data.get("runtimes") or [])

    def has_enabled_runtime(self, runtime_id: str | None = None) -> bool:
        for runtime in self.list_runtimes():
            if runtime_id and runtime.get("runtime_id") != runtime_id:
                continue
            if runtime.get("enabled", True):
                return True
        return False

    def create_invoke(
        self,
        *,
        runtime: str,
        model_url: str,
        inputs_url: str = "",
        timeout_sec: int = 600,
    ) -> str:
        payload: dict[str, Any] = {
            "runtime": runtime,
            "model_url": model_url,
            "inputs_url": inputs_url,
            "timeout_sec": timeout_sec,
        }
        r = self._request("POST", "/v1/gpu/invoke", json=payload)
        data = r.json()
        invoke_id = data.get("id")
        if not invoke_id:
            raise GPUSharingError(f"no invoke id in response: {data!r}")
        return str(invoke_id)

    def get_invoke(self, invoke_id: str) -> dict[str, Any]:
        r = self._request("GET", f"/v1/gpu/invokes/{invoke_id}")
        return r.json()

    def get_invoke_logs(self, invoke_id: str) -> str:
        r = self._request("GET", f"/v1/gpu/invokes/{invoke_id}/logs")
        return r.text

    def wait_invoke(
        self,
        invoke_id: str,
        *,
        timeout_sec: float | None = None,
        poll_interval_sec: float | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + (timeout_sec or 3600.0)
        interval = poll_interval_sec if poll_interval_sec is not None else self.poll_interval_sec
        while time.monotonic() < deadline:
            invoke = self.get_invoke(invoke_id)
            status = invoke.get("status")
            if status in ("done", "failed"):
                return invoke
            time.sleep(interval)
        raise GPUSharingError(f"invoke {invoke_id} timed out waiting for completion")

    def run_invoke(
        self,
        *,
        runtime: str,
        model_url: str,
        inputs_url: str = "",
        timeout_sec: int = 600,
        wait_timeout_sec: float | None = None,
    ) -> dict[str, Any]:
        invoke_id = self.create_invoke(
            runtime=runtime,
            model_url=model_url,
            inputs_url=inputs_url,
            timeout_sec=timeout_sec,
        )
        invoke = self.wait_invoke(
            invoke_id, timeout_sec=wait_timeout_sec or float(timeout_sec) + 120
        )
        logs = self.get_invoke_logs(invoke_id)
        if invoke.get("status") == "failed":
            err = invoke.get("error_message") or logs
            raise GPUSharingError(f"invoke {invoke_id} failed: {err}")
        return {"invoke_id": invoke_id, "invoke": invoke, "logs": logs}

    def invoke_device(self, invoke: dict[str, Any]) -> str | None:
        result = invoke.get("result") or {}
        metrics = result.get("metrics") or {}
        device = metrics.get("device")
        return str(device) if device else None

    # Legacy v1/v2 — Docker jobs (deprecated; allowlist often empty).
    def create_job(
        self,
        *,
        image: str,
        command: list[str],
        env: dict[str, str] | None = None,
        timeout_sec: int = 300,
    ) -> str:
        payload: dict[str, Any] = {
            "image": image,
            "command": command,
            "timeout_sec": timeout_sec,
        }
        if env:
            payload["env"] = env
        r = self._request("POST", "/v1/jobs", json=payload)
        data = r.json()
        job_id = data.get("id") or (data.get("job") or {}).get("id")
        if not job_id:
            raise GPUSharingError(f"no job id in response: {data!r}")
        return str(job_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        r = self._request("GET", f"/v1/jobs/{job_id}")
        data = r.json()
        if isinstance(data, dict) and "job" in data:
            return data["job"]
        return data

    def get_logs(self, job_id: str) -> str:
        r = self._request("GET", f"/v1/jobs/{job_id}/logs")
        text = r.text
        if not text.strip():
            return ""
        # API returns plain text; older gateways may wrap JSON.
        if text.lstrip().startswith("{"):
            try:
                data = r.json()
                if isinstance(data, str):
                    return data
                if isinstance(data, dict):
                    return str(data.get("logs") or data.get("log") or data)
            except Exception:
                pass
        return text

    def wait_job(
        self,
        job_id: str,
        *,
        timeout_sec: float | None = None,
        poll_interval_sec: float | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + (timeout_sec or 3600.0)
        interval = poll_interval_sec if poll_interval_sec is not None else self.poll_interval_sec
        while time.monotonic() < deadline:
            job = self.get_job(job_id)
            status = job.get("status")
            if status in ("done", "failed"):
                return job
            time.sleep(interval)
        raise GPUSharingError(f"job {job_id} timed out waiting for completion")

    def run_job(
        self,
        *,
        image: str,
        command: list[str],
        env: dict[str, str] | None = None,
        timeout_sec: int = 300,
        wait_timeout_sec: float | None = None,
    ) -> dict[str, Any]:
        job_id = self.create_job(
            image=image,
            command=command,
            env=env,
            timeout_sec=timeout_sec,
        )
        job = self.wait_job(job_id, timeout_sec=wait_timeout_sec or float(timeout_sec) + 120)
        logs = self.get_logs(job_id)
        if job.get("status") == "failed":
            raise GPUSharingError(f"job {job_id} failed; logs:\n{logs}")
        return {"job_id": job_id, "job": job, "logs": logs}


def client_from_config() -> GPUSharingClient | None:
    from app.config import GPU_SHARING_API_KEY, GPU_SHARING_URL

    if not GPU_SHARING_API_KEY:
        return None
    return GPUSharingClient(GPU_SHARING_URL, GPU_SHARING_API_KEY)
