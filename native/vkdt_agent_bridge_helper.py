from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from http.client import HTTPConnection
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from native.vkdt_graph import (
    action_path,
    history_payload,
    modules_payload,
    parse_graph_text,
)
from server.vkdt_catalog import adjustment_surfaces, module_catalog
from shared.protocol import (
    Capability,
    CapabilityManifest,
    EditableSetting,
    GraphOperation,
    ImageSnapshot,
    PreviewImage,
    RefinementRequest,
    RequestEnvelope,
    RequestSession,
    UIContext,
    UserMessage,
)


@dataclass(slots=True)
class TurnMeta:
    app_session_id: str
    image_session_id: str
    conversation_id: str
    turn_id: str
    view: str
    image_name: str
    image_id: int | None
    graph_path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-dir", required=True)
    parser.add_argument(
        "--backend-host", default=os.environ.get("VKDT_AGENT_BACKEND_HOST", "127.0.0.1")
    )
    parser.add_argument(
        "--backend-port",
        type=int,
        default=int(os.environ.get("VKDT_AGENT_BACKEND_PORT", "4000")),
    )
    parser.add_argument(
        "--vkdt-cli", default=os.environ.get("VKDT_AGENT_VKDT_CLI", "vkdt-cli")
    )
    parser.add_argument("--preview-width", type=int, default=1024)
    parser.add_argument("--preview-height", type=int, default=1024)
    parser.add_argument("--poll-interval", type=float, default=0.2)
    return parser.parse_args()


def read_meta(path: Path) -> TurnMeta:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    image_id_text = values.get("image_id", "")
    image_id = int(image_id_text) if image_id_text else None
    return TurnMeta(
        app_session_id=values["app_session_id"],
        image_session_id=values["image_session_id"],
        conversation_id=values["conversation_id"],
        turn_id=values["turn_id"],
        view=values.get("view", "darkroom"),
        image_name=values.get("image_name", values["graph_path"]),
        image_id=image_id,
        graph_path=Path(values["graph_path"]),
    )


def read_graph_text(graph_path: Path) -> str:
    return graph_path.read_text()


