from typing import Any

from a2a_pydantic.base import _ONE_OF_FIELDS
from a2a_pydantic.v10 import models as _models
from a2a_pydantic.v10.models import *  # noqa: F401,F403

# v1.0 spec pins the following as "exactly one of" unions that the proto-derived
# JSON Schema leaves as flat optional fields. Register them so A2ABaseModel's
# _enforce_one_of validator fires at construction time.
_ONE_OF_FIELDS.update(
    {
        _models.Part: ("text", "raw", "url", "data"),
        _models.SecurityScheme: (
            "api_key_security_scheme",
            "http_auth_security_scheme",
            "oauth2_security_scheme",
            "open_id_connect_security_scheme",
            "mtls_security_scheme",
        ),
        _models.OAuthFlows: (
            "authorization_code",
            "client_credentials",
            "implicit",
            "password",
            "device_code",
        ),
        _models.SendMessageResponse: ("task", "message"),
        _models.StreamResponse: (
            "task",
            "message",
            "status_update",
            "artifact_update",
        ),
    }
)


# Timestamp is generated as RootModel[AwareDatetime] with no ordering dunders,
# so `sorted(tasks, key=lambda t: t.status.timestamp)` raises TypeError. Patch
# ordering here (not in models.py) because models.py is regenerated from the
# JSON Schema and manual edits would be lost. setattr is used instead of
# direct attribute assignment to sidestep mypy's method-assign check — the
# generated Timestamp class has no typing info mypy can reason about here.
def _timestamp_lt(self: Any, other: Any) -> Any:
    if isinstance(other, _models.Timestamp):
        return self.root < other.root
    return NotImplemented


def _timestamp_le(self: Any, other: Any) -> Any:
    if isinstance(other, _models.Timestamp):
        return self.root <= other.root
    return NotImplemented


def _timestamp_gt(self: Any, other: Any) -> Any:
    if isinstance(other, _models.Timestamp):
        return self.root > other.root
    return NotImplemented


def _timestamp_ge(self: Any, other: Any) -> Any:
    if isinstance(other, _models.Timestamp):
        return self.root >= other.root
    return NotImplemented


setattr(_models.Timestamp, "__lt__", _timestamp_lt)  # noqa: B010
setattr(_models.Timestamp, "__le__", _timestamp_le)  # noqa: B010
setattr(_models.Timestamp, "__gt__", _timestamp_gt)  # noqa: B010
setattr(_models.Timestamp, "__ge__", _timestamp_ge)  # noqa: B010


# TaskState values are uppercase on the wire (proto convention), but member
# names are lowercase. Make `TaskState("submitted")` and `TaskState("Submitted")`
# resolve to the same member as `TaskState("TASK_STATE_SUBMITTED")`, so callers
# storing the state as a string (Redis/SQL) don't have to normalize case.
def _task_state_missing(cls: Any, value: Any) -> Any:
    if not isinstance(value, str):
        return None
    upper = value.upper()
    if not upper.startswith("TASK_STATE_"):
        upper = f"TASK_STATE_{upper}"
    for member in cls:
        if member.value == upper:
            return member
    return None


setattr(_models.TaskState, "_missing_", classmethod(_task_state_missing))  # noqa: B010
