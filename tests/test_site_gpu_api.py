from __future__ import annotations

from app.site.gpu_api import fetch_gpu_status


def test_fetch_gpu_status_not_configured(monkeypatch) -> None:
    monkeypatch.setattr("app.config.GPU_SHARING_API_KEY", "")
    out = fetch_gpu_status()
    assert out["configured"] is False
    assert out["ready"] is False


def test_fetch_gpu_status_ok(monkeypatch) -> None:
    class FakeClient:
        def health(self):
            return {"status": "ok"}

        def list_nodes(self):
            return [{"status": "online"}]

        def list_runtimes(self):
            return [{"runtime_id": "onnx_cuda", "enabled": True, "description": "CUDA"}]

    monkeypatch.setattr("app.config.GPU_SHARING_API_KEY", "gpu_sk_test")
    monkeypatch.setattr("app.gpu_sharing.client.client_from_config", lambda: FakeClient())
    out = fetch_gpu_status()
    assert out["configured"] is True
    assert out["ready"] is True
    assert out["nodes_online"] == 1
