"""a2a-pydantic: Pydantic models for the A2A protocol.

Dual v0.3 / v1.0 support, zero protobuf dependency. Two layers:

- :mod:`a2a_pydantic.models` — the data primitives (Message, Task, AgentCard,
  …) with full dual-version dump/validate support.
- :mod:`a2a_pydantic.jsonrpc` — the v0.3 JSON-RPC envelope types
  (SendMessageRequest, A2ARequest, JSONRPCErrorResponse, …) for building
  a typed FastAPI endpoint that dispatches by ``method``.

The optional ``[proto]`` extra installs ``protobuf`` so
:func:`a2a_pydantic.proto.to_proto` can convert any supported model into a
proto message — useful for handing them to an ``a2a-sdk`` ``AgentExecutor``.

Quick start::

    from a2a_pydantic import Message, Part, Role

    msg = Message(
        role=Role.USER,
        parts=[Part(text="Translate to French")],
        message_id="msg-001",
    )
    msg.dump(version="0.3")  # v0.3 wire format
    msg.dump(version="1.0")  # v1.0 wire format
"""

from __future__ import annotations

from a2a_pydantic._base import A2ABaseModel
from a2a_pydantic._config import (
    ENV_VAR,
    A2AVersionError,
    Version,
    resolve_version,
)
from a2a_pydantic.enums import (
    ROLE_V03_TO_V10,
    ROLE_V10_TO_V03,
    TASK_STATE_V03_TO_V10,
    TASK_STATE_V10_TO_V03,
    Role,
    TaskState,
    TransportProtocol,
)
from a2a_pydantic.jsonrpc import (
    A2ARequest,
    A2ASpecificError,
    AuthenticatedExtendedCardNotConfiguredError,
    CancelTaskRequest,
    CancelTaskResponse,
    CancelTaskSuccessResponse,
    ContentTypeNotSupportedError,
    DeleteTaskPushNotificationConfigParams,
    DeleteTaskPushNotificationConfigRequest,
    DeleteTaskPushNotificationConfigResponse,
    DeleteTaskPushNotificationConfigSuccessResponse,
    GetAuthenticatedExtendedCardRequest,
    GetAuthenticatedExtendedCardResponse,
    GetAuthenticatedExtendedCardSuccessResponse,
    GetTaskPushNotificationConfigParams,
    GetTaskPushNotificationConfigRequest,
    GetTaskPushNotificationConfigResponse,
    GetTaskPushNotificationConfigSuccessResponse,
    GetTaskRequest,
    GetTaskResponse,
    GetTaskSuccessResponse,
    InternalError,
    InvalidAgentResponseError,
    InvalidParamsError,
    InvalidRequestError,
    JSONParseError,
    JSONRPCError,
    JSONRPCErrorResponse,
    JSONRPCMessage,
    JSONRPCRequest,
    JSONRPCResponse,
    JSONRPCSuccessResponse,
    ListTaskPushNotificationConfigParams,
    ListTaskPushNotificationConfigRequest,
    ListTaskPushNotificationConfigResponse,
    ListTaskPushNotificationConfigSuccessResponse,
    MethodNotFoundError,
    PushNotificationNotSupportedError,
    SendMessageRequest,
    SendMessageResponse,
    SendMessageSuccessResponse,
    SendStreamingMessageRequest,
    SendStreamingMessageResponse,
    SendStreamingMessageSuccessResponse,
    SetTaskPushNotificationConfigRequest,
    SetTaskPushNotificationConfigResponse,
    SetTaskPushNotificationConfigSuccessResponse,
    TaskIdParams,
    TaskNotCancelableError,
    TaskNotFoundError,
    TaskQueryParams,
    TaskResubscriptionRequest,
    UnsupportedOperationError,
)
from a2a_pydantic.models import (
    A2AError,
    AgentCapabilities,
    AgentCard,
    AgentCardSignature,
    AgentExtension,
    AgentInterface,
    AgentProvider,
    AgentSkill,
    APIKeySecurityScheme,
    Artifact,
    AuthorizationCodeOAuthFlow,
    ClientCredentialsOAuthFlow,
    ErrorInfo,
    HTTPAuthSecurityScheme,
    ImplicitOAuthFlow,
    Message,
    MessageSendConfiguration,
    MessageSendParams,
    MutualTLSSecurityScheme,
    OAuth2SecurityScheme,
    OAuthFlows,
    OpenIdConnectSecurityScheme,
    Part,
    PasswordOAuthFlow,
    PushNotificationAuthenticationInfo,
    PushNotificationConfig,
    SecurityScheme,
    StreamEvent,
    Task,
    TaskArtifactUpdateEvent,
    TaskPushNotificationConfig,
    TaskStatus,
    TaskStatusUpdateEvent,
)

