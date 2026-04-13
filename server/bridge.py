from __future__ import annotations

import base64
import json
import logging
import select
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from shared.protocol import AgentPlan, GraphOperation, RequestEnvelope

from .vkdt_catalog import get_playbook, module_catalog, playbook_ids

logger = logging.getLogger("vkdt_agent.codex")

THREAD_INSTRUCTIONS = """You are vkdtAgent, an expert RAW photo editor
operating the native vkdt UI through a bounded app bridge.

Core rules:
- The running vkdt app is the source of truth.
- This is always a live multi-turn edit loop.
- Use only these tools: get_image_state, get_preview_image, get_playbook,
  apply_operations, end.
- Never invent state that is not present in the latest image state or preview.
- Prefer concrete operations against surfaced actionPath values or explicit
  graph actions.
- After apply_operations, wait for the refreshed native preview/state before
  continuing.
- Finish by calling end with a concise user-facing summary.

Return exactly one JSON object matching the output schema after tool calls."""


class CodexAppServerError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class CancelRequestKey:
    request_id: str
    app_session_id: str
    image_session_id: str
    conversation_id: str
    turn_id: str


@dataclass(slots=True)
class ActiveRequest:
    request_id: str
    app_session_id: str
    image_session_id: str
    conversation_id: str
    client_turn_id: str
    cancel_event: threading.Event = field(default_factory=threading.Event)
    cancel_reason: str | None = None
    thread_id: str | None = None
    codex_turn_id: str | None = None
    status: str = "queued"
    message: str = "Request accepted"
    last_tool_name: str | None = None
    progress_version: int = 0

    @property
    def cancel_key(self) -> CancelRequestKey:
        return CancelRequestKey(
            request_id=self.request_id,
            app_session_id=self.app_session_id,
            image_session_id=self.image_session_id,
            conversation_id=self.conversation_id,
            turn_id=self.client_turn_id,
        )


@dataclass(slots=True)
class TurnContext:
    request: RequestEnvelope
    state_payload: dict[str, object]
    preview_data_url: str | None
    max_tool_calls: int = 12
    tool_calls_used: int = 0
    applied_operations: list[dict[str, object]] = field(default_factory=list)
    render_event: threading.Event = field(default_factory=threading.Event)
    rendered_preview_bytes: bytes | None = None
    requires_render_callback: bool = False
    completed_plan: AgentPlan | None = None


@dataclass(slots=True)
class CodexTurnResult:
    plan: AgentPlan
    thread_id: str
    turn_id: str
    raw_message: str


def _data_url(image_bytes: bytes, mime_type: str, *, revision_token: str) -> str:
    encoded = base64.b64encode(image_bytes).decode()
    return f"data:{mime_type};revision={revision_token};base64,{encoded}"


def _build_state_payload(request: RequestEnvelope) -> dict[str, object]:
    return {
        "uiContext": request.uiContext.model_dump(mode="json"),
        "capabilityManifest": request.capabilityManifest.model_dump(mode="json"),
        "imageSnapshot": request.imageSnapshot.model_dump(mode="json"),
        "moduleCatalog": module_catalog(),
    }


def _build_output_schema() -> dict[str, object]:
    return cast(dict[str, object], AgentPlan.model_json_schema())


