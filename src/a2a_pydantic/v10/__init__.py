import base64
from typing import Any

from a2a_pydantic.base import _INPUT_COERCERS, _ONE_OF_FIELDS
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


# The proto-derived JSON Schema emits ``Part.filename`` and ``Part.media_type``
# as ``str | None = ""`` to mirror proto3 "unset scalar string == empty string"
# semantics. That's faithful on the wire but a papercut in Python: every
# consumer ends up writing ``p.filename or None`` to get sensible behavior.
# Flip to ``None`` here so the natural ``if p.filename:`` idiom works and the
# two states ("" / None) collapse to a single "unset" sentinel. Proto
# round-trips are unaffected because both "" and None serialize to the same
# pb2 default (empty string on the wire).
_models.Part.model_fields["filename"].default = None
_models.Part.model_fields["media_type"].default = None
_models.Part.model_rebuild(force=True)


# v10.Part takes ``data`` as a ``Value`` wrapper and ``raw`` as a base64
# string on the wire. In Python callers almost always have a plain dict /
# list / scalar for ``data`` and raw bytes for ``raw``. Coerce those inputs
# here so ``v10.Part(data={"k": "v"})`` and ``v10.Part(raw=b"...")`` just
# work without forcing every construction site to wrap or encode by hand.
def _coerce_part_inputs(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    raw = data.get("raw")
    val = data.get("data")
    needs_copy = isinstance(raw, bytes | bytearray) or (
        val is not None and not isinstance(val, _models.Value)
    )
    if not needs_copy:
        return data
    out = dict(data)
    if isinstance(raw, bytes | bytearray):
        out["raw"] = base64.b64encode(bytes(raw)).decode("ascii")
    if val is not None and not isinstance(val, _models.Value):
        out["data"] = _models.Value(root=val)
    return out


_INPUT_COERCERS[_models.Part] = _coerce_part_inputs


# v10.Struct is conceptually a typed-dict wrapper — no declared fields,
# ConfigDict(extra='allow') so every user-supplied key lands in
# __pydantic_extra__. Without a Mapping/MutableMapping API on top of that,
# callers can't do the natural ``struct.get(key)`` / ``key in struct`` /
# ``for k, v in struct.items()`` and end up with ``meta_as_dict`` /
# ``meta_as_struct`` wrapper helpers at every call site. Expose the
# MutableMapping protocol here against ``__pydantic_extra__`` directly.
#
# ``__iter__`` is overridden to yield keys (MutableMapping convention)
# rather than ``(key, value)`` tuples (BaseModel convention). Use
# ``struct.items()`` for the pair form.
def _struct_getitem(self: Any, key: str) -> Any:
    extra = self.__pydantic_extra__ or {}
    if key not in extra:
        raise KeyError(key)
    return extra[key]


def _struct_setitem(self: Any, key: str, value: Any) -> None:
    if self.__pydantic_extra__ is None:
        object.__setattr__(self, "__pydantic_extra__", {})
    self.__pydantic_extra__[key] = value


def _struct_delitem(self: Any, key: str) -> None:
    extra = self.__pydantic_extra__ or {}
    if key not in extra:
        raise KeyError(key)
    del extra[key]


def _struct_iter(self: Any) -> Any:
    return iter(self.__pydantic_extra__ or {})


def _struct_len(self: Any) -> int:
    return len(self.__pydantic_extra__ or {})


def _struct_contains(self: Any, key: object) -> bool:
    return key in (self.__pydantic_extra__ or {})


def _struct_get(self: Any, key: str, default: Any = None) -> Any:
    return (self.__pydantic_extra__ or {}).get(key, default)


def _struct_keys(self: Any) -> Any:
    return (self.__pydantic_extra__ or {}).keys()


def _struct_values(self: Any) -> Any:
    return (self.__pydantic_extra__ or {}).values()


def _struct_items(self: Any) -> Any:
    return (self.__pydantic_extra__ or {}).items()


_STRUCT_POP_SENTINEL = object()


def _struct_pop(self: Any, key: str, default: Any = _STRUCT_POP_SENTINEL) -> Any:
    extra = self.__pydantic_extra__ or {}
    if key in extra:
        return extra.pop(key)
    if default is _STRUCT_POP_SENTINEL:
        raise KeyError(key)
    return default


def _struct_setdefault(self: Any, key: str, default: Any = None) -> Any:
    if self.__pydantic_extra__ is None:
        object.__setattr__(self, "__pydantic_extra__", {})
    return self.__pydantic_extra__.setdefault(key, default)


def _struct_update(self: Any, *args: Any, **kwargs: Any) -> None:
    if self.__pydantic_extra__ is None:
        object.__setattr__(self, "__pydantic_extra__", {})
    self.__pydantic_extra__.update(*args, **kwargs)


setattr(_models.Struct, "__getitem__", _struct_getitem)  # noqa: B010
setattr(_models.Struct, "__setitem__", _struct_setitem)  # noqa: B010
setattr(_models.Struct, "__delitem__", _struct_delitem)  # noqa: B010
setattr(_models.Struct, "__iter__", _struct_iter)  # noqa: B010
setattr(_models.Struct, "__len__", _struct_len)  # noqa: B010
setattr(_models.Struct, "__contains__", _struct_contains)  # noqa: B010
setattr(_models.Struct, "get", _struct_get)  # noqa: B010
setattr(_models.Struct, "keys", _struct_keys)  # noqa: B010
setattr(_models.Struct, "values", _struct_values)  # noqa: B010
setattr(_models.Struct, "items", _struct_items)  # noqa: B010
setattr(_models.Struct, "pop", _struct_pop)  # noqa: B010
setattr(_models.Struct, "setdefault", _struct_setdefault)  # noqa: B010
setattr(_models.Struct, "update", _struct_update)  # noqa: B010


# Model-level coercers only run on construction (``model_validate`` path).
# ``validate_assignment`` is a separate Pydantic path that only re-validates
# the single changed field against its declared type, so a later
# ``part.raw = b"..."`` would bypass the coercer above and Pydantic's default
# ``bytes -> str`` coercion would silently UTF-8-decode the bytes (wrong —
# ``raw`` requires base64 on the wire). Override ``__setattr__`` on Part to
# pre-coerce the same two inputs before Pydantic's validate_assignment runs.
_part_original_setattr = _models.Part.__setattr__


def _part_setattr(self: Any, name: str, value: Any) -> None:
    if name == "raw" and isinstance(value, bytes | bytearray):
        value = base64.b64encode(bytes(value)).decode("ascii")
    elif name == "data" and value is not None and not isinstance(value, _models.Value):
        value = _models.Value(root=value)
    _part_original_setattr(self, name, value)


setattr(_models.Part, "__setattr__", _part_setattr)  # noqa: B010
