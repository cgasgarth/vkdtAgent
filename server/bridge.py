from __future__ import annotations

import json
import logging
import select
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from shared.protocol import AgentPlan, ExportRequest, GraphEdit, RequestEnvelope

from .session import VkdtSession
from .vkdt_catalog import get_playbook, module_catalog, playbook_ids

logger = logging.getLogger("vkdt_agent.codex")

THREAD_INSTRUCTIONS = """You are vkdtAgent, an expert RAW photo editor
operating vkdt through a structured node-graph editing interface.

Core rules:
- This is an image-editing workflow, not a coding workflow.
- This interface is always a live multi-turn run.
- Use only these tools in this run: get_workflow_state, get_preview_image,
  get_module_catalog, get_playbook, apply_graph_edits, render_export, and end.
- Do not call generic command execution, patching, filesystem editing, or
  other workspace tools.
- Think in vkdt graph terms: modules, instances, connections, and params.
- Prefer coherent graph edits that preserve a valid main processing path.
- Follow this loop: inspect state, apply edits, inspect the refreshed state or
  preview if needed, continue iterating, then call end.
- Use colour, hilite, filmcurv or OpenDRT, llap, crop, lens, grade, curves,
  mask, draw, guided, blend, colenc, and export sinks when they fit the
  request.
- If the request is broad, make a strong professional edit rather than asking
  for unnecessary clarification.
- Use get_playbook only when it materially changes the plan.
- After enough inspection, use apply_graph_edits instead of continuing to read.
- In live runs, once the graph and output are satisfactory, call end with the
  final user-facing message.

Return exactly one JSON object matching the output schema after tool calls."""


class CodexAppServerError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(slots=True)
class ActiveRequest:
    request_id: str
    conversation_id: str
    client_turn_id: str
    status: str = "queued"
    message: str = "Request accepted"
    cancel_event: threading.Event = field(default_factory=threading.Event)
    thread_id: str | None = None
    turn_id: str | None = None


@dataclass(slots=True)
class TurnContext:
    request: RequestEnvelope
    session: VkdtSession
    preview_data_url: str
    operations: list[dict[str, Any]] = field(default_factory=list)
    completed_plan: AgentPlan | None = None


@dataclass(slots=True)
class CodexTurnResult:
    plan: AgentPlan
    thread_id: str
    turn_id: str
    raw_message: str


def _build_output_schema() -> dict[str, Any]:
    schema = AgentPlan.model_json_schema()

    def _rewrite(node: Any) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                node["required"] = list(properties)
                node.setdefault("additionalProperties", False)
                for child in properties.values():
                    _rewrite(child)
            for key in ("items", "anyOf", "allOf", "oneOf", "prefixItems", "$defs"):
                child = node.get(key)
                if isinstance(child, dict):
                    for grandchild in child.values():
                        _rewrite(grandchild)
                elif isinstance(child, list):
                    for grandchild in child:
                        _rewrite(grandchild)
        elif isinstance(node, list):
            for child in node:
                _rewrite(child)

    _rewrite(schema)
    return cast(dict[str, Any], schema)


