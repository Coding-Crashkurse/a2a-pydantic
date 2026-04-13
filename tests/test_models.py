"""Smoke tests for v1.0 and v0.3 model construction."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from a2a_pydantic import v03, v10


def test_v10_message_minimal() -> None:
    msg = v10.Message(
        message_id="m-1",
        role=v10.Role.role_user,
        parts=[v10.Part(text="hi")],
    )
    assert msg.message_id == "m-1"
    assert msg.role is v10.Role.role_user
    assert msg.parts[0].text == "hi"


def test_v10_role_enum_values() -> None:
    assert v10.Role.role_user.value == "ROLE_USER"
    assert v10.Role.role_agent.value == "ROLE_AGENT"


def test_v10_send_message_request_accepts_tenant() -> None:
    req = v10.SendMessageRequest(
        message=v10.Message(
            message_id="m-1",
            role=v10.Role.role_user,
            parts=[v10.Part(text="hi")],
        ),
        tenant="acme",
    )
    assert req.tenant == "acme"


def test_v10_rejects_invalid_role() -> None:
    with pytest.raises(ValidationError):
        v10.Message(
            message_id="m-1",
            role="NOT_A_ROLE",  # type: ignore[arg-type]
            parts=[v10.Part(text="hi")],
        )


def test_v03_part_is_discriminated_union() -> None:
    part = v03.Part(root=v03.TextPart(text="hi"))
    assert isinstance(part.root, v03.TextPart)
    assert part.root.text == "hi"


def test_v03_role_lowercase() -> None:
    assert v03.Role.user.value == "user"
    assert v03.Role.agent.value == "agent"


def test_v10_camelcase_alias_on_wire() -> None:
    msg = v10.Message(
        message_id="m-1",
        role=v10.Role.role_user,
        parts=[v10.Part(text="hi")],
    )
    wire = msg.model_dump(by_alias=True, exclude_none=True)
    assert "messageId" in wire
    assert "message_id" not in wire