def try_render_preview(
    *,
    vkdt_cli: str,
    graph_path: Path,
    preview_dir: Path,
    width: int,
    height: int,
) -> PreviewImage | None:
    preview_dir.mkdir(parents=True, exist_ok=True)
    output_base = preview_dir / "preview"
    jpg_path = preview_dir / "preview.jpg"
    if jpg_path.exists():
        jpg_path.unlink()
    command = [
        vkdt_cli,
        "-g",
        str(graph_path),
        "--format",
        "o-jpg",
        "--filename",
        str(output_base),
        "--width",
        str(width),
        "--height",
        str(height),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except Exception:
        return None
    if not jpg_path.exists():
        return None
    return PreviewImage(
        previewId=f"preview-{uuid4().hex[:8]}",
        mimeType="image/jpeg",
        width=width,
        height=height,
        base64Data=base64.b64encode(jpg_path.read_bytes()).decode(),
    )


def build_controls(
    graph_text: str,
) -> tuple[CapabilityManifest, list[EditableSetting], list[dict[str, object]]]:
    parsed = parse_graph_text(graph_text)
    spec_map = {entry["name"]: entry for entry in module_catalog()}
    targets: list[Capability] = []
    editable: list[EditableSetting] = []
    present_modules = modules_payload(parsed)
    for module in parsed.modules:
        spec = spec_map.get(module.name)
        if spec is None:
            continue
        for param_name in cast(tuple[str, ...], spec.get("params", ())):
            raw_value = module.params.get(param_name)
            if not raw_value or len(raw_value) != 1:
                continue
            try:
                current = float(raw_value[0])
            except ValueError:
                continue
            module_id = f"{module.name}:{module.instance}"
            capability_id = f"{module_id}.{param_name}"
            path = action_path(module.name, module.instance, param_name)
            targets.append(
                Capability(
                    moduleId=module_id,
                    moduleLabel=module.name,
                    capabilityId=capability_id,
                    label=param_name,
                    kind="set-float",
                    targetType="vkdt-action",
                    actionPath=path,
                    supportedModes=["delta", "set"],
                    minNumber=-10.0,
                    maxNumber=10.0,
                    defaultNumber=current,
                    stepNumber=0.1,
                )
            )
            editable.append(
                EditableSetting(
                    moduleId=module_id,
                    moduleLabel=module.name,
                    settingId=capability_id,
                    capabilityId=capability_id,
                    label=param_name,
                    actionPath=path,
                    kind="set-float",
                    supportedModes=["delta", "set"],
                    currentNumber=current,
                    minNumber=-10.0,
                    maxNumber=10.0,
                    defaultNumber=current,
                    stepNumber=0.1,
                )
            )
    if not targets:
        targets.append(
            Capability(
                moduleId="graph",
                moduleLabel="Graph",
                capabilityId="graph.exposure-fallback",
                label="Fallback Exposure",
                kind="set-float",
                targetType="vkdt-action",
                actionPath=f"module/colour:01/param/{quote('exposure', safe='')}",
                supportedModes=["delta", "set"],
                minNumber=-10.0,
                maxNumber=10.0,
                defaultNumber=0.0,
                stepNumber=0.1,
            )
        )
    return (
        CapabilityManifest(manifestVersion="1", targets=targets),
        editable,
        adjustment_surfaces(present_modules),
    )


def build_request(
    *,
    meta: TurnMeta,
    prompt_text: str,
    graph_text: str,
    preview: PreviewImage | None,
) -> RequestEnvelope:
    parsed = parse_graph_text(graph_text)
    capability_manifest, editable_settings, surfaces = build_controls(graph_text)
    return RequestEnvelope(
        requestId=f"req-{uuid4().hex[:10]}",
        session=RequestSession(
            appSessionId=meta.app_session_id,
            imageSessionId=meta.image_session_id,
            conversationId=meta.conversation_id,
            turnId=meta.turn_id,
        ),
        uiContext=UIContext(
            view=meta.view, imageId=meta.image_id, imageName=meta.image_name
        ),
        message=UserMessage(role="user", text=prompt_text),
        capabilityManifest=capability_manifest,
        imageSnapshot=ImageSnapshot(
            imageRevisionId=f"rev-{uuid4().hex[:8]}",
            graphPath=str(meta.graph_path),
            graphText=graph_text,
            moduleOrder=parsed.module_order,
            modules=modules_payload(parsed),
            connections=parsed.connections,
            adjustmentSurfaces=surfaces,
            editableSettings=editable_settings,
            history=history_payload(parsed),
            preview=preview,
        ),
        fast=False,
        refinement=RefinementRequest(
            mode="multi-turn",
            enabled=True,
            maxPasses=8,
            passIndex=1,
            goalText=prompt_text,
        ),
    )


def post_json(
    host: str,
    port: int,
    path: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> tuple[int, bytes]:
    connection = HTTPConnection(host, port, timeout=120)
    body = json.dumps(payload).encode()
    request_headers = {
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
    }
    if headers:
        request_headers.update(headers)
    connection.request("POST", path, body=body, headers=request_headers)
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response.status, data


def post_bytes(
    host: str, port: int, path: str, payload: bytes, headers: dict[str, str]
) -> tuple[int, bytes]:
    connection = HTTPConnection(host, port, timeout=120)
    request_headers = {
        "Content-Type": "image/jpeg",
        "Content-Length": str(len(payload)),
    }
    request_headers.update(headers)
    connection.request("POST", path, body=payload, headers=request_headers)
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response.status, data


def stream_chat(host: str, port: int, payload: dict[str, Any]):
    connection = HTTPConnection(host, port, timeout=120)
    body = json.dumps(payload).encode()
    connection.request(
        "POST",
        "/v1/chat/stream",
        body=body,
        headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
    )
    response = connection.getresponse()
    if response.status != 200:
        raise RuntimeError(response.read().decode())
    return connection, response


def parse_sse_events(response) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    current_event = "message"
    data_lines: list[str] = []
    while True:
        raw_line = response.fp.readline()
        if not raw_line:
            break
        line = raw_line.decode().rstrip("\n")
        if line.startswith("event: "):
            current_event = line[7:]
            continue
        if line.startswith("data: "):
            data_lines.append(line[6:])
            continue
        if line == "":
            if data_lines:
                events.append((current_event, json.loads("\n".join(data_lines))))
            current_event = "message"
            data_lines = []
    return events


def operation_lines(operations: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for operation in operations:
        op = GraphOperation.model_validate(operation)
        if op.kind in {"set-float", "set-bool", "set-choice"}:
            value = ""
            if op.kind == "set-float" and op.valueNumber is not None:
                value = str(op.valueNumber)
            elif op.kind == "set-bool" and op.valueBool is not None:
                value = "1" if op.valueBool else "0"
            elif op.kind == "set-choice" and op.valueChoiceId is not None:
                value = op.valueChoiceId
            lines.append(f"{op.kind}\t{op.actionPath}\t{op.mode or 'set'}\t{value}")
            continue
        payload = op.graphPayload or {}
        if op.actionPath == "graph/add-module":
            lines.append(
                "\t".join(
                    [
                        "graph-add-module",
                        str(payload.get("module", "")),
                        str(payload.get("instance", "01")),
                    ]
                )
            )
        elif op.actionPath == "graph/remove-module":
            lines.append(
                "\t".join(
                    [
                        "graph-remove-module",
                        str(payload.get("module", "")),
                        str(payload.get("instance", "01")),
                    ]
                )
            )
        elif op.actionPath == "graph/connect":
            lines.append(
                "\t".join(
                    [
                        "graph-connect",
                        str(payload.get("sourceModule", "")),
                        str(payload.get("sourceInstance", "")),
                        str(payload.get("sourceConnector", "")),
                        str(payload.get("targetModule", "")),
                        str(payload.get("targetInstance", "")),
                        str(payload.get("targetConnector", "")),
                    ]
                )
            )
        elif op.actionPath == "graph/disconnect":
            lines.append(
                "\t".join(
                    [
                        "graph-disconnect",
                        str(payload.get("targetModule", "")),
                        str(payload.get("targetInstance", "")),
                        str(payload.get("targetConnector", "")),
                    ]
                )
            )
        elif op.actionPath == "graph/activate-module":
            lines.append(
                "\t".join(
                    [
                        "graph-activate-module",
                        str(payload.get("module", "")),
                        str(payload.get("instance", "01")),
                    ]
                )
            )
        elif op.actionPath == "graph/set-param":
            path = action_path(
                str(payload.get("module", "")),
                str(payload.get("instance", "01")),
                str(payload.get("param", "")),
            )
            lines.append(
                "\t".join(
                    [
                        "set-float",
                        path,
                        str(payload.get("mode", "set")),
                        str(payload.get("valueNumber", 0)),
                    ]
                )
            )
    return lines


def write_text(path: Path, text: str) -> None:
    path.write_text(text)


def wait_for_file(path: Path, poll_interval: float) -> None:
    while not path.exists():
        time.sleep(poll_interval)


def handle_turn(turn_dir: Path, args: argparse.Namespace) -> None:
    meta = read_meta(turn_dir / "meta.txt")
    prompt_text = (turn_dir / "prompt.txt").read_text().strip()
    graph_text = read_graph_text(meta.graph_path)
    preview = try_render_preview(
        vkdt_cli=args.vkdt_cli,
        graph_path=meta.graph_path,
        preview_dir=turn_dir / "preview",
        width=args.preview_width,
        height=args.preview_height,
    )
    request = build_request(
        meta=meta, prompt_text=prompt_text, graph_text=graph_text, preview=preview
    )
    connection, response = stream_chat(
        args.backend_host, args.backend_port, request.model_dump(mode="json")
    )
    try:
        applied_count = 0
        for event_name, payload in parse_sse_events(response):
            if event_name == "progress":
                operations = payload.get("operations")
                if not isinstance(operations, list) or len(operations) <= applied_count:
                    continue
                new_operations = operations[applied_count:]
                batch_index = applied_count + 1
                ops_path = turn_dir / f"ops-{batch_index:04d}.txt"
                write_text(ops_path, "\n".join(operation_lines(new_operations)) + "\n")
                ack_path = turn_dir / f"ops-{batch_index:04d}.applied"
                wait_for_file(ack_path, args.poll_interval)
                render = try_render_preview(
                    vkdt_cli=args.vkdt_cli,
                    graph_path=meta.graph_path,
                    preview_dir=turn_dir / "preview",
                    width=args.preview_width,
                    height=args.preview_height,
                )
                if render is not None:
                    jpg_path = turn_dir / "preview" / "preview.jpg"
                    post_bytes(
                        args.backend_host,
                        args.backend_port,
                        "/v1/chat/render",
                        jpg_path.read_bytes(),
                        {
                            "X-Vkdt-Image-Session-Id": meta.image_session_id,
                            "X-Vkdt-Turn-Id": meta.turn_id,
                        },
                    )
                applied_count = len(operations)
            elif event_name == "final":
                final_message = payload.get("assistantMessage", {}).get("text", "")
                write_text(turn_dir / "final.txt", str(final_message))
                write_text(turn_dir / "response.json", json.dumps(payload, indent=2))
                return
            elif event_name == "error":
                write_text(turn_dir / "error.txt", json.dumps(payload, indent=2))
                return
    finally:
        connection.close()


def run(args: argparse.Namespace) -> None:
    session_dir = Path(args.session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    while True:
        turn_dirs = sorted(path for path in session_dir.glob("turn-*") if path.is_dir())
        for turn_dir in turn_dirs:
            if (turn_dir / "done.ok").exists():
                continue
            if (
                not (turn_dir / "meta.txt").exists()
                or not (turn_dir / "prompt.txt").exists()
            ):
                continue
            try:
                handle_turn(turn_dir, args)
            except Exception as exc:
                write_text(turn_dir / "error.txt", str(exc))
            finally:
                write_text(turn_dir / "done.ok", "done\n")
        time.sleep(args.poll_interval)


if __name__ == "__main__":
    run(parse_args())
