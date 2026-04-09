"""Enum dual-accept and value mapping."""

from __future__ import annotations

import pytest

from a2a_pydantic import Role, TaskState, TransportProtocol


class TestTaskState:
    def test_canonical_v10_value(self):
        assert TaskState.COMPLETED.value == "TASK_STATE_COMPLETED"
        assert TaskState.SUBMITTED.value == "TASK_STATE_SUBMITTED"
        assert TaskState.WORKING.value == "TASK_STATE_WORKING"

    def test_accept_v03_string(self):
        assert TaskState("completed") is TaskState.COMPLETED
        assert TaskState("submitted") is TaskState.SUBMITTED
        assert TaskState("input-required") is TaskState.INPUT_REQUIRED
        assert TaskState("auth-required") is TaskState.AUTH_REQUIRED

    def test_accept_v10_string(self):
        assert TaskState("TASK_STATE_COMPLETED") is TaskState.COMPLETED

    def test_accept_loose(self):
        assert TaskState("COMPLETED") is TaskState.COMPLETED
        assert TaskState("Completed") is TaskState.COMPLETED

    def test_unknown_maps_to_unspecified(self):
        # v0.3 had "unknown" which we route to v1.0 UNSPECIFIED.
        assert TaskState("unknown") is TaskState.UNSPECIFIED

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            TaskState("not-a-state")


class TestRole:
    def test_canonical(self):
        assert Role.USER.value == "ROLE_USER"
        assert Role.AGENT.value == "ROLE_AGENT"

    def test_accept_v03(self):
        assert Role("user") is Role.USER
        assert Role("agent") is Role.AGENT

    def test_accept_v10(self):
        assert Role("ROLE_USER") is Role.USER

    def test_accept_loose(self):
        assert Role("USER") is Role.USER


class TestTransportProtocol:
    def test_values(self):
        assert TransportProtocol.JSONRPC.value == "JSONRPC"
        assert TransportProtocol.GRPC.value == "GRPC"
        assert TransportProtocol.HTTP_JSON.value == "HTTP+JSON"

    def test_lookup(self):
        assert TransportProtocol("JSONRPC") is TransportProtocol.JSONRPC
        assert TransportProtocol("HTTP+JSON") is TransportProtocol.HTTP_JSON
