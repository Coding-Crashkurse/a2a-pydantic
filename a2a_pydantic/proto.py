"""Optional proto bridge: convert a2a-pydantic models to proto messages.

The bridge has **zero hard dependency on ``a2a-sdk``**. It works against any
proto module that exposes the standard A2A v1.0 message classes (``Part``,
``Message``, ``Task``, etc.). Two ways to use it:

1. **Bring your own proto module**::

       from my_company import a2a_pb2
       from a2a_pydantic.proto import to_proto

       proto_msg = to_proto(message, pb2=a2a_pb2)

2. **Convenience auto-import** — if you happen to have ``a2a-sdk``
   installed, the bridge will auto-import ``a2a.grpc.a2a_pb2`` for you::

       from a2a_pydantic.proto import to_proto

       proto_msg = to_proto(message)  # auto-imports a2a.grpc.a2a_pb2

The only hard dependency is ``protobuf`` itself (for
``google.protobuf.json_format.ParseDict``). Install it via the optional
extra::

    pip install a2a-pydantic[proto]

Implementation strategy
-----------------------
Rather than hand-mapping every field (which breaks every time the proto
schema renames a field — and it has, more than once: ``parts`` ->
``content``, ``CANCELED`` -> ``CANCELLED``, etc.), we go through the
proto's own JSON layer:

1. Serialise the Pydantic model to a v1.0-shaped dict via
   ``model.dump(version="1.0")``.
2. Hand the dict to ``json_format.ParseDict`` targeting the right proto
   class. ``ParseDict`` understands camelCase JSON field names and
   bytes-as-base64, so it stays compatible across schema drift.
   ``ignore_unknown_fields=True`` makes it tolerant of fields the
   installed pb2 doesn't know about.

The only drift we can't push to ``ParseDict`` is **enum value renames**:
``ParseDict`` rejects unknown enum names. We do a single recursive pass
over the payload to rewrite known-aliased enum strings (currently just
``TASK_STATE_CANCELED`` -> ``TASK_STATE_CANCELLED`` for older pb2s).

There is intentionally **no ``from_proto``**: going proto -> Pydantic
loses typing and validation guarantees. Use ``MessageToDict`` from
``google.protobuf.json_format`` and then ``Model.model_validate`` if you
need to come back into the Pydantic world.
"""

from __future__ import annotations

import contextlib
from typing import Any

from a2a_pydantic.models import (
    Artifact,
    Message,
    Part,
    Task,
    TaskArtifactUpdateEvent,
    TaskStatus,
    TaskStatusUpdateEvent,
)

# ---------------------------------------------------------------------------
# pb2 module discovery
# ---------------------------------------------------------------------------


def _resolve_pb2(pb2: Any | None) -> Any:
    """Return a usable pb2 module.

    If ``pb2`` is given, use it. Otherwise try to auto-import
    ``a2a.grpc.a2a_pb2`` as a convenience for ``a2a-sdk`` users. If neither
    works, raise an :class:`ImportError` with installation guidance — and
    a hint about the ``pb2=`` parameter for users who don't want to pull in
    ``a2a-sdk``.
    """
    if pb2 is not None:
        return pb2
    try:
        from a2a.grpc import a2a_pb2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError(
            "to_proto() needs a proto module. Either:\n"
            "  1) pass one explicitly:  to_proto(model, pb2=my_a2a_pb2)\n"
            "  2) install a2a-sdk for the auto-import convenience:\n"
            "       pip install a2a-sdk\n"
            "Note: the [proto] extra only installs protobuf itself; it\n"
            "deliberately does NOT pull in a2a-sdk so a2a-pydantic stays\n"
            "SDK-independent."
        ) from exc
    return a2a_pb2


def _check_protobuf_available() -> None:
    """Verify ``google.protobuf.json_format`` is importable."""
    try:
        from google.protobuf import json_format  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "a2a_pydantic.proto requires the ``protobuf`` package. "
            "Install with: pip install 'a2a-pydantic[proto]'"
        ) from exc


# ---------------------------------------------------------------------------
# Schema-drift compensation
# ---------------------------------------------------------------------------


def _enum_name_aliases(pb2: Any) -> dict[str, str]:
    """Probe ``pb2`` for known-aliased enum value names.

    Cached on the pb2 module object so we only probe once per process.
    Currently the only known alias is the US/UK spelling of CANCELED.
    """
    cached = getattr(pb2, "__a2a_pydantic_enum_aliases__", None)
    if cached is not None:
        return cached
    aliases: dict[str, str] = {}
    if not hasattr(pb2, "TASK_STATE_CANCELED") and hasattr(pb2, "TASK_STATE_CANCELLED"):
        aliases["TASK_STATE_CANCELED"] = "TASK_STATE_CANCELLED"
    # Some module objects forbid attribute assignment; cache miss is fine.
    with contextlib.suppress(AttributeError, TypeError):
        pb2.__a2a_pydantic_enum_aliases__ = aliases  # type: ignore[attr-defined]
    return aliases


