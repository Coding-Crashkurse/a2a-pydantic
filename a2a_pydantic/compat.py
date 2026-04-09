"""v0.3 <-> v1.0 normalisation helpers.

This module is deliberately stateless: it exposes pure functions that take
incoming raw dicts (as produced by ``json.loads`` of a v0.3 *or* v1.0 wire
payload) and return a dict in the canonical internal shape (v1.0 + snake-case
or camelCase Python field names — Pydantic's ``populate_by_name`` lets the
model accept either).

Each model in :mod:`a2a_pydantic.models` calls into one of these helpers from
its ``@model_validator(mode="before")``. Keeping the rules here (instead of
inline) makes them easy to audit and to share between models.
"""

from __future__ import annotations

from typing import Any

from a2a_pydantic.enums import (
    ROLE_V03_TO_V10,
    ROLE_V10_TO_V03,
    TASK_STATE_V03_TO_V10,
    TASK_STATE_V10_TO_V03,
    Role,
    TaskState,
)

__all__ = [
    "normalize_part",
    "downgrade_part",
    "normalize_message",
    "downgrade_message",
    "normalize_task_status",
    "downgrade_task_status",
    "normalize_task",
    "downgrade_task",
    "normalize_artifact",
    "normalize_status_update",
    "downgrade_status_update",
    "normalize_artifact_update",
    "downgrade_artifact_update",
    "normalize_agent_card",
    "downgrade_agent_card",
    "normalize_agent_capabilities",
    "downgrade_agent_capabilities",
    "normalize_agent_interface",
    "downgrade_agent_interface",
    "normalize_push_notification_config",
    "downgrade_push_notification_config",
    "normalize_message_send_configuration",
    "downgrade_message_send_configuration",
    "normalize_state_value",
    "downgrade_state_value",
    "normalize_role_value",
    "downgrade_role_value",
]


# ---------------------------------------------------------------------------
# enum value helpers
# ---------------------------------------------------------------------------


def normalize_state_value(value: Any) -> Any:
    """Upgrade a v0.3 state string (``"completed"``) to v1.0 (``"TASK_STATE_COMPLETED"``)."""
    if isinstance(value, str) and value in TASK_STATE_V03_TO_V10:
        return TASK_STATE_V03_TO_V10[value]
    return value


def downgrade_state_value(value: Any) -> Any:
    """Render an internal v1.0 state value as the v0.3 wire string."""
    if isinstance(value, TaskState):
        value = value.value
    if isinstance(value, str) and value in TASK_STATE_V10_TO_V03:
        return TASK_STATE_V10_TO_V03[value]
    return value


def normalize_role_value(value: Any) -> Any:
    if isinstance(value, str) and value in ROLE_V03_TO_V10:
        return ROLE_V03_TO_V10[value]
    return value


def downgrade_role_value(value: Any) -> Any:
    if isinstance(value, Role):
        value = value.value
    if isinstance(value, str) and value in ROLE_V10_TO_V03:
        return ROLE_V10_TO_V03[value]
    return value


# ---------------------------------------------------------------------------
# Part: the largest structural change between v0.3 and v1.0
# ---------------------------------------------------------------------------


def normalize_part(data: Any) -> Any:
    """Convert any incoming Part dict (v0.3 or v1.0) to the canonical shape.

    The canonical shape is the v1.0 *flat* form, but with field names in
    either snake_case or camelCase (Pydantic accepts both):

    - Text part:  ``{"text": "..."}``
    - Data part:  ``{"data": {...}}``
    - File-URL:   ``{"url": "...", "mediaType": "...", "filename": "..."}``
    - File-bytes: ``{"raw": "<base64>", "mediaType": "...", "filename": "..."}``
    """
    if not isinstance(data, dict):
        return data

    # Already v1.0-flat? Detect by absence of v0.3's `kind` discriminator.
    if "kind" not in data:
        return data

    kind = data.get("kind")
    metadata = data.get("metadata")
    out: dict[str, Any] = {}
    if metadata is not None:
        out["metadata"] = metadata

    if kind == "text":
        if "text" in data:
            out["text"] = data["text"]
        return out

    if kind == "data":
        if "data" in data:
            out["data"] = data["data"]
        return out

    if kind == "file":
        file_obj = data.get("file") or {}
        # v0.3 FileWithUri: {"uri": ..., "mimeType": ..., "name": ...}
        # v0.3 FileWithBytes: {"bytes": "<base64>", "mimeType": ..., "name": ...}
        if isinstance(file_obj, dict):
            if "uri" in file_obj:
                out["url"] = file_obj["uri"]
            if "bytes" in file_obj:
                out["raw"] = file_obj["bytes"]
            mime = file_obj.get("mimeType") or file_obj.get("mime_type")
            if mime is not None:
                out["mediaType"] = mime
            name = file_obj.get("name")
            if name is not None:
                out["filename"] = name
        return out

    # Unknown kind: pass through untouched and let Pydantic validate.
    return data


