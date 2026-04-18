"""Tests for the v0.3 -> v1.0 upward converter."""

from __future__ import annotations

import warnings

import pytest

from a2a_pydantic import convert_to_v10, v03, v10


def test_send_message_params_roundtrips_core_fields() -> None:
    params = v03.MessageSendParams(
        message=v03.Message(
            message_id="m-1",
            role=v03.Role.user,
            parts=[v03.Part(root=v03.TextPart(text="hi"))],
        ),
    )
    req = convert_to_v10(params)
    assert isinstance(req, v10.SendMessageRequest)
    assert req.message.message_id == "m-1"
    assert req.message.role is v10.Role.role_user
    assert len(req.message.parts) == 1
    assert req.message.parts[0].text == "hi"


def test_tenant_kwarg_fills_request_and_is_scoped() -> None:
    params = v03.MessageSendParams(
        message=v03.Message(
            message_id="m-1",
            role=v03.Role.user,
            parts=[v03.Part(root=v03.TextPart(text="hi"))],
        ),
    )
    with_tenant = convert_to_v10(params, tenant="acme-corp")
    assert with_tenant.tenant == "acme-corp"

    # Kwarg must not leak into a later kwarg-free call.
    without_tenant = convert_to_v10(params)
    assert without_tenant.tenant == ""


def test_message_extensions_kwarg_overrides_when_v03_empty() -> None:
    params = v03.MessageSendParams(
        message=v03.Message(
            message_id="m-1",
            role=v03.Role.user,
            parts=[v03.Part(root=v03.TextPart(text="hi"))],
        ),
    )
    req = convert_to_v10(params, message_extensions=["urn:ext:foo"])
    assert req.message.extensions == ["urn:ext:foo"]


def test_message_extensions_kwarg_overrides_even_when_v03_has_values() -> None:
    # Author's spec: when caller passes the kwarg, it wins — the caller
    # signaled they know what they want.
    params = v03.MessageSendParams(
        message=v03.Message(
            message_id="m-1",
            role=v03.Role.user,
            parts=[v03.Part(root=v03.TextPart(text="hi"))],
            extensions=["urn:from:v03"],
        ),
    )
    req = convert_to_v10(params, message_extensions=["urn:override"])
    assert req.message.extensions == ["urn:override"]


def test_role_enum_maps() -> None:
    assert convert_to_v10(v03.Role.user) is v10.Role.role_user
    assert convert_to_v10(v03.Role.agent) is v10.Role.role_agent


def test_task_state_enum_maps() -> None:
    assert convert_to_v10(v03.TaskState.submitted) is v10.TaskState.task_state_submitted
    assert convert_to_v10(v03.TaskState.completed) is v10.TaskState.task_state_completed


def test_task_state_unknown_coerces_with_warning() -> None:
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        out = convert_to_v10(v03.TaskState.unknown)
    assert out is v10.TaskState.task_state_submitted
    assert any("unknown" in str(w.message).lower() for w in captured)


class TestPart:
    def test_text_part(self) -> None:
        part = v03.Part(root=v03.TextPart(text="hi"))
        out = convert_to_v10(part)
        assert out.text == "hi"

    def test_data_part_wraps_in_value(self) -> None:
        part = v03.Part(root=v03.DataPart(data={"k": 1}))
        out = convert_to_v10(part)
        assert out.data is not None
        assert out.data.root == {"k": 1}
        assert out.media_type == "application/json"

    def test_file_with_bytes_maps_to_raw(self) -> None:
        part = v03.Part(
            root=v03.FilePart(
                file=v03.FileWithBytes(bytes="aGVsbG8=", mime_type="text/plain", name="h.txt")
            )
        )
        out = convert_to_v10(part)
        assert out.raw == "aGVsbG8="
        assert out.media_type == "text/plain"
        assert out.filename == "h.txt"

    def test_file_with_uri_maps_to_url(self) -> None:
        part = v03.Part(
            root=v03.FilePart(file=v03.FileWithUri(uri="https://x/y.pdf", mime_type="app/pdf"))
        )
        out = convert_to_v10(part)
        assert out.url == "https://x/y.pdf"
        assert out.media_type == "app/pdf"


def test_task_timestamp_parses_iso_to_timestamp() -> None:
    task = v03.Task(
        id="t-1",
        context_id="c-1",
        status=v03.TaskStatus(
            state=v03.TaskState.completed,
            timestamp="2026-03-01T10:15:30+00:00",
        ),
    )
    out = convert_to_v10(task)
    assert out.status.timestamp is not None
    assert out.status.timestamp.root.isoformat() == "2026-03-01T10:15:30+00:00"


def test_task_metadata_dict_wraps_in_struct() -> None:
    task = v03.Task(
        id="t-1",
        context_id="c-1",
        status=v03.TaskStatus(state=v03.TaskState.completed),
        metadata={"trace_id": "abc"},
    )
    out = convert_to_v10(task)
    assert isinstance(out.metadata, v10.Struct)
    assert out.metadata.model_dump(by_alias=False, exclude_none=True) == {"trace_id": "abc"}


