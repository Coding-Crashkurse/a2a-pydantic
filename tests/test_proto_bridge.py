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

    # Bypass v10.Part's one-of validator via model_construct — the pb2
    # converter's own guard still fires because pb2's oneof would silently
    # collapse to the last write.
    part = v10.Part.model_construct(text="a", url="https://x/y")
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
    # TaskState=0 (UNSPECIFIED) now raises strictly; set a valid state
    pb_resp.task.status.state = pb2.TASK_STATE_COMPLETED
    back = convert_from_proto(pb_resp)
    assert back.task is not None
    assert back.task.id == "t-42"
    assert back.message is None


def test_unsupported_type_raises_for_both_directions() -> None:
    with pytest.raises(TypeError):
        convert_to_proto(42)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        convert_from_proto(42)  # type: ignore[arg-type]


def test_decode_raw_rejects_invalid_base64() -> None:
    # v10.Part.raw is supposed to be base64; silent utf-8 fallback would
    # corrupt binary payloads instead of telling the caller about the bug.
    bad_part = v10.Part.model_construct(raw="this is not base64 at all!!")
    with pytest.raises(ValueError, match="not valid base64"):
        convert_to_proto(bad_part)


def test_decode_raw_accepts_valid_base64() -> None:
    import base64 as _b64

    payload = b"binary data \x00\x01\x02"
    part = v10.Part(raw=_b64.b64encode(payload).decode("ascii"))
    out = convert_to_proto(part)
    assert out.raw == payload


def test_part_default_filename_media_type_roundtrip_none() -> None:
    # Default filename / media_type are None (was "" before 0.0.7). Proto3
    # has no distinction between "unset" and "empty string" for scalars, so
    # both should round-trip through pb2 as None on the Pydantic side.
    original = v10.Part(text="hi")
    assert original.filename is None and original.media_type is None
    back = convert_from_proto(convert_to_proto(original))
    assert back.filename is None
    assert back.media_type is None


def test_part_explicit_filename_roundtrips() -> None:
    original = v10.Part(
        url="https://x/y.pdf",
        media_type="application/pdf",
        filename="invoice.pdf",
    )
    back = convert_from_proto(convert_to_proto(original))
    assert back.filename == "invoice.pdf"
    assert back.media_type == "application/pdf"
    assert back.url == "https://x/y.pdf"


def test_part_raw_bytes_constructor_roundtrips_binary_payload() -> None:
    # v10.Part(raw=b"...") is the construction path the 0.0.7 coercer
    # enables. Round-trip through pb2 should recover the exact bytes,
    # including non-UTF-8 ones, so silent UTF-8 coercion can't sneak in.
    payload = b"\x00\x01\x02 mixed with text"
    part = v10.Part(raw=payload, media_type="application/octet-stream")
    back = convert_from_proto(convert_to_proto(part))
    import base64 as _b64

    assert back.raw is not None
    assert _b64.b64decode(back.raw) == payload


def test_role_unspecified_raises_loudly() -> None:
    # Silent coercion ROLE_UNSPECIFIED -> ROLE_USER would mask a server bug.
    bad_msg = pb2.Message(
        message_id="m",
        role=pb2.ROLE_UNSPECIFIED,
        parts=[pb2.Part(text="x")],
    )
    with pytest.raises(ValueError, match="ROLE_UNSPECIFIED"):
        convert_from_proto(bad_msg)


def test_task_state_unspecified_raises_loudly() -> None:
    bad_status = pb2.TaskStatus(state=pb2.TASK_STATE_UNSPECIFIED)
    with pytest.raises(ValueError, match="TASK_STATE_UNSPECIFIED"):
        convert_from_proto(bad_status)


def test_empty_pb_part_raises_on_spec_violation() -> None:
    # pb2.Part with no content oneof populated violates A2A §4.1.6. We raise
    # loudly instead of silently emitting an empty TextPart that would bubble
    # up as a confusing empty artifact downstream.
    empty_part = pb2.Part()
    with pytest.raises(ValueError, match="has no content oneof"):
        convert_from_proto(empty_part)


def test_v10_to_proto_to_v10_roundtrip() -> None:
    """Roundtrip catches bugs a single-direction test would miss."""
    original = v10.SendMessageRequest(
        message=v10.Message(
            message_id="m-1",
            role=v10.Role.role_agent,
            parts=[v10.Part(text="round trip")],
            metadata=v10.Struct(trace_id="abc", retries=3),
        ),
        tenant="acme",
    )
    pb_form = convert_to_proto(original)
    roundtripped = convert_from_proto(pb_form)

    assert roundtripped.tenant == "acme"
    assert roundtripped.message.message_id == "m-1"
    assert roundtripped.message.role is v10.Role.role_agent
    assert roundtripped.message.parts[0].text == "round trip"
    # Struct metadata survives thanks to extra='allow'
    assert roundtripped.message.metadata is not None
    assert roundtripped.message.metadata.model_dump(exclude_none=True) == {
        "trace_id": "abc",
        "retries": 3,
    }
