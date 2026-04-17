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


def test_get_task_request_converts_with_tenant_warning() -> None:
    req = v10.GetTaskRequest(id="t-1", tenant="acme", history_length=5)
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        out = convert_to_v03(req)
    assert isinstance(out, v03.TaskQueryParams)
    assert out.id == "t-1"
    assert out.history_length == 5
    assert any("tenant" in str(w.message) for w in captured)


def test_cancel_task_request_converts() -> None:
    req = v10.CancelTaskRequest(id="t-2")
    out = convert_to_v03(req)
    assert isinstance(out, v03.TaskIdParams)
    assert out.id == "t-2"


def test_subscribe_to_task_request_converts() -> None:
    req = v10.SubscribeToTaskRequest(id="t-3")
    out = convert_to_v03(req)
    assert isinstance(out, v03.TaskIdParams)
    assert out.id == "t-3"


def test_get_push_notification_config_request_remaps_ids() -> None:
    # In v1.0 the task_id is the path-parent and `id` is the config id.
    # v0.3 flattens this: TaskQueryParams-style where `id` is the task
    # and push_notification_config_id is the nested config id.
    req = v10.GetTaskPushNotificationConfigRequest(task_id="t-4", id="cfg-1")
    out = convert_to_v03(req)
    assert isinstance(out, v03.GetTaskPushNotificationConfigParams)
    assert out.id == "t-4"
    assert out.push_notification_config_id == "cfg-1"


def test_delete_push_notification_config_request_remaps_ids() -> None:
    req = v10.DeleteTaskPushNotificationConfigRequest(task_id="t-5", id="cfg-2")
    out = convert_to_v03(req)
    assert isinstance(out, v03.DeleteTaskPushNotificationConfigParams)
    assert out.id == "t-5"
    assert out.push_notification_config_id == "cfg-2"


def test_list_push_notification_configs_request_warns_on_pagination() -> None:
    req = v10.ListTaskPushNotificationConfigsRequest(task_id="t-6", page_size=50, page_token="abc")
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        out = convert_to_v03(req)
    assert isinstance(out, v03.ListTaskPushNotificationConfigParams)
    assert out.id == "t-6"
    messages = [str(w.message) for w in captured]
    assert any("page_size" in m for m in messages)
    assert any("page_token" in m for m in messages)
