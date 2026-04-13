from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from server import app as app_module


def test_health() -> None:
    client = TestClient(app_module.app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_mock_chat_smoke(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VKDT_AGENT_USE_MOCK_RESPONSES", "1")
    client = TestClient(app_module.app)
    response = client.post(
        "/v1/chat",
        json={
            "schemaVersion": "1.0",
            "requestId": "req-smoke",
            "session": {
                "appSessionId": "app-1",
                "imageSessionId": "img-1",
                "conversationId": "conv-1",
                "turnId": "turn-1",
            },
            "message": {"role": "user", "text": "Give this a clean natural edit"},
            "workspace": {
                "imagePath": "/tmp/source.raw",
                "sessionRoot": str(tmp_path),
                "previewWidth": 64,
                "previewHeight": 64,
            },
            "fast": False,
            "refinement": {
                "mode": "multi-turn",
                "enabled": True,
                "maxPasses": 5,
                "passIndex": 1,
                "goalText": "Give this a clean natural edit",
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["assistantMessage"]["text"]
    assert payload["workflow"]["preview"]["base64Data"]
