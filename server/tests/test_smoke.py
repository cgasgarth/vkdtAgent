from __future__ import annotations

from fastapi.testclient import TestClient

from server import app as app_module
from server.tests.test_api import sample_request


def test_health() -> None:
    client = TestClient(app_module.app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_mock_chat_smoke(monkeypatch) -> None:
    monkeypatch.setenv("VKDT_AGENT_USE_MOCK_RESPONSES", "1")
    client = TestClient(app_module.app)
    response = client.post("/v1/chat", json=sample_request())
    assert response.status_code == 200
    assert response.json()["assistantMessage"]["text"]


def test_stream_smoke(monkeypatch) -> None:
    monkeypatch.setenv("VKDT_AGENT_USE_MOCK_RESPONSES", "1")
    client = TestClient(app_module.app)
    with client.stream("POST", "/v1/chat/stream", json=sample_request()) as response:
        body = "".join(chunk for chunk in response.iter_text())
    assert response.status_code == 200
    assert "event: final" in body