def _rewrite_enum_aliases(value: Any, aliases: dict[str, str]) -> Any:
    """Recursively rewrite known-aliased enum strings inside a JSON-like payload."""
    if not aliases:
        return value
    if isinstance(value, dict):
        return {k: _rewrite_enum_aliases(v, aliases) for k, v in value.items()}
    if isinstance(value, list):
        return [_rewrite_enum_aliases(v, aliases) for v in value]
    if isinstance(value, str) and value in aliases:
        return aliases[value]
    return value


# Field renames the proto schema has shipped between versions. We probe
# each one against the *actual* installed proto class — if the canonical
# JSON field name is missing but an alternate is present, we rewrite that
# top-level key in the payload before handing it to ``ParseDict``.
# Otherwise ``ignore_unknown_fields=True`` would silently drop the data.
#
# Each entry is (canonical_camelCase, alternate_camelCase, list_of_proto_classes_to_check).
_FIELD_ALIASES: list[tuple[str, str, tuple[str, ...]]] = [
    # ``parts`` was renamed to ``content`` on Message in newer SDKs.
    ("parts", "content", ("Message",)),
]


def _field_aliases_for(pb2: Any, proto_cls_name: str) -> dict[str, str]:
    """Return canonical -> alternate field name renames for ``proto_cls_name``."""
    cache_attr = f"__a2a_pydantic_field_aliases_{proto_cls_name}__"
    cached = getattr(pb2, cache_attr, None)
    if cached is not None:
        return cached

    out: dict[str, str] = {}
    proto_cls = getattr(pb2, proto_cls_name, None)
    if proto_cls is not None:
        try:
            descriptor = proto_cls.DESCRIPTOR
            present = {f.json_name for f in descriptor.fields}
        except AttributeError:
            present = set()

        for canonical, alternate, classes in _FIELD_ALIASES:
            if proto_cls_name not in classes:
                continue
            if canonical not in present and alternate in present:
                out[canonical] = alternate

    with contextlib.suppress(AttributeError, TypeError):
        setattr(pb2, cache_attr, out)
    return out


def _rewrite_field_aliases(
    payload: dict[str, Any], aliases: dict[str, str]
) -> dict[str, Any]:
    """Rename top-level keys in ``payload`` per ``aliases`` (canonical -> alternate)."""
    if not aliases or not isinstance(payload, dict):
        return payload
    return {aliases.get(k, k): v for k, v in payload.items()}


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------


# Map our model classes to their canonical proto class name. We resolve the
# actual class via ``getattr(pb2, name)`` at call time so we don't hard-fail
# at import time if the user's pb2 is missing one.
_PROTO_CLASS_NAMES: dict[type, str] = {
    Part: "Part",
    Message: "Message",
    TaskStatus: "TaskStatus",
    Task: "Task",
    Artifact: "Artifact",
    TaskStatusUpdateEvent: "TaskStatusUpdateEvent",
    TaskArtifactUpdateEvent: "TaskArtifactUpdateEvent",
}


def to_proto(model: Any, *, pb2: Any | None = None) -> Any:
    """Convert an a2a-pydantic model to its proto counterpart.

    Parameters
    ----------
    model:
        Any supported a2a-pydantic model instance (Part, Message, Task,
        TaskStatus, Artifact, TaskStatusUpdateEvent, TaskArtifactUpdateEvent).
    pb2:
        The proto module to target. If ``None`` (the default), the bridge
        tries to auto-import ``a2a.grpc.a2a_pb2`` from ``a2a-sdk`` as a
        convenience. Pass your own module if you don't want the SDK in
        your dependency tree.

    Raises
    ------
    ImportError
        If ``pb2`` is ``None`` and ``a2a.grpc.a2a_pb2`` is not importable,
        or if ``protobuf`` itself is not installed.
    TypeError
        If ``model`` isn't a type the bridge knows how to convert.
    AttributeError
        If the resolved ``pb2`` module doesn't expose the proto class we
        need (e.g. an incompatible schema).
    """
    proto_name = _PROTO_CLASS_NAMES.get(type(model))
    if proto_name is None:
        raise TypeError(
            f"to_proto() does not support {type(model).__name__}; "
            f"supported types: {sorted(t.__name__ for t in _PROTO_CLASS_NAMES)}"
        )

    _check_protobuf_available()
    resolved_pb2 = _resolve_pb2(pb2)

    proto_cls = getattr(resolved_pb2, proto_name, None)
    if proto_cls is None:
        raise AttributeError(
            f"Provided pb2 module has no proto class named {proto_name!r}"
        )

    from google.protobuf import json_format  # type: ignore[import-not-found]

    payload = model.dump(version="1.0")
    payload = _rewrite_enum_aliases(payload, _enum_name_aliases(resolved_pb2))
    payload = _rewrite_field_aliases(
        payload, _field_aliases_for(resolved_pb2, proto_name)
    )

    return json_format.ParseDict(payload, proto_cls(), ignore_unknown_fields=True)
