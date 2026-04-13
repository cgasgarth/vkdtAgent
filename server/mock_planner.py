from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from shared.protocol import AgentPlan, GraphEdit, RequestEnvelope

from .session import VkdtSession
from .vkdt_runner import VkdtRunner


@dataclass(slots=True)
class MockTurnResult:
    plan: AgentPlan
    thread_id: str
    turn_id: str
    raw_message: str


class MockPlannerBridge:
    def plan(self, request: RequestEnvelope) -> MockTurnResult:
        fake_vkdt = Path(__file__).resolve().parent / "tests" / "fake_vkdt_cli.py"
        session = VkdtSession.create(
            request,
            runner=VkdtRunner(command=["python3", str(fake_vkdt)]),
        )
        operation = GraphEdit(
            kind="set_param",
            module="colour",
            instance="01",
            param="exposure",
            values=[0.5],
        )
        session.apply_edits([operation])
        plan = AgentPlan(
            assistantText="Raised exposure slightly in mock mode.",
            continueRefining=False,
            operations=[operation],
            workflow=session.workflow_state(),
        )
        return MockTurnResult(
            plan=plan,
            thread_id="mock-thread-1",
            turn_id="mock-turn-1",
            raw_message=plan.model_dump_json(),
        )
