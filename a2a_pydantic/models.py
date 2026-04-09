"""All Pydantic models for the A2A protocol.

Internal representation is **always v1.0** semantics. Each model:

- accepts both v0.3 and v1.0 wire formats via ``@model_validator(mode="before")``
  delegating to the helpers in :mod:`a2a_pydantic.compat`
- emits the v1.0 form by default and the v0.3 form when called via
  ``dump(version="0.3")`` (which threads the version through ``model_dump``'s
  ``context``); the per-model ``@model_serializer(mode="wrap")`` reads the
  version off ``info.context`` and dispatches to the right downgrade helper

Field names are stored snake_case in Python and aliased to camelCase on the
wire (matches both v0.3 and v1.0 JSON conventions). The base class enables
``populate_by_name`` so users can construct models with snake_case kwargs.
"""

from __future__ import annotations

import base64
from typing import Annotated, Any, Literal

from pydantic import (
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)
from pydantic_core.core_schema import SerializationInfo

from a2a_pydantic import compat
from a2a_pydantic._base import A2ABaseModel, get_version
from a2a_pydantic.enums import Role, TaskState

__all__ = [
    # data primitives
    "Part",
    "Message",
    "TaskStatus",
    "Task",
    "Artifact",
    # stream events
    "TaskStatusUpdateEvent",
    "TaskArtifactUpdateEvent",
    "StreamEvent",
    # send-message
    "MessageSendParams",
    "MessageSendConfiguration",
    # push notification
    "PushNotificationAuthenticationInfo",
    "PushNotificationConfig",
    "TaskPushNotificationConfig",
    # agent card
    "AgentProvider",
    "AgentExtension",
    "AgentCapabilities",
    "AgentSkill",
    "AgentInterface",
    "AgentCardSignature",
    "AgentCard",
    # security schemes
    "APIKeySecurityScheme",
    "HTTPAuthSecurityScheme",
    "OAuth2SecurityScheme",
    "OpenIdConnectSecurityScheme",
    "MutualTLSSecurityScheme",
    "SecurityScheme",
    "OAuthFlows",
    "AuthorizationCodeOAuthFlow",
    "ClientCredentialsOAuthFlow",
    "ImplicitOAuthFlow",
    "PasswordOAuthFlow",
    # errors
    "ErrorInfo",
    "A2AError",
]


