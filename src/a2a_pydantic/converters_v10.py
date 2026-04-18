"""Upward conversion from A2A v0.3 models to v1.0 models.

Public API is exactly one function: :func:`convert_to_v10`. Hand it any
supported v0.3 model and it returns the matching v1.0 model, dispatching
on the input type.

Upward conversion is fundamentally lossy in a *different* direction from
:func:`a2a_pydantic.converters.convert_to_v03`: v1.0 introduces fields
that v0.3 has no source for (``tenant``, ``protocol_binding`` vs
``protocol_version`` split, ``pkce_required``, AwareDatetime timestamps,
per-message extensions, ...). Rather than silently invent values, the
converter defaults them to ``None`` / ``[]`` / ``""`` and accepts two
optional context kwargs so wire-layer callers can fill in what they
know:

- ``tenant`` — applied to :class:`v10.SendMessageRequest`,
  :class:`v10.AgentInterface` and :class:`v10.TaskPushNotificationConfig`.
- ``message_extensions`` — overrides :attr:`v10.Message.extensions` when
  the v0.3 source has nothing to copy from. Useful when the framework
  knows which protocol extensions are in play from request metadata.

Both kwargs are propagated through recursive calls via
:class:`contextvars.ContextVar` so top-level context reaches every
nested converter without threading through function signatures.

Every lossy step (``TaskState.unknown`` coerced to
``task_state_submitted``, multi-scheme push auth collapsed to a single
scheme, v0.3-only ``state_transition_history`` dropped, ...) emits a
``UserWarning`` so callers can capture and surface them.
"""

from __future__ import annotations

import warnings
from contextvars import ContextVar
from datetime import datetime
from functools import singledispatch
from typing import Any, overload

from a2a_pydantic import v03, v10

__all__ = ["convert_to_v10"]


def _warn(message: str) -> None:
    warnings.warn(message, UserWarning, stacklevel=3)


_TENANT: ContextVar[str | None] = ContextVar("_convert_to_v10_tenant", default=None)
_MESSAGE_EXT: ContextVar[list[str] | None] = ContextVar(
    "_convert_to_v10_message_extensions", default=None
)


def _dict_to_struct(data: dict[str, Any] | None) -> v10.Struct | None:
    if not data:
        return None
    return v10.Struct.model_validate(data)


def _iso_to_timestamp(iso: str | None) -> v10.Timestamp | None:
    if iso is None:
        return None
    parsed = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return v10.Timestamp(root=parsed)


_ROLE_V03_TO_V10: dict[v03.Role, v10.Role] = {
    v03.Role.user: v10.Role.role_user,
    v03.Role.agent: v10.Role.role_agent,
}

_TASK_STATE_V03_TO_V10: dict[v03.TaskState, v10.TaskState] = {
    v03.TaskState.submitted: v10.TaskState.task_state_submitted,
    v03.TaskState.working: v10.TaskState.task_state_working,
    v03.TaskState.completed: v10.TaskState.task_state_completed,
    v03.TaskState.failed: v10.TaskState.task_state_failed,
    v03.TaskState.canceled: v10.TaskState.task_state_canceled,
    v03.TaskState.input_required: v10.TaskState.task_state_input_required,
    v03.TaskState.rejected: v10.TaskState.task_state_rejected,
    v03.TaskState.auth_required: v10.TaskState.task_state_auth_required,
}

_API_KEY_LOCATION_TO_V10: dict[v03.In, str] = {
    v03.In.query: "query",
    v03.In.header: "header",
    v03.In.cookie: "cookie",
}


def _role(v: v03.Role) -> v10.Role:
    return _ROLE_V03_TO_V10[v]


def _task_state(v: v03.TaskState) -> v10.TaskState:
    mapped = _TASK_STATE_V03_TO_V10.get(v)
    if mapped is not None:
        return mapped
    _warn(
        f"v03.TaskState.{v.name!r} has no v1.0 equivalent; coercing to "
        "v10.TaskState.task_state_submitted"
    )
    return v10.TaskState.task_state_submitted


