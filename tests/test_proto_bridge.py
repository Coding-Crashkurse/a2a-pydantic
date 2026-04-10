"""Tests for the optional :mod:`a2a_pydantic.proto` bridge.

These run against the repo-root [a2a_pb2.py](../a2a_pb2.py) (a real
generated v1.0 proto module). The conftest fixture puts the repo root on
``sys.path`` so the tests don't need ``a2a-sdk`` installed; the only
runtime requirement is the ``protobuf`` package itself.

Coverage groups:

- **Auto-import** path (only when ``a2a-sdk`` happens to be installed)
- **Helpful error** when neither pb2 nor a2a-sdk is available
- **Data primitives** — Message, Task, Artifact, status events
- **Renamed types** — class-name renames (MessageSendConfiguration →
  SendMessageConfiguration, MutualTLSSecurityScheme → MutualTlsSecurityScheme,
  PushNotificationAuthenticationInfo → AuthenticationInfo)
- **Field renames** — APIKeySecurityScheme ``in`` → ``location``
- **Structural rewrites** — TaskPushNotificationConfig flattening,
  SendMessageConfiguration nested-config projection
- **Oneof wrapping** — SecurityScheme variants nested inside AgentCard
- **AgentCard** end-to-end with skills, provider, security schemes
- **MessageSendParams** → SendMessageRequest (the headline FastAPI →
  AgentExecutor use case)
- **Wire round-trip** — SerializeToString / ParseFromString to confirm the
  produced proto is actually wire-valid
"""

from __future__ import annotations

import importlib.util

import pytest