def _b64_encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64_decode(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


class Part(A2ABaseModel):
    """A single piece of message or artifact content.

    Internally one model with member-based discrimination (matching the v1.0
    proto ``oneof``). Exactly one of ``text``, ``data``, ``url``, ``raw`` must
    be set per instance.

    Two equally-valid ways to build one:

    - Direct Pydantic constructor (fully typed via Pydantic's generated
      ``__init__``)::

          Part(text="hello")
          Part(data={"k": "v"})
          Part(url="https://x/y.pdf", media_type="application/pdf")
          Part(raw=b"\\x00\\x01", media_type="image/png", filename="img.png")

    - Convenience factories (positional-friendly shortcut)::

          Part.from_text("hello")
          Part.from_data({"k": "v"})
          Part.from_file(url="https://x/y.pdf", media_type="application/pdf")
    """

    text: str | None = None
    data: dict[str, Any] | None = None
    url: str | None = None
    raw: bytes | None = None
    filename: str | None = None
    media_type: str | None = None
    metadata: dict[str, Any] | None = None

    @classmethod
    def from_text(cls, text: str, *, metadata: dict[str, Any] | None = None) -> Part:
        return cls(text=text, metadata=metadata)

    @classmethod
    def from_data(
        cls,
        data: dict[str, Any],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> Part:
        return cls(data=data, metadata=metadata)

    @classmethod
    def from_file(
        cls,
        *,
        url: str | None = None,
        raw: bytes | str | None = None,
        media_type: str | None = None,
        filename: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Part:
        if (url is None) == (raw is None):
            raise ValueError("Part.from_file requires exactly one of `url` or `raw`.")
        raw_bytes: bytes | None = _b64_decode(raw) if isinstance(raw, str) else raw
        return cls(
            url=url,
            raw=raw_bytes,
            media_type=media_type,
            filename=filename,
            metadata=metadata,
        )

    @model_validator(mode="before")
    @classmethod
    def _accept_v03_or_v10(cls, data: Any) -> Any:
        return compat.normalize_part(data)

    @field_validator("raw", mode="before")
    @classmethod
    def _decode_raw(cls, value: Any) -> Any:
        # JSON wire format encodes bytes as base64; convert back to bytes.
        if isinstance(value, str):
            return _b64_decode(value)
        return value

    @model_validator(mode="after")
    def _check_exactly_one_member(self) -> Part:
        set_members = [
            name
            for name, val in (
                ("text", self.text),
                ("data", self.data),
                ("url", self.url),
                ("raw", self.raw),
            )
            if val is not None
        ]
        if len(set_members) != 1:
            raise ValueError(
                "Part must set exactly one of `text`, `data`, `url`, or `raw`; "
                f"got {set_members or 'none'}"
            )
        return self

    @model_serializer(mode="wrap")
    def _serialize(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        version = get_version(info)
        # Default v1.0 dump via the model handler. ``raw`` (bytes) needs
        # base64 encoding manually because Pydantic's default emits a UTF-8
        # decoded string which would corrupt binary content.
        snapshot = handler(self)
        if self.raw is not None:
            snapshot["raw"] = _b64_encode(self.raw)
        if version == "1.0":
            return snapshot
        return compat.downgrade_part(snapshot)


class Message(A2ABaseModel):
    """A single conversational turn between a user and an agent."""

    message_id: str
    role: Role
    parts: list[Part]
    context_id: str | None = None
    task_id: str | None = None
    metadata: dict[str, Any] | None = None
    extensions: list[str] | None = None
    reference_task_ids: list[str] | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_v03_or_v10(cls, data: Any) -> Any:
        return compat.normalize_message(data)

    @model_serializer(mode="wrap")
    def _serialize(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        version = get_version(info)
        snapshot = handler(self)
        if version == "1.0":
            return snapshot
        return compat.downgrade_message(snapshot)


class TaskStatus(A2ABaseModel):
    state: TaskState
    message: Message | None = None
    timestamp: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_v03_or_v10(cls, data: Any) -> Any:
        return compat.normalize_task_status(data)

    @model_serializer(mode="wrap")
    def _serialize(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        version = get_version(info)
        snapshot = handler(self)
        if version == "1.0":
            return snapshot
        return compat.downgrade_task_status(snapshot)


class Artifact(A2ABaseModel):
    artifact_id: str
    parts: list[Part]
    name: str | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None
    extensions: list[str] | None = None


class Task(A2ABaseModel):
    id: str
    context_id: str
    status: TaskStatus
    artifacts: list[Artifact] | None = None
    history: list[Message] | None = None
    metadata: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_v03_or_v10(cls, data: Any) -> Any:
        return compat.normalize_task(data)

    @model_serializer(mode="wrap")
    def _serialize(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        version = get_version(info)
        snapshot = handler(self)
        if version == "1.0":
            return snapshot
        return compat.downgrade_task(snapshot)


class TaskStatusUpdateEvent(A2ABaseModel):
    """Sent by an agent to update task status during streaming."""

    task_id: str
    context_id: str
    status: TaskStatus
    # ``final`` is a v0.3-only field. We keep it on the model so v0.3 round-
    # trips losslessly. v1.0 dumps drop it.
    final: bool | None = None
    metadata: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_v03_or_v10(cls, data: Any) -> Any:
        return compat.normalize_status_update(data)

    @model_serializer(mode="wrap")
    def _serialize(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        version = get_version(info)
        snapshot = handler(self)
        if version == "1.0":
            snapshot.pop("final", None)
            return snapshot
        return compat.downgrade_status_update(snapshot)


class TaskArtifactUpdateEvent(A2ABaseModel):
    task_id: str
    context_id: str
    artifact: Artifact
    append: bool | None = None
    last_chunk: bool | None = None
    metadata: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_v03_or_v10(cls, data: Any) -> Any:
        return compat.normalize_artifact_update(data)

    @model_serializer(mode="wrap")
    def _serialize(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        version = get_version(info)
        snapshot = handler(self)
        if version == "1.0":
            return snapshot
        return compat.downgrade_artifact_update(snapshot)


class StreamEvent(A2ABaseModel):
    """A single SSE / streaming event from a ``message/stream`` response.

    Internally a tagged container with at most one of ``task``, ``message``,
    ``status_update``, ``artifact_update`` set. The validator accepts both
    the v0.3 ``{"kind": "...", ...}`` form and the v1.0 wrapper form
    ``{"taskStatusUpdate": {...}}``.
    """

    task: Task | None = None
    message: Message | None = None
    status_update: TaskStatusUpdateEvent | None = None
    artifact_update: TaskArtifactUpdateEvent | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_v03_or_v10(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        # v1.0 wrapper form: a single key naming the event variant.
        v10_keys = {
            "task": "task",
            "message": "message",
            "taskStatusUpdate": "status_update",
            "task_status_update": "status_update",
            "statusUpdate": "status_update",
            "status_update": "status_update",
            "taskArtifactUpdate": "artifact_update",
            "task_artifact_update": "artifact_update",
            "artifactUpdate": "artifact_update",
            "artifact_update": "artifact_update",
        }
        keys = list(data.keys())
        if len(keys) == 1 and keys[0] in v10_keys:
            internal = v10_keys[keys[0]]
            return {internal: data[keys[0]]}

        # v0.3 form: dispatch by ``kind``.
        kind = data.get("kind")
        if kind == "status-update":
            return {"status_update": data}
        if kind == "artifact-update":
            return {"artifact_update": data}
        if kind == "task":
            return {"task": data}
        if kind == "message":
            return {"message": data}

        # Already in canonical (snake_case multi-field) form — pass through.
        return data

    @model_validator(mode="after")
    def _check_exactly_one(self) -> StreamEvent:
        members = sum(
            1
            for v in (
                self.task,
                self.message,
                self.status_update,
                self.artifact_update,
            )
            if v is not None
        )
        if members != 1:
            raise ValueError(
                "StreamEvent must have exactly one of task, message, "
                "status_update, artifact_update set."
            )
        return self

    @model_serializer(mode="wrap")
    def _serialize(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        version = get_version(info)
        if version == "1.0":
            # Wrapper form: a single key.
            if self.task is not None:
                return {
                    "task": self.task.model_dump(
                        by_alias=True,
                        exclude_none=True,
                        context={"a2a_version": "1.0"},
                        mode="json",
                    )
                }
            if self.message is not None:
                return {
                    "message": self.message.model_dump(
                        by_alias=True,
                        exclude_none=True,
                        context={"a2a_version": "1.0"},
                        mode="json",
                    )
                }
            if self.status_update is not None:
                return {
                    "taskStatusUpdate": self.status_update.model_dump(
                        by_alias=True,
                        exclude_none=True,
                        context={"a2a_version": "1.0"},
                        mode="json",
                    )
                }
            if self.artifact_update is not None:
                return {
                    "taskArtifactUpdate": self.artifact_update.model_dump(
                        by_alias=True,
                        exclude_none=True,
                        context={"a2a_version": "1.0"},
                        mode="json",
                    )
                }
            return {}

        # v0.3: a single flat object with the variant's fields and a kind tag.
        if self.task is not None:
            return self.task.model_dump(
                by_alias=True,
                exclude_none=True,
                context={"a2a_version": "0.3"},
                mode="json",
            )
        if self.message is not None:
            return self.message.model_dump(
                by_alias=True,
                exclude_none=True,
                context={"a2a_version": "0.3"},
                mode="json",
            )
        if self.status_update is not None:
            return self.status_update.model_dump(
                by_alias=True,
                exclude_none=True,
                context={"a2a_version": "0.3"},
                mode="json",
            )
        if self.artifact_update is not None:
            return self.artifact_update.model_dump(
                by_alias=True,
                exclude_none=True,
                context={"a2a_version": "0.3"},
                mode="json",
            )
        return {}


class PushNotificationAuthenticationInfo(A2ABaseModel):
    """v0.3 used a list of schemes; v1.0 collapsed to a single scheme.

    The internal representation matches v1.0 (single scheme). Construction
    from a v0.3 dict via ``PushNotificationConfig.model_validate`` will pick
    the first scheme automatically.
    """

    scheme: str | None = None
    credentials: str | None = None


class PushNotificationConfig(A2ABaseModel):
    url: str
    id: str | None = None
    token: str | None = None
    authentication: PushNotificationAuthenticationInfo | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_v03_or_v10(cls, data: Any) -> Any:
        return compat.normalize_push_notification_config(data)

    @model_serializer(mode="wrap")
    def _serialize(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        version = get_version(info)
        snapshot = handler(self)
        if version == "1.0":
            return snapshot
        return compat.downgrade_push_notification_config(snapshot)


class TaskPushNotificationConfig(A2ABaseModel):
    """Pairs a push-notification config with a task ID."""

    task_id: str
    push_notification_config: PushNotificationConfig


class MessageSendConfiguration(A2ABaseModel):
    accepted_output_modes: list[str] | None = None
    history_length: int | None = None
    return_immediately: bool | None = None
    task_push_notification_config: PushNotificationConfig | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_v03_or_v10(cls, data: Any) -> Any:
        return compat.normalize_message_send_configuration(data)

    @model_serializer(mode="wrap")
    def _serialize(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        version = get_version(info)
        snapshot = handler(self)
        if version == "1.0":
            return snapshot
        return compat.downgrade_message_send_configuration(snapshot)


class MessageSendParams(A2ABaseModel):
    message: Message
    configuration: MessageSendConfiguration | None = None
    metadata: dict[str, Any] | None = None


class AgentProvider(A2ABaseModel):
    organization: str
    url: str


class AgentExtension(A2ABaseModel):
    uri: str
    description: str | None = None
    required: bool | None = None
    params: dict[str, Any] | None = None


class AgentCapabilities(A2ABaseModel):
    streaming: bool | None = None
    push_notifications: bool | None = None
    extensions: list[AgentExtension] | None = None
    # v0.3-only:
    state_transition_history: bool | None = None
    # v1.0-only:
    extended_agent_card: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_v03_or_v10(cls, data: Any) -> Any:
        return compat.normalize_agent_capabilities(data)

    @model_serializer(mode="wrap")
    def _serialize(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        version = get_version(info)
        snapshot = handler(self)
        if version == "1.0":
            snapshot.pop("stateTransitionHistory", None)
            return snapshot
        return compat.downgrade_agent_capabilities(snapshot)


class AgentSkill(A2ABaseModel):
    id: str
    name: str
    description: str
    tags: list[str]
    examples: list[str] | None = None
    input_modes: list[str] | None = None
    output_modes: list[str] | None = None
    security: list[dict[str, list[str]]] | None = None


class AgentInterface(A2ABaseModel):
    """A (URL, transport) pair the agent can be reached at.

    The internal field name is ``protocol_binding`` (v1.0). v0.3 input uses
    ``transport``; the validator translates it.
    """

    url: str
    protocol_binding: str = "JSONRPC"
    tenant: str | None = None
    protocol_version: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_v03_or_v10(cls, data: Any) -> Any:
        return compat.normalize_agent_interface(data)

    @model_serializer(mode="wrap")
    def _serialize(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        version = get_version(info)
        snapshot = handler(self)
        if version == "1.0":
            return snapshot
        return compat.downgrade_agent_interface(snapshot)


class AgentCardSignature(A2ABaseModel):
    protected: str
    signature: str
    header: dict[str, Any] | None = None


class APIKeySecurityScheme(A2ABaseModel):
    type: Literal["apiKey"] = "apiKey"
    name: str
    in_: Annotated[Literal["query", "header", "cookie"], Field(alias="in")] = "header"
    description: str | None = None


class HTTPAuthSecurityScheme(A2ABaseModel):
    type: Literal["http"] = "http"
    scheme: str
    bearer_format: str | None = None
    description: str | None = None


class AuthorizationCodeOAuthFlow(A2ABaseModel):
    authorization_url: str
    token_url: str
    refresh_url: str | None = None
    scopes: dict[str, str] = Field(default_factory=dict)


class ClientCredentialsOAuthFlow(A2ABaseModel):
    token_url: str
    refresh_url: str | None = None
    scopes: dict[str, str] = Field(default_factory=dict)


class ImplicitOAuthFlow(A2ABaseModel):
    authorization_url: str
    refresh_url: str | None = None
    scopes: dict[str, str] = Field(default_factory=dict)


class PasswordOAuthFlow(A2ABaseModel):
    token_url: str
    refresh_url: str | None = None
    scopes: dict[str, str] = Field(default_factory=dict)


class OAuthFlows(A2ABaseModel):
    authorization_code: AuthorizationCodeOAuthFlow | None = None
    client_credentials: ClientCredentialsOAuthFlow | None = None
    implicit: ImplicitOAuthFlow | None = None
    password: PasswordOAuthFlow | None = None


class OAuth2SecurityScheme(A2ABaseModel):
    type: Literal["oauth2"] = "oauth2"
    flows: OAuthFlows
    description: str | None = None
    oauth2_metadata_url: str | None = None


class OpenIdConnectSecurityScheme(A2ABaseModel):
    type: Literal["openIdConnect"] = "openIdConnect"
    open_id_connect_url: str
    description: str | None = None


class MutualTLSSecurityScheme(A2ABaseModel):
    type: Literal["mutualTLS"] = "mutualTLS"
    description: str | None = None


SecurityScheme = (
    APIKeySecurityScheme
    | HTTPAuthSecurityScheme
    | OAuth2SecurityScheme
    | OpenIdConnectSecurityScheme
    | MutualTLSSecurityScheme
)


class AgentCard(A2ABaseModel):
    """Self-describing manifest for an agent.

    Internal representation matches v1.0 (``supported_interfaces`` +
    ``capabilities.extended_agent_card``). The validator accepts both
    formats; the serialiser routes by version.
    """

    name: str
    description: str
    version: str
    capabilities: AgentCapabilities
    default_input_modes: list[str] = Field(default_factory=lambda: ["text/plain"])
    default_output_modes: list[str] = Field(default_factory=lambda: ["text/plain"])
    skills: list[AgentSkill] = Field(default_factory=list)
    supported_interfaces: list[AgentInterface] = Field(default_factory=list)
    provider: AgentProvider | None = None
    icon_url: str | None = None
    documentation_url: str | None = None
    security_schemes: dict[str, SecurityScheme] | None = None
    security: list[dict[str, list[str]]] | None = None
    signatures: list[AgentCardSignature] | None = None
    protocol_version: str | None = None
    # ``url`` is preserved on the model only so v0.3 round-trips work for
    # legacy clients that read the top-level url. Internally we use
    # ``supported_interfaces`` as the source of truth.
    url: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_v03_or_v10(cls, data: Any) -> Any:
        return compat.normalize_agent_card(data)

    @model_validator(mode="after")
    def _ensure_url_consistency(self) -> AgentCard:
        if self.url is None and self.supported_interfaces:
            self.url = self.supported_interfaces[0].url
        return self

    @model_serializer(mode="wrap")
    def _serialize(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        version = get_version(info)
        # Read v1.0-only fields from the live model *before* calling the
        # handler — the nested AgentCapabilities serializer drops
        # ``extendedAgentCard`` for v0.3, so we'd otherwise lose it.
        eac = self.capabilities.extended_agent_card if self.capabilities else None
        snapshot = handler(self)
        if version == "1.0":
            # v1.0 has no top-level ``url`` — drop the convenience copy.
            snapshot.pop("url", None)
            return snapshot
        out = compat.downgrade_agent_card(snapshot)
        if eac is not None:
            out["supportsAuthenticatedExtendedCard"] = eac
        return out


class ErrorInfo(A2ABaseModel):
    """A google.rpc.ErrorInfo entry from a v1.0 error ``details`` array."""

    type_: Annotated[str | None, Field(alias="@type")] = None
    reason: str | None = None
    domain: str | None = None
    metadata: dict[str, Any] | None = None


class A2AError(A2ABaseModel):
    """Dual-format error wrapper.

    v0.3 (JSON-RPC):
    ``{"code": -32001, "message": "Task not found", "data": ...}``

    v1.0 (google.rpc.Status):
    ``{"error": {"code": 404, "status": "NOT_FOUND", "message": "...",
                 "details": [{"@type": "...", "reason": "...", ...}]}}``
    """

    code: int
    message: str
    status: str | None = None  # v1.0 only ("NOT_FOUND", "INVALID_ARGUMENT", ...)
    details: list[ErrorInfo] | None = None  # v1.0 only
    data: Any | None = None  # v0.3 only

    @model_validator(mode="before")
    @classmethod
    def _accept_v03_or_v10(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        # v1.0 form is wrapped under "error".
        if "error" in data and isinstance(data["error"], dict) and len(data) == 1:
            return data["error"]
        return data

    @model_serializer(mode="wrap")
    def _serialize(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        version = get_version(info)
        snapshot = handler(self)
        if version == "1.0":
            # v1.0 wraps the error under an "error" key and drops v0.3-only
            # fields like ``data``.
            snapshot.pop("data", None)
            return {"error": snapshot}
        # v0.3 form: drop v1.0-only fields.
        snapshot.pop("status", None)
        snapshot.pop("details", None)
        return snapshot
