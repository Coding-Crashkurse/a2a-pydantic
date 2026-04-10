"""Optional proto bridge: convert a2a-pydantic models to proto messages.

The bridge has **zero hard dependency on ``a2a-sdk``**. It works against any
proto module that exposes the standard A2A v1.0 message classes (``Part``,
``Message``, ``Task``, …). Two ways to use it:

1. **Bring your own proto module**::

       from my_company import a2a_pb2
       from a2a_pydantic.proto import to_proto

       proto_msg = to_proto(message, pb2=a2a_pb2)

2. **Convenience auto-import** — if you happen to have ``a2a-sdk`` installed,
   the bridge auto-imports ``a2a.grpc.a2a_pb2`` for you::

       from a2a_pydantic.proto import to_proto

       proto_msg = to_proto(message)

The only hard dependency is ``protobuf`` itself (for
``google.protobuf.json_format.ParseDict``). Install it via the optional
extra::

    pip install a2a-pydantic[proto]

Implementation strategy
-----------------------
Rather than hand-mapping every field (which breaks every time the proto
schema renames a field — and it has, more than once), we go through the
proto's own JSON layer:

1. Serialise the Pydantic model to a v1.0-shaped dict via
   ``model.dump(version="1.0")``.
2. Walk the proto descriptor in parallel with the dict, applying per-class
   *transformers* at each nested message field. Transformers handle the
   genuine schema mismatches between the v1.0 *JSON* spec (what Pydantic
   dumps) and the v1.0 *proto* shape — field renames (``in`` → ``location``),
   structural flattening (nested ``pushNotificationConfig`` → flat fields on
   ``TaskPushNotificationConfig``), and oneof wrapping (Pydantic
   ``SecurityScheme`` union → proto ``SecurityScheme`` oneof).
3. Hand the rewritten dict to ``json_format.ParseDict`` with
   ``ignore_unknown_fields=True``, so any spec drift between proto schema
   versions is silently absorbed.

There is intentionally **no ``from_proto``**: going proto → Pydantic loses
typing and validation guarantees. If you need to round-trip the other way,
use ``MessageToDict`` from ``google.protobuf.json_format`` and then
``Model.model_validate``.
"""

from __future__ import annotations

import contextlib
from typing import Any

from a2a_pydantic.models import (
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
    ClientCredentialsOAuthFlow,
    HTTPAuthSecurityScheme,
    ImplicitOAuthFlow,
    Message,
    MessageSendConfiguration,
    MessageSendParams,
    MutualTLSSecurityScheme,
    OAuth2SecurityScheme,
    OAuthFlows,
    OpenIdConnectSecurityScheme,
    Part,
    PasswordOAuthFlow,
    PushNotificationAuthenticationInfo,
    Task,
    TaskArtifactUpdateEvent,
    TaskPushNotificationConfig,
    TaskStatus,
    TaskStatusUpdateEvent,
)


def _resolve_pb2(pb2: Any | None) -> Any:
    """Return a usable pb2 module, falling back to a2a-sdk if available."""
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
    try:
        from google.protobuf import json_format  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "a2a_pydantic.proto requires the ``protobuf`` package. "
            "Install with: pip install 'a2a-pydantic[proto]'"
        ) from exc


_ENUM_ALIASES_CACHE_ATTR = "__a2a_pydantic_enum_aliases__"


def _enum_value_aliases(pb2: Any) -> dict[str, str]:
    """Probe ``pb2`` for known-aliased enum *value* names (e.g. CANCELED → CANCELLED).

    Cached on the pb2 module so we only probe once per process.
    """
    cached = getattr(pb2, _ENUM_ALIASES_CACHE_ATTR, None)
    if cached is not None:
        return cached
    aliases: dict[str, str] = {}
    if not hasattr(pb2, "TASK_STATE_CANCELED") and hasattr(pb2, "TASK_STATE_CANCELLED"):
        aliases["TASK_STATE_CANCELED"] = "TASK_STATE_CANCELLED"
    with contextlib.suppress(AttributeError, TypeError):
        setattr(pb2, _ENUM_ALIASES_CACHE_ATTR, aliases)
    return aliases


def _rewrite_enum_values(value: Any, aliases: dict[str, str]) -> Any:
    """Recursively replace known-aliased enum *strings* anywhere in a payload."""
    if not aliases:
        return value
    if isinstance(value, dict):
        return {k: _rewrite_enum_values(v, aliases) for k, v in value.items()}
    if isinstance(value, list):
        return [_rewrite_enum_values(v, aliases) for v in value]
    if isinstance(value, str) and value in aliases:
        return aliases[value]
    return value


_SECURITY_TYPE_TO_ONEOF: dict[str, str] = {
    "apiKey": "apiKeySecurityScheme",
    "http": "httpAuthSecurityScheme",
    "oauth2": "oauth2SecurityScheme",
    "openIdConnect": "openIdConnectSecurityScheme",
    "mutualTLS": "mtlsSecurityScheme",
}


