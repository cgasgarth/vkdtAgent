from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from shared.protocol import (
    ExportRequest,
    GraphEdit,
    PreviewImage,
    RenderedArtifact,
    RequestEnvelope,
    WorkflowState,
)

from .vkdt_catalog import adjustment_surfaces
from .vkdt_graph import VkdtGraph
from .vkdt_runner import VkdtRunner


@dataclass(slots=True)
class VkdtSession:
    request: RequestEnvelope
    root: Path
    graph_path: Path
    graph: VkdtGraph
    runner: VkdtRunner
    preview: PreviewImage | None = None
    artifacts: list[RenderedArtifact] = field(default_factory=list)

    @classmethod
    def create(
        cls, request: RequestEnvelope, *, runner: VkdtRunner | None = None
    ) -> "VkdtSession":
        root_parent = (
            Path(request.workspace.sessionRoot)
            if request.workspace.sessionRoot
            else Path(tempfile.mkdtemp(prefix="vkdt-agent-"))
        )
        root_parent.mkdir(parents=True, exist_ok=True)
        if request.workspace.sessionRoot:
            session_root = root_parent / request.requestId
            session_root.mkdir(parents=True, exist_ok=True)
        else:
            session_root = root_parent

        graph_path = session_root / "working.cfg"
        if request.workspace.graphText:
            graph = VkdtGraph.parse(request.workspace.graphText)
        elif request.workspace.graphPath:
            source = Path(request.workspace.graphPath)
            shutil.copyfile(source, graph_path)
            graph = VkdtGraph.parse(graph_path.read_text())
        else:
            graph = VkdtGraph.default_for_image(request.workspace.imagePath)
        graph.write(graph_path)
        session = cls(
            request=request,
            root=session_root,
            graph_path=graph_path,
            graph=graph,
            runner=runner or VkdtRunner(),
        )
        session.refresh_preview()
        return session

    def refresh_preview(self) -> None:
        preview, artifact = self.runner.render_preview(
            graph_path=self.graph_path,
            width=self.request.workspace.previewWidth,
            height=self.request.workspace.previewHeight,
        )
        self.preview = preview
        self.artifacts = [
            artifact,
            *[item for item in self.artifacts if item.kind != "preview"],
        ]

    def apply_edits(self, edits: list[GraphEdit]) -> list[dict[str, Any]]:
        applied: list[dict[str, Any]] = []
        for edit in edits:
            if edit.kind == "set_param":
                self.graph.set_param(
                    edit.module or "",
                    edit.instance or "",
                    edit.param or "",
                    edit.values or [],
                )
            elif edit.kind == "add_module":
                self.graph.add_module(
                    edit.module or "",
                    edit.instance or "",
                    x=edit.x,
                    y=edit.y,
                )
            elif edit.kind == "remove_module":
                self.graph.remove_module(edit.module or "", edit.instance or "")
            elif edit.kind == "connect":
                self.graph.connect(
                    edit.srcModule or "",
                    edit.srcInstance or "",
                    edit.srcConnector or "",
                    edit.dstModule or "",
                    edit.dstInstance or "",
                    edit.dstConnector or "",
                )
            elif edit.kind == "disconnect":
                self.graph.disconnect(
                    edit.srcModule or "",
                    edit.srcInstance or "",
                    edit.srcConnector or "",
                    edit.dstModule or "",
                    edit.dstInstance or "",
                    edit.dstConnector or "",
                )
            elif edit.kind == "insert_module_after":
                self.graph.insert_module_after(
                    edit.module or "",
                    edit.instance or "",
                    after_module=edit.afterModule or "",
                    after_instance=edit.afterInstance or "",
                    input_connector=edit.inputConnector or "input",
                    output_connector=edit.outputConnector or "output",
                )
            applied.append(edit.model_dump(mode="json"))
        errors = self.graph.validate()
        if errors:
            raise ValueError("; ".join(errors))
        self.graph.write(self.graph_path)
        self.refresh_preview()
        return applied

    def render_export(self, export: ExportRequest) -> RenderedArtifact:
        artifact = self.runner.render_export(graph_path=self.graph_path, export=export)
        self.artifacts.append(artifact)
        return artifact

    def workflow_state(self) -> WorkflowState:
        summary = self.graph.summary()
        module_order = cast(list[str], summary["moduleOrder"])
        modules = cast(list[dict[str, Any]], summary["modules"])
        connections = cast(list[dict[str, str]], summary["connections"])
        return WorkflowState(
            graphPath=str(self.graph_path),
            graphText=self.graph_path.read_text(),
            moduleOrder=module_order,
            modules=modules,
            connections=connections,
            adjustmentSurfaces=adjustment_surfaces(modules),
            exports=[item for item in self.artifacts if item.kind == "export"],
            preview=self.preview,
        )
