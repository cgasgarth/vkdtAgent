from __future__ import annotations

from fastapi.testclient import TestClient

from server import app as app_module


def sample_request() -> dict[str, object]:
    return {
        "schemaVersion": "2.0",
        "requestId": "req-1",
        "session": {
            "appSessionId": "app-1",
            "imageSessionId": "img-1",
            "conversationId": "conv-1",
            "turnId": "turn-1",
        },
        "uiContext": {"view": "darkroom", "imageId": 1, "imageName": "sample.raw"},
        "message": {"role": "user", "text": "Brighten the image slightly"},
        "capabilityManifest": {
            "manifestVersion": "1",
            "targets": [
                {
                    "moduleId": "colour:01",
                    "moduleLabel": "Colour",
                    "capabilityId": "colour.exposure",
                    "label": "Exposure",
                    "kind": "set-float",
                    "targetType": "vkdt-action",
                    "actionPath": "module/colour:01/param/exposure",
                    "supportedModes": ["delta", "set"],
                    "minNumber": -5,
                    "maxNumber": 5,
                    "defaultNumber": 0,
                    "stepNumber": 0.1,
                }
            ],
        },
        "imageSnapshot": {
            "imageRevisionId": "rev-1",
            "graphPath": "/tmp/working.cfg",
            "graphText": "module:colour:01\n",
            "moduleOrder": ["colour:01"],
            "modules": [
                {"module": "colour", "instance": "01", "params": {"exposure": ["0"]}}
            ],
            "connections": [],
            "adjustmentSurfaces": [{"module": "colour", "present": True}],
            "editableSettings": [
                {
                    "moduleId": "colour:01",
                    "moduleLabel": "Colour",
                    "settingId": "colour.exposure",
                    "capabilityId": "colour.exposure",
                    "label": "Exposure",
                    "actionPath": "module/colour:01/param/exposure",
                    "kind": "set-float",
                    "supportedModes": ["delta", "set"],
                    "currentNumber": 0,
                    "minNumber": -5,
                    "maxNumber": 5,
                    "defaultNumber": 0,
                    "stepNumber": 0.1,
                }
            ],
            "history": [
                {"num": 0, "module": "colour", "enabled": True, "instanceName": "01"}
            ],
            "preview": {
                "previewId": "preview-1",
                "mimeType": "image/jpeg",
                "width": 100,
                "height": 100,
                "base64Data": "ZmFrZQ==",
            },
        },
        "fast": False,
        "refinement": {
            "mode": "multi-turn",
            "enabled": True,
            "maxPasses": 5,
            "passIndex": 1,
            "goalText": "Brighten the image slightly",
        },
    }


def test_index_explains_native_bridge() -> None:
    client = TestClient(app_module.app)
    response = client.get("/")
    assert response.status_code == 200
    assert "native vkdt UI build" in response.text


def test_chat_endpoint_uses_mock_planner(monkeypatch) -> None:
    monkeypatch.setenv("VKDT_AGENT_USE_MOCK_RESPONSES", "1")
    client = TestClient(app_module.app)
    response = client.post("/v1/chat", json=sample_request())
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["plan"]["operations"][0]["targetType"] == "vkdt-action"


def test_cancel_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("VKDT_AGENT_USE_MOCK_RESPONSES", "1")
    client = TestClient(app_module.app)
    response = client.post(
        "/v1/chat/cancel",
        json={
            "requestId": "req-1",
            "session": sample_request()["session"],
            "reason": "user canceled",
        },
    )
    assert response.status_code == 200
    assert response.json()["canceled"] is True