import a2a_pb2  # repo-root reference proto
from a2a_pydantic import (
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
    HTTPAuthSecurityScheme,
    Message,
    MessageSendConfiguration,
    MessageSendParams,
    MutualTLSSecurityScheme,
    OAuth2SecurityScheme,
    OAuthFlows,
    OpenIdConnectSecurityScheme,
    Part,
    PushNotificationAuthenticationInfo,
    PushNotificationConfig,
    Role,
    Task,
    TaskArtifactUpdateEvent,
    TaskPushNotificationConfig,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from a2a_pydantic.proto import to_proto

HAS_A2A_SDK = importlib.util.find_spec("a2a") is not None


@pytest.mark.skipif(HAS_A2A_SDK, reason="a2a-sdk is installed")
class TestAutoImportMissing:
    def test_helpful_error_when_no_sdk_and_no_pb2(self):
        msg = Message(role=Role.USER, parts=[Part(text="x")], message_id="m")
        with pytest.raises(ImportError, match="pb2"):
            to_proto(msg)


class TestPrimitives:
    def test_message(self):
        msg = Message(
            role=Role.USER,
            parts=[Part(text="hello")],
            message_id="m1",
            context_id="c1",
        )
        proto = to_proto(msg, pb2=a2a_pb2)
        assert proto.message_id == "m1"
        assert proto.context_id == "c1"
        assert proto.parts[0].text == "hello"

    def test_task(self):
        task = Task(
            id="t1",
            context_id="c1",
            status=TaskStatus(state=TaskState.COMPLETED),
        )
        proto = to_proto(task, pb2=a2a_pb2)
        assert proto.id == "t1"
        assert proto.context_id == "c1"
        assert proto.status.state == a2a_pb2.TASK_STATE_COMPLETED

    def test_task_status_canceled(self):
        """Both US (CANCELED) and UK (CANCELLED) spellings of the proto enum
        round-trip — the bridge rewrites the dumped enum string at runtime."""
        status = TaskStatus(state=TaskState.CANCELED)
        proto = to_proto(status, pb2=a2a_pb2)
        canceled = getattr(
            a2a_pb2, "TASK_STATE_CANCELED", getattr(a2a_pb2, "TASK_STATE_CANCELLED", None)
        )
        assert canceled is not None
        assert proto.state == canceled

    def test_artifact(self):
        artifact = Artifact(
            artifact_id="a1", parts=[Part(text="x")], name="thing"
        )
        proto = to_proto(artifact, pb2=a2a_pb2)
        assert proto.artifact_id == "a1"
        assert proto.name == "thing"

    def test_status_update_event(self):
        event = TaskStatusUpdateEvent(
            task_id="t1",
            context_id="c1",
            status=TaskStatus(state=TaskState.WORKING),
        )
        proto = to_proto(event, pb2=a2a_pb2)
        assert proto.task_id == "t1"

    def test_artifact_update_event(self):
        event = TaskArtifactUpdateEvent(
            task_id="t1",
            context_id="c1",
            artifact=Artifact(artifact_id="a1", parts=[Part(text="x")]),
        )
        proto = to_proto(event, pb2=a2a_pb2)
        assert proto.task_id == "t1"
        assert proto.artifact.artifact_id == "a1"


class TestRenamedTypes:
    def test_message_send_configuration_class_rename(self):
        cfg = MessageSendConfiguration(
            accepted_output_modes=["text"], history_length=5
        )
        proto = to_proto(cfg, pb2=a2a_pb2)
        assert isinstance(proto, a2a_pb2.SendMessageConfiguration)
        assert list(proto.accepted_output_modes) == ["text"]
        assert proto.history_length == 5

    def test_authentication_info_class_rename(self):
        auth = PushNotificationAuthenticationInfo(
            scheme="Bearer", credentials="abc"
        )
        proto = to_proto(auth, pb2=a2a_pb2)
        assert isinstance(proto, a2a_pb2.AuthenticationInfo)
        assert proto.scheme == "Bearer"
        assert proto.credentials == "abc"

    def test_mutual_tls_class_rename(self):
        mtls = MutualTLSSecurityScheme(description="client cert")
        proto = to_proto(mtls, pb2=a2a_pb2)
        assert isinstance(proto, a2a_pb2.MutualTlsSecurityScheme)
        assert proto.description == "client cert"


class TestFieldRenames:
    def test_api_key_in_to_location(self):
        scheme = APIKeySecurityScheme(name="X-API-Key", in_="header")
        proto = to_proto(scheme, pb2=a2a_pb2)
        assert isinstance(proto, a2a_pb2.APIKeySecurityScheme)
        assert proto.name == "X-API-Key"
        assert proto.location == "header"

    def test_security_scheme_type_discriminator_dropped(self):
        scheme = HTTPAuthSecurityScheme(scheme="bearer", bearer_format="JWT")
        proto = to_proto(scheme, pb2=a2a_pb2)
        assert proto.scheme == "bearer"
        assert proto.bearer_format == "JWT"


class TestStructuralRewrites:
    def test_task_push_notification_config_flattens(self):
        tpc = TaskPushNotificationConfig(
            task_id="t1",
            push_notification_config=PushNotificationConfig(
                url="https://hook", token="tok", id="n1"
            ),
        )
        proto = to_proto(tpc, pb2=a2a_pb2)
        assert proto.task_id == "t1"
        assert proto.url == "https://hook"
        assert proto.token == "tok"
        assert proto.id == "n1"

    def test_task_push_notification_with_authentication(self):
        tpc = TaskPushNotificationConfig(
            task_id="t1",
            push_notification_config=PushNotificationConfig(
                url="https://hook",
                authentication=PushNotificationAuthenticationInfo(
                    scheme="Bearer", credentials="abc"
                ),
            ),
        )
        proto = to_proto(tpc, pb2=a2a_pb2)
        assert proto.authentication.scheme == "Bearer"
        assert proto.authentication.credentials == "abc"

    def test_send_message_configuration_with_inner_push_config(self):
        cfg = MessageSendConfiguration(
            accepted_output_modes=["text"],
            task_push_notification_config=PushNotificationConfig(
                url="https://hook"
            ),
        )
        proto = to_proto(cfg, pb2=a2a_pb2)
        assert proto.task_push_notification_config.url == "https://hook"


class TestSecuritySchemeOneof:
    """When SecurityScheme is nested inside AgentCard.security_schemes (a map<string, SecurityScheme>),
    each value must be wrapped in the proto's oneof container by ``type``."""

    def _card(self, schemes: dict[str, object]) -> AgentCard:
        return AgentCard(
            name="t",
            description="d",
            version="1.0",
            url="https://x",
            preferred_transport="JSONRPC",
            capabilities=AgentCapabilities(streaming=True),
            skills=[
                AgentSkill(
                    id="s1", name="S", description="d", tags=["a"]
                )
            ],
            security_schemes=schemes,
        )

    def test_apikey_wrapped_into_oneof(self):
        card = self._card(
            {"k": APIKeySecurityScheme(name="X-API-Key", in_="query")}
        )
        proto = to_proto(card, pb2=a2a_pb2)
        wrapped = proto.security_schemes["k"]
        assert wrapped.WhichOneof("scheme") == "api_key_security_scheme"
        assert wrapped.api_key_security_scheme.name == "X-API-Key"
        assert wrapped.api_key_security_scheme.location == "query"

    def test_http_wrapped_into_oneof(self):
        card = self._card({"k": HTTPAuthSecurityScheme(scheme="bearer")})
        proto = to_proto(card, pb2=a2a_pb2)
        wrapped = proto.security_schemes["k"]
        assert wrapped.WhichOneof("scheme") == "http_auth_security_scheme"
        assert wrapped.http_auth_security_scheme.scheme == "bearer"

    def test_oauth2_wrapped_into_oneof(self):
        oauth = OAuth2SecurityScheme(
            flows=OAuthFlows(
                authorization_code=AuthorizationCodeOAuthFlow(
                    authorization_url="https://a",
                    token_url="https://t",
                    scopes={"r": "read"},
                )
            )
        )
        card = self._card({"k": oauth})
        proto = to_proto(card, pb2=a2a_pb2)
        wrapped = proto.security_schemes["k"]
        assert wrapped.WhichOneof("scheme") == "oauth2_security_scheme"
        flow = wrapped.oauth2_security_scheme.flows.authorization_code
        assert flow.authorization_url == "https://a"

    def test_openid_wrapped_into_oneof(self):
        card = self._card(
            {"k": OpenIdConnectSecurityScheme(open_id_connect_url="https://x")}
        )
        proto = to_proto(card, pb2=a2a_pb2)
        wrapped = proto.security_schemes["k"]
        assert wrapped.WhichOneof("scheme") == "open_id_connect_security_scheme"

    def test_mtls_wrapped_into_oneof(self):
        card = self._card({"k": MutualTLSSecurityScheme(description="d")})
        proto = to_proto(card, pb2=a2a_pb2)
        wrapped = proto.security_schemes["k"]
        assert wrapped.WhichOneof("scheme") == "mtls_security_scheme"


class TestAgentCardEndToEnd:
    def test_full_card(self):
        card = AgentCard(
            name="recipe",
            description="cooks",
            version="1.0",
            url="https://x",
            preferred_transport="JSONRPC",
            capabilities=AgentCapabilities(
                streaming=True,
                push_notifications=False,
                extensions=[
                    AgentExtension(uri="ext://x", description="d", required=True)
                ],
            ),
            skills=[
                AgentSkill(
                    id="s1",
                    name="S",
                    description="d",
                    tags=["cooking"],
                    input_modes=["text/plain"],
                    output_modes=["text/plain"],
                )
            ],
            provider=AgentProvider(organization="ACME", url="https://acme.com"),
            documentation_url="https://docs",
            icon_url="https://icon",
            signatures=[
                AgentCardSignature(protected="p", signature="s", header={"kid": "k"})
            ],
        )
        proto = to_proto(card, pb2=a2a_pb2)
        assert proto.name == "recipe"
        assert proto.provider.organization == "ACME"
        assert proto.documentation_url == "https://docs"
        assert proto.icon_url == "https://icon"
        assert len(proto.skills) == 1
        assert proto.skills[0].id == "s1"
        assert proto.capabilities.streaming is True
        assert len(proto.capabilities.extensions) == 1
        assert proto.signatures[0].protected == "p"


class TestMessageSendParamsToRequest:
    """The headline use case: FastAPI receives MessageSendParams, hands it
    to an a2a-sdk AgentExecutor as a SendMessageRequest proto."""

    def test_full_send_message_request(self):
        params = MessageSendParams(
            message=Message(
                role=Role.USER,
                parts=[Part(text="hi")],
                message_id="m1",
                context_id="c1",
            ),
            configuration=MessageSendConfiguration(
                accepted_output_modes=["text"], history_length=10
            ),
            metadata={"trace_id": "abc"},
        )
        proto = to_proto(params, pb2=a2a_pb2)
        assert isinstance(proto, a2a_pb2.SendMessageRequest)
        assert proto.message.message_id == "m1"
        assert proto.message.parts[0].text == "hi"
        assert list(proto.configuration.accepted_output_modes) == ["text"]
        assert proto.configuration.history_length == 10
        assert proto.metadata["trace_id"] == "abc"


class TestWireRoundTrip:
    """Confirm the produced proto messages survive a full serialise / parse cycle."""

    def test_message_wire(self):
        msg = Message(
            role=Role.USER, parts=[Part(text="hi")], message_id="m1"
        )
        proto = to_proto(msg, pb2=a2a_pb2)
        wire = proto.SerializeToString()
        parsed = a2a_pb2.Message()
        parsed.ParseFromString(wire)
        assert parsed.message_id == "m1"

    def test_agent_card_wire(self):
        card = AgentCard(
            name="t",
            description="d",
            version="1",
            url="https://x",
            preferred_transport="JSONRPC",
            capabilities=AgentCapabilities(streaming=True),
            skills=[
                AgentSkill(id="s1", name="S", description="d", tags=["a"])
            ],
            security_schemes={
                "k": APIKeySecurityScheme(name="X-API-Key", in_="header")
            },
        )
        proto = to_proto(card, pb2=a2a_pb2)
        wire = proto.SerializeToString()
        parsed = a2a_pb2.AgentCard()
        parsed.ParseFromString(wire)
        assert parsed.name == "t"
        assert (
            parsed.security_schemes["k"].api_key_security_scheme.location
            == "header"
        )


class TestUnsupportedTypeRaises:
    def test_unsupported_raises_typeerror(self):
        with pytest.raises(TypeError, match="does not support"):
            to_proto("not a model", pb2=a2a_pb2)


class TestExplicitInterface:
    """The most common single AgentInterface field — verify the field rename
    transport → protocol_binding works through the bridge."""

    def test_agent_interface_protocol_binding(self):
        iface = AgentInterface(url="https://x", transport="GRPC")
        proto = to_proto(iface, pb2=a2a_pb2)
        assert proto.url == "https://x"
        assert proto.protocol_binding == "GRPC"