def _t_api_key_security_scheme(payload: dict[str, Any]) -> dict[str, Any]:
    """Pydantic dumps ``in`` (per OpenAPI) — proto json_name is ``location``."""
    out = {k: v for k, v in payload.items() if k != "type"}
    if "in" in out:
        out["location"] = out.pop("in")
    return out


def _t_drop_type_discriminator(payload: dict[str, Any]) -> dict[str, Any]:
    """The various security schemes carry a ``type`` discriminator the proto lacks."""
    return {k: v for k, v in payload.items() if k != "type"}


def _t_security_scheme_oneof(payload: dict[str, Any]) -> dict[str, Any]:
    """Wrap a discriminated SecurityScheme dict in the proto oneof container.

    Pydantic produces ``{type: 'apiKey', name: 'X', in: 'header'}``; the proto
    needs ``{apiKeySecurityScheme: {name: 'X', location: 'header'}}``. The
    recursive walker then descends into the wrapped value and the per-subtype
    transformer cleans up the inner shape.
    """
    type_tag = payload.get("type")
    oneof_field = _SECURITY_TYPE_TO_ONEOF.get(type_tag) if type_tag else None
    if oneof_field is None:
        return payload
    inner = {k: v for k, v in payload.items() if k != "type"}
    return {oneof_field: inner}


def _t_authentication_info(payload: dict[str, Any]) -> dict[str, Any]:
    """Pydantic v1.0 already uses singular ``scheme`` — match the proto field name."""
    return payload


def _t_task_push_notification_config(payload: dict[str, Any]) -> dict[str, Any]:
    """Flatten the nested ``pushNotificationConfig`` into top-level proto fields.

    Pydantic shape:    ``{taskId, pushNotificationConfig: {url, id, token, authentication}}``
    Proto shape:       ``{tenant, id, task_id, url, token, authentication}``
    """
    out = dict(payload)
    inner = out.pop("pushNotificationConfig", None)
    if isinstance(inner, dict):
        for key in ("url", "id", "token", "authentication"):
            if key in inner:
                out[key] = inner[key]
    return out


def _t_send_message_configuration(payload: dict[str, Any]) -> dict[str, Any]:
    """Synthesize the flat ``TaskPushNotificationConfig`` shape from the inner config.

    Pydantic ``MessageSendConfiguration.task_push_notification_config`` is a
    plain ``PushNotificationConfig`` (no task_id at this level — there's no
    task yet at send time). The proto field is typed as the full
    ``TaskPushNotificationConfig``, which is flat. We project the available
    fields into that shape; ``task_id`` simply stays unset.
    """
    out = dict(payload)
    inner = out.get("taskPushNotificationConfig")
    if isinstance(inner, dict):
        flat: dict[str, Any] = {}
        for key in ("url", "id", "token", "authentication"):
            if key in inner:
                flat[key] = inner[key]
        out["taskPushNotificationConfig"] = flat
    return out


def _t_stream_response(payload: dict[str, Any]) -> dict[str, Any]:
    """StreamEvent dumps ``taskStatusUpdate`` / ``taskArtifactUpdate``; proto wants ``statusUpdate`` / ``artifactUpdate``."""
    rename = {
        "taskStatusUpdate": "statusUpdate",
        "taskArtifactUpdate": "artifactUpdate",
    }
    return {rename.get(k, k): v for k, v in payload.items()}


def _make_field_alias_transformer(
    proto_cls: Any,
) -> "Callable[[dict[str, Any]], dict[str, Any]] | None":
    """Build a transformer that renames legacy ``parts`` → ``content`` on Message.

    Some newer pb2 generations renamed ``Message.parts`` to ``Message.content``.
    We probe the descriptor and only emit the rename when the alternate is
    present and the canonical is missing.
    """
    try:
        present = {f.json_name for f in proto_cls.DESCRIPTOR.fields}
    except AttributeError:
        return None
    if "parts" in present or "content" not in present:
        return None

    def transform(payload: dict[str, Any]) -> dict[str, Any]:
        if "parts" not in payload:
            return payload
        out = dict(payload)
        out["content"] = out.pop("parts")
        return out

    return transform


_PROTO_TRANSFORMERS = {
    "APIKeySecurityScheme": _t_api_key_security_scheme,
    "HTTPAuthSecurityScheme": _t_drop_type_discriminator,
    "OAuth2SecurityScheme": _t_drop_type_discriminator,
    "OpenIdConnectSecurityScheme": _t_drop_type_discriminator,
    "MutualTlsSecurityScheme": _t_drop_type_discriminator,
    "SecurityScheme": _t_security_scheme_oneof,
    "AuthenticationInfo": _t_authentication_info,
    "TaskPushNotificationConfig": _t_task_push_notification_config,
    "SendMessageConfiguration": _t_send_message_configuration,
    "StreamResponse": _t_stream_response,
}


