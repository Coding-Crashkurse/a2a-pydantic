"""Converters between A2A protocol versions.

This module provides downward conversion from v1.0 models to v0.3 models.
Upward conversion (v0.3 -> v1.0) is intentionally not supported: v1.0
introduces fields that have no v0.3 counterpart (``tenant`` on every
request, ``protocol_binding``/``protocol_version`` split on interfaces,
device-code OAuth flow, per-task list RPC, AwareDatetime timestamps, ...),
and inventing defaults for them would silently drop or corrupt data.

Whenever a v1.0 field cannot be represented in v0.3 and has to be
dropped, coerced, or defaulted, a ``UserWarning`` is emitted so callers
can see exactly which data was lost.
"""

from __future__ import annotations

import warnings
from functools import singledispatch
from typing import Any

from pydantic import BaseModel

from a2apydantic import v03, v10


def _warn(message: str) -> None:
    warnings.warn(message, UserWarning, stacklevel=3)


def _struct_to_dict(struct: v10.Struct | None) -> dict[str, Any] | None:
    """Convert a v10 ``Struct`` (opaque JSON object) to a plain dict.

    ``Struct`` is generated as an empty ``A2ABaseModel`` subclass, so in
    practice only extra fields (if any were accepted) would be preserved.
    We dump via pydantic to be safe and return ``None`` when empty so the
    v0.3 side stays ``None`` rather than ``{}``.
    """
    if struct is None:
        return None
    if isinstance(struct, BaseModel):
        data = struct.model_dump(by_alias=False, exclude_none=True)
    else:
        data = dict(struct)  # type: ignore[arg-type]
    return data or None


def _value_to_any(value: v10.Value | None) -> Any:
    if value is None:
        return None
    return value.root


def _timestamp_to_str(ts: v10.Timestamp | None) -> str | None:
    if ts is None:
        return None
    return ts.root.isoformat()


_ROLE_V10_TO_V03: dict[v10.Role, v03.Role] = {
    v10.Role.role_user: v03.Role.user,
    v10.Role.role_agent: v03.Role.agent,
}

_TASK_STATE_V10_TO_V03: dict[v10.TaskState, v03.TaskState] = {
    v10.TaskState.task_state_submitted: v03.TaskState.submitted,
    v10.TaskState.task_state_working: v03.TaskState.working,
    v10.TaskState.task_state_completed: v03.TaskState.completed,
    v10.TaskState.task_state_failed: v03.TaskState.failed,
    v10.TaskState.task_state_canceled: v03.TaskState.canceled,
    v10.TaskState.task_state_input_required: v03.TaskState.input_required,
    v10.TaskState.task_state_rejected: v03.TaskState.rejected,
    v10.TaskState.task_state_auth_required: v03.TaskState.auth_required,
}

_API_KEY_LOCATION_TO_V03: dict[str, v03.In] = {
    "query": v03.In.query,
    "header": v03.In.header,
    "cookie": v03.In.cookie,
}


def role(v: v10.Role) -> v03.Role:
    return _ROLE_V10_TO_V03[v]


def task_state(v: v10.TaskState) -> v03.TaskState:
    return _TASK_STATE_V10_TO_V03[v]


def part(p: v10.Part) -> v03.Part:
    """Fan out a flat v1.0 ``Part`` to the correct v0.3 discriminated subtype.

    v1.0 bundles ``text``, ``raw``, ``url`` and ``data`` on a single model.
    v0.3 uses a strict one-of between ``TextPart``, ``FilePart`` and
    ``DataPart``. Precedence here is text > raw bytes > url > data, and
    a warning is raised when more than one payload is populated so the
    caller knows which payload survived.
    """
    metadata = _struct_to_dict(p.metadata)

    populated = [
        name for name in ("text", "raw", "url", "data") if getattr(p, name) is not None
    ]
    if not populated:
        _warn("v10.Part has no payload set; emitting empty v03.TextPart")
        return v03.Part(root=v03.TextPart(text="", metadata=metadata))
    if len(populated) > 1:
        _warn(
            f"v10.Part has multiple payloads {populated}; keeping "
            f"{populated[0]!r} and dropping the rest (v03 Part is strict one-of)"
        )

    chosen = populated[0]
    if chosen == "text":
        return v03.Part(root=v03.TextPart(text=p.text or "", metadata=metadata))

    if chosen == "raw":
        file_model = v03.FileWithBytes(
            bytes=p.raw or "",
            mime_type=p.media_type or None,
            name=p.filename or None,
        )
        return v03.Part(root=v03.FilePart(file=file_model, metadata=metadata))

    if chosen == "url":
        file_model = v03.FileWithUri(
            uri=p.url or "",
            mime_type=p.media_type or None,
            name=p.filename or None,
        )
        return v03.Part(root=v03.FilePart(file=file_model, metadata=metadata))

    raw_value = _value_to_any(p.data)
    if not isinstance(raw_value, dict):
        _warn(
            "v10.Part.data is not a JSON object; v03.DataPart requires "
            "dict[str, Any] so the value is wrapped in {'value': ...}"
        )
        raw_value = {"value": raw_value}
    return v03.Part(root=v03.DataPart(data=raw_value, metadata=metadata))


