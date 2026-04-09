"""a2a-pydantic: Pydantic models for the A2A protocol.

Dual v0.3 / v1.0 support, zero protobuf dependency. The optional ``[proto]``
extra installs the official ``a2a-sdk`` so :func:`a2a_pydantic.proto.to_proto`
can convert these models into proto messages for use with the official Python
SDK's ``AgentExecutor``.

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
    # errors
    "ErrorInfo",
    "A2AError",
]
