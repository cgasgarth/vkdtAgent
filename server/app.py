from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator, Mapping
from typing import Literal, cast

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    JSONResponse,
    PlainTextResponse,
    Response,
    StreamingResponse,
)
from pydantic import BaseModel, Field

from server.bridge import CodexAppServerBridge, CodexAppServerError
from server.bridge_types import PlannerBridge, PlannerTurnResult, RequestProgressPayload
from server.mock_planner import MockPlannerBridge
from shared.protocol import (
    AssistantMessage,
    ErrorInfo,
    RefinementStatus,
    RequestEnvelope,
    RequestSession,
    ResponseEnvelope,
    ResponseSession,
)

logger = logging.getLogger("vkdt_agent.server")
app = FastAPI(title="vkdtAgent server", version="0.2.0")
_codex_bridge = CodexAppServerBridge()
_mock_bridge = MockPlannerBridge()


class CancelRequestEnvelope(BaseModel):
    requestId: str = Field(min_length=1)
    session: RequestSession
    reason: str | None = None


class CancelResponseEnvelope(BaseModel):
    requestId: str
    canceled: bool
    message: str


def get_bridge() -> PlannerBridge:
    if os.environ.get("VKDT_AGENT_USE_MOCK_RESPONSES") == "1":
        return cast(PlannerBridge, _mock_bridge)
    return cast(PlannerBridge, _codex_bridge)


def build_refinement_status(
    request: RequestEnvelope,
    *,
    continue_refining: bool,
    stop_reason: Literal[
        "planner-complete",
        "cancelled",
        "tool-budget",
        "render-timeout",
        "error",
    ],
) -> RefinementStatus:
    return RefinementStatus(
        mode=request.refinement.mode,
        enabled=request.refinement.enabled,
        passIndex=request.refinement.passIndex,
        maxPasses=request.refinement.maxPasses,
        continueRefining=continue_refining,
        stopReason=stop_reason,
    )


def build_response(
    request: RequestEnvelope, turn_result: PlannerTurnResult
) -> ResponseEnvelope:
    return ResponseEnvelope(
        requestId=request.requestId,
        session=ResponseSession.model_validate(request.session.model_dump(mode="json")),
        status="ok",
        assistantMessage=AssistantMessage(
            role="assistant", text=turn_result.plan.assistantText
        ),
        refinement=build_refinement_status(
            request,
            continue_refining=turn_result.plan.continueRefining,
            stop_reason="planner-complete",
        ),
        plan=turn_result.plan,
        error=None,
    )


def build_error_response(
    request_id: str,
    session: dict[str, str],
    *,
    refinement: RefinementStatus | None,
    code: str,
    message: str,
    status_code: int,
) -> JSONResponse:
    payload = ResponseEnvelope(
        requestId=request_id,
        session=ResponseSession.model_validate(session),
        status="error",
        assistantMessage=AssistantMessage(role="assistant", text=message),
        refinement=refinement
        or RefinementStatus(
            mode="multi-turn",
            enabled=True,
            passIndex=1,
            maxPasses=2,
            continueRefining=False,
            stopReason="error",
        ),
        plan=None,
        error=ErrorInfo(code=code, message=message),
    )
    return JSONResponse(
        status_code=status_code, content=payload.model_dump(mode="json")
    )


def parse_request_ids(body: object) -> tuple[str, dict[str, str]]:
    if isinstance(body, dict):
        payload = cast(dict[str, object], body)
        raw_request_id = payload.get("requestId")
        request_id = raw_request_id if isinstance(raw_request_id, str) else ""
        raw_session = payload.get("session")
        session = (
            cast(dict[str, object], raw_session)
            if isinstance(raw_session, dict)
            else {}
        )
        return request_id, {
            "appSessionId": str(session.get("appSessionId") or ""),
            "imageSessionId": str(session.get("imageSessionId") or ""),
            "conversationId": str(session.get("conversationId") or ""),
            "turnId": str(session.get("turnId") or ""),
        }
    return "", {
        "appSessionId": "",
        "imageSessionId": "",
        "conversationId": "",
        "turnId": "",
    }


