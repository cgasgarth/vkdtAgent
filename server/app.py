from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from server.bridge import CodexAppServerBridge, CodexAppServerError
from server.mock_planner import MockPlannerBridge
from shared.protocol import AssistantMessage, RequestEnvelope, ResponseEnvelope

logger = logging.getLogger("vkdt_agent.server")
app = FastAPI(title="vkdt agent server", version="0.1.0")
_codex_bridge = CodexAppServerBridge()
_mock_bridge = MockPlannerBridge()
_CLIENT_ROOT = Path(__file__).resolve().parent / "client"

app.mount("/assets", StaticFiles(directory=str(_CLIENT_ROOT)), name="assets")


def _planner() -> CodexAppServerBridge | MockPlannerBridge:
    return (
        _mock_bridge
        if os.environ.get("VKDT_AGENT_USE_MOCK_RESPONSES") == "1"
        else _codex_bridge
    )


def _error_response(
    request: RequestEnvelope, code: str, message: str, status_code: int
) -> JSONResponse:
    payload = ResponseEnvelope(
        requestId=request.requestId,
        session=request.session,
        status="error",
        assistantMessage=AssistantMessage(role="assistant", text=message),
        plan=None,
        workflow=None,
        error={"code": code, "message": message},
    )
    return JSONResponse(
        status_code=status_code, content=payload.model_dump(mode="json")
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_CLIENT_ROOT / "index.html")


@app.post("/v1/chat")
async def chat(request: RequestEnvelope) -> JSONResponse:
    try:
        result = _planner().plan(request)
    except CodexAppServerError as exc:
        return _error_response(request, exc.code, exc.message, exc.status_code)
    except Exception as exc:
        logger.exception("vkdt_agent_unexpected_error")
        return _error_response(request, "internal_error", str(exc), 500)
    payload = ResponseEnvelope(
        requestId=request.requestId,
        session=request.session,
        status="ok",
        assistantMessage=AssistantMessage(
            role="assistant", text=result.plan.assistantText
        ),
        plan=result.plan,
        workflow=result.plan.workflow,
        error=None,
    )
    return JSONResponse(content=payload.model_dump(mode="json"))
