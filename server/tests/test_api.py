from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from server import app as app_module
from server.mock_planner import MockPlannerBridge


def test_chat_endpoint_uses_mock_planner(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VKDT_AGENT_USE_MOCK_RESPONSES", "1")

    class LocalMockPlanner(MockPlannerBridge):
        pass

    monkeypatch.setattr(app_module, "_mock_bridge", LocalMockPlanner())
    client = TestClient(app_module.app)
    response = client.post(
        "/v1/chat",
        json={
            "schemaVersion": "1.0",
            "requestId": "req-1",
            "session": {
                "appSessionId": "app-1",
                "imageSessionId": "img-1",
                "conversationId": "conv-1",
                "turnId": "turn-1",
            },
            "message": {"role": "user", "text": "Brighten the photo"},
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
                "goalText": "Brighten the photo",
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["plan"]["operations"][0]["kind"] == "set_param"
    assert payload["workflow"]["graphText"]
    assert payload["workflow"]["adjustmentSurfaces"]


def test_index_serves_client() -> None:
    client = TestClient(app_module.app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Multi-turn vkdt editing client" in response.text
