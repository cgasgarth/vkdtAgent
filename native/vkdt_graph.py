from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from shared.protocol import ImageHistoryItem


@dataclass(slots=True)
class ParsedModule:
    name: str
    instance: str
    params: dict[str, list[str]]


@dataclass(slots=True)
class ParsedGraph:
    modules: list[ParsedModule]
    connections: list[dict[str, str]]
    module_order: list[str]


def parse_graph_text(graph_text: str) -> ParsedGraph:
    modules: list[ParsedModule] = []
    module_index: dict[tuple[str, str], ParsedModule] = {}
    connections: list[dict[str, str]] = []
    module_order: list[str] = []
    for raw_line in graph_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(":")
        if parts[0] == "module" and len(parts) >= 3:
            key = (parts[1], parts[2])
            if key in module_index:
                continue
            module = ParsedModule(name=parts[1], instance=parts[2], params={})
            module_index[key] = module
            modules.append(module)
            module_order.append(f"{parts[1]}:{parts[2]}")
            continue
        if parts[0] == "param" and len(parts) >= 5:
            key = (parts[1], parts[2])
            module = module_index.get(key)
            if module is None:
                module = ParsedModule(name=parts[1], instance=parts[2], params={})
                module_index[key] = module
                modules.append(module)
                module_order.append(f"{parts[1]}:{parts[2]}")
            module.params[parts[3]] = parts[4:]
            continue
        if parts[0] == "connect" and len(parts) >= 7:
            connections.append(
                {
                    "sourceModule": parts[1],
                    "sourceInstance": parts[2],
                    "sourceConnector": parts[3],
                    "targetModule": parts[4],
                    "targetInstance": parts[5],
                    "targetConnector": parts[6],
                }
            )
    return ParsedGraph(
        modules=modules, connections=connections, module_order=module_order
    )


def modules_payload(graph: ParsedGraph) -> list[dict[str, Any]]:
    return [
        {
            "module": module.name,
            "instance": module.instance,
            "params": module.params,
        }
        for module in graph.modules
    ]


def history_payload(graph: ParsedGraph) -> list[ImageHistoryItem]:
    return [
        ImageHistoryItem(
            num=index,
            module=module.name,
            enabled=True,
            instanceName=module.instance,
        )
        for index, module in enumerate(graph.modules)
    ]


def action_path(module_name: str, instance: str, param_name: str) -> str:
    return f"module/{module_name}:{instance}/param/{quote(param_name, safe='')}"