def _part(p: v03.Part) -> v10.Part:
    """Fold a v0.3 discriminated-union ``Part`` into v1.0's flat shape."""
    root = p.root
    metadata = _dict_to_struct(root.metadata)

    if isinstance(root, v03.TextPart):
        return v10.Part(text=root.text, metadata=metadata)

    if isinstance(root, v03.DataPart):
        return v10.Part(
            data=root.data,
            media_type="application/json",
            metadata=metadata,
        )

    file_payload = root.file
    if isinstance(file_payload, v03.FileWithBytes):
        return v10.Part(
            raw=file_payload.bytes,
            media_type=file_payload.mime_type,
            filename=file_payload.name,
            metadata=metadata,
        )
    return v10.Part(
        url=file_payload.uri,
        media_type=file_payload.mime_type,
        filename=file_payload.name,
        metadata=metadata,
    )


def _message(m: v03.Message) -> v10.Message:
    kwarg_ext = _MESSAGE_EXT.get()
    if kwarg_ext is not None:
        extensions: list[str] | None = list(kwarg_ext)
    elif m.extensions:
        extensions = list(m.extensions)
    else:
        extensions = None

    return v10.Message(
        context_id=m.context_id or "",
        extensions=extensions,
        message_id=m.message_id,
        metadata=_dict_to_struct(m.metadata),
        parts=[_part(p) for p in m.parts],
        reference_task_ids=(list(m.reference_task_ids) if m.reference_task_ids else None),
        role=_role(m.role),
        task_id=m.task_id or "",
    )


def _artifact(a: v03.Artifact) -> v10.Artifact:
    return v10.Artifact(
        artifact_id=a.artifact_id,
        description=a.description or "",
        extensions=list(a.extensions) if a.extensions else None,
        metadata=_dict_to_struct(a.metadata),
        name=a.name or "",
        parts=[_part(p) for p in a.parts],
    )


def _task_status(s: v03.TaskStatus) -> v10.TaskStatus:
    return v10.TaskStatus(
        message=_message(s.message) if s.message is not None else None,
        state=_task_state(s.state),
        timestamp=_iso_to_timestamp(s.timestamp),
    )


def _task(t: v03.Task) -> v10.Task:
    return v10.Task(
        artifacts=[_artifact(a) for a in t.artifacts] if t.artifacts else None,
        context_id=t.context_id or "",
        history=[_message(m) for m in t.history] if t.history else None,
        id=t.id,
        metadata=_dict_to_struct(t.metadata),
        status=_task_status(t.status),
    )


def _authentication_info(
    a: v03.PushNotificationAuthenticationInfo,
) -> v10.AuthenticationInfo:
    if not a.schemes:
        _warn(
            "v03.PushNotificationAuthenticationInfo.schemes is empty; "
            "v10.AuthenticationInfo requires a scheme, defaulting to ''"
        )
        scheme = ""
    else:
        scheme = a.schemes[0]
        if len(a.schemes) > 1:
            _warn(
                f"v03.PushNotificationAuthenticationInfo.schemes={a.schemes!r} "
                f"has multiple entries; v10.AuthenticationInfo has a single "
                f"'scheme' field, keeping {scheme!r} and dropping the rest"
            )
    return v10.AuthenticationInfo(credentials=a.credentials or "", scheme=scheme)


def _push_notification_config(c: v03.PushNotificationConfig) -> v10.TaskPushNotificationConfig:
    """Convert a v0.3 ``PushNotificationConfig`` into a v1.0
    ``TaskPushNotificationConfig``.

    v0.3's push notification config is a standalone object; v1.0 folds
    config + task id into a single flat model. We leave ``task_id=""``
    since v0.3 has no task id at this level; callers that know the task
    id should use the :class:`v03.TaskPushNotificationConfig` converter
    or re-assign after.
    """
    return v10.TaskPushNotificationConfig(
        authentication=(
            _authentication_info(c.authentication) if c.authentication is not None else None
        ),
        id=c.id or "",
        task_id="",
        tenant=_TENANT.get() or "",
        token=c.token or "",
        url=c.url,
    )


def _task_push_notification_config(
    c: v03.TaskPushNotificationConfig,
) -> v10.TaskPushNotificationConfig:
    inner = _push_notification_config(c.push_notification_config)
    inner.task_id = c.task_id
    return inner


