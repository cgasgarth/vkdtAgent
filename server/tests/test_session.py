from __future__ import annotations

from pathlib import Path

from server.session import VkdtSession
from server.vkdt_runner import VkdtRunner
from shared.protocol import GraphEdit, RequestEnvelope


def _request(tmp_path: Path) -> RequestEnvelope:
    return RequestEnvelope.model_validate(
        {
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
                "previewWidth": 100,
                "previewHeight": 100,
            },
            "fast": False,
            "refinement": {
                "mode": "multi-turn",
                "enabled": True,
                "maxPasses": 5,
                "passIndex": 1,
                "goalText": "Brighten the photo",
            },
        }
    )


def test_session_refreshes_preview_and_applies_edits(tmp_path: Path) -> None:
    runner = VkdtRunner(
        command=["python3", str(Path(__file__).with_name("fake_vkdt_cli.py"))]
    )
    session = VkdtSession.create(_request(tmp_path), runner=runner)
    workflow = session.workflow_state()
    assert workflow.preview is not None
    session.apply_edits(
        [
            GraphEdit(
                kind="set_param",
                module="colour",
                instance="01",
                param="exposure",
                values=[1.0],
            )
        ]
    )
    assert "param:colour:01:exposure:1.0" in session.graph_path.read_text()
