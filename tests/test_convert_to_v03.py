"""Tests for the v1.0 -> v0.3 downward converter."""

from __future__ import annotations

import warnings

import pytest

from a2a_pydantic import convert_to_v03, v03, v10


def test_send_message_request_roundtrips_core_fields() -> None:
    req = v10.SendMessageRequest(
        message=v10.Message(
            message_id="m-1",
            role=v10.Role.role_user,
            parts=[v10.Part(text="hi")],
        ),
    )
    params = convert_to_v03(req)
    assert isinstance(params, v03.MessageSendParams)
    assert params.message.message_id == "m-1"
    assert params.message.role is v03.Role.user
    assert len(params.message.parts) == 1


def test_tenant_on_send_message_request_emits_warning() -> None:
    req = v10.SendMessageRequest(
        message=v10.Message(
            message_id="m-1",
            role=v10.Role.role_user,
            parts=[v10.Part(text="hi")],
        ),
        tenant="acme",
    )
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        convert_to_v03(req)

    tenant_warnings = [w for w in captured if "tenant" in str(w.message)]
    assert len(tenant_warnings) == 1
    assert "acme" in str(tenant_warnings[0].message)


def test_multi_payload_part_warns_and_keeps_text() -> None:
    # v10.Part's one-of validator blocks normal construction of a
    # multi-payload part, but the converter still defends against values
    # that bypassed validation (e.g. model_construct, post-construction
    # attribute assignment). Use model_construct to reproduce that state.
    part = v10.Part.model_construct(text="hi", url="https://x/y", media_type="text/plain")
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        out = convert_to_v03(part)

    assert isinstance(out, v03.Part)
    assert isinstance(out.root, v03.TextPart)
    assert out.root.text == "hi"
    assert any("multiple payloads" in str(w.message) for w in captured)


def test_task_state_enum_maps() -> None:
    status = v10.TaskStatus(state=v10.TaskState.task_state_completed)
    out = convert_to_v03(status)
    assert out.state is v03.TaskState.completed


def test_unsupported_type_raises() -> None:
    with pytest.raises(TypeError, match="No v10 -> v03 converter registered"):
        convert_to_v03(42)  # type: ignore[arg-type]