def message(m: v10.Message) -> v03.Message:
    return v03.Message(
        context_id=m.context_id or None,
        extensions=list(m.extensions) if m.extensions else None,
        message_id=m.message_id,
        metadata=_struct_to_dict(m.metadata),
        parts=[part(p) for p in m.parts],
        reference_task_ids=(
            list(m.reference_task_ids) if m.reference_task_ids else None
        ),
        role=role(m.role),
        task_id=m.task_id or None,
    )


def artifact(a: v10.Artifact) -> v03.Artifact:
    return v03.Artifact(
        artifact_id=a.artifact_id,
        description=a.description or None,
        extensions=list(a.extensions) if a.extensions else None,
        metadata=_struct_to_dict(a.metadata),
        name=a.name or None,
        parts=[part(p) for p in a.parts],
    )


def task_status(s: v10.TaskStatus) -> v03.TaskStatus:
    return v03.TaskStatus(
        message=message(s.message) if s.message is not None else None,
        state=task_state(s.state),
        timestamp=_timestamp_to_str(s.timestamp),
    )


def task(t: v10.Task) -> v03.Task:
    return v03.Task(
        artifacts=[artifact(a) for a in t.artifacts] if t.artifacts else None,
        context_id=t.context_id or "",
        history=[message(m) for m in t.history] if t.history else None,
        id=t.id,
        metadata=_struct_to_dict(t.metadata),
        status=task_status(t.status),
    )


def task_status_update_event(
    e: v10.TaskStatusUpdateEvent,
) -> v03.TaskStatusUpdateEvent:
    _warn(
        "v10.TaskStatusUpdateEvent has no 'final' field; defaulting "
        "v03.TaskStatusUpdateEvent.final=False"
    )
    return v03.TaskStatusUpdateEvent(
        context_id=e.context_id,
        final=False,
        metadata=_struct_to_dict(e.metadata),
        status=task_status(e.status),
        task_id=e.task_id,
    )


def task_artifact_update_event(
    e: v10.TaskArtifactUpdateEvent,
) -> v03.TaskArtifactUpdateEvent:
    return v03.TaskArtifactUpdateEvent(
        append=e.append,
        artifact=artifact(e.artifact),
        context_id=e.context_id,
        last_chunk=e.last_chunk,
        metadata=_struct_to_dict(e.metadata),
        task_id=e.task_id,
    )


def authentication_info(
    a: v10.AuthenticationInfo,
) -> v03.PushNotificationAuthenticationInfo:
    return v03.PushNotificationAuthenticationInfo(
        credentials=a.credentials or None,
        schemes=[a.scheme],
    )


def push_notification_config(
    c: v10.TaskPushNotificationConfig,
) -> v03.PushNotificationConfig:
    """Extract the inner ``PushNotificationConfig`` from a v1.0
    ``TaskPushNotificationConfig``.

    v1.0 keeps ``task_id`` alongside the push-notification settings on a
    flat model. v0.3 splits these into an outer ``TaskPushNotificationConfig``
    wrapping an inner ``PushNotificationConfig``. This helper returns just
    the inner piece; use :func:`task_push_notification_config` when you
    also need the outer wrapper.
    """
    if c.tenant:
        _warn(
            f"v10.TaskPushNotificationConfig.tenant={c.tenant!r} is dropped "
            "(v0.3 has no tenant concept)"
        )
    return v03.PushNotificationConfig(
        authentication=(
            authentication_info(c.authentication)
            if c.authentication is not None
            else None
        ),
        id=c.id or None,
        token=c.token or None,
        url=c.url,
    )


def task_push_notification_config(
    c: v10.TaskPushNotificationConfig,
) -> v03.TaskPushNotificationConfig:
    return v03.TaskPushNotificationConfig(
        push_notification_config=push_notification_config(c),
        task_id=c.task_id,
    )