def _send_message_configuration(
    c: v03.MessageSendConfiguration,
) -> v10.SendMessageConfiguration:
    push_cfg: v10.TaskPushNotificationConfig | None = None
    if c.push_notification_config is not None:
        push_cfg = _push_notification_config(c.push_notification_config)

    return v10.SendMessageConfiguration(
        accepted_output_modes=(list(c.accepted_output_modes) if c.accepted_output_modes else None),
        history_length=c.history_length,
        return_immediately=(not c.blocking) if c.blocking is not None else False,
        task_push_notification_config=push_cfg,
    )


def _message_send_params(r: v03.MessageSendParams) -> v10.SendMessageRequest:
    return v10.SendMessageRequest(
        configuration=(
            _send_message_configuration(r.configuration) if r.configuration is not None else None
        ),
        message=_message(r.message),
        metadata=_dict_to_struct(r.metadata),
        tenant=_TENANT.get() or "",
    )


def _agent_extension(e: v03.AgentExtension) -> v10.AgentExtension:
    return v10.AgentExtension(
        description=e.description or "",
        params=_dict_to_struct(e.params),
        required=e.required if e.required is not None else False,
        uri=e.uri,
    )


def _agent_capabilities(c: v03.AgentCapabilities) -> v10.AgentCapabilities:
    if c.state_transition_history is not None:
        _warn(
            "v03.AgentCapabilities.state_transition_history has no v1.0 "
            "equivalent and was dropped"
        )
    return v10.AgentCapabilities(
        extended_agent_card=None,
        extensions=([_agent_extension(x) for x in c.extensions] if c.extensions else None),
        push_notifications=c.push_notifications,
        streaming=c.streaming,
    )


def _agent_interface(i: v03.AgentInterface) -> v10.AgentInterface:
    return v10.AgentInterface(
        protocol_binding=i.transport,
        protocol_version="0.3",
        tenant=_TENANT.get() or "",
        url=i.url,
    )


def _agent_provider(p: v03.AgentProvider) -> v10.AgentProvider:
    return v10.AgentProvider(organization=p.organization, url=p.url)


def _security_dict_to_requirement(entry: dict[str, list[str]]) -> v10.SecurityRequirement:
    return v10.SecurityRequirement(
        schemes={name: v10.StringList(strings=list(scopes)) for name, scopes in entry.items()}
    )


def _agent_skill(s: v03.AgentSkill) -> v10.AgentSkill:
    security_requirements: list[v10.SecurityRequirement] | None = None
    if s.security:
        security_requirements = [_security_dict_to_requirement(entry) for entry in s.security]
    return v10.AgentSkill(
        description=s.description,
        examples=list(s.examples) if s.examples else None,
        id=s.id,
        input_modes=list(s.input_modes) if s.input_modes else None,
        name=s.name,
        output_modes=list(s.output_modes) if s.output_modes else None,
        security_requirements=security_requirements,
        tags=list(s.tags),
    )


def _agent_card_signature(s: v03.AgentCardSignature) -> v10.AgentCardSignature:
    return v10.AgentCardSignature(
        header=_dict_to_struct(s.header),
        protected=s.protected,
        signature=s.signature,
    )


def _api_key_scheme(s: v03.APIKeySecurityScheme) -> v10.APIKeySecurityScheme:
    return v10.APIKeySecurityScheme(
        description=s.description or "",
        location=_API_KEY_LOCATION_TO_V10[s.in_],
        name=s.name,
    )


def _http_auth_scheme(s: v03.HTTPAuthSecurityScheme) -> v10.HTTPAuthSecurityScheme:
    return v10.HTTPAuthSecurityScheme(
        bearer_format=s.bearer_format or "",
        description=s.description or "",
        scheme=s.scheme,
    )


def _mtls_scheme(s: v03.MutualTLSSecurityScheme) -> v10.MutualTlsSecurityScheme:
    return v10.MutualTlsSecurityScheme(description=s.description or "")


def _openid_scheme(s: v03.OpenIdConnectSecurityScheme) -> v10.OpenIdConnectSecurityScheme:
    return v10.OpenIdConnectSecurityScheme(
        description=s.description or "",
        open_id_connect_url=s.open_id_connect_url,
    )


def _authorization_code_flow(
    f: v03.AuthorizationCodeOAuthFlow,
) -> v10.AuthorizationCodeOAuthFlow:
    return v10.AuthorizationCodeOAuthFlow(
        authorization_url=f.authorization_url,
        pkce_required=False,
        refresh_url=f.refresh_url or "",
        scopes=dict(f.scopes),
        token_url=f.token_url,
    )


