"""Tests for the v1.0 <-> pb2 bridge.

The whole module is skipped when the optional [proto] extra is not
installed, so the core test suite still passes on a minimal install.
"""

from __future__ import annotations

import pytest

pb2 = pytest.importorskip("a2a.types.a2a_pb2")

from a2a_pydantic import convert_from_proto, convert_to_proto, v10


def test_message_forward_conversion() -> None:
    msg = v10.Message(
        message_id="m-1",
        role=v10.Role.role_user,
        parts=[v10.Part(text="hallo")],
    )
    out = convert_to_proto(msg)
    assert isinstance(out, pb2.Message)
    assert out.message_id == "m-1"
    assert out.role == pb2.ROLE_USER
    assert out.parts[0].text == "hallo"
    assert out.parts[0].WhichOneof("content") == "text"


def test_send_message_request_roundtrip() -> None:
    req = v10.SendMessageRequest(
        message=v10.Message(
            message_id="m-1",
            role=v10.Role.role_user,
            parts=[v10.Part(text="hi")],
        ),
        tenant="acme",
    )
    pb_req = convert_to_proto(req)
    back = convert_from_proto(pb_req)
    assert isinstance(back, v10.SendMessageRequest)
    assert back.tenant == "acme"
    assert back.message.message_id == "m-1"
    assert back.message.role is v10.Role.role_user
    assert back.message.parts[0].text == "hi"


def test_wire_roundtrip_is_lossless_for_scalar_fields() -> None:
    req = v10.SendMessageRequest(
        message=v10.Message(
            message_id="m-2",
            role=v10.Role.role_agent,
            parts=[v10.Part(text="pong")],
        ),
    )
    wire = convert_to_proto(req).SerializeToString()

    parsed = pb2.SendMessageRequest()
    parsed.ParseFromString(wire)
    back = convert_from_proto(parsed)

    assert back.message.message_id == "m-2"
    assert back.message.role is v10.Role.role_agent
    assert back.message.parts[0].text == "pong"


def test_part_oneof_collapse_warns_on_multi_payload() -> None:
    import warnings

    part = v10.Part(text="a", url="https://x/y")
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        convert_to_proto(part)

    assert any("multiple content payloads" in str(w.message) for w in captured)


def test_task_with_artifacts_roundtrips() -> None:
    pb_task = pb2.Task(
        id="t1",
        context_id="c1",
        status=pb2.TaskStatus(state=pb2.TASK_STATE_COMPLETED),
    )
    pb_task.artifacts.append(
        pb2.Artifact(
            artifact_id="a1",
            name="response",
            parts=[pb2.Part(text="Hello back!")],
        )
    )
    back = convert_from_proto(pb_task)
    assert back.id == "t1"
    assert back.status.state is v10.TaskState.task_state_completed
    assert back.artifacts is not None
    assert back.artifacts[0].parts[0].text == "Hello back!"


def test_send_message_response_oneof() -> None:
    pb_resp = pb2.SendMessageResponse()
    pb_resp.task.id = "t-42"
    back = convert_from_proto(pb_resp)
    assert back.task is not None
    assert back.task.id == "t-42"
    assert back.message is None


def test_unsupported_type_raises_for_both_directions() -> None:
    with pytest.raises(TypeError):
        convert_to_proto(42)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        convert_from_proto(42)  # type: ignore[arg-type]
