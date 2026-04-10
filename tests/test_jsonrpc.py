"""Tests for the v0.3 JSON-RPC envelope types in :mod:`a2a_pydantic.jsonrpc`.

Covers the three things a typed FastAPI endpoint actually needs:

- Request envelope round-trip (build, validate, dump)
- :class:`A2ARequest` discriminated dispatch by ``method``
- Error envelope with the literal-coded error subclasses
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from a2a_pydantic import (
    A2ARequest,
    AuthenticatedExtendedCardNotConfiguredError,
    CancelTaskRequest,
    DeleteTaskPushNotificationConfigParams,
    DeleteTaskPushNotificationConfigRequest,
    GetTaskRequest,
    GetTaskSuccessResponse,
    InvalidParamsError,
    InvalidRequestError,
    JSONRPCErrorResponse,
    Message,
    MessageSendParams,
    Part,
    PushNotificationConfig,
    Role,
    SendMessageRequest,
    SendMessageSuccessResponse,
    SendStreamingMessageRequest,
    SetTaskPushNotificationConfigRequest,
    Task,
    TaskIdParams,
    TaskNotCancelableError,
    TaskNotFoundError,
    TaskPushNotificationConfig,
    TaskQueryParams,
    TaskResubscriptionRequest,
    TaskState,
    TaskStatus,
)


def _msg() -> Message:
    return Message(role=Role.USER, parts=[Part(text="hi")], message_id="m1")


def _task() -> Task:
    return Task(id="t1", context_id="c1", status=TaskStatus(state=TaskState.COMPLETED))


class TestRequestEnvelope:
    def test_send_message_request_dump(self):
        req = SendMessageRequest(id="r1", params=MessageSendParams(message=_msg()))
        out = req.dump(version="0.3")
        assert out["jsonrpc"] == "2.0"
        assert out["id"] == "r1"
        assert out["method"] == "message/send"
        assert out["params"]["message"]["messageId"] == "m1"
        assert out["params"]["message"]["kind"] == "message"

    def test_send_message_request_v10_params_dump(self):
        req = SendMessageRequest(id="r1", params=MessageSendParams(message=_msg()))
        out = req.dump(version="1.0")
        assert out["params"]["message"]["role"] == "ROLE_USER"
        assert "kind" not in out["params"]["message"]

    def test_get_task_request(self):
        req = GetTaskRequest(id=42, params=TaskQueryParams(id="t1", history_length=10))
        out = req.dump(version="0.3")
        assert out["method"] == "tasks/get"
        assert out["params"] == {"id": "t1", "historyLength": 10}

    def test_cancel_task_request(self):
        req = CancelTaskRequest(id="x", params=TaskIdParams(id="t1"))
        out = req.dump(version="0.3")
        assert out["method"] == "tasks/cancel"
        assert out["params"] == {"id": "t1"}

    def test_resubscribe_request(self):
        req = TaskResubscriptionRequest(id=1, params=TaskIdParams(id="t1"))
        assert req.dump(version="0.3")["method"] == "tasks/resubscribe"

    def test_streaming_send_request(self):
        req = SendStreamingMessageRequest(
            id=1, params=MessageSendParams(message=_msg())
        )
        assert req.dump(version="0.3")["method"] == "message/stream"

    def test_set_push_config_request(self):
        cfg = TaskPushNotificationConfig(
            task_id="t1",
            push_notification_config=PushNotificationConfig(url="https://hook"),
        )
        req = SetTaskPushNotificationConfigRequest(id=1, params=cfg)
        out = req.dump(version="0.3")
        assert out["method"] == "tasks/pushNotificationConfig/set"
        assert out["params"]["taskId"] == "t1"

    def test_delete_push_config_request(self):
        params = DeleteTaskPushNotificationConfigParams(
            id="t1", push_notification_config_id="n1"
        )
        req = DeleteTaskPushNotificationConfigRequest(id=1, params=params)
        out = req.dump(version="0.3")
        assert out["params"]["pushNotificationConfigId"] == "n1"


class TestA2ARequestDispatch:
    """Single endpoint, validates against the union, pattern-matches by method."""

    def test_dispatch_get_task(self):
        raw = {
            "jsonrpc": "2.0",
            "id": "r1",
            "method": "tasks/get",
            "params": {"id": "t1"},
        }
        wrapped = A2ARequest.model_validate(raw)
        assert isinstance(wrapped.root, GetTaskRequest)
        assert wrapped.root.params.id == "t1"

    def test_dispatch_send_message(self):
        raw = {
            "jsonrpc": "2.0",
            "id": "r2",
            "method": "message/send",
            "params": {
                "message": {
                    "kind": "message",
                    "role": "user",
                    "parts": [{"kind": "text", "text": "hi"}],
                    "messageId": "m1",
                }
            },
        }
        wrapped = A2ARequest.model_validate(raw)
        assert isinstance(wrapped.root, SendMessageRequest)
        assert wrapped.root.params.message.message_id == "m1"

    def test_dispatch_cancel(self):
        raw = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/cancel",
            "params": {"id": "t1"},
        }
        assert isinstance(A2ARequest.model_validate(raw).root, CancelTaskRequest)

    def test_unknown_method_rejected(self):
        raw = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/teleport",
            "params": {},
        }
        with pytest.raises(ValidationError):
            A2ARequest.model_validate(raw)

    def test_v10_input_shape_also_validates(self):
        """The nested params accept v1.0 wire shape via their own validator."""
        raw = {
            "jsonrpc": "2.0",
            "id": "r1",
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": "m1",
                    "role": "ROLE_USER",
                    "parts": [{"text": "hi"}],
                }
            },
        }
        wrapped = A2ARequest.model_validate(raw)
        assert isinstance(wrapped.root, SendMessageRequest)
        assert wrapped.root.params.message.role == Role.USER


class TestErrors:
    def test_specific_error_codes(self):
        cases = [
            (TaskNotFoundError(), -32001),
            (TaskNotCancelableError(), -32002),
            (InvalidParamsError(), -32602),
            (InvalidRequestError(), -32600),
            (AuthenticatedExtendedCardNotConfiguredError(), -32007),
        ]
        for err, expected in cases:
            assert err.code == expected

    def test_error_response_envelope(self):
        resp = JSONRPCErrorResponse(
            id="r1", error=TaskNotFoundError(data={"taskId": "t1"})
        )
        out = resp.dump(version="0.3")
        assert out == {
            "jsonrpc": "2.0",
            "id": "r1",
            "error": {
                "code": -32001,
                "message": "Task not found",
                "data": {"taskId": "t1"},
            },
        }

    def test_error_response_validates_specific_subclass(self):
        raw = {
            "jsonrpc": "2.0",
            "id": "r1",
            "error": {"code": -32001, "message": "Task not found"},
        }
        resp = JSONRPCErrorResponse.model_validate(raw)
        assert resp.error.code == -32001


class TestSuccessResponses:
    def test_get_task_success(self):
        resp = GetTaskSuccessResponse(id="r1", result=_task())
        out = resp.dump(version="0.3")
        assert out["result"]["id"] == "t1"
        assert out["result"]["kind"] == "task"

    def test_send_message_success_with_task_result(self):
        resp = SendMessageSuccessResponse(id=1, result=_task())
        out = resp.dump(version="0.3")
        assert out["result"]["kind"] == "task"

    def test_send_message_success_with_message_result(self):
        resp = SendMessageSuccessResponse(id=1, result=_msg())
        out = resp.dump(version="0.3")
        assert out["result"]["kind"] == "message"