def _client_credentials_flow(
    f: v03.ClientCredentialsOAuthFlow,
) -> v10.ClientCredentialsOAuthFlow:
    return v10.ClientCredentialsOAuthFlow(
        refresh_url=f.refresh_url or "",
        scopes=dict(f.scopes),
        token_url=f.token_url,
    )


def _implicit_flow(f: v03.ImplicitOAuthFlow) -> v10.ImplicitOAuthFlow:
    return v10.ImplicitOAuthFlow(
        authorization_url=f.authorization_url,
        refresh_url=f.refresh_url or "",
        scopes=dict(f.scopes),
    )


def _password_flow(f: v03.PasswordOAuthFlow) -> v10.PasswordOAuthFlow:
    return v10.PasswordOAuthFlow(
        refresh_url=f.refresh_url or "",
        scopes=dict(f.scopes),
        token_url=f.token_url,
    )


def _oauth_flows(f: v03.OAuthFlows) -> v10.OAuthFlows:
    populated = [
        name
        for name in ("authorization_code", "client_credentials", "implicit", "password")
        if getattr(f, name) is not None
    ]
    if not populated:
        raise ValueError(
            "v03.OAuthFlows has no flow populated; v10.OAuthFlows enforces "
            "exactly one of {authorization_code, client_credentials, "
            "device_code, implicit, password}"
        )
    if len(populated) > 1:
        kept = populated[0]
        dropped = populated[1:]
        _warn(
            f"v03.OAuthFlows has multiple flows populated; v10.OAuthFlows is "
            f"strict one-of, keeping {kept!r} and dropping {dropped}"
        )

    chosen = populated[0]
    kwargs: dict[str, Any] = {}
    if chosen == "authorization_code":
        assert f.authorization_code is not None
        kwargs["authorization_code"] = _authorization_code_flow(f.authorization_code)
    elif chosen == "client_credentials":
        assert f.client_credentials is not None
        kwargs["client_credentials"] = _client_credentials_flow(f.client_credentials)
    elif chosen == "implicit":
        assert f.implicit is not None
        kwargs["implicit"] = _implicit_flow(f.implicit)
    else:
        assert f.password is not None
        kwargs["password"] = _password_flow(f.password)
    return v10.OAuthFlows(**kwargs)


def _oauth2_scheme(s: v03.OAuth2SecurityScheme) -> v10.OAuth2SecurityScheme:
    return v10.OAuth2SecurityScheme(
        description=s.description or "",
        flows=_oauth_flows(s.flows),
        oauth2_metadata_url=s.oauth2_metadata_url or "",
    )


def _security_scheme(s: v03.SecurityScheme) -> v10.SecurityScheme:
    root = s.root
    if isinstance(root, v03.APIKeySecurityScheme):
        return v10.SecurityScheme(api_key_security_scheme=_api_key_scheme(root))
    if isinstance(root, v03.HTTPAuthSecurityScheme):
        return v10.SecurityScheme(http_auth_security_scheme=_http_auth_scheme(root))
    if isinstance(root, v03.OAuth2SecurityScheme):
        return v10.SecurityScheme(oauth2_security_scheme=_oauth2_scheme(root))
    if isinstance(root, v03.OpenIdConnectSecurityScheme):
        return v10.SecurityScheme(open_id_connect_security_scheme=_openid_scheme(root))
    return v10.SecurityScheme(mtls_security_scheme=_mtls_scheme(root))


