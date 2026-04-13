from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "2.0"
type JsonObject = dict[str, object]

OperationKind = Literal["set-float", "set-choice", "set-bool", "graph-action"]
OperationMode = Literal["delta", "set"]
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


class ResponseSession(StrictBaseModel):
    appSessionId: str
    imageSessionId: str
    conversationId: str
    turnId: str


class UIContext(StrictBaseModel):
    view: str = Field(min_length=1)
    imageId: int | None = None
    imageName: str | None = None


class RefinementRequest(StrictBaseModel):
    mode: RefinementMode
    enabled: bool
    maxPasses: int = Field(ge=1)
    passIndex: int = Field(ge=1)
    goalText: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_live_run(self) -> "RefinementRequest":
        expected: RefinementMode = "multi-turn" if self.enabled else "single-turn"
        if self.mode != expected:
            raise ValueError("refinement mode does not match enabled flag")
        if self.passIndex > self.maxPasses:
            raise ValueError("passIndex must be <= maxPasses")
        if not self.enabled or self.mode != "multi-turn":
            raise ValueError("vkdtAgent only supports multi-turn live refinement")
        if self.maxPasses < 2:
            raise ValueError("vkdtAgent multi-turn runs require maxPasses >= 2")
        return self


class RefinementStatus(StrictBaseModel):
    mode: RefinementMode
    enabled: bool
    passIndex: int = Field(ge=1)
    maxPasses: int = Field(ge=1)
    continueRefining: bool
    stopReason: Literal[
        "planner-complete",
        "cancelled",
        "tool-budget",
        "render-timeout",
        "error",
    ]


class PreviewImage(StrictBaseModel):
    previewId: str = Field(min_length=1)
    mimeType: str = Field(min_length=1)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    base64Data: str = Field(min_length=1)


class ChoiceOption(StrictBaseModel):
    choiceValue: int
    choiceId: str = Field(min_length=1)
    label: str = Field(min_length=1)


class Capability(StrictBaseModel):
    moduleId: str = Field(min_length=1)
    moduleLabel: str = Field(min_length=1)
    capabilityId: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: Literal["set-float", "set-choice", "set-bool"]
    targetType: Literal["vkdt-action", "vkdt-graph"]
    actionPath: str = Field(min_length=1)
    supportedModes: list[OperationMode] = Field(min_length=1)
    minNumber: float | None = None
    maxNumber: float | None = None
    defaultNumber: float | None = None
    stepNumber: float | None = None
    choices: list[ChoiceOption] | None = None
    defaultChoiceValue: int | None = None
    defaultBool: bool | None = None


class CapabilityManifest(StrictBaseModel):
    manifestVersion: str = Field(min_length=1)
    targets: list[Capability] = Field(min_length=1)


class EditableSetting(StrictBaseModel):
    moduleId: str = Field(min_length=1)
    moduleLabel: str = Field(min_length=1)
    settingId: str = Field(min_length=1)
    capabilityId: str = Field(min_length=1)
    label: str = Field(min_length=1)
    actionPath: str = Field(min_length=1)
    kind: Literal["set-float", "set-choice", "set-bool"]
    supportedModes: list[OperationMode] = Field(min_length=1)
    currentNumber: float | None = None
    minNumber: float | None = None
    maxNumber: float | None = None
    defaultNumber: float | None = None
    stepNumber: float | None = None
    currentChoiceValue: int | None = None
    currentChoiceId: str | None = None
    choices: list[ChoiceOption] | None = None
    defaultChoiceValue: int | None = None
    currentBool: bool | None = None
    defaultBool: bool | None = None


class ImageHistoryItem(StrictBaseModel):
    num: int
    module: str | None = None
    enabled: bool
    instanceName: str | None = None


class ImageSnapshot(StrictBaseModel):
    imageRevisionId: str = Field(min_length=1)
    graphPath: str = Field(min_length=1)
    graphText: str = Field(min_length=1)
    moduleOrder: list[str]
    modules: list[JsonObject]
    connections: list[dict[str, str]]
    adjustmentSurfaces: list[JsonObject]
    editableSettings: list[EditableSetting]
    history: list[ImageHistoryItem]
    preview: PreviewImage | None = None


class RequestEnvelope(StrictBaseModel):
    schemaVersion: str = SCHEMA_VERSION
    requestId: str = Field(min_length=1)
    session: RequestSession
    uiContext: UIContext
    message: UserMessage
    capabilityManifest: CapabilityManifest
    imageSnapshot: ImageSnapshot
    fast: bool = False
    refinement: RefinementRequest


class GraphOperation(StrictBaseModel):
    kind: OperationKind
    targetType: Literal["vkdt-action", "vkdt-graph"]
    actionPath: str = Field(min_length=1)
    mode: OperationMode | None = None
    valueNumber: float | None = None
    valueBool: bool | None = None
    valueChoiceId: str | None = None
    graphPayload: JsonObject | None = None
    summary: str | None = None


class AgentPlan(StrictBaseModel):
    assistantText: str = Field(min_length=1)
    continueRefining: bool
    operations: list[GraphOperation]


class ErrorInfo(StrictBaseModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ResponseEnvelope(StrictBaseModel):
    requestId: str = Field(min_length=1)
    session: ResponseSession
    status: Literal["ok", "error"]
    assistantMessage: AssistantMessage
    refinement: RefinementStatus
    plan: AgentPlan | None
    error: ErrorInfo | None = None
