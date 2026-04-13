from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0"
RefinementMode = Literal["single-turn", "multi-turn"]


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserMessage(StrictBaseModel):
    role: Literal["user"]
    text: str = Field(min_length=1)


class AssistantMessage(StrictBaseModel):
    role: Literal["assistant"]
    text: str = Field(min_length=1)


class RequestSession(StrictBaseModel):
    appSessionId: str = Field(min_length=1)
    imageSessionId: str = Field(min_length=1)
    conversationId: str = Field(min_length=1)
    turnId: str = Field(min_length=1)


class RefinementRequest(StrictBaseModel):
    mode: RefinementMode
    enabled: bool
    maxPasses: int = Field(ge=1)
    passIndex: int = Field(ge=1)
    goalText: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate(self) -> "RefinementRequest":
        expected: RefinementMode = "multi-turn" if self.enabled else "single-turn"
        if self.mode != expected:
            raise ValueError("refinement mode does not match enabled flag")
        if self.passIndex > self.maxPasses:
            raise ValueError("passIndex must be <= maxPasses")
        if not self.enabled and (self.maxPasses != 1 or self.passIndex != 1):
            raise ValueError("single-turn runs must use passIndex=1 and maxPasses=1")
        if not self.enabled or self.mode != "multi-turn":
            raise ValueError("vkdtAgent only supports multi-turn live refinement")
        if self.maxPasses < 2:
            raise ValueError("vkdtAgent multi-turn runs require maxPasses >= 2")
        return self


class WorkspaceContext(StrictBaseModel):
    imagePath: str = Field(min_length=1)
    graphPath: str | None = None
    graphText: str | None = None
    sessionRoot: str | None = None
    previewWidth: int = Field(default=1600, ge=64)
    previewHeight: int = Field(default=900, ge=64)
    defaultRenderFormat: str = Field(default="o-jpg", min_length=1)


class RequestEnvelope(StrictBaseModel):
    schemaVersion: str = SCHEMA_VERSION
    requestId: str = Field(min_length=1)
    session: RequestSession
    message: UserMessage
    workspace: WorkspaceContext
    fast: bool = False
    refinement: RefinementRequest


class PreviewImage(StrictBaseModel):
    previewId: str = Field(min_length=1)
    mimeType: str = Field(min_length=1)
    width: int | None = None
    height: int | None = None
    base64Data: str = Field(min_length=1)


class RenderedArtifact(StrictBaseModel):
    kind: Literal["preview", "export"]
    format: str = Field(min_length=1)
    path: str = Field(min_length=1)
    mimeType: str = Field(min_length=1)


class GraphEdit(StrictBaseModel):
    kind: Literal[
        "set_param",
        "add_module",
        "remove_module",
        "connect",
        "disconnect",
        "insert_module_after",
    ]
    module: str | None = None
    instance: str | None = None
    param: str | None = None
    values: list[str | int | float | bool] | None = None
    x: int | None = None
    y: int | None = None
    srcModule: str | None = None
    srcInstance: str | None = None
    srcConnector: str | None = None
    dstModule: str | None = None
    dstInstance: str | None = None
    dstConnector: str | None = None
    afterModule: str | None = None
    afterInstance: str | None = None
    inputConnector: str | None = None
    outputConnector: str | None = None


class ExportRequest(StrictBaseModel):
    format: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    quality: float | None = Field(default=None, ge=0, le=100)
    output: str = Field(default="main", min_length=1)
    lastFrameOnly: bool = True


class WorkflowState(StrictBaseModel):
    graphPath: str = Field(min_length=1)
    graphText: str = Field(min_length=1)
    moduleOrder: list[str]
    modules: list[dict[str, Any]]
    connections: list[dict[str, str]]
    adjustmentSurfaces: list[dict[str, Any]]
    exports: list[RenderedArtifact]
    preview: PreviewImage | None


class AgentPlan(StrictBaseModel):
    assistantText: str = Field(min_length=1)
    continueRefining: bool
    operations: list[GraphEdit]
    workflow: WorkflowState


class ResponseEnvelope(StrictBaseModel):
    requestId: str = Field(min_length=1)
    session: RequestSession
    status: Literal["ok", "error"]
    assistantMessage: AssistantMessage
    plan: AgentPlan | None
    workflow: WorkflowState | None
    error: dict[str, str] | None = None
