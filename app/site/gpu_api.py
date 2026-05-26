"""Public GPU Sharing status for pible.ru (API key stays server-side)."""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

logger = logging.getLogger(__name__)


def fetch_gpu_status() -> dict[str, Any]:
    """Return safe public JSON (no secrets)."""
    from app.config import GPU_SHARING_ENABLED, GPU_SHARING_RUNTIME, GPU_SHARING_URL
    from app.gpu_sharing.client import GPUSharingError, client_from_config

    base: dict[str, Any] = {
        "configured": False,
        "enabled": GPU_SHARING_ENABLED,
        "url": GPU_SHARING_URL,
        "runtime": GPU_SHARING_RUNTIME,
        "api_ok": False,
        "nodes_online": 0,
        "nodes_total": 0,
        "runtimes": [],
        "ready": False,
    }

    client = client_from_config()
    if client is None:
        return base

    base["configured"] = True
    try:
        health = client.health()
        base["api_ok"] = health.get("status") == "ok"
        try:
            nodes = client.list_nodes()
            base["nodes_total"] = len(nodes)
            base["nodes_online"] = sum(1 for n in nodes if n.get("status") == "online")
        except GPUSharingError as exc:
            base["nodes_error"] = str(exc)[:200]
            logger.warning("GPU nodes check failed: %s", exc)
        runtimes = client.list_runtimes()
        base["runtimes"] = [
            {
                "id": r.get("runtime_id"),
                "enabled": r.get("enabled"),
                "description": r.get("description"),
            }
            for r in runtimes
        ]
        runtime_ready = any(r.get("enabled", True) for r in runtimes)
        base["ready"] = base["api_ok"] and (base["nodes_online"] > 0 or runtime_ready)
    except GPUSharingError as exc:
        base["error"] = str(exc)[:200]
        logger.warning("GPU status check failed: %s", exc)
    return base


class _SiteAPIHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        logger.debug(fmt, *args)

    def _send_json(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path in ("/health", "/health/"):
            self._send_json(200, {"status": "ok"})
            return
        if self.path in ("/api/gpu-status", "/api/gpu-status/"):
            self._send_json(200, fetch_gpu_status())
            return
        self.send_error(404)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()


def run_site_api(*, host: str = "0.0.0.0", port: int = 8080) -> None:
    server = ThreadingHTTPServer((host, port), _SiteAPIHandler)
    logger.info("Site API listening on %s:%s", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