def send_message_configuration(
    c: v10.SendMessageConfiguration,
) -> v03.MessageSendConfiguration:
    push_cfg: v03.PushNotificationConfig | None = None
    if c.task_push_notification_config is not None:
        push_cfg = push_notification_config(c.task_push_notification_config)

    return v03.MessageSendConfiguration(
        accepted_output_modes=(
            list(c.accepted_output_modes) if c.accepted_output_modes else None
        ),
        blocking=(not c.return_immediately) if c.return_immediately is not None else None,
        history_length=c.history_length,
        push_notification_config=push_cfg,
    )


def send_message_request(r: v10.SendMessageRequest) -> v03.MessageSendParams:
    """Convert a v1.0 ``SendMessageRequest`` to a v0.3 ``MessageSendParams``.

    Note the asymmetry: v1.0 ``SendMessageRequest`` corresponds to the
    *params* payload in v0.3, not to v0.3's ``SendMessageRequest`` (which
    is the JSON-RPC envelope). v1.0 has no JSON-RPC envelope layer.
    """
    if r.tenant:
        _warn(
            f"v10.SendMessageRequest.tenant={r.tenant!r} is dropped "
            "(v0.3 has no tenant concept)"
        )
    return v03.MessageSendParams(
        configuration=(
            send_message_configuration(r.configuration)
            if r.configuration is not None
            else None
        ),
        message=message(r.message),
        metadata=_struct_to_dict(r.metadata),
    )


def agent_extension(e: v10.AgentExtension) -> v03.AgentExtension:
    if not e.uri:
        _warn(
            "v10.AgentExtension.uri is empty; v0.3 requires a non-empty URI, "
            "using '' which will fail validation on strict parsers"
        )
    return v03.AgentExtension(
        description=e.description or None,
        params=_struct_to_dict(e.params),
        required=e.required,
        uri=e.uri or "",
    )


def agent_capabilities(c: v10.AgentCapabilities) -> v03.AgentCapabilities:
    return v03.AgentCapabilities(
        extensions=(
            [agent_extension(x) for x in c.extensions] if c.extensions else None
        ),
        push_notifications=c.push_notifications,
        state_transition_history=None,
        streaming=c.streaming,
    )


def agent_interface(i: v10.AgentInterface) -> v03.AgentInterface:
    if i.tenant:
        _warn(
            f"v10.AgentInterface.tenant={i.tenant!r} is dropped "
            "(v0.3 has no tenant concept)"
        )
    if i.protocol_version and i.protocol_version != "0.3":
        _warn(
            f"v10.AgentInterface.protocol_version={i.protocol_version!r} "
            "is not representable in v0.3 and was dropped"
        )
    return v03.AgentInterface(transport=i.protocol_binding, url=i.url)


def agent_provider(p: v10.AgentProvider) -> v03.AgentProvider:
    return v03.AgentProvider(organization=p.organization, url=p.url)


def _security_requirement_to_dict(
    req: v10.SecurityRequirement,
) -> dict[str, list[str]]:
    return {name: list(sl.strings) for name, sl in req.schemes.items()}


def agent_skill(s: v10.AgentSkill) -> v03.AgentSkill:
    security: list[dict[str, list[str]]] | None = None
    if s.security_requirements:
        security = [_security_requirement_to_dict(r) for r in s.security_requirements]
    return v03.AgentSkill(
        description=s.description,
        examples=list(s.examples) if s.examples else None,
        id=s.id,
        input_modes=list(s.input_modes) if s.input_modes else None,
        name=s.name,
        output_modes=list(s.output_modes) if s.output_modes else None,
        security=security,
        tags=list(s.tags),
    )


def agent_card_signature(
    s: v10.AgentCardSignature,
) -> v03.AgentCardSignature:
    return v03.AgentCardSignature(
        header=_struct_to_dict(s.header),
        protected=s.protected,
        signature=s.signature,
    )


def _api_key_scheme(s: v10.APIKeySecurityScheme) -> v03.APIKeySecurityScheme:
    location_key = (s.location or "").lower()
    if location_key not in _API_KEY_LOCATION_TO_V03:
        _warn(
            f"v10.APIKeySecurityScheme.location={s.location!r} is not one of "
            "('query','header','cookie'); defaulting to 'header'"
        )
        location_key = "header"
    return v03.APIKeySecurityScheme(
        description=s.description or None,
        in_=_API_KEY_LOCATION_TO_V03[location_key],
        name=s.name,
    )


def _http_auth_scheme(
    s: v10.HTTPAuthSecurityScheme,
) -> v03.HTTPAuthSecurityScheme:
    return v03.HTTPAuthSecurityScheme(
        bearer_format=s.bearer_format or None,
        description=s.description or None,
        scheme=s.scheme,
    )