def _agent_card(c: v03.AgentCard) -> v10.AgentCard:
    """Convert a v0.3 ``AgentCard`` into a v1.0 ``AgentCard``.

    The main shape mismatch is in how interfaces are listed: v0.3 has a
    main ``url``/``preferred_transport`` pair plus an optional
    ``additional_interfaces`` list; v1.0 merges both into a single
    ``supported_interfaces`` list with the preferred interface first.
    Security requirements are also reshaped from
    ``list[dict[str, list[str]]]`` to
    ``list[SecurityRequirement]``.
    """
    main_iface = v10.AgentInterface(
        protocol_binding=c.preferred_transport or "JSONRPC",
        protocol_version="0.3",
        tenant=_TENANT.get() or "",
        url=c.url,
    )
    supported: list[v10.AgentInterface] = [main_iface]
    if c.additional_interfaces:
        supported.extend(_agent_interface(i) for i in c.additional_interfaces)

    security_requirements: list[v10.SecurityRequirement] | None = None
    if c.security:
        security_requirements = [_security_dict_to_requirement(entry) for entry in c.security]

    security_schemes: dict[str, v10.SecurityScheme] | None = None
    if c.security_schemes:
        security_schemes = {name: _security_scheme(v) for name, v in c.security_schemes.items()}

    capabilities = _agent_capabilities(c.capabilities)
    if c.supports_authenticated_extended_card is not None:
        capabilities.extended_agent_card = c.supports_authenticated_extended_card

    return v10.AgentCard(
        capabilities=capabilities,
        default_input_modes=list(c.default_input_modes),
        default_output_modes=list(c.default_output_modes),
        description=c.description,
        documentation_url=c.documentation_url,
        icon_url=c.icon_url,
        name=c.name,
        provider=_agent_provider(c.provider) if c.provider is not None else None,
        security_requirements=security_requirements,
        security_schemes=security_schemes,
        signatures=(
            [_agent_card_signature(s) for s in c.signatures] if c.signatures else None
        ),
        skills=[_agent_skill(s) for s in c.skills],
        supported_interfaces=supported,
        version=c.version,
    )


@singledispatch
def _dispatch_to_v10(obj: Any) -> Any:
    raise TypeError(f"No v03 -> v10 converter registered for {type(obj).__name__}")


for _v03_type, _fn in {
    v03.Part: _part,
    v03.Message: _message,
    v03.Artifact: _artifact,
    v03.TaskStatus: _task_status,
    v03.Task: _task,
    v03.MessageSendConfiguration: _send_message_configuration,
    v03.MessageSendParams: _message_send_params,
    v03.PushNotificationAuthenticationInfo: _authentication_info,
    v03.PushNotificationConfig: _push_notification_config,
    v03.TaskPushNotificationConfig: _task_push_notification_config,
    v03.AgentExtension: _agent_extension,
    v03.AgentInterface: _agent_interface,
    v03.AgentSkill: _agent_skill,
    v03.AgentCapabilities: _agent_capabilities,
    v03.AgentProvider: _agent_provider,
    v03.AgentCardSignature: _agent_card_signature,
    v03.SecurityScheme: _security_scheme,
    v03.OAuthFlows: _oauth_flows,
    v03.AgentCard: _agent_card,
}.items():
    _dispatch_to_v10.register(_v03_type)(_fn)  # type: ignore[arg-type]


# Enums dispatch by their own class; register separately so that
# ``convert_to_v10(v03.Role.user)`` and ``convert_to_v10(v03.TaskState.working)``
# return the mapped v1.0 enum member rather than raising.
_dispatch_to_v10.register(v03.Role)(_role)
_dispatch_to_v10.register(v03.TaskState)(_task_state)