def test_push_notification_auth_multi_scheme_warns_and_keeps_first() -> None:
    auth = v03.PushNotificationAuthenticationInfo(schemes=["Bearer", "Basic"], credentials="tok")
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        out = convert_to_v10(auth)
    assert out.scheme == "Bearer"
    assert out.credentials == "tok"
    assert any("multiple entries" in str(w.message) for w in captured)


def test_blocking_true_maps_to_return_immediately_false() -> None:
    cfg = v03.MessageSendConfiguration(blocking=True)
    out = convert_to_v10(cfg)
    assert out.return_immediately is False


def test_blocking_false_maps_to_return_immediately_true() -> None:
    cfg = v03.MessageSendConfiguration(blocking=False)
    out = convert_to_v10(cfg)
    assert out.return_immediately is True


def test_task_push_notification_config_flat_conversion() -> None:
    cfg = v03.TaskPushNotificationConfig(
        task_id="t-1",
        push_notification_config=v03.PushNotificationConfig(
            url="https://notify/x",
            id="cfg-1",
            token="tok",
        ),
    )
    out = convert_to_v10(cfg, tenant="acme")
    assert out.task_id == "t-1"
    assert out.url == "https://notify/x"
    assert out.id == "cfg-1"
    assert out.token == "tok"
    assert out.tenant == "acme"


class TestAgentCard:
    def _card(self, **overrides: object) -> v03.AgentCard:
        kwargs: dict[str, object] = dict(
            capabilities=v03.AgentCapabilities(streaming=True, push_notifications=False),
            default_input_modes=["text/plain"],
            default_output_modes=["text/plain"],
            description="test agent",
            name="TestAgent",
            skills=[
                v03.AgentSkill(
                    description="do the thing",
                    id="skill-1",
                    name="Thing",
                    tags=["demo"],
                )
            ],
            url="https://main/a2a",
            version="0.1.0",
            preferred_transport="JSONRPC",
        )
        kwargs.update(overrides)
        return v03.AgentCard(**kwargs)  # type: ignore[arg-type]

    def test_main_interface_comes_first(self) -> None:
        card = self._card(
            additional_interfaces=[
                v03.AgentInterface(transport="GRPC", url="https://grpc/a2a"),
            ]
        )
        out = convert_to_v10(card, tenant="acme")
        assert out.supported_interfaces[0].url == "https://main/a2a"
        assert out.supported_interfaces[0].protocol_binding == "JSONRPC"
        assert out.supported_interfaces[0].tenant == "acme"
        assert out.supported_interfaces[1].url == "https://grpc/a2a"
        assert out.supported_interfaces[1].protocol_binding == "GRPC"

    def test_security_list_maps_to_requirements(self) -> None:
        card = self._card(security=[{"google": ["oidc"]}])
        out = convert_to_v10(card)
        assert out.security_requirements is not None
        req = out.security_requirements[0]
        assert "google" in req.schemes
        assert list(req.schemes["google"].strings) == ["oidc"]

    def test_extended_card_flag_preserved(self) -> None:
        card = self._card(supports_authenticated_extended_card=True)
        out = convert_to_v10(card)
        assert out.capabilities.extended_agent_card is True


class TestSecurityScheme:
    def test_api_key_roundtrips(self) -> None:
        s = v03.SecurityScheme(root=v03.APIKeySecurityScheme(in_=v03.In.header, name="X-Key"))
        out = convert_to_v10(s)
        assert out.api_key_security_scheme is not None
        assert out.api_key_security_scheme.location == "header"
        assert out.api_key_security_scheme.name == "X-Key"

    def test_oauth2_roundtrips(self) -> None:
        s = v03.SecurityScheme(
            root=v03.OAuth2SecurityScheme(
                flows=v03.OAuthFlows(
                    authorization_code=v03.AuthorizationCodeOAuthFlow(
                        authorization_url="https://auth",
                        token_url="https://tok",
                        scopes={},
                    )
                ),
            )
        )
        out = convert_to_v10(s)
        assert out.oauth2_security_scheme is not None
        assert out.oauth2_security_scheme.flows.authorization_code is not None


def test_oauth_flows_multi_warns_and_keeps_first() -> None:
    flows = v03.OAuthFlows(
        authorization_code=v03.AuthorizationCodeOAuthFlow(
            authorization_url="https://auth",
            token_url="https://tok",
            scopes={},
        ),
        implicit=v03.ImplicitOAuthFlow(authorization_url="https://auth", scopes={}),
    )
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        out = convert_to_v10(flows)
    assert out.authorization_code is not None
    assert out.implicit is None
    assert any("multiple flows" in str(w.message) for w in captured)


def test_unsupported_type_raises() -> None:
    with pytest.raises(TypeError, match="No v03 -> v10 converter registered"):
        convert_to_v10(42)  # type: ignore[call-overload]


def test_state_transition_history_drop_warns() -> None:
    caps = v03.AgentCapabilities(state_transition_history=True, streaming=True)
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        convert_to_v10(caps)
    assert any("state_transition_history" in str(w.message) for w in captured)