def _mtls_scheme(s: v10.MutualTlsSecurityScheme) -> v03.MutualTLSSecurityScheme:
    return v03.MutualTLSSecurityScheme(description=s.description or None)


def _openid_scheme(
    s: v10.OpenIdConnectSecurityScheme,
) -> v03.OpenIdConnectSecurityScheme:
    return v03.OpenIdConnectSecurityScheme(
        description=s.description or None,
        open_id_connect_url=s.open_id_connect_url,
    )


def _authorization_code_flow(
    f: v10.AuthorizationCodeOAuthFlow,
) -> v03.AuthorizationCodeOAuthFlow:
    if f.pkce_required:
        _warn(
            "v10.AuthorizationCodeOAuthFlow.pkce_required=True is dropped "
            "(v0.3 has no PKCE flag)"
        )
    return v03.AuthorizationCodeOAuthFlow(
        authorization_url=f.authorization_url,
        refresh_url=f.refresh_url or None,
        scopes=dict(f.scopes),
        token_url=f.token_url,
    )


def _client_credentials_flow(
    f: v10.ClientCredentialsOAuthFlow,
) -> v03.ClientCredentialsOAuthFlow:
    return v03.ClientCredentialsOAuthFlow(
        refresh_url=f.refresh_url or None,
        scopes=dict(f.scopes),
        token_url=f.token_url,
    )


def _implicit_flow(f: v10.ImplicitOAuthFlow) -> v03.ImplicitOAuthFlow:
    return v03.ImplicitOAuthFlow(
        authorization_url=f.authorization_url,
        refresh_url=f.refresh_url or None,
        scopes=dict(f.scopes),
    )


def _password_flow(f: v10.PasswordOAuthFlow) -> v03.PasswordOAuthFlow:
    return v03.PasswordOAuthFlow(
        refresh_url=f.refresh_url or None,
        scopes=dict(f.scopes),
        token_url=f.token_url,
    )


def oauth_flows(f: v10.OAuthFlows) -> v03.OAuthFlows:
    if f.device_code is not None:
        _warn(
            "v10.OAuthFlows.device_code has no v0.3 equivalent and was dropped"
        )
    return v03.OAuthFlows(
        authorization_code=(
            _authorization_code_flow(f.authorization_code)
            if f.authorization_code is not None
            else None
        ),
        client_credentials=(
            _client_credentials_flow(f.client_credentials)
            if f.client_credentials is not None
            else None
        ),
        implicit=_implicit_flow(f.implicit) if f.implicit is not None else None,
        password=_password_flow(f.password) if f.password is not None else None,
    )


def _oauth2_scheme(s: v10.OAuth2SecurityScheme) -> v03.OAuth2SecurityScheme:
    return v03.OAuth2SecurityScheme(
        description=s.description or None,
        flows=oauth_flows(s.flows),
        oauth2_metadata_url=s.oauth2_metadata_url or None,
    )


def security_scheme(s: v10.SecurityScheme) -> v03.SecurityScheme:
    """Pick the single populated sub-scheme and emit the v0.3 union variant.

    v1.0 ``SecurityScheme`` is an envelope with five optional fields, one
    per scheme type. v0.3 is a strict ``RootModel`` union. If more than
    one field is populated we warn and keep the first; if none is we
    raise ``ValueError`` because v0.3 requires exactly one variant.
    """
    candidates: list[tuple[str, v03.SecurityScheme]] = []
    if s.api_key_security_scheme is not None:
        candidates.append(
            ("api_key", v03.SecurityScheme(root=_api_key_scheme(s.api_key_security_scheme)))
        )
    if s.http_auth_security_scheme is not None:
        candidates.append(
            (
                "http_auth",
                v03.SecurityScheme(root=_http_auth_scheme(s.http_auth_security_scheme)),
            )
        )
    if s.oauth2_security_scheme is not None:
        candidates.append(
            ("oauth2", v03.SecurityScheme(root=_oauth2_scheme(s.oauth2_security_scheme)))
        )
    if s.open_id_connect_security_scheme is not None:
        candidates.append(
            (
                "openid",
                v03.SecurityScheme(
                    root=_openid_scheme(s.open_id_connect_security_scheme)
                ),
            )
        )
    if s.mtls_security_scheme is not None:
        candidates.append(
            ("mtls", v03.SecurityScheme(root=_mtls_scheme(s.mtls_security_scheme)))
        )

    if not candidates:
        raise ValueError(
            "v10.SecurityScheme has no sub-scheme populated; v0.3 requires "
            "exactly one of api_key / http_auth / oauth2 / openid / mtls"
        )
    if len(candidates) > 1:
        kept = candidates[0][0]
        dropped = [n for n, _ in candidates[1:]]
        _warn(
            f"v10.SecurityScheme has multiple sub-schemes populated; keeping "
            f"{kept!r} and dropping {dropped} (v0.3 SecurityScheme is strict one-of)"
        )
    return candidates[0][1]