def downgrade_part(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Render an already-serialised v1.0 Part dict in v0.3 wire shape.

    ``snapshot`` is the output of ``Part.model_dump(by_alias=True)`` (the
    canonical v1.0 form). We rebuild it as a v0.3 ``{"kind": ..., ...}`` dict.
    """
    text = snapshot.get("text")
    data = snapshot.get("data")
    url = snapshot.get("url")
    raw = snapshot.get("raw")
    metadata = snapshot.get("metadata")

    if text is not None:
        out: dict[str, Any] = {"kind": "text", "text": text}
        if metadata is not None:
            out["metadata"] = metadata
        return out

    if data is not None:
        out = {"kind": "data", "data": data}
        if metadata is not None:
            out["metadata"] = metadata
        return out

    if url is not None or raw is not None:
        file_block: dict[str, Any] = {}
        if url is not None:
            file_block["uri"] = url
        if raw is not None:
            file_block["bytes"] = raw
        media = snapshot.get("mediaType")
        if media is not None:
            file_block["mimeType"] = media
        filename = snapshot.get("filename")
        if filename is not None:
            file_block["name"] = filename
        out = {"kind": "file", "file": file_block}
        if metadata is not None:
            out["metadata"] = metadata
        return out

    # Empty Part — emit as text with empty string to keep the v0.3 schema valid.
    return {"kind": "text", "text": ""}


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------


def normalize_message(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    out = dict(data)
    out.pop("kind", None)  # v0.3 has kind="message"; we drop it.
    if "role" in out:
        out["role"] = normalize_role_value(out["role"])
    return out


def downgrade_message(snapshot: dict[str, Any]) -> dict[str, Any]:
    out = dict(snapshot)
    if "role" in out:
        out["role"] = downgrade_role_value(out["role"])
    out["kind"] = "message"
    return out


# ---------------------------------------------------------------------------
# TaskStatus
# ---------------------------------------------------------------------------


def normalize_task_status(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    out = dict(data)
    if "state" in out:
        out["state"] = normalize_state_value(out["state"])
    return out


def downgrade_task_status(snapshot: dict[str, Any]) -> dict[str, Any]:
    out = dict(snapshot)
    if "state" in out:
        out["state"] = downgrade_state_value(out["state"])
    return out


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


def normalize_task(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    out = dict(data)
    out.pop("kind", None)  # v0.3 has kind="task"
    return out


def downgrade_task(snapshot: dict[str, Any]) -> dict[str, Any]:
    out = dict(snapshot)
    out["kind"] = "task"
    return out


# ---------------------------------------------------------------------------
# Artifact
# ---------------------------------------------------------------------------


def normalize_artifact(data: Any) -> Any:
    # v0.3 and v1.0 use the same field names — only the ``parts`` change,
    # which is handled by Part itself.
    return data


# ---------------------------------------------------------------------------
# Stream events
# ---------------------------------------------------------------------------


def normalize_status_update(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    out = dict(data)
    out.pop("kind", None)  # v0.3 has kind="status-update"
    # ``final`` is a v0.3-only field — keep it on the model so v0.3 round-trips.
    return out


def downgrade_status_update(snapshot: dict[str, Any]) -> dict[str, Any]:
    out = dict(snapshot)
    out["kind"] = "status-update"
    # v0.3 requires ``final`` to be a bool, defaulting to False if absent.
    out.setdefault("final", False)
    return out


def normalize_artifact_update(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    out = dict(data)
    out.pop("kind", None)  # v0.3 has kind="artifact-update"
    return out


def downgrade_artifact_update(snapshot: dict[str, Any]) -> dict[str, Any]:
    out = dict(snapshot)
    out["kind"] = "artifact-update"
    return out


# ---------------------------------------------------------------------------
# AgentCapabilities
# ---------------------------------------------------------------------------


def normalize_agent_capabilities(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    out = dict(data)
    # v0.3 had stateTransitionHistory; preserve it on the model so v0.3
    # round-trips, but it's not part of v1.0.
    return out


def downgrade_agent_capabilities(snapshot: dict[str, Any]) -> dict[str, Any]:
    out = dict(snapshot)
    # extendedAgentCard is v1.0-only; drop it for v0.3 output.
    out.pop("extendedAgentCard", None)
    return out


# ---------------------------------------------------------------------------
# AgentInterface
# ---------------------------------------------------------------------------


def normalize_agent_interface(data: Any) -> Any:
    """Accept both v0.3 ``transport`` and v1.0 ``protocolBinding``."""
    if not isinstance(data, dict):
        return data
    out = dict(data)
    # v0.3 calls it "transport"; v1.0 "protocolBinding".
    if (
        "protocolBinding" not in out
        and "protocol_binding" not in out
        and "transport" in out
    ):
        out["protocolBinding"] = out.pop("transport")
    return out


def downgrade_agent_interface(snapshot: dict[str, Any]) -> dict[str, Any]:
    out = dict(snapshot)
    binding = out.pop("protocolBinding", None)
    if binding is not None:
        out["transport"] = binding
    # tenant + protocolVersion are v1.0-only on AgentInterface; drop them.
    out.pop("tenant", None)
    out.pop("protocolVersion", None)
    return out


# ---------------------------------------------------------------------------
# AgentCard
# ---------------------------------------------------------------------------


def normalize_agent_card(data: Any) -> Any:
    """Accept either the v0.3 (``url`` + ``preferredTransport``) or v1.0
    (``supportedInterfaces``) shape and produce the canonical v1.0 form."""
    if not isinstance(data, dict):
        return data
    out = dict(data)

    # v0.3 -> v1.0: lift ``url`` + ``preferredTransport`` into supportedInterfaces.
    has_supported = "supportedInterfaces" in out or "supported_interfaces" in out
    legacy_url = out.get("url")
    legacy_xport = out.pop("preferredTransport", None) or out.pop(
        "preferred_transport", None
    )
    additional = out.pop("additionalInterfaces", None) or out.pop(
        "additional_interfaces", None
    )

    if not has_supported and (legacy_url or additional):
        interfaces: list[dict[str, Any]] = []
        if legacy_url:
            interfaces.append(
                {
                    "url": legacy_url,
                    "protocolBinding": legacy_xport or "JSONRPC",
                    "protocolVersion": "0.3",
                }
            )
        if isinstance(additional, list):
            for entry in additional:
                if isinstance(entry, dict):
                    interfaces.append(normalize_agent_interface(entry))
        out["supportedInterfaces"] = interfaces

    # Keep ``url`` on the model for v0.3 round-trip even if v1.0 input was used:
    # we'll re-derive it on dump from supportedInterfaces[0] if missing.

    # supportsAuthenticatedExtendedCard (v0.3) -> capabilities.extendedAgentCard (v1.0)
    saec = out.pop("supportsAuthenticatedExtendedCard", None)
    if saec is None:
        saec = out.pop("supports_authenticated_extended_card", None)
    if saec is not None:
        caps = out.get("capabilities") or {}
        if isinstance(caps, dict):
            caps = dict(caps)
            caps.setdefault("extendedAgentCard", saec)
            out["capabilities"] = caps

    # protocolVersion is informational; we don't enforce a value internally.
    return out


def downgrade_agent_card(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Render an internal AgentCard snapshot as a v0.3 wire dict."""
    out = dict(snapshot)
    interfaces = out.pop("supportedInterfaces", None) or []

    # Pick the first interface as the v0.3 main url + preferredTransport.
    main = interfaces[0] if interfaces else None
    if main:
        out["url"] = main.get("url", out.get("url", ""))
        out["preferredTransport"] = main.get("protocolBinding", "JSONRPC")
    if len(interfaces) > 1:
        out["additionalInterfaces"] = [
            {
                "url": iface.get("url"),
                "transport": iface.get("protocolBinding", "JSONRPC"),
            }
            for iface in interfaces
        ]

    # Lift extendedAgentCard back up to supportsAuthenticatedExtendedCard.
    caps = out.get("capabilities")
    if isinstance(caps, dict):
        eac = caps.pop("extendedAgentCard", None)
        if eac is not None:
            out["supportsAuthenticatedExtendedCard"] = eac
        out["capabilities"] = caps

    out.setdefault("protocolVersion", "0.3.0")
    return out


# ---------------------------------------------------------------------------
# PushNotificationConfig
# ---------------------------------------------------------------------------


def normalize_push_notification_config(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    out = dict(data)
    auth = out.get("authentication")
    if isinstance(auth, dict):
        new_auth = dict(auth)
        # v0.3 uses ``schemes`` (list[str]); v1.0 uses ``scheme`` (single str).
        if "schemes" in new_auth and "scheme" not in new_auth:
            schemes = new_auth.pop("schemes")
            if isinstance(schemes, list) and schemes:
                new_auth["scheme"] = schemes[0]
        out["authentication"] = new_auth
    return out


def downgrade_push_notification_config(
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    out = dict(snapshot)
    auth = out.get("authentication")
    if isinstance(auth, dict):
        new_auth = dict(auth)
        scheme = new_auth.pop("scheme", None)
        if scheme is not None:
            new_auth["schemes"] = [scheme]
        out["authentication"] = new_auth
    return out


# ---------------------------------------------------------------------------
# MessageSendConfiguration
# ---------------------------------------------------------------------------


def normalize_message_send_configuration(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    out = dict(data)
    # v0.3 ``blocking`` (positive sense) -> v1.0 ``returnImmediately`` (negated).
    if "blocking" in out and "returnImmediately" not in out:
        blocking = out.pop("blocking")
        if blocking is not None:
            out["returnImmediately"] = not bool(blocking)
    # v0.3 ``pushNotificationConfig`` -> v1.0 ``taskPushNotificationConfig``.
    if "pushNotificationConfig" in out and "taskPushNotificationConfig" not in out:
        out["taskPushNotificationConfig"] = out.pop("pushNotificationConfig")
    return out


def downgrade_message_send_configuration(
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    out = dict(snapshot)
    if "returnImmediately" in out:
        ri = out.pop("returnImmediately")
        out["blocking"] = not bool(ri)
    if "taskPushNotificationConfig" in out:
        out["pushNotificationConfig"] = out.pop("taskPushNotificationConfig")
    return out
