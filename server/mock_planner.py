from __future__ import annotations

from dataclasses import dataclass

from server.bridge_types import RequestProgressPayload
from shared.protocol import AgentPlan, GraphOperation, RequestEnvelope


@dataclass(slots=True)
class MockTurnResult:
    plan: AgentPlan
    thread_id: str
    turn_id: str
    raw_message: str


class MockPlannerBridge:
    def plan(self, request: RequestEnvelope) -> MockTurnResult:
        first_setting = request.imageSnapshot.editableSettings[0]
        operation = GraphOperation(
            kind=first_setting.kind,
            targetType="vkdt-action",
            actionPath=first_setting.actionPath,
            mode="delta" if "delta" in first_setting.supportedModes else "set",
            valueNumber=0.25 if first_setting.kind == "set-float" else None,
            valueBool=True if first_setting.kind == "set-bool" else None,
            valueChoiceId=(
                first_setting.choices[0].choiceId
                if first_setting.kind == "set-choice" and first_setting.choices
                else None
            ),
            summary=f"Adjust {first_setting.label}",
        )
        plan = AgentPlan(
            assistantText="Prepared one native vkdt edit operation in mock mode.",
            continueRefining=False,
            operations=[operation],
        )
        return MockTurnResult(
            plan=plan,
            thread_id="mock-thread-1",
            turn_id="mock-turn-1",
            raw_message=plan.model_dump_json(),
        )

    def cancel_request(
        self,
        *,
        request_id: str,
        app_session_id: str,
        image_session_id: str,
        conversation_id: str,
        turn_id: str,
        reason: str | None = None,
    ) -> bool:
        del (
            request_id,
            app_session_id,
            image_session_id,
            conversation_id,
            turn_id,
            reason,
        )
        return True

    def get_request_progress(
        self,
        *,
        request_id: str,
        app_session_id: str,
        image_session_id: str,
        conversation_id: str,
        turn_id: str,
    ) -> RequestProgressPayload:
        del request_id, app_session_id, image_session_id, conversation_id, turn_id
        return {
            "found": False,
            "status": "not_found",
            "toolCallsUsed": 0,
            "maxToolCalls": 0,
            "appliedOperationCount": 0,
            "operations": [],
            "latestOperation": None,
            "message": "No active request found.",
            "lastToolName": None,
            "progressVersion": 0,
            "requiresRenderCallback": False,
        }

    def provide_render_callback(
        self,
        *,
        image_session_id: str,
        turn_id: str,
        image_bytes: bytes,
    ) -> bool:
        del image_session_id, turn_id, image_bytes
        return True