__version__ = "0.1.0"

__all__ = [
    # core
    "A2ABaseModel",
    "Version",
    "ENV_VAR",
    "A2AVersionError",
    "resolve_version",
    # enums
    "TaskState",
    "Role",
    "TransportProtocol",
    "TASK_STATE_V03_TO_V10",
    "TASK_STATE_V10_TO_V03",
    "ROLE_V03_TO_V10",
    "ROLE_V10_TO_V03",
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
    # push notifications
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
    # errors (data layer)
    "ErrorInfo",
    "A2AError",
    # JSON-RPC envelope (v0.3 transport)
    "JSONRPCMessage",
    "JSONRPCRequest",
    "JSONRPCError",
    "JSONRPCSuccessResponse",
    "JSONRPCErrorResponse",
    "JSONRPCResponse",
    # JSON-RPC specific errors
    "JSONParseError",
    "InvalidRequestError",
    "MethodNotFoundError",
    "InvalidParamsError",
    "InternalError",
    "TaskNotFoundError",
    "TaskNotCancelableError",
    "PushNotificationNotSupportedError",
    "UnsupportedOperationError",
    "ContentTypeNotSupportedError",
    "InvalidAgentResponseError",
    "AuthenticatedExtendedCardNotConfiguredError",
    "A2ASpecificError",
    # JSON-RPC param types
    "TaskIdParams",
    "TaskQueryParams",
    "GetTaskPushNotificationConfigParams",
    "ListTaskPushNotificationConfigParams",
    "DeleteTaskPushNotificationConfigParams",
    # JSON-RPC request wrappers + union
    "SendMessageRequest",
    "SendStreamingMessageRequest",
    "GetTaskRequest",
    "CancelTaskRequest",
    "SetTaskPushNotificationConfigRequest",
    "GetTaskPushNotificationConfigRequest",
    "DeleteTaskPushNotificationConfigRequest",
    "ListTaskPushNotificationConfigRequest",
    "TaskResubscriptionRequest",
    "GetAuthenticatedExtendedCardRequest",
    "A2ARequest",
    # JSON-RPC response wrappers + unions
    "SendMessageSuccessResponse",
    "SendStreamingMessageSuccessResponse",
    "GetTaskSuccessResponse",
    "CancelTaskSuccessResponse",
    "SetTaskPushNotificationConfigSuccessResponse",
    "GetTaskPushNotificationConfigSuccessResponse",
    "DeleteTaskPushNotificationConfigSuccessResponse",
    "ListTaskPushNotificationConfigSuccessResponse",
    "GetAuthenticatedExtendedCardSuccessResponse",
    "SendMessageResponse",
    "SendStreamingMessageResponse",
    "GetTaskResponse",
    "CancelTaskResponse",
    "SetTaskPushNotificationConfigResponse",
    "GetTaskPushNotificationConfigResponse",
    "DeleteTaskPushNotificationConfigResponse",
    "ListTaskPushNotificationConfigResponse",
    "GetAuthenticatedExtendedCardResponse",
]