class CodexAppServerBridge:
    def __init__(
        self,
        *,
        command: list[str] | None = None,
        cwd: Path | None = None,
        timeout_seconds: float = 600.0,
    ) -> None:
        if command is None:
            configured_env = None
            try:
                import os

                configured_env = os.environ.get("VKDT_AGENT_CODEX_APP_SERVER_CMD")
            except Exception:
                configured_env = None
            command = (
                shlex.split(configured_env)
                if configured_env
                else ["codex", "app-server", "--listen", "stdio://"]
            )
        self._command = list(command)
        self._cwd = str((cwd or Path(__file__).resolve().parent.parent).resolve())
        self._timeout_seconds = timeout_seconds
        self._process: subprocess.Popen[str] | None = None
        self._initialized = False
        self._next_request_id = 1
        self._lock = threading.Lock()
        self._active_requests: dict[str, ActiveRequest] = {}
        self._conversation_threads: dict[str, str] = {}
        self._turn_contexts: dict[tuple[str, str], TurnContext] = {}

    def plan(self, request: RequestEnvelope) -> CodexTurnResult:
        deadline = time.monotonic() + self._timeout_seconds
        active = ActiveRequest(
            request_id=request.requestId,
            conversation_id=request.session.conversationId,
            client_turn_id=request.session.turnId,
        )
        self._active_requests[request.requestId] = active
        try:
            with self._lock:
                self._ensure_initialized(deadline)
                thread_id = self._get_or_create_thread(
                    request.session.conversationId, deadline
                )
                active.thread_id = thread_id
                return self._run_turn(thread_id, request, deadline, active)
        finally:
            self._active_requests.pop(request.requestId, None)

    def _ensure_initialized(self, deadline: float) -> None:
        if self._process and self._process.poll() is not None:
            self._reset_process()
        if not self._process:
            self._start_process()
        if self._initialized:
            return
        response = self._send_request(
            "initialize",
            {
                "clientInfo": {
                    "name": "vkdtAgent",
                    "title": "vkdt Agent",
                    "version": "0.1.0",
                },
                "capabilities": {
                    "experimentalApi": True,
                    "optOutNotificationMethods": [],
                },
            },
            deadline,
        )
        if "result" not in response:
            raise CodexAppServerError(
                "codex_initialize_failed", "Codex initialize failed"
            )
        self._send_notification("initialized")
        self._initialized = True

    def _start_process(self) -> None:
        try:
            self._process = subprocess.Popen(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=self._cwd,
            )
        except OSError as exc:
            raise CodexAppServerError(
                "codex_process_start_failed",
                f"Failed to launch Codex app server: {exc}",
                status_code=503,
            ) from exc

    def _reset_process(self) -> None:
        if self._process:
            try:
                self._process.kill()
            except OSError:
                pass
            try:
                self._process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        self._process = None
        self._initialized = False
        self._next_request_id = 1
        self._conversation_threads.clear()
        self._turn_contexts.clear()

    def _send_notification(self, method: str, params: object | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self._send_json(payload)

    def _send_request(
        self,
        method: str,
        params: object,
        deadline: float,
    ) -> dict[str, Any]:
        request_id = self._next_request_id
        self._next_request_id += 1
        self._send_json(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        while True:
            message = self._read_message(deadline)
            if message.get("id") == request_id and "method" not in message:
                error = message.get("error")
                if isinstance(error, dict):
                    raise CodexAppServerError(
                        "codex_jsonrpc_error",
                        str(error.get("message") or f"Codex {method} failed"),
                    )
                return message
            self._handle_message(message, None)

    def _send_json(self, payload: dict[str, Any]) -> None:
        if not self._process or not self._process.stdin:
            raise CodexAppServerError(
                "codex_process_unavailable", "Codex app server is not running"
            )
        self._process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self._process.stdin.flush()

    def _read_message(
        self, deadline: float, *, max_wait_seconds: float | None = None
    ) -> dict[str, Any]:
        if not self._process or not self._process.stdout or not self._process.stderr:
            raise CodexAppServerError(
                "codex_process_unavailable", "Codex app server is not running"
            )
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CodexAppServerError(
                    "codex_timeout", "Codex app server timed out", status_code=504
                )
            ready, _, _ = select.select(
                [self._process.stdout, self._process.stderr],
                [],
                [],
                min(remaining, 0.5 if max_wait_seconds is None else max_wait_seconds),
            )
            if not ready:
                if max_wait_seconds is not None:
                    return {}
                continue
            for stream in ready:
                line = stream.readline()
                if not line:
                    continue
                if stream is self._process.stderr:
                    logger.warning(line.rstrip())
                    continue
                payload = json.loads(line)
                if isinstance(payload, dict):
                    return cast(dict[str, Any], payload)

    def _get_or_create_thread(self, conversation_id: str, deadline: float) -> str:
        existing = self._conversation_threads.get(conversation_id)
        if existing:
            return existing
        response = self._send_request(
            "thread/start",
            {
                "cwd": self._cwd,
                "approvalPolicy": "never",
                "sandbox": "read-only",
                "personality": "pragmatic",
                "developerInstructions": THREAD_INSTRUCTIONS,
                "dynamicTools": self._dynamic_tools(),
                "model": "gpt-5.4",
            },
            deadline,
        )
        result = cast(dict[str, Any], response.get("result") or {})
        thread = cast(dict[str, Any], result.get("thread") or {})
        thread_id = thread.get("id")
        if not isinstance(thread_id, str) or not thread_id:
            raise CodexAppServerError(
                "codex_thread_start_failed", "Codex did not return a thread id"
            )
        self._conversation_threads[conversation_id] = thread_id
        return thread_id

    def _run_turn(
        self,
        thread_id: str,
        request: RequestEnvelope,
        deadline: float,
        active: ActiveRequest,
    ) -> CodexTurnResult:
        session = VkdtSession.create(request)
        turn_input = self._build_turn_input(request, session)
        response = self._send_request(
            "turn/start",
            {
                "threadId": thread_id,
                "input": turn_input,
                "outputSchema": _build_output_schema(),
                "approvalPolicy": "never",
                "personality": "pragmatic",
                "effort": "high",
                "model": "gpt-5.4",
            },
            deadline,
        )
        result = cast(dict[str, Any], response.get("result") or {})
        turn = cast(dict[str, Any], result.get("turn") or {})
        turn_id = turn.get("id")
        if not isinstance(turn_id, str) or not turn_id:
            raise CodexAppServerError(
                "codex_turn_start_failed", "Codex did not return a turn id"
            )
        active.turn_id = turn_id
        context = TurnContext(
            request=request,
            session=session,
            preview_data_url=self._preview_data_url(session.preview),
        )
        self._turn_contexts[(thread_id, turn_id)] = context
        state: dict[str, Any] = {
            "thread_id": thread_id,
            "turn_id": turn_id,
            "chunks": [],
            "final_message": None,
            "completed": False,
            "turn_error": None,
        }
        try:
            while not state["completed"]:
                message = self._read_message(deadline, max_wait_seconds=0.5)
                if not message:
                    if context.completed_plan is not None:
                        state["final_message"] = (
                            context.completed_plan.model_dump_json()
                        )
                        state["completed"] = True
                    continue
                self._handle_message(message, state)
                if context.completed_plan is not None:
                    state["final_message"] = context.completed_plan.model_dump_json()
                    state["completed"] = True
            if state["turn_error"]:
                raise CodexAppServerError("codex_turn_failed", state["turn_error"])
            raw_message = state["final_message"] or "".join(state["chunks"]).strip()
            if not raw_message:
                raise CodexAppServerError(
                    "codex_empty_response", "Codex completed without returning a plan"
                )
            plan = AgentPlan.model_validate_json(raw_message)
            return CodexTurnResult(
                plan=plan, thread_id=thread_id, turn_id=turn_id, raw_message=raw_message
            )
        finally:
            self._turn_contexts.pop((thread_id, turn_id), None)

    @staticmethod
    def _preview_data_url(preview: object | None) -> str:
        if preview is None:
            return ""
        from shared.protocol import PreviewImage

        if isinstance(preview, PreviewImage):
            return f"data:{preview.mimeType};base64,{preview.base64Data}"
        return ""

    def _build_turn_input(
        self, request: RequestEnvelope, session: VkdtSession
    ) -> list[dict[str, str]]:
        workflow = session.workflow_state()
        payload = {
            "requestId": request.requestId,
            "conversationId": request.session.conversationId,
            "turnId": request.session.turnId,
            "imagePath": request.workspace.imagePath,
            "message": request.message.text,
            "graphPath": workflow.graphPath,
            "workflow": workflow.model_dump(mode="json"),
        }
        items = [{"type": "text", "text": json.dumps(payload, separators=(",", ":"))}]
        if workflow.preview is not None:
            items.append(
                {"type": "image", "url": self._preview_data_url(workflow.preview)}
            )
        return items

    def _dynamic_tools(self) -> list[dict[str, Any]]:
        empty_object = {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
        return [
            {
                "name": "get_workflow_state",
                "description": (
                    "Get the current vkdt graph, module summary, connections, "
                    "preview metadata, and export artifacts."
                ),
                "inputSchema": empty_object,
            },
            {
                "name": "get_preview_image",
                "description": "Get the current rendered preview image as a data URL.",
                "inputSchema": empty_object,
            },
            {
                "name": "get_module_catalog",
                "description": (
                    "Get the built-in vkdt module catalog for core editing workflows."
                ),
                "inputSchema": empty_object,
            },
            {
                "name": "get_playbook",
                "description": "Fetch one vkdt editing playbook by id.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "playbookId": {"type": "string", "enum": playbook_ids()}
                    },
                    "required": ["playbookId"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "apply_graph_edits",
                "description": (
                    "Apply vkdt graph edits, validate the graph, render a "
                    "refreshed preview, and return the updated workflow state."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "edits": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "object"},
                        }
                    },
                    "required": ["edits"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "render_export",
                "description": (
                    "Render a final export through vkdt-cli and return the "
                    "produced artifact path."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "format": {"type": "string"},
                        "filename": {"type": "string"},
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                        "quality": {"type": "number"},
                        "output": {"type": "string"},
                        "lastFrameOnly": {"type": "boolean"},
                    },
                    "required": ["format", "filename"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "end",
                "description": (
                    "Finish the live run and record the final assistant message."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {"message": {"type": "string", "minLength": 1}},
                    "required": ["message"],
                    "additionalProperties": False,
                },
            },
        ]

    def _handle_message(
        self, message: dict[str, Any], state: dict[str, Any] | None
    ) -> None:
        if "method" in message and "id" in message:
            self._handle_server_request(message)
            return
        method = message.get("method")
        if not isinstance(method, str) or state is None:
            return
        params = cast(dict[str, Any], message.get("params") or {})
        if method == "item/agentMessage/delta":
            if (
                params.get("threadId") == state["thread_id"]
                and params.get("turnId") == state["turn_id"]
            ):
                delta = params.get("delta")
                if isinstance(delta, str):
                    state["chunks"].append(delta)
            return
        if method == "item/completed":
            if (
                params.get("threadId") != state["thread_id"]
                or params.get("turnId") != state["turn_id"]
            ):
                return
            item = cast(dict[str, Any], params.get("item") or {})
            if item.get("type") == "agentMessage":
                text = item.get("text")
                if isinstance(text, str):
                    state["final_message"] = text
                if item.get("phase") == "final_answer":
                    state["completed"] = True
            return
        if method == "turn/completed":
            if params.get("threadId") != state["thread_id"]:
                return
            turn = cast(dict[str, Any], params.get("turn") or {})
            if turn.get("id") != state["turn_id"]:
                return
            error = (
                cast(dict[str, Any], turn.get("error") or {})
                if isinstance(turn.get("error"), dict)
                else {}
            )
            if error:
                state["turn_error"] = str(error.get("message") or "Codex turn failed")
            state["completed"] = True

    def _handle_server_request(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        method = message.get("method")
        if request_id is None or not isinstance(method, str):
            return
        if method in {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
            "item/permissions/requestApproval",
            "applyPatchApproval",
            "execCommandApproval",
        }:
            self._send_json(
                {"jsonrpc": "2.0", "id": request_id, "result": {"decision": "decline"}}
            )
            return
        if method != "item/tool/call":
            self._send_json(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": f"Unsupported request: {method}",
                    },
                }
            )
            return
        params = cast(dict[str, Any], message.get("params") or {})
        thread_id = params.get("threadId")
        turn_id = params.get("turnId")
        tool = params.get("tool")
        arguments = cast(dict[str, Any], params.get("arguments") or {})
        context = (
            self._turn_contexts.get((thread_id, turn_id))
            if isinstance(thread_id, str) and isinstance(turn_id, str)
            else None
        )
        if context is None or not isinstance(tool, str):
            self._send_json(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": self._tool_error("No active turn context is available."),
                }
            )
            return
        if tool == "get_workflow_state":
            payload = {
                "success": True,
                "contentItems": [
                    {
                        "type": "inputText",
                        "text": context.session.workflow_state().model_dump_json(),
                    }
                ],
            }
        elif tool == "get_preview_image":
            payload = {
                "success": True,
                "contentItems": [
                    {
                        "type": "inputImage",
                        "imageUrl": self._preview_data_url(context.session.preview),
                    }
                ],
            }
        elif tool == "get_module_catalog":
            payload = {
                "success": True,
                "contentItems": [
                    {
                        "type": "inputText",
                        "text": json.dumps(module_catalog(), separators=(",", ":")),
                    }
                ],
            }
        elif tool == "get_playbook":
            playbook_id = arguments.get("playbookId")
            if not isinstance(playbook_id, str):
                payload = self._tool_error("get_playbook requires a playbookId string.")
            else:
                payload = {
                    "success": True,
                    "contentItems": [
                        {
                            "type": "inputText",
                            "text": json.dumps(
                                get_playbook(playbook_id), separators=(",", ":")
                            ),
                        }
                    ],
                }
        elif tool == "apply_graph_edits":
            try:
                raw_edits = arguments.get("edits")
                if not isinstance(raw_edits, list):
                    raise ValueError("apply_graph_edits requires an edits array")
                edits = [GraphEdit.model_validate(item) for item in raw_edits]
                applied = context.session.apply_edits(edits)
                context.operations.extend(applied)
                payload = {
                    "success": True,
                    "contentItems": [
                        {
                            "type": "inputText",
                            "text": (
                                f"Applied {len(applied)} graph edits and "
                                "rendered a refreshed preview."
                            ),
                        },
                        {
                            "type": "inputImage",
                            "imageUrl": self._preview_data_url(context.session.preview),
                        },
                        {
                            "type": "inputText",
                            "text": context.session.workflow_state().model_dump_json(),
                        },
                    ],
                }
            except Exception as exc:
                payload = self._tool_error(str(exc))
        elif tool == "render_export":
            try:
                export = ExportRequest.model_validate(arguments)
                artifact = context.session.render_export(export)
                payload = {
                    "success": True,
                    "contentItems": [
                        {
                            "type": "inputText",
                            "text": json.dumps(
                                artifact.model_dump(mode="json"), separators=(",", ":")
                            ),
                        }
                    ],
                }
            except Exception as exc:
                payload = self._tool_error(str(exc))
        elif tool == "end":
            message_text = arguments.get("message")
            if not isinstance(message_text, str) or not message_text.strip():
                payload = self._tool_error("end requires a non-empty message string.")
            else:
                context.completed_plan = AgentPlan(
                    assistantText=message_text.strip(),
                    continueRefining=False,
                    operations=[
                        GraphEdit.model_validate(item) for item in context.operations
                    ],
                    workflow=context.session.workflow_state(),
                )
                payload = {
                    "success": True,
                    "contentItems": [{"type": "inputText", "text": "Run completed."}],
                }
        else:
            payload = self._tool_error(f"Unsupported tool '{tool}'.")
        self._send_json({"jsonrpc": "2.0", "id": request_id, "result": payload})

    @staticmethod
    def _tool_error(message: str) -> dict[str, Any]:
        return {
            "success": False,
            "contentItems": [{"type": "inputText", "text": message}],
        }
