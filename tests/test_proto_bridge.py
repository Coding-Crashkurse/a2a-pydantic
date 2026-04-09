"""Tests for the optional :mod:`a2a_pydantic.proto` bridge.

Three scenarios are exercised:

- ``protobuf`` not installed → :func:`to_proto` raises ``ImportError``.
- ``a2a-sdk`` happens to be installed → auto-import path works.
- BYO pb2 module passed via ``pb2=`` → bypasses any SDK detection.
"""

from __future__ import annotations

import importlib.util

import pytest

from a2a_pydantic import Message, Part, Role, Task, TaskState, TaskStatus

HAS_A2A_SDK = importlib.util.find_spec("a2a") is not None
HAS_PROTOBUF = importlib.util.find_spec("google.protobuf") is not None


@pytest.mark.skipif(HAS_A2A_SDK, reason="a2a-sdk is installed")
class TestAutoImportMissing:
    def test_helpful_error_when_no_sdk_and_no_pb2(self):
        from a2a_pydantic.proto import to_proto

        msg = Message(role=Role.USER, parts=[Part(text="x")], message_id="m")
        with pytest.raises(ImportError, match="pb2"):
            to_proto(msg)


@pytest.mark.skipif(not HAS_A2A_SDK, reason="a2a-sdk not installed")
class TestAutoImportConvenience:
    def test_message(self):
        from a2a_pydantic.proto import to_proto

        msg = Message(
            role=Role.USER,
            parts=[Part(text="hello")],
            message_id="m1",
            context_id="c1",
        )
        proto_msg = to_proto(msg)
        assert proto_msg.message_id == "m1"
        assert proto_msg.context_id == "c1"
        parts_field = getattr(proto_msg, "parts", None) or getattr(
            proto_msg, "content", None
        )
        assert parts_field is not None and len(parts_field) == 1
        assert parts_field[0].text == "hello"

    def test_task(self):
        from a2a_pydantic.proto import to_proto

        task = Task(
            id="t1",
            context_id="c1",
            status=TaskStatus(state=TaskState.COMPLETED),
        )
        proto_task = to_proto(task)
        assert proto_task.id == "t1"
        assert proto_task.context_id == "c1"


@pytest.mark.skipif(
    not HAS_A2A_SDK,
    reason="needs an a2a_pb2-compatible module to inject; we use a2a-sdk's "
    "as a stand-in but the test exercises the explicit pb2= parameter path",
)
class TestExplicitPb2Parameter:
    def test_pb2_parameter_is_used(self):
        """Passing ``pb2=`` must bypass auto-import entirely."""
        from a2a.grpc import a2a_pb2 as my_pb2  # type: ignore[import-not-found]

        from a2a_pydantic.proto import to_proto

        msg = Message(role=Role.USER, parts=[Part(text="x")], message_id="m")
        proto_msg = to_proto(msg, pb2=my_pb2)
        assert proto_msg.message_id == "m"
        assert isinstance(proto_msg, my_pb2.Message)