def _rewrite_for_proto(payload: Any, proto_cls: Any, pb2: Any) -> Any:
    """Recursively rewrite a JSON-shaped payload to match the proto JSON shape.

    At each level we:

    1. Apply the per-proto-class transformer (if any). The transformer may
       rename fields, drop discriminators, flatten nested structures, or wrap
       the payload in a oneof container.
    2. Apply the dynamic ``parts`` → ``content`` rename for Message if the
       installed pb2 uses the newer field name.
    3. Walk into nested message fields by looking up each key's
       ``json_name`` in the proto descriptor. For ``map<string, T>`` fields
       we recurse into the values; for repeated fields we recurse into list
       items.

    Anything we don't recognise (unknown keys, primitives, ``Any``-typed
    metadata, ``google.protobuf.Struct`` fields) is passed through unchanged
    — ``ParseDict`` handles those natively.
    """
    if not isinstance(payload, dict):
        return payload

    proto_name = proto_cls.DESCRIPTOR.name
    transformer = _PROTO_TRANSFORMERS.get(proto_name)
    if transformer is not None:
        payload = transformer(payload)

    field_alias = _make_field_alias_transformer(proto_cls)
    if field_alias is not None:
        payload = field_alias(payload)

    json_to_field = {f.json_name: f for f in proto_cls.DESCRIPTOR.fields}
    out: dict[str, Any] = {}
    for key, value in payload.items():
        field = json_to_field.get(key)
        if field is None or field.message_type is None or value is None:
            out[key] = value
            continue

        if field.message_type.GetOptions().map_entry:
            value_field = field.message_type.fields_by_name["value"]
            if value_field.message_type and isinstance(value, dict):
                child_cls = getattr(pb2, value_field.message_type.name, None)
                if child_cls is not None:
                    out[key] = {
                        k: _rewrite_for_proto(v, child_cls, pb2)
                        if isinstance(v, dict)
                        else v
                        for k, v in value.items()
                    }
                    continue
            out[key] = value
            continue

        if field.message_type.full_name == "google.protobuf.Struct":
            out[key] = value
            continue

        child_cls = getattr(pb2, field.message_type.name, None)
        if child_cls is None:
            out[key] = value
            continue

        if isinstance(value, list):
            out[key] = [
                _rewrite_for_proto(item, child_cls, pb2)
                if isinstance(item, dict)
                else item
                for item in value
            ]
        elif isinstance(value, dict):
            out[key] = _rewrite_for_proto(value, child_cls, pb2)
        else:
            out[key] = value

    return out


_PROTO_CLASS_NAMES: dict[type, str] = {
    Part: "Part",
    Message: "Message",
    TaskStatus: "TaskStatus",
    Task: "Task",
    Artifact: "Artifact",
    TaskStatusUpdateEvent: "TaskStatusUpdateEvent",
    TaskArtifactUpdateEvent: "TaskArtifactUpdateEvent",
    MessageSendConfiguration: "SendMessageConfiguration",
    MessageSendParams: "SendMessageRequest",
    PushNotificationAuthenticationInfo: "AuthenticationInfo",
    TaskPushNotificationConfig: "TaskPushNotificationConfig",
    AgentCard: "AgentCard",
    AgentProvider: "AgentProvider",
    AgentExtension: "AgentExtension",
    AgentCapabilities: "AgentCapabilities",
    AgentSkill: "AgentSkill",
    AgentInterface: "AgentInterface",
    AgentCardSignature: "AgentCardSignature",
    APIKeySecurityScheme: "APIKeySecurityScheme",
    HTTPAuthSecurityScheme: "HTTPAuthSecurityScheme",
    OAuth2SecurityScheme: "OAuth2SecurityScheme",
    OpenIdConnectSecurityScheme: "OpenIdConnectSecurityScheme",
    MutualTLSSecurityScheme: "MutualTlsSecurityScheme",
    OAuthFlows: "OAuthFlows",
    AuthorizationCodeOAuthFlow: "AuthorizationCodeOAuthFlow",
    ClientCredentialsOAuthFlow: "ClientCredentialsOAuthFlow",
    ImplicitOAuthFlow: "ImplicitOAuthFlow",
    PasswordOAuthFlow: "PasswordOAuthFlow",
}


def to_proto(model: Any, *, pb2: Any | None = None) -> Any:
    """Convert an a2a-pydantic model to its proto counterpart.

    Parameters
    ----------
    model:
        Any supported a2a-pydantic model instance. See ``_PROTO_CLASS_NAMES``
        in this module for the full list.
    pb2:
        The proto module to target. If ``None``, the bridge tries to
        auto-import ``a2a.grpc.a2a_pb2`` from ``a2a-sdk`` as a convenience.
        Pass your own module if you don't want the SDK in your dependency
        tree.

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
    payload = _rewrite_enum_values(payload, _enum_value_aliases(resolved_pb2))
    payload = _rewrite_for_proto(payload, proto_cls, resolved_pb2)

    return json_format.ParseDict(payload, proto_cls(), ignore_unknown_fields=True)
