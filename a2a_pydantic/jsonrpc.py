"""JSON-RPC 2.0 envelope types for the A2A v0.3 protocol.

The v0.3 transport is JSON-RPC 2.0 over HTTP. Every method call is wrapped
in a request envelope ``{id, jsonrpc, method, params}`` and every response
in either a success envelope ``{id, jsonrpc, result}`` or an error envelope
``{id, jsonrpc, error}``. v1.0 drops this layer entirely in favour of
native gRPC, so these types are v0.3-only — there is no version dispatch
on the envelopes themselves. The *params* and *result* payloads they wrap
are the same dual-version models from :mod:`a2a_pydantic.models`, so a
``SendMessageRequest.dump(version="0.3")`` will dump its nested
``MessageSendParams`` in v0.3 form just like a direct call would.

The discriminated union :class:`A2ARequest` lets a single FastAPI endpoint
accept any A2A method by validating against the union — Pydantic dispatches
to the right concrete request class based on the ``method`` literal, so the
handler can ``match`` on the variant for type-safe routing.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, RootModel

from a2a_pydantic._base import A2ABaseModel
from a2a_pydantic.models import (
    AgentCard,
    Message,
    MessageSendParams,
    Task,
    TaskArtifactUpdateEvent,
    TaskPushNotificationConfig,
    TaskStatusUpdateEvent,
)

__all__ = [
    "JSONRPCMessage",
    "JSONRPCRequest",
    "JSONRPCError",
    "JSONRPCSuccessResponse",
    "JSONRPCErrorResponse",
    "JSONRPCResponse",
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
    "TaskIdParams",
    "TaskQueryParams",
    "GetTaskPushNotificationConfigParams",
    "ListTaskPushNotificationConfigParams",
    "DeleteTaskPushNotificationConfigParams",
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


JSONRPCId = str | int | None


class JSONRPCMessage(A2ABaseModel):
    """Common JSON-RPC 2.0 envelope fields shared by request and response."""

    jsonrpc: Literal["2.0"] = "2.0"
    id: JSONRPCId = None


class JSONRPCRequest(JSONRPCMessage):
    """Generic JSON-RPC 2.0 request — used as a fallback when the method is unknown."""

    method: str
    params: dict[str, Any] | None = None


class JSONRPCError(A2ABaseModel):
    """JSON-RPC 2.0 error object embedded in :class:`JSONRPCErrorResponse`."""

    code: int
    message: str
    data: Any | None = None


class JSONParseError(JSONRPCError):
    code: Literal[-32700] = -32700
    message: str = "Invalid JSON payload"


class InvalidRequestError(JSONRPCError):
    code: Literal[-32600] = -32600
    message: str = "Request payload validation error"


class MethodNotFoundError(JSONRPCError):
    code: Literal[-32601] = -32601
    message: str = "Method not found"


class InvalidParamsError(JSONRPCError):
    code: Literal[-32602] = -32602
    message: str = "Invalid parameters"


class InternalError(JSONRPCError):
    code: Literal[-32603] = -32603
    message: str = "Internal error"


class TaskNotFoundError(JSONRPCError):
    code: Literal[-32001] = -32001
    message: str = "Task not found"


class TaskNotCancelableError(JSONRPCError):
    code: Literal[-32002] = -32002
    message: str = "Task cannot be canceled"


class PushNotificationNotSupportedError(JSONRPCError):
    code: Literal[-32003] = -32003
    message: str = "Push Notification is not supported"


class UnsupportedOperationError(JSONRPCError):
    code: Literal[-32004] = -32004
    message: str = "This operation is not supported"


class ContentTypeNotSupportedError(JSONRPCError):
    code: Literal[-32005] = -32005
    message: str = "Incompatible content types"


class InvalidAgentResponseError(JSONRPCError):
    code: Literal[-32006] = -32006
    message: str = "Invalid agent response"


class AuthenticatedExtendedCardNotConfiguredError(JSONRPCError):
    code: Literal[-32007] = -32007
    message: str = "Authenticated Extended Card is not configured"


A2ASpecificError = (
    JSONParseError
    | InvalidRequestError
    | MethodNotFoundError
    | InvalidParamsError
    | InternalError
    | TaskNotFoundError
    | TaskNotCancelableError
    | PushNotificationNotSupportedError
    | UnsupportedOperationError
    | ContentTypeNotSupportedError
    | InvalidAgentResponseError
    | AuthenticatedExtendedCardNotConfiguredError
)


class JSONRPCSuccessResponse(JSONRPCMessage):
    result: Any


class JSONRPCErrorResponse(JSONRPCMessage):
    error: A2ASpecificError | JSONRPCError


class TaskIdParams(A2ABaseModel):
    """Just a task ID, used by simple task operations like cancel/resubscribe."""

    id: str
    metadata: dict[str, Any] | None = None


class TaskQueryParams(A2ABaseModel):
    """Task ID plus optional history-length cap, used by ``tasks/get``."""

    id: str
    history_length: int | None = None
    metadata: dict[str, Any] | None = None


class GetTaskPushNotificationConfigParams(A2ABaseModel):
    id: str
    push_notification_config_id: str | None = None
    metadata: dict[str, Any] | None = None


class ListTaskPushNotificationConfigParams(A2ABaseModel):
    id: str
    metadata: dict[str, Any] | None = None


class DeleteTaskPushNotificationConfigParams(A2ABaseModel):
    id: str
    push_notification_config_id: str
    metadata: dict[str, Any] | None = None


class SendMessageRequest(JSONRPCMessage):
    method: Literal["message/send"] = "message/send"
    params: MessageSendParams


class SendStreamingMessageRequest(JSONRPCMessage):
    method: Literal["message/stream"] = "message/stream"
    params: MessageSendParams


class GetTaskRequest(JSONRPCMessage):
    method: Literal["tasks/get"] = "tasks/get"
    params: TaskQueryParams


class CancelTaskRequest(JSONRPCMessage):
    method: Literal["tasks/cancel"] = "tasks/cancel"
    params: TaskIdParams


class SetTaskPushNotificationConfigRequest(JSONRPCMessage):
    method: Literal["tasks/pushNotificationConfig/set"] = (
        "tasks/pushNotificationConfig/set"
    )
    params: TaskPushNotificationConfig


class GetTaskPushNotificationConfigRequest(JSONRPCMessage):
    method: Literal["tasks/pushNotificationConfig/get"] = (
        "tasks/pushNotificationConfig/get"
    )
    params: TaskIdParams | GetTaskPushNotificationConfigParams


class DeleteTaskPushNotificationConfigRequest(JSONRPCMessage):
    method: Literal["tasks/pushNotificationConfig/delete"] = (
        "tasks/pushNotificationConfig/delete"
    )
    params: DeleteTaskPushNotificationConfigParams


class ListTaskPushNotificationConfigRequest(JSONRPCMessage):
    method: Literal["tasks/pushNotificationConfig/list"] = (
        "tasks/pushNotificationConfig/list"
    )
    params: ListTaskPushNotificationConfigParams


class TaskResubscriptionRequest(JSONRPCMessage):
    method: Literal["tasks/resubscribe"] = "tasks/resubscribe"
    params: TaskIdParams


class GetAuthenticatedExtendedCardRequest(JSONRPCMessage):
    method: Literal["agent/getAuthenticatedExtendedCard"] = (
        "agent/getAuthenticatedExtendedCard"
    )


class A2ARequest(
    RootModel[
        Annotated[
            SendMessageRequest
            | SendStreamingMessageRequest
            | GetTaskRequest
            | CancelTaskRequest
            | SetTaskPushNotificationConfigRequest
            | GetTaskPushNotificationConfigRequest
            | TaskResubscriptionRequest
            | ListTaskPushNotificationConfigRequest
            | DeleteTaskPushNotificationConfigRequest
            | GetAuthenticatedExtendedCardRequest,
            Field(discriminator="method"),
        ]
    ]
):
    """Discriminated union over every JSON-RPC method the A2A spec defines.

    The ``method`` literal on each variant is the discriminator, so a
    FastAPI handler can declare ``req: A2ARequest`` and pattern-match on
    ``req.root`` for type-safe dispatch.
    """


class SendMessageSuccessResponse(JSONRPCMessage):
    """``message/send`` returns either a ``Task`` or a direct ``Message`` reply."""

    result: Task | Message


class SendStreamingMessageSuccessResponse(JSONRPCMessage):
    """A single SSE frame from ``message/stream``: task, message, or update event."""

    result: Task | Message | TaskStatusUpdateEvent | TaskArtifactUpdateEvent


class GetTaskSuccessResponse(JSONRPCMessage):
    result: Task


class CancelTaskSuccessResponse(JSONRPCMessage):
    result: Task


class SetTaskPushNotificationConfigSuccessResponse(JSONRPCMessage):
    result: TaskPushNotificationConfig


class GetTaskPushNotificationConfigSuccessResponse(JSONRPCMessage):
    result: TaskPushNotificationConfig


class DeleteTaskPushNotificationConfigSuccessResponse(JSONRPCMessage):
    result: None = None


class ListTaskPushNotificationConfigSuccessResponse(JSONRPCMessage):
    result: list[TaskPushNotificationConfig]


class GetAuthenticatedExtendedCardSuccessResponse(JSONRPCMessage):
    result: AgentCard


SendMessageResponse = SendMessageSuccessResponse | JSONRPCErrorResponse
SendStreamingMessageResponse = (
    SendStreamingMessageSuccessResponse | JSONRPCErrorResponse
)
GetTaskResponse = GetTaskSuccessResponse | JSONRPCErrorResponse
CancelTaskResponse = CancelTaskSuccessResponse | JSONRPCErrorResponse
SetTaskPushNotificationConfigResponse = (
    SetTaskPushNotificationConfigSuccessResponse | JSONRPCErrorResponse
)
GetTaskPushNotificationConfigResponse = (
    GetTaskPushNotificationConfigSuccessResponse | JSONRPCErrorResponse
)
DeleteTaskPushNotificationConfigResponse = (
    DeleteTaskPushNotificationConfigSuccessResponse | JSONRPCErrorResponse
)
ListTaskPushNotificationConfigResponse = (
    ListTaskPushNotificationConfigSuccessResponse | JSONRPCErrorResponse
)
GetAuthenticatedExtendedCardResponse = (
    GetAuthenticatedExtendedCardSuccessResponse | JSONRPCErrorResponse
)

JSONRPCResponse = (
    SendMessageResponse
    | SendStreamingMessageResponse
    | GetTaskResponse
    | CancelTaskResponse
    | SetTaskPushNotificationConfigResponse
    | GetTaskPushNotificationConfigResponse
    | DeleteTaskPushNotificationConfigResponse
    | ListTaskPushNotificationConfigResponse
    | GetAuthenticatedExtendedCardResponse
)
