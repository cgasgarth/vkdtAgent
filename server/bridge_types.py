from __future__ import annotations

from typing import Protocol, TypedDict

from shared.protocol import AgentPlan, JsonObject, RequestEnvelope


class RequestProgressPayload(TypedDict):
    found: bool
    status: str
    toolCallsUsed: int
    maxToolCalls: int
    appliedOperationCount: int
    operations: list[JsonObject]
    latestOperation: JsonObject | None
    message: str
    lastToolName: str | None
    progressVersion: int
    requiresRenderCallback: bool


class PlannerTurnResult(Protocol):
    plan: AgentPlan
    thread_id: str
    turn_id: str
    raw_message: str


class PlannerBridge(Protocol):
    def plan(self, request: RequestEnvelope) -> PlannerTurnResult: ...

    def cancel_request(
        self,
        *,
        request_id: str,
        app_session_id: str,
        image_session_id: str,
        conversation_id: str,
        turn_id: str,
        reason: str | None = None,
    ) -> bool: ...

    def get_request_progress(
        self,
        *,
        request_id: str,
        app_session_id: str,
        image_session_id: str,
        conversation_id: str,
        turn_id: str,
    ) -> RequestProgressPayload: ...

    def provide_render_callback(
        self,
        *,
        image_session_id: str,
        turn_id: str,
        image_bytes: bytes,
    ) -> bool: ...
