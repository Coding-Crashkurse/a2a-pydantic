"""Regression tests for v1.0 one-of validators and Struct round-trip.

Covers the three spec-conformance fixes shipped in v0.0.3:

* ``Part`` / ``SecurityScheme`` / ``OAuthFlows`` / ``SendMessageResponse`` /
  ``StreamResponse`` now enforce "exactly one of" at construction time via
  the ``_ONE_OF_FIELDS`` registry on :class:`a2a_pydantic.base.A2ABaseModel`.
* ``Struct`` is generated with ``model_config.extra='allow'`` so
  ``metadata`` / ``params`` / ``header`` payloads survive round-trips.
* ``AgentExtension.uri`` is now required (v1.0 spec table says optional,
  but prose uses it as the unique identifier and v0.3 has it required).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from a2a_pydantic import v03, v10


class TestPartOneOf:
    def test_single_text_ok(self) -> None:
        p = v10.Part(text="hi")
        assert p.text == "hi"

    def test_single_url_ok(self) -> None:
        p = v10.Part(url="https://x/y", media_type="text/plain")
        assert p.url == "https://x/y"

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must set exactly one of"):
            v10.Part()

    def test_multi_payload_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must set exactly one of"):
            v10.Part(text="a", url="b")

    def test_all_four_rejected(self) -> None:
        with pytest.raises(ValidationError):
            v10.Part(
                text="a",
                raw="cmF3",
                url="u",
                data=v10.Value(root={"k": "v"}),
            )


class TestSecuritySchemeOneOf:
    def test_single_api_key_ok(self) -> None:
        s = v10.SecurityScheme(
            api_key_security_scheme=v10.APIKeySecurityScheme(location="header", name="X-Key")
        )
        assert s.api_key_security_scheme is not None

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must set exactly one of"):
            v10.SecurityScheme()

    def test_multi_scheme_rejected(self) -> None:
        with pytest.raises(ValidationError):
            v10.SecurityScheme(
                api_key_security_scheme=v10.APIKeySecurityScheme(location="header", name="X-Key"),
                mtls_security_scheme=v10.MutualTlsSecurityScheme(),
            )


class TestOAuthFlowsOneOf:
    def test_single_flow_ok(self) -> None:
        f = v10.OAuthFlows(
            authorization_code=v10.AuthorizationCodeOAuthFlow(
                authorization_url="https://x/auth",
                token_url="https://x/token",
                scopes={},
            )
        )
        assert f.authorization_code is not None

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must set exactly one of"):
            v10.OAuthFlows()

    def test_multiple_flows_rejected(self) -> None:
        with pytest.raises(ValidationError):
            v10.OAuthFlows(
                authorization_code=v10.AuthorizationCodeOAuthFlow(
                    authorization_url="https://x/auth",
                    token_url="https://x/token",
                    scopes={},
                ),
                implicit=v10.ImplicitOAuthFlow(authorization_url="https://x/auth", scopes={}),
            )

    def test_v03_oauth_flows_still_permissive(self) -> None:
        """v0.3 OAuthFlows is the same-named class but different base — it
        must NOT inherit v10's one-of constraint (spec allows it empty)."""
        f = v03.OAuthFlows()
        assert f is not None


class TestSendMessageResponseOneOf:
    def test_task_ok(self) -> None:
        r = v10.SendMessageResponse(
            task=v10.Task(
                id="t",
                status=v10.TaskStatus(state=v10.TaskState.task_state_completed),
            )
        )
        assert r.task is not None

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            v10.SendMessageResponse()

    def test_both_rejected(self) -> None:
        with pytest.raises(ValidationError):
            v10.SendMessageResponse(
                task=v10.Task(
                    id="t",
                    status=v10.TaskStatus(state=v10.TaskState.task_state_completed),
                ),
                message=v10.Message(
                    message_id="m",
                    role=v10.Role.role_user,
                    parts=[v10.Part(text="x")],
                ),
            )


class TestStreamResponseOneOf:
    def test_message_ok(self) -> None:
        r = v10.StreamResponse(
            message=v10.Message(
                message_id="m",
                role=v10.Role.role_agent,
                parts=[v10.Part(text="x")],
            )
        )
        assert r.message is not None

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            v10.StreamResponse()


class TestStructRoundTrip:
    def test_struct_accepts_arbitrary_keys(self) -> None:
        s = v10.Struct(foo="bar", count=42, nested={"a": 1})
        dumped = s.model_dump(by_alias=False, exclude_none=True)
        assert dumped == {"foo": "bar", "count": 42, "nested": {"a": 1}}

    def test_metadata_round_trip_on_message(self) -> None:
        # Pydantic's alias_generator applies to declared fields only; Struct
        # has no declared fields (extras via extra='allow'), so user-chosen
        # metadata keys are preserved verbatim. That's the correct behavior:
        # metadata is free-form payload, not a spec-defined field.
        m = v10.Message(
            message_id="m-1",
            role=v10.Role.role_user,
            parts=[v10.Part(text="hi")],
            metadata=v10.Struct(trace_id="abc-123", retries=0),
        )
        wire = m.model_dump(by_alias=True, exclude_none=True)
        assert wire["metadata"] == {"trace_id": "abc-123", "retries": 0}


class TestAgentExtensionUriRequired:
    def test_uri_set_ok(self) -> None:
        e = v10.AgentExtension(uri="https://x/ext")
        assert e.uri == "https://x/ext"

    def test_missing_uri_rejected(self) -> None:
        with pytest.raises(ValidationError):
            v10.AgentExtension()
