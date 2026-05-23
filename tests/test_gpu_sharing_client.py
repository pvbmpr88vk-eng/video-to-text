from __future__ import annotations

import httpx
import pytest

from app.gpu_sharing.client import GPUSharingClient, GPUSharingError


def test_health_and_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/v1/nodes":
            return httpx.Response(
                200,
                json=[{"id": "n1", "status": "online"}],
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        httpx,
        "request",
        lambda method, url, **kw: httpx.Client(transport=transport).request(
            method, url, **kw
        ),
    )
    client = GPUSharingClient("http://gpu.test", "gpu_sk_test")
    assert client.health()["status"] == "ok"
    assert client.has_online_node()


def test_create_job_requires_id(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v1/jobs":
            return httpx.Response(200, json={})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        httpx,
        "request",
        lambda method, url, **kw: httpx.Client(transport=transport).request(
            method, url, **kw
        ),
    )
    client = GPUSharingClient("http://gpu.test", "key")
    with pytest.raises(GPUSharingError, match="no job id"):
        client.create_job(image="python:3.11-slim", command=["true"])
