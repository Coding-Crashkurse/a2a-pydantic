"""AgentCard dual-format: v0.3 (url + preferredTransport) vs v1.0 (supportedInterfaces)."""

from __future__ import annotations

from a2a_pydantic import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
)


class TestAgentCardV03Input:
    def test_lifts_url_to_supported_interfaces(self):
        card = AgentCard.model_validate(
            {
                "name": "My Agent",
                "description": "An agent",
                "version": "1.0.0",
                "url": "https://agent.example.com/a2a",
                "protocolVersion": "0.3",
                "preferredTransport": "JSONRPC",
                "supportsAuthenticatedExtendedCard": True,
                "capabilities": {"streaming": True},
                "skills": [],
            }
        )
        assert len(card.supported_interfaces) == 1
        assert card.supported_interfaces[0].url == "https://agent.example.com/a2a"
        assert card.supported_interfaces[0].protocol_binding == "JSONRPC"
        assert card.capabilities.extended_agent_card is True


class TestAgentCardV10Input:
    def test_canonical_v10_form(self):
        card = AgentCard.model_validate(
            {
                "name": "My Agent",
                "description": "An agent",
                "version": "1.0.0",
                "supportedInterfaces": [
                    {
                        "url": "https://agent.example.com/a2a",
                        "protocolBinding": "JSONRPC",
                        "protocolVersion": "1.0",
                    }
                ],
                "capabilities": {"extendedAgentCard": True},
                "skills": [],
            }
        )
        assert card.supported_interfaces[0].url == "https://agent.example.com/a2a"
        assert card.supported_interfaces[0].protocol_binding == "JSONRPC"
        assert card.capabilities.extended_agent_card is True


class TestAgentCardOutput:
    def _build(self) -> AgentCard:
        return AgentCard(
            name="My Agent",
            description="An agent",
            version="1.0.0",
            capabilities=AgentCapabilities(streaming=True, extended_agent_card=True),
            supported_interfaces=[
                AgentInterface(
                    url="https://agent.example.com/a2a",
                    protocol_binding="JSONRPC",
                )
            ],
            skills=[],
        )

    def test_v10_dump(self):
        out = self._build().dump(version="1.0")
        assert out["supportedInterfaces"][0]["url"] == "https://agent.example.com/a2a"
        assert out["supportedInterfaces"][0]["protocolBinding"] == "JSONRPC"
        assert out["capabilities"]["extendedAgentCard"] is True
        # v1.0 should not emit the legacy ``url``.
        assert "url" not in out
        assert "preferredTransport" not in out
        assert "supportsAuthenticatedExtendedCard" not in out

    def test_v03_dump(self):
        out = self._build().dump(version="0.3")
        assert out["url"] == "https://agent.example.com/a2a"
        assert out["preferredTransport"] == "JSONRPC"
        assert out["supportsAuthenticatedExtendedCard"] is True
        assert "extendedAgentCard" not in out["capabilities"]
        assert "supportedInterfaces" not in out
        # v0.3 wants a protocolVersion string
        assert "protocolVersion" in out


class TestRoundTrip:
    def test_v03_in_v03_out_preserves_legacy_shape(self):
        card = AgentCard.model_validate(
            {
                "name": "My Agent",
                "description": "An agent",
                "version": "1.0.0",
                "url": "https://agent.example.com/a2a",
                "preferredTransport": "JSONRPC",
                "capabilities": {"streaming": True},
                "skills": [],
            }
        )
        out = card.dump(version="0.3")
        assert out["url"] == "https://agent.example.com/a2a"
        assert out["preferredTransport"] == "JSONRPC"