def encode_sse(event: str, payload: Mapping[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


def build_error_payload(
    request_id: str,
    session: dict[str, str],
    *,
    refinement: RefinementStatus,
    code: str,
    message: str,
) -> dict[str, object]:
    return ResponseEnvelope(
        requestId=request_id,
        session=ResponseSession.model_validate(session),
        status="error",
        assistantMessage=AssistantMessage(role="assistant", text=message),
        refinement=refinement,
        plan=None,
        error=ErrorInfo(code=code, message=message),
    ).model_dump(mode="json")


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    del request
    request_id, session = parse_request_ids(getattr(exc, "body", None))
    message = (
        "; ".join(
            (
                f"{'/'.join(str(part) for part in error.get('loc', ('request',)))}: "
                f"{error.get('msg')}"
            )
            for error in exc.errors()
            if isinstance(error, dict)
        )
        or "Request validation failed"
    )
    return build_error_response(
        request_id,
        session,
        refinement=None,
        code="invalid_request",
        message=message,
        status_code=422,
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def index() -> PlainTextResponse:
    return PlainTextResponse(
        "vkdtAgent expects a native vkdt UI build to talk to "
        "/v1/chat/stream and /v1/chat/render."
    )


@app.post("/v1/chat/cancel", response_model=CancelResponseEnvelope)
async def cancel_chat(request: CancelRequestEnvelope) -> CancelResponseEnvelope:
    canceled = await asyncio.to_thread(
        get_bridge().cancel_request,
        request_id=request.requestId,
        app_session_id=request.session.appSessionId,
        image_session_id=request.session.imageSessionId,
        conversation_id=request.session.conversationId,
        turn_id=request.session.turnId,
        reason=request.reason,
    )
    return CancelResponseEnvelope(
        requestId=request.requestId,
        canceled=True,
        message=(
            "Cancellation requested for the active chat turn"
            if canceled
            else "Cancellation recorded for this chat turn"
        ),
    )


@app.post("/v1/chat", response_model=ResponseEnvelope)
async def chat(request: RequestEnvelope) -> ResponseEnvelope | JSONResponse:
    try:
        result = await asyncio.to_thread(get_bridge().plan, request)
    except CodexAppServerError as exc:
        return build_error_response(
            request.requestId,
            request.session.model_dump(mode="json"),
            refinement=build_refinement_status(
                request, continue_refining=False, stop_reason="error"
            ),
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
        )
    except Exception as exc:
        logger.exception("vkdt_agent_unexpected_error")
        return build_error_response(
            request.requestId,
            request.session.model_dump(mode="json"),
            refinement=build_refinement_status(
                request, continue_refining=False, stop_reason="error"
            ),
            code="internal_error",
            message=str(exc),
            status_code=500,
        )
    return build_response(request, result)


@app.post("/v1/chat/stream")
async def chat_stream(request: RequestEnvelope) -> StreamingResponse:
    bridge = get_bridge()

    async def event_stream() -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        plan_task = loop.run_in_executor(None, bridge.plan, request)
        last_version = -1
        while True:
            if plan_task.done():
                break
            progress: RequestProgressPayload = await asyncio.to_thread(
                bridge.get_request_progress,
                request_id=request.requestId,
                app_session_id=request.session.appSessionId,
                image_session_id=request.session.imageSessionId,
                conversation_id=request.session.conversationId,
                turn_id=request.session.turnId,
            )
            version = int(progress["progressVersion"])
            if version != last_version and progress["found"]:
                last_version = version
                yield encode_sse("progress", progress)
            await asyncio.sleep(0.2)
        try:
            result = await plan_task
        except CodexAppServerError as exc:
            payload = build_error_payload(
                request.requestId,
                request.session.model_dump(mode="json"),
                refinement=build_refinement_status(
                    request, continue_refining=False, stop_reason="error"
                ),
                code=exc.code,
                message=exc.message,
            )
            yield encode_sse("error", payload)
            return
        except Exception as exc:
            payload = build_error_payload(
                request.requestId,
                request.session.model_dump(mode="json"),
                refinement=build_refinement_status(
                    request, continue_refining=False, stop_reason="error"
                ),
                code="internal_error",
                message=str(exc),
            )
            yield encode_sse("error", payload)
            return
        yield encode_sse(
            "final", build_response(request, result).model_dump(mode="json")
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/v1/chat/render")
async def provide_render(
    request: Request,
    x_vkdt_image_session_id: str = Header(alias="X-Vkdt-Image-Session-Id"),
    x_vkdt_turn_id: str = Header(alias="X-Vkdt-Turn-Id"),
) -> Response:
    image_bytes = await request.body()
    accepted = await asyncio.to_thread(
        get_bridge().provide_render_callback,
        image_session_id=x_vkdt_image_session_id,
        turn_id=x_vkdt_turn_id,
        image_bytes=image_bytes,
    )
    return Response(status_code=202 if accepted else 404)