def agent_card(c: v10.AgentCard) -> v03.AgentCard:
    """Convert a v1.0 ``AgentCard`` into a v0.3 ``AgentCard``.

    The biggest shape mismatch is the interface list: v1.0 has a single
    ``supported_interfaces`` list (ordered, first is preferred) while v0.3
    splits this into a main ``url``/``preferred_transport`` pair plus an
    optional ``additional_interfaces`` list. We take the first v1.0
    interface as the main pair and put the rest into ``additional_interfaces``.
    Security requirements are also reshaped from ``list[SecurityRequirement]``
    to ``list[dict[str, list[str]]]``.
    """
    if not c.supported_interfaces:
        raise ValueError(
            "v10.AgentCard.supported_interfaces is empty; v0.3 requires at "
            "least a main url/preferred_transport pair and cannot be built"
        )

    main_iface = c.supported_interfaces[0]
    additional = (
        [agent_interface(i) for i in c.supported_interfaces[1:]]
        if len(c.supported_interfaces) > 1
        else None
    )
    if main_iface.tenant:
        _warn(
            f"v10.AgentCard main interface tenant={main_iface.tenant!r} dropped"
        )
    if main_iface.protocol_version and main_iface.protocol_version != "0.3":
        _warn(
            f"v10.AgentCard main interface protocol_version="
            f"{main_iface.protocol_version!r} is not 0.3 and was dropped"
        )

    security: list[dict[str, list[str]]] | None = None
    if c.security_requirements:
        security = [_security_requirement_to_dict(r) for r in c.security_requirements]

    security_schemes: dict[str, v03.SecurityScheme] | None = None
    if c.security_schemes:
        security_schemes = {
            name: security_scheme(scheme) for name, scheme in c.security_schemes.items()
        }

    return v03.AgentCard(
        additional_interfaces=additional,
        capabilities=agent_capabilities(c.capabilities),
        default_input_modes=list(c.default_input_modes),
        default_output_modes=list(c.default_output_modes),
        description=c.description,
        documentation_url=c.documentation_url,
        icon_url=c.icon_url,
        name=c.name,
        preferred_transport=main_iface.protocol_binding or "JSONRPC",
        protocol_version="0.3.0",
        provider=agent_provider(c.provider) if c.provider is not None else None,
        security=security,
        security_schemes=security_schemes,
        signatures=(
            [agent_card_signature(s) for s in c.signatures] if c.signatures else None
        ),
        skills=[agent_skill(s) for s in c.skills],
        supports_authenticated_extended_card=c.capabilities.extended_agent_card,
        url=main_iface.url,
        version=c.version,
    )


@singledispatch
def from_v10_to_v03(obj: Any) -> Any:
    """Dispatch a v1.0 model to the matching v0.3 converter.

    Falls back to a ``TypeError`` for unsupported types rather than
    silently returning the input, so callers notice when they forget to
    handle a message shape.
    """
    raise TypeError(f"No v10 -> v03 converter registered for {type(obj).__name__}")


for _v10_type, _fn in {
    v10.Message: message,
    v10.Part: part,
    v10.Artifact: artifact,
    v10.Task: task,
    v10.TaskStatus: task_status,
    v10.TaskStatusUpdateEvent: task_status_update_event,
    v10.TaskArtifactUpdateEvent: task_artifact_update_event,
    v10.AuthenticationInfo: authentication_info,
    v10.TaskPushNotificationConfig: task_push_notification_config,
    v10.SendMessageConfiguration: send_message_configuration,
    v10.SendMessageRequest: send_message_request,
    v10.AgentCard: agent_card,
    v10.AgentCapabilities: agent_capabilities,
    v10.AgentInterface: agent_interface,
    v10.AgentProvider: agent_provider,
    v10.AgentExtension: agent_extension,
    v10.AgentSkill: agent_skill,
    v10.AgentCardSignature: agent_card_signature,
    v10.SecurityScheme: security_scheme,
    v10.OAuthFlows: oauth_flows,
}.items():
    from_v10_to_v03.register(_v10_type)(_fn)