@overload
def convert_to_v10(
    obj: v03.MessageSendParams,
    *,
    tenant: str | None = None,
    message_extensions: list[str] | None = None,
) -> v10.SendMessageRequest: ...
@overload
def convert_to_v10(
    obj: v03.MessageSendConfiguration,
    *,
    tenant: str | None = None,
    message_extensions: list[str] | None = None,
) -> v10.SendMessageConfiguration: ...
@overload
def convert_to_v10(
    obj: v03.Message,
    *,
    tenant: str | None = None,
    message_extensions: list[str] | None = None,
) -> v10.Message: ...
@overload
def convert_to_v10(
    obj: v03.Part,
    *,
    tenant: str | None = None,
    message_extensions: list[str] | None = None,
) -> v10.Part: ...
@overload
def convert_to_v10(
    obj: v03.Artifact,
    *,
    tenant: str | None = None,
    message_extensions: list[str] | None = None,
) -> v10.Artifact: ...
@overload
def convert_to_v10(
    obj: v03.Task,
    *,
    tenant: str | None = None,
    message_extensions: list[str] | None = None,
) -> v10.Task: ...
@overload
def convert_to_v10(
    obj: v03.TaskStatus,
    *,
    tenant: str | None = None,
    message_extensions: list[str] | None = None,
) -> v10.TaskStatus: ...
@overload
def convert_to_v10(
    obj: v03.PushNotificationAuthenticationInfo,
    *,
    tenant: str | None = None,
    message_extensions: list[str] | None = None,
) -> v10.AuthenticationInfo: ...
@overload
def convert_to_v10(
    obj: v03.PushNotificationConfig,
    *,
    tenant: str | None = None,
    message_extensions: list[str] | None = None,
) -> v10.TaskPushNotificationConfig: ...
@overload
def convert_to_v10(
    obj: v03.TaskPushNotificationConfig,
    *,
    tenant: str | None = None,
    message_extensions: list[str] | None = None,
) -> v10.TaskPushNotificationConfig: ...
@overload
def convert_to_v10(
    obj: v03.AgentExtension,
    *,
    tenant: str | None = None,
    message_extensions: list[str] | None = None,
) -> v10.AgentExtension: ...
@overload
def convert_to_v10(
    obj: v03.AgentInterface,
    *,
    tenant: str | None = None,
    message_extensions: list[str] | None = None,
) -> v10.AgentInterface: ...
@overload
def convert_to_v10(
    obj: v03.AgentSkill,
    *,
    tenant: str | None = None,
    message_extensions: list[str] | None = None,
) -> v10.AgentSkill: ...
@overload
def convert_to_v10(
    obj: v03.AgentCapabilities,
    *,
    tenant: str | None = None,
    message_extensions: list[str] | None = None,
) -> v10.AgentCapabilities: ...
@overload
def convert_to_v10(
    obj: v03.AgentProvider,
    *,
    tenant: str | None = None,
    message_extensions: list[str] | None = None,
) -> v10.AgentProvider: ...
@overload
def convert_to_v10(
    obj: v03.AgentCardSignature,
    *,
    tenant: str | None = None,
    message_extensions: list[str] | None = None,
) -> v10.AgentCardSignature: ...
@overload
def convert_to_v10(
    obj: v03.SecurityScheme,
    *,
    tenant: str | None = None,
    message_extensions: list[str] | None = None,
) -> v10.SecurityScheme: ...
@overload
def convert_to_v10(
    obj: v03.OAuthFlows,
    *,
    tenant: str | None = None,
    message_extensions: list[str] | None = None,
) -> v10.OAuthFlows: ...
@overload
def convert_to_v10(
    obj: v03.AgentCard,
    *,
    tenant: str | None = None,
    message_extensions: list[str] | None = None,
) -> v10.AgentCard: ...
@overload
def convert_to_v10(
    obj: v03.Role,
    *,
    tenant: str | None = None,
    message_extensions: list[str] | None = None,
) -> v10.Role: ...
@overload
def convert_to_v10(
    obj: v03.TaskState,
    *,
    tenant: str | None = None,
    message_extensions: list[str] | None = None,
) -> v10.TaskState: ...
def convert_to_v10(
    obj: Any,
    *,
    tenant: str | None = None,
    message_extensions: list[str] | None = None,
) -> Any:
    """Upgrade a v0.3 A2A model to its v1.0 equivalent.

    Dispatches on the runtime type of ``obj``. Raises :class:`TypeError`
    for unsupported types rather than silently returning the input.

    Fields v1.0 has but v0.3 doesn't (``tenant``, ``protocol_binding``,
    ``pkce_required``, ...) default to ``None`` / ``[]`` / ``""`` unless
    a context kwarg provides a value:

    - ``tenant`` flows into :class:`v10.SendMessageRequest.tenant`,
      :class:`v10.AgentInterface.tenant` and
      :class:`v10.TaskPushNotificationConfig.tenant`.
    - ``message_extensions`` overrides :attr:`v10.Message.extensions`
      when the v0.3 source has no extensions to copy.

    Every lossy step (``TaskState.unknown`` coerced, multi-scheme push
    auth collapsed to a single scheme, ``state_transition_history``
    dropped, ...) emits a ``UserWarning``. Typical capture pattern::

        import warnings
        from a2a_pydantic import convert_to_v10, v03

        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            req = convert_to_v10(v03_params, tenant="acme")

        for w in captured:
            log.warning("a2a upgrade: %s", w.message)
    """
    tenant_token = _TENANT.set(tenant)
    ext_token = _MESSAGE_EXT.set(message_extensions)
    try:
        return _dispatch_to_v10(obj)
    finally:
        _MESSAGE_EXT.reset(ext_token)
        _TENANT.reset(tenant_token)
