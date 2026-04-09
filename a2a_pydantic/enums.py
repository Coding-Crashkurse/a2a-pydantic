"""Enum types with dual v0.3 / v1.0 accept and explicit upgrade/downgrade maps.

The canonical (internal) representation is **always v1.0**:
``"TASK_STATE_COMPLETED"``, ``"ROLE_USER"``, etc. The ``_missing_`` hook
upgrades any v0.3 wire value to its v1.0 equivalent so users can write
``TaskState("completed")`` and get :attr:`TaskState.COMPLETED`.

Per-model serialisers in :mod:`a2a_pydantic.models` use the maps in this
module to render the right wire value when ``dump(version="0.3")`` is
requested.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class TaskState(StrEnum):
    """Lifecycle state of a Task. Internal value matches the v1.0 proto enum."""

    UNSPECIFIED = "TASK_STATE_UNSPECIFIED"
    SUBMITTED = "TASK_STATE_SUBMITTED"
    WORKING = "TASK_STATE_WORKING"
    COMPLETED = "TASK_STATE_COMPLETED"
    FAILED = "TASK_STATE_FAILED"
    CANCELED = "TASK_STATE_CANCELED"
    INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
    REJECTED = "TASK_STATE_REJECTED"
    AUTH_REQUIRED = "TASK_STATE_AUTH_REQUIRED"

    @classmethod
    def _missing_(cls, value: object) -> TaskState | None:
        # Accept v0.3 wire values, full v1.0 values, and snake_case Python.
        if not isinstance(value, str):
            return None
        v03 = TASK_STATE_V03_TO_V10.get(value)
        if v03 is not None:
            return cls(v03)
        # Loose match: case-insensitive on the v1.0 form.
        upper = value.upper().replace("-", "_")
        if not upper.startswith("TASK_STATE_"):
            upper = f"TASK_STATE_{upper}"
        for member in cls:
            if member.value == upper:
                return member
        return None


# v0.3 wire value -> v1.0 enum string. Bidirectional via TASK_STATE_V10_TO_V03.
TASK_STATE_V03_TO_V10: Final[dict[str, str]] = {
    "submitted": TaskState.SUBMITTED.value,
    "working": TaskState.WORKING.value,
    "completed": TaskState.COMPLETED.value,
    "failed": TaskState.FAILED.value,
    "canceled": TaskState.CANCELED.value,
    "input-required": TaskState.INPUT_REQUIRED.value,
    "rejected": TaskState.REJECTED.value,
    "auth-required": TaskState.AUTH_REQUIRED.value,
    # v0.3 also has "unknown" which maps to v1.0 UNSPECIFIED.
    "unknown": TaskState.UNSPECIFIED.value,
}

TASK_STATE_V10_TO_V03: Final[dict[str, str]] = {
    TaskState.SUBMITTED.value: "submitted",
    TaskState.WORKING.value: "working",
    TaskState.COMPLETED.value: "completed",
    TaskState.FAILED.value: "failed",
    TaskState.CANCELED.value: "canceled",
    TaskState.INPUT_REQUIRED.value: "input-required",
    TaskState.REJECTED.value: "rejected",
    TaskState.AUTH_REQUIRED.value: "auth-required",
    TaskState.UNSPECIFIED.value: "unknown",
}


class Role(StrEnum):
    """Sender of a Message. Internal value matches the v1.0 proto enum."""

    UNSPECIFIED = "ROLE_UNSPECIFIED"
    USER = "ROLE_USER"
    AGENT = "ROLE_AGENT"

    @classmethod
    def _missing_(cls, value: object) -> Role | None:
        if not isinstance(value, str):
            return None
        v03 = ROLE_V03_TO_V10.get(value)
        if v03 is not None:
            return cls(v03)
        upper = value.upper()
        if not upper.startswith("ROLE_"):
            upper = f"ROLE_{upper}"
        for member in cls:
            if member.value == upper:
                return member
        return None


ROLE_V03_TO_V10: Final[dict[str, str]] = {
    "user": Role.USER.value,
    "agent": Role.AGENT.value,
}

ROLE_V10_TO_V03: Final[dict[str, str]] = {
    Role.USER.value: "user",
    Role.AGENT.value: "agent",
    Role.UNSPECIFIED.value: "user",  # defensive fallback; never serialised
}


class TransportProtocol(StrEnum):
    """Wire transport label. The string value is identical in v0.3 and v1.0."""

    JSONRPC = "JSONRPC"
    GRPC = "GRPC"
    HTTP_JSON = "HTTP+JSON"

    @classmethod
    def _missing_(cls, value: object) -> TransportProtocol | None:
        if not isinstance(value, str):
            return None
        upper = value.upper().replace("-", "_")
        for member in cls:
            if member.name == upper or member.value.upper() == upper:
                return member
        return None