class CodexAppServerBridge:
    def __init__(
        self,
        *,
        command: list[str] | None = None,
        cwd: Path | None = None,
        timeout_seconds: float = 600.0,
    ) -> None:
        if command is None:
            import os

            configured_env = os.environ.get("VKDT_AGENT_CODEX_APP_SERVER_CMD")
            command = (
                shlex.split(configured_env)
                if configured_env
                else ["codex", "app-server", "--listen", "stdio://"]
            )
        self._command = list(command)
        self._cwd = str((cwd or Path(__file__).resolve().parent.parent).resolve())
        self._timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._initialized = False
        self._next_request_id = 1
        self._conversation_threads: dict[str, str] = {}
        self._active_requests: dict[str, ActiveRequest] = {}
        self._cancelled_requests: dict[CancelRequestKey, str] = {}
        self._turn_contexts: dict[tuple[str, str], TurnContext] = {}

    def plan(self, request: RequestEnvelope) -> CodexTurnResult:
        deadline = time.monotonic() + self._timeout_seconds
        active = self._register_request(request)
        try:
            with self._lock:
                self._set_active_request_status_locked(
                    request.requestId,
                    status="initializing",
                    message="Initializing Codex app server",
                )
                self._ensure_initialized(deadline)
                thread_id = self._get_or_create_thread(
                    request.session.conversationId, deadline
                )
                active.thread_id = thread_id
                self._set_active_request_status_locked(
                    request.requestId,
                    status="starting-turn",
                    message="Starting Codex turn",
                )
                return self._run_turn(thread_id, request, deadline, active)
        finally:
            self._unregister_request(request.requestId)

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
        cancel_key = CancelRequestKey(
            request_id=request_id,
            app_session_id=app_session_id,
            image_session_id=image_session_id,
            conversation_id=conversation_id,
            turn_id=turn_id,
        )
        matched = False
        with self._state_lock:
            self._cancelled_requests[cancel_key] = reason or "Chat request was canceled"
            active = self._active_requests.get(request_id)
            if active and active.cancel_key == cancel_key:
                active.cancel_event.set()
                active.cancel_reason = reason
                active.status = "cancel-requested"
                active.message = reason or "Cancellation requested"
                matched = True
        return matched

    def get_request_progress(
        self,
        *,
        request_id: str,
        app_session_id: str,
        image_session_id: str,
        conversation_id: str,
        turn_id: str,
    ) -> dict[str, object]:
        with self._state_lock:
            active = self._active_requests.get(request_id)
            if active is None:
                return {
                    "found": False,
                    "status": "not_found",
                    "toolCallsUsed": 0,
                    "maxToolCalls": 0,
                    "appliedOperationCount": 0,
                    "operations": [],
                    "latestOperation": None,
                    "message": "No active request found for that requestId.",
                    "lastToolName": None,
                    "progressVersion": 0,
                    "requiresRenderCallback": False,
                }
            if (
                active.app_session_id != app_session_id
                or active.image_session_id != image_session_id
                or active.conversation_id != conversation_id
                or active.client_turn_id != turn_id
            ):
                return {
                    "found": False,
                    "status": "not_found",
                    "toolCallsUsed": 0,
                    "maxToolCalls": 0,
                    "appliedOperationCount": 0,
                    "operations": [],
                    "latestOperation": None,
                    "message": (
                        "No active request matched the provided session identifiers."
                    ),
                    "lastToolName": None,
                    "progressVersion": 0,
                    "requiresRenderCallback": False,
                }
            context = None
            if active.thread_id and active.codex_turn_id:
                context = self._turn_contexts.get(
                    (active.thread_id, active.codex_turn_id)
                )
            operations = list(context.applied_operations) if context else []
            return {
                "found": True,
                "status": active.status,
                "toolCallsUsed": context.tool_calls_used if context else 0,
                "maxToolCalls": context.max_tool_calls if context else 0,
                "appliedOperationCount": len(operations),
                "operations": operations,
                "latestOperation": operations[-1] if operations else None,
                "message": active.message,
                "lastToolName": active.last_tool_name,
                "progressVersion": active.progress_version,
                "requiresRenderCallback": context.requires_render_callback
                if context
                else False,
            }

    def provide_render_callback(
        self,
        *,
        image_session_id: str,
        turn_id: str,
        image_bytes: bytes,
    ) -> bool:
        with self._state_lock:
            for active in self._active_requests.values():
                if (
                    active.image_session_id == image_session_id
                    and active.client_turn_id == turn_id
                    and active.thread_id
                    and active.codex_turn_id
                ):
                    context = self._turn_contexts.get(
                        (active.thread_id, active.codex_turn_id)
                    )
                    if context is None:
                        return False
                    context.rendered_preview_bytes = image_bytes
                    context.render_event.set()
                    context.requires_render_callback = False
                    active.progress_version += 1
                    active.message = "Received refreshed native preview"
                    return True
        return False

    def _register_request(self, request: RequestEnvelope) -> ActiveRequest:
        active = ActiveRequest(
            request_id=request.requestId,
            app_session_id=request.session.appSessionId,
            image_session_id=request.session.imageSessionId,
            conversation_id=request.session.conversationId,
            client_turn_id=request.session.turnId,
        )
        with self._state_lock:
            self._active_requests[request.requestId] = active
            cancel_reason = self._cancelled_requests.get(active.cancel_key)
            if cancel_reason:
                active.cancel_event.set()
                active.cancel_reason = cancel_reason
        return active

    def _unregister_request(self, request_id: str) -> None:
        with self._state_lock:
            active = self._active_requests.pop(request_id, None)
            if active is not None:
                self._cancelled_requests.pop(active.cancel_key, None)

    def _raise_if_cancelled_locked(self, active: ActiveRequest | None) -> None:
        if active is None:
            return
        with self._state_lock:
            cancelled = active.cancel_event.is_set()
        if not cancelled:
            return
        self._set_active_request_status_locked(
            active.request_id,
            status="cancelled",
            message=active.cancel_reason or "Chat request was canceled",
        )
        self._reset_process_locked()
        raise CodexAppServerError(
            "request_cancelled",
            active.cancel_reason or "Chat request was canceled",
            status_code=499,
        )

    def _set_active_request_status_locked(
        self,
        request_id: str,
        *,
        status: str,
        message: str,
        last_tool_name: str | None = None,
    ) -> None:
        with self._state_lock:
            active = self._active_requests.get(request_id)
            if active is None:
                return
            active.status = status
            active.message = message
            if last_tool_name is not None:
                active.last_tool_name = last_tool_name
            active.progress_version += 1

    def _ensure_initialized(self, deadline: float) -> None:
        if self._process and self._process.poll() is not None:
            self._reset_process_locked()
        if not self._process:
            self._start_process_locked()
        if self._initialized:
            return
        response = self._send_request(
            "initialize",
            {
                "clientInfo": {
                    "name": "vkdtAgent",
                    "title": "vkdt Agent",
                    "version": "0.2.0",
                },
                "capabilities": {
                    "experimentalApi": True,
                    "optOutNotificationMethods": [],
                },
            },
            deadline,
            None,
        )
        if "result" not in response:
            raise CodexAppServerError(
                "codex_initialize_failed", "Codex initialize failed"
            )
        self._send_notification("initialized")
        self._initialized = True

    def _start_process_locked(self) -> None:
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

    def _reset_process_locked(self) -> None:
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
        payload: dict[str, object] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self._send_json(payload)

    def _send_request(
        self,
        method: str,
        params: object,
        deadline: float,
        active: ActiveRequest | None,
    ) -> dict[str, object]:
        request_id = self._next_request_id
        self._next_request_id += 1
        self._send_json(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        while True:
            self._raise_if_cancelled_locked(active)
            message = self._read_message(deadline, active)
            if message.get("id") == request_id and "method" not in message:
                error = message.get("error")
                if isinstance(error, dict):
                    error_dict = cast(dict[str, object], error)
                    raise CodexAppServerError(
                        "codex_jsonrpc_error",
                        str(error_dict.get("message") or f"Codex {method} failed"),
                    )
                return message
            self._handle_message(message, None)

    def _send_json(self, payload: dict[str, object]) -> None:
        if not self._process or not self._process.stdin:
            raise CodexAppServerError(
                "codex_process_unavailable", "Codex app server is not running"
            )
        self._process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self._process.stdin.flush()

    def _read_message(
        self,
        deadline: float,
        active: ActiveRequest | None,
        *,
        max_wait_seconds: float | None = None,
    ) -> dict[str, object]:
        if not self._process or not self._process.stdout or not self._process.stderr:
            raise CodexAppServerError(
                "codex_process_unavailable", "Codex app server is not running"
            )
        while True:
            self._raise_if_cancelled_locked(active)
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
                    return cast(dict[str, object], payload)

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
            None,
        )
        result = cast(dict[str, object], response.get("result") or {})
        thread = cast(dict[str, object], result.get("thread") or {})
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
        preview = request.imageSnapshot.preview
        preview_data_url = (
            f"data:{preview.mimeType};base64,{preview.base64Data}" if preview else None
        )
        turn_input: list[dict[str, str]] = [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "requestId": request.requestId,
                        "message": request.message.text,
                        "state": _build_state_payload(request),
                    },
                    separators=(",", ":"),
                ),
            }
        ]
        if preview_data_url:
            turn_input.append({"type": "image", "url": preview_data_url})
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
            active,
        )
        result = cast(dict[str, object], response.get("result") or {})
        turn = cast(dict[str, object], result.get("turn") or {})
        turn_id = turn.get("id")
        if not isinstance(turn_id, str) or not turn_id:
            raise CodexAppServerError(
                "codex_turn_start_failed", "Codex did not return a turn id"
            )
        active.codex_turn_id = turn_id
        context = TurnContext(
            request=request,
            state_payload=_build_state_payload(request),
            preview_data_url=preview_data_url,
        )
        self._turn_contexts[(thread_id, turn_id)] = context
        self._set_active_request_status_locked(
            active.request_id,
            status="running",
            message="Waiting for Codex turn output",
        )
        state: dict[str, object] = {
            "thread_id": thread_id,
            "turn_id": turn_id,
            "chunks": [],
            "final_message": None,
            "completed": False,
            "turn_error": None,
        }
        try:
            while not bool(state["completed"]):
                message = self._read_message(deadline, active, max_wait_seconds=0.5)
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
            turn_error = state["turn_error"]
            if isinstance(turn_error, str) and turn_error:
                raise CodexAppServerError("codex_turn_failed", turn_error)
            raw_message = state["final_message"] or "".join(
                cast(list[str], state["chunks"])
            )
            if not raw_message:
                raise CodexAppServerError(
                    "codex_empty_response", "Codex completed without returning a plan"
                )
            plan = AgentPlan.model_validate_json(cast(str, raw_message))
            return CodexTurnResult(
                plan=plan, thread_id=thread_id, turn_id=turn_id, raw_message=raw_message
            )
        finally:
            self._turn_contexts.pop((thread_id, turn_id), None)
            active.codex_turn_id = None

    @staticmethod
    def _dynamic_tools() -> list[dict[str, object]]:
        empty = {"type": "object", "properties": {}, "additionalProperties": False}
        return [
            {
                "name": "get_image_state",
                "description": (
                    "Get the latest native vkdt image state, editable "
                    "controls, graph summary, and surfaced adjustment modules."
                ),
                "inputSchema": empty,
            },
            {
                "name": "get_preview_image",
                "description": "Get the latest native vkdt preview as a data URL.",
                "inputSchema": empty,
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
                "name": "apply_operations",
                "description": (
                    "Send native vkdt operations to the app, wait for "
                    "refreshed preview/state, and continue once the UI render "
                    "callback arrives."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "operations": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "object"},
                        }
                    },
                    "required": ["operations"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "end",
                "description": (
                    "Finish the native live run with the final assistant message."
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
        self, message: dict[str, object], state: dict[str, object] | None
    ) -> None:
        if "method" in message and "id" in message:
            self._handle_server_request(message)
            return
        method = message.get("method")
        if not isinstance(method, str) or state is None:
            return
        params = cast(dict[str, object], message.get("params") or {})
        if method == "item/agentMessage/delta":
            if (
                params.get("threadId") == state["thread_id"]
                and params.get("turnId") == state["turn_id"]
            ):
                delta = params.get("delta")
                if isinstance(delta, str):
                    cast(list[str], state["chunks"]).append(delta)
            return
        if method == "item/completed":
            if (
                params.get("threadId") != state["thread_id"]
                or params.get("turnId") != state["turn_id"]
            ):
                return
            item = cast(dict[str, object], params.get("item") or {})
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
            turn = cast(dict[str, object], params.get("turn") or {})
            if turn.get("id") != state["turn_id"]:
                return
            error = turn.get("error")
            if isinstance(error, dict):
                error_dict = cast(dict[str, object], error)
                state["turn_error"] = str(
                    error_dict.get("message") or "Codex turn failed"
                )
            state["completed"] = True

    def _handle_server_request(self, message: dict[str, object]) -> None:
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
        params = cast(dict[str, object], message.get("params") or {})
        thread_id = params.get("threadId")
        turn_id = params.get("turnId")
        tool = params.get("tool")
        arguments = cast(dict[str, object], params.get("arguments") or {})
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
        response = self._handle_dynamic_tool_call(context, tool, arguments)
        self._send_json({"jsonrpc": "2.0", "id": request_id, "result": response})

    def _handle_dynamic_tool_call(
        self,
        context: TurnContext,
        tool: str,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        context.tool_calls_used += 1
        self._set_active_request_status_locked(
            context.request.requestId,
            status="running",
            message=f"Handling tool {tool}",
            last_tool_name=tool,
        )
        if tool == "get_image_state":
            return {
                "success": True,
                "contentItems": [
                    {
                        "type": "inputText",
                        "text": json.dumps(
                            context.state_payload, separators=(",", ":")
                        ),
                    }
                ],
            }
        if tool == "get_preview_image":
            if context.preview_data_url is None:
                return self._tool_error("No preview image is available yet.")
            return {
                "success": True,
                "contentItems": [
                    {"type": "inputImage", "imageUrl": context.preview_data_url}
                ],
            }
        if tool == "get_playbook":
            playbook_id = arguments.get("playbookId")
            if not isinstance(playbook_id, str):
                return self._tool_error("get_playbook requires a playbookId string.")
            try:
                playbook = get_playbook(playbook_id)
            except ValueError as exc:
                return self._tool_error(str(exc))
            return {
                "success": True,
                "contentItems": [
                    {
                        "type": "inputText",
                        "text": json.dumps(playbook, separators=(",", ":")),
                    }
                ],
            }
        if tool == "apply_operations":
            raw_operations = arguments.get("operations")
            if not isinstance(raw_operations, list):
                return self._tool_error(
                    "apply_operations requires an operations array."
                )
            try:
                operations = [
                    GraphOperation.model_validate(item) for item in raw_operations
                ]
            except Exception as exc:
                return self._tool_error(str(exc))
            context.applied_operations.extend(
                op.model_dump(mode="json") for op in operations
            )
            context.render_event.clear()
            context.requires_render_callback = True
            self._set_active_request_status_locked(
                context.request.requestId,
                status="waiting-render",
                message="Waiting for the native vkdt preview refresh",
                last_tool_name=tool,
            )
            render_arrived = context.render_event.wait(timeout=15.0)
            if not render_arrived or context.rendered_preview_bytes is None:
                context.requires_render_callback = False
                return self._tool_error(
                    "Timed out waiting for the native vkdt render callback."
                )
            context.preview_data_url = _data_url(
                context.rendered_preview_bytes,
                "image/jpeg",
                revision_token=str(len(context.applied_operations)),
            )
            context.state_payload["renderRevision"] = len(context.applied_operations)
            return {
                "success": True,
                "contentItems": [
                    {
                        "type": "inputText",
                        "text": (
                            f"Applied {len(operations)} native operations and "
                            "received a refreshed preview."
                        ),
                    },
                    {"type": "inputImage", "imageUrl": context.preview_data_url},
                    {
                        "type": "inputText",
                        "text": json.dumps(
                            context.state_payload, separators=(",", ":")
                        ),
                    },
                ],
            }
        if tool == "end":
            message = arguments.get("message")
            if not isinstance(message, str) or not message.strip():
                return self._tool_error("end requires a non-empty message string.")
            context.completed_plan = AgentPlan(
                assistantText=message.strip(),
                continueRefining=False,
                operations=[
                    GraphOperation.model_validate(item)
                    for item in context.applied_operations
                ],
            )
            return {
                "success": True,
                "contentItems": [{"type": "inputText", "text": "Run completed."}],
            }
        return self._tool_error(f"Unsupported tool '{tool}'.")

    @staticmethod
    def _tool_error(message: str) -> dict[str, object]:
        return {
            "success": False,
            "contentItems": [{"type": "inputText", "text": message}],
        }
