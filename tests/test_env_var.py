"""A2A_VERSION env var resolution and strict no-default behaviour."""

from __future__ import annotations

import pytest

from a2a_pydantic import A2AVersionError, Message, Part, Role
from a2a_pydantic._config import resolve_version


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv("A2A_VERSION", raising=False)


class TestResolveVersion:
    def test_no_source_raises(self, clean_env):
        with pytest.raises(A2AVersionError):
            resolve_version()

    def test_explicit_overrides_env(self, monkeypatch):
        monkeypatch.setenv("A2A_VERSION", "0.3")
        assert resolve_version("1.0") == "1.0"

    def test_env_resolves(self, monkeypatch):
        monkeypatch.setenv("A2A_VERSION", "0.3")
        assert resolve_version() == "0.3"

    def test_env_full_semver(self, monkeypatch):
        monkeypatch.setenv("A2A_VERSION", "0.3.0")
        assert resolve_version() == "0.3"
        monkeypatch.setenv("A2A_VERSION", "1.0.0")
        assert resolve_version() == "1.0"

    def test_invalid_env_falls_through_and_raises(self, monkeypatch):
        monkeypatch.setenv("A2A_VERSION", "garbage")
        with pytest.raises(A2AVersionError):
            resolve_version()

    def test_invalid_explicit_with_valid_env_uses_env(self, monkeypatch):
        monkeypatch.setenv("A2A_VERSION", "1.0")
        assert resolve_version("garbage") == "1.0"


class TestDumpUsesEnv:
    def test_dump_without_source_raises(self, clean_env):
        msg = Message(role=Role.USER, parts=[Part(text="hi")], message_id="m")
        with pytest.raises(A2AVersionError):
            msg.dump()

    def test_env_drives_dump(self, monkeypatch):
        monkeypatch.setenv("A2A_VERSION", "0.3")
        msg = Message(role=Role.USER, parts=[Part(text="hi")], message_id="m")
        out = msg.dump()
        assert out["role"] == "user"

    def test_explicit_overrides_env(self, monkeypatch):
        monkeypatch.setenv("A2A_VERSION", "0.3")
        msg = Message(role=Role.USER, parts=[Part(text="hi")], message_id="m")
        out = msg.dump(version="1.0")
        assert out["role"] == "ROLE_USER"

    def test_old_env_var_name_is_not_recognised(self, monkeypatch, clean_env):
        monkeypatch.setenv("A2A_PROTOCOL_VERSION", "0.3")
        msg = Message(role=Role.USER, parts=[Part(text="hi")], message_id="m")
        with pytest.raises(A2AVersionError):
            msg.dump()
