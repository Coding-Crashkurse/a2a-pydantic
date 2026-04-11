"""Convert a2a-pydantic v1.0 models to a2a-sdk protobuf messages.

Public API is exactly one function: :func:`convert_to_proto`. It takes any
supported v1.0 Pydantic model and returns the matching ``a2a_pb2``
``google.protobuf.Message`` instance, dispatching on the input type.

Only v1.0 is supported. v0.3 models have no direct proto counterpart —
go through :func:`a2a_pydantic.convert_to_v03` in reverse (not provided)
or upgrade your data path to v1.0 first.

**Requires the optional [proto] extra:**

    pip install a2a-pydantic[proto]

which pulls in ``a2a-sdk>=1.0.0a0`` for the ``a2a.types.a2a_pb2`` module.
Importing this module without the extra raises a clear ``ImportError``
pointing at the install command.
"""

from __future__ import annotations

try:
    from a2a.types import a2a_pb2 as pb2
    from google.protobuf import struct_pb2, timestamp_pb2
except ImportError as e:
    raise ImportError(
        "a2a_pydantic.to_proto requires the [proto] optional extra.\n"
        "Install with:  pip install a2a-pydantic[proto]"
    ) from e

import base64
import warnings
from functools import singledispatch
from typing import Any, overload

from a2a_pydantic import v10

__all__ = ["convert_to_proto"]


def _warn_multi_oneof(type_name: str, oneof_name: str, populated: list[str]) -> None:
    """Warn when a Pydantic envelope populates more than one oneof slot.

    pb2 silently collapses to the last write, which would drop earlier
    payloads without a trace. We mirror the v0.3 converter's behavior
    of warning about strict one-of violations so callers see the loss.
    """
    warnings.warn(
        f"{type_name} has multiple {oneof_name} payloads {populated}; "
        f"pb2's oneof collapses to the last-written field, dropping "
        f"earlier writes. Only populate one.",
        UserWarning,
        stacklevel=3,
    )


def _value_from_any(v: Any) -> struct_pb2.Value:
    """Build a ``google.protobuf.Value`` from an arbitrary Python JSON value."""
    out = struct_pb2.Value()
    if v is None:
        out.null_value = struct_pb2.NULL_VALUE
    elif isinstance(v, bool):
        out.bool_value = v
    elif isinstance(v, (int, float)):
        out.number_value = float(v)
    elif isinstance(v, str):
        out.string_value = v
    elif isinstance(v, list):
        for item in v:
            out.list_value.values.append(_value_from_any(item))
    elif isinstance(v, dict):
        for k, val in v.items():
            out.struct_value.fields[str(k)].CopyFrom(_value_from_any(val))
    else:
        out.string_value = str(v)
    return out


def _dict_to_pb_struct(d: dict[str, Any] | None) -> struct_pb2.Struct | None:
    if not d:
        return None
    s = struct_pb2.Struct()
    for k, v in d.items():
        s.fields[str(k)].CopyFrom(_value_from_any(v))
    return s


def _struct_obj_to_pb(s: v10.Struct | None) -> struct_pb2.Struct | None:
    """Convert a v10 ``Struct`` placeholder to a ``google.protobuf.Struct``.

    v10's ``Struct`` is a generated stub with no declared fields, so this
    normally yields an empty proto Struct. We still go through
    ``model_dump`` so that any ``extra='allow'`` payload (if the base
    class ever gains it) round-trips.
    """
    if s is None:
        return None
    data = s.model_dump(by_alias=False, exclude_none=True)
    return _dict_to_pb_struct(data)


def _value_obj_to_pb(v: v10.Value | None) -> struct_pb2.Value | None:
    if v is None:
        return None
    return _value_from_any(v.root)


def _timestamp_to_pb(
    ts: v10.Timestamp | None,
) -> timestamp_pb2.Timestamp | None:
    if ts is None:
        return None
    out = timestamp_pb2.Timestamp()
    out.FromDatetime(ts.root)
    return out


_ROLE_TO_PROTO: dict[v10.Role, int] = {
    v10.Role.role_user: pb2.ROLE_USER,
    v10.Role.role_agent: pb2.ROLE_AGENT,
}

_TASK_STATE_TO_PROTO: dict[v10.TaskState, int] = {
    v10.TaskState.task_state_submitted: pb2.TASK_STATE_SUBMITTED,
    v10.TaskState.task_state_working: pb2.TASK_STATE_WORKING,
    v10.TaskState.task_state_completed: pb2.TASK_STATE_COMPLETED,
    v10.TaskState.task_state_failed: pb2.TASK_STATE_FAILED,
    v10.TaskState.task_state_canceled: pb2.TASK_STATE_CANCELED,
    v10.TaskState.task_state_input_required: pb2.TASK_STATE_INPUT_REQUIRED,
    v10.TaskState.task_state_rejected: pb2.TASK_STATE_REJECTED,
    v10.TaskState.task_state_auth_required: pb2.TASK_STATE_AUTH_REQUIRED,
}


def _decode_raw(raw: str | None) -> bytes:
    """v10 stores ``Part.raw`` as a base64 string; pb2 needs raw bytes."""
    if not raw:
        return b""
    try:
        return base64.b64decode(raw, validate=False)
    except Exception:
        return raw.encode("utf-8")


def _to_pb_part(p: v10.Part) -> pb2.Part:
    populated = [
        n for n in ("text", "raw", "url", "data") if getattr(p, n) is not None
    ]
    if len(populated) > 1:
        _warn_multi_oneof("v10.Part", "content", populated)
    out = pb2.Part()
    if p.text is not None:
        out.text = p.text
    if p.raw is not None:
        out.raw = _decode_raw(p.raw)
    if p.url is not None:
        out.url = p.url
    if p.data is not None:
        out.data.CopyFrom(_value_from_any(p.data.root))
    if p.filename:
        out.filename = p.filename
    if p.media_type:
        out.media_type = p.media_type
    meta = _struct_obj_to_pb(p.metadata)
    if meta is not None:
        out.metadata.CopyFrom(meta)
    return out


def _to_pb_message(m: v10.Message) -> pb2.Message:
    out = pb2.Message(
        message_id=m.message_id,
        context_id=m.context_id or "",
        task_id=m.task_id or "",
        role=_ROLE_TO_PROTO[m.role],
    )
    for part in m.parts:
        out.parts.append(_to_pb_part(part))
    if m.extensions:
        out.extensions.extend(m.extensions)
    if m.reference_task_ids:
        out.reference_task_ids.extend(m.reference_task_ids)
    meta = _struct_obj_to_pb(m.metadata)
    if meta is not None:
        out.metadata.CopyFrom(meta)
    return out


def _to_pb_artifact(a: v10.Artifact) -> pb2.Artifact:
    out = pb2.Artifact(
        artifact_id=a.artifact_id,
        name=a.name or "",
        description=a.description or "",
    )
    for part in a.parts:
        out.parts.append(_to_pb_part(part))
    if a.extensions:
        out.extensions.extend(a.extensions)
    meta = _struct_obj_to_pb(a.metadata)
    if meta is not None:
        out.metadata.CopyFrom(meta)
    return out


def _to_pb_task_status(s: v10.TaskStatus) -> pb2.TaskStatus:
    out = pb2.TaskStatus(state=_TASK_STATE_TO_PROTO[s.state])
    if s.message is not None:
        out.message.CopyFrom(_to_pb_message(s.message))
    ts = _timestamp_to_pb(s.timestamp)
    if ts is not None:
        out.timestamp.CopyFrom(ts)
    return out


def _to_pb_task(t: v10.Task) -> pb2.Task:
    out = pb2.Task(
        id=t.id,
        context_id=t.context_id or "",
        status=_to_pb_task_status(t.status),
    )
    if t.artifacts:
        for art in t.artifacts:
            out.artifacts.append(_to_pb_artifact(art))
    if t.history:
        for msg in t.history:
            out.history.append(_to_pb_message(msg))
    meta = _struct_obj_to_pb(t.metadata)
    if meta is not None:
        out.metadata.CopyFrom(meta)
    return out


def _to_pb_task_status_update_event(
    e: v10.TaskStatusUpdateEvent,
) -> pb2.TaskStatusUpdateEvent:
    out = pb2.TaskStatusUpdateEvent(
        task_id=e.task_id,
        context_id=e.context_id,
        status=_to_pb_task_status(e.status),
    )
    meta = _struct_obj_to_pb(e.metadata)
    if meta is not None:
        out.metadata.CopyFrom(meta)
    return out


def _to_pb_task_artifact_update_event(
    e: v10.TaskArtifactUpdateEvent,
) -> pb2.TaskArtifactUpdateEvent:
    out = pb2.TaskArtifactUpdateEvent(
        task_id=e.task_id,
        context_id=e.context_id,
        artifact=_to_pb_artifact(e.artifact),
        append=bool(e.append),
        last_chunk=bool(e.last_chunk),
    )
    meta = _struct_obj_to_pb(e.metadata)
    if meta is not None:
        out.metadata.CopyFrom(meta)
    return out


def _to_pb_authentication_info(
    a: v10.AuthenticationInfo,
) -> pb2.AuthenticationInfo:
    return pb2.AuthenticationInfo(
        scheme=a.scheme,
        credentials=a.credentials or "",
    )


def _to_pb_task_push_notification_config(
    c: v10.TaskPushNotificationConfig,
) -> pb2.TaskPushNotificationConfig:
    out = pb2.TaskPushNotificationConfig(
        tenant=c.tenant or "",
        id=c.id or "",
        task_id=c.task_id,
        url=c.url,
        token=c.token or "",
    )
    if c.authentication is not None:
        out.authentication.CopyFrom(_to_pb_authentication_info(c.authentication))
    return out


def _to_pb_send_message_configuration(
    c: v10.SendMessageConfiguration,
) -> pb2.SendMessageConfiguration:
    out = pb2.SendMessageConfiguration()
    if c.accepted_output_modes:
        out.accepted_output_modes.extend(c.accepted_output_modes)
    if c.task_push_notification_config is not None:
        out.task_push_notification_config.CopyFrom(
            _to_pb_task_push_notification_config(c.task_push_notification_config)
        )
    if c.history_length is not None:
        out.history_length = c.history_length
    if c.return_immediately is not None:
        out.return_immediately = c.return_immediately
    return out


def _to_pb_send_message_request(
    r: v10.SendMessageRequest,
) -> pb2.SendMessageRequest:
    out = pb2.SendMessageRequest(
        tenant=r.tenant or "",
        message=_to_pb_message(r.message),
    )
    if r.configuration is not None:
        out.configuration.CopyFrom(_to_pb_send_message_configuration(r.configuration))
    meta = _struct_obj_to_pb(r.metadata)
    if meta is not None:
        out.metadata.CopyFrom(meta)
    return out


def _to_pb_send_message_response(
    r: v10.SendMessageResponse,
) -> pb2.SendMessageResponse:
    populated = [n for n in ("task", "message") if getattr(r, n) is not None]
    if len(populated) > 1:
        _warn_multi_oneof("v10.SendMessageResponse", "payload", populated)
    out = pb2.SendMessageResponse()
    if r.task is not None:
        out.task.CopyFrom(_to_pb_task(r.task))
    if r.message is not None:
        out.message.CopyFrom(_to_pb_message(r.message))
    return out


def _to_pb_stream_response(r: v10.StreamResponse) -> pb2.StreamResponse:
    populated = [
        n
        for n in ("task", "message", "status_update", "artifact_update")
        if getattr(r, n) is not None
    ]
    if len(populated) > 1:
        _warn_multi_oneof("v10.StreamResponse", "payload", populated)
    out = pb2.StreamResponse()
    if r.task is not None:
        out.task.CopyFrom(_to_pb_task(r.task))
    if r.message is not None:
        out.message.CopyFrom(_to_pb_message(r.message))
    if r.status_update is not None:
        out.status_update.CopyFrom(_to_pb_task_status_update_event(r.status_update))
    if r.artifact_update is not None:
        out.artifact_update.CopyFrom(
            _to_pb_task_artifact_update_event(r.artifact_update)
        )
    return out


def _to_pb_agent_extension(e: v10.AgentExtension) -> pb2.AgentExtension:
    out = pb2.AgentExtension(
        uri=e.uri or "",
        description=e.description or "",
        required=bool(e.required),
    )
    params = _struct_obj_to_pb(e.params)
    if params is not None:
        out.params.CopyFrom(params)
    return out


def _to_pb_agent_capabilities(
    c: v10.AgentCapabilities,
) -> pb2.AgentCapabilities:
    out = pb2.AgentCapabilities()
    if c.streaming is not None:
        out.streaming = c.streaming
    if c.push_notifications is not None:
        out.push_notifications = c.push_notifications
    if c.extended_agent_card is not None:
        out.extended_agent_card = c.extended_agent_card
    if c.extensions:
        for ext in c.extensions:
            out.extensions.append(_to_pb_agent_extension(ext))
    return out


def _to_pb_agent_interface(i: v10.AgentInterface) -> pb2.AgentInterface:
    return pb2.AgentInterface(
        url=i.url,
        protocol_binding=i.protocol_binding,
        tenant=i.tenant or "",
        protocol_version=i.protocol_version,
    )


def _to_pb_agent_provider(p: v10.AgentProvider) -> pb2.AgentProvider:
    return pb2.AgentProvider(url=p.url, organization=p.organization)


def _to_pb_string_list(s: v10.StringList) -> pb2.StringList:
    out = pb2.StringList()
    out.list.extend(s.strings)
    return out


def _to_pb_security_requirement(
    r: v10.SecurityRequirement,
) -> pb2.SecurityRequirement:
    out = pb2.SecurityRequirement()
    for name, string_list in r.schemes.items():
        out.schemes[name].CopyFrom(_to_pb_string_list(string_list))
    return out


def _to_pb_api_key_scheme(
    s: v10.APIKeySecurityScheme,
) -> pb2.APIKeySecurityScheme:
    return pb2.APIKeySecurityScheme(
        description=s.description or "",
        location=s.location,
        name=s.name,
    )


def _to_pb_http_auth_scheme(
    s: v10.HTTPAuthSecurityScheme,
) -> pb2.HTTPAuthSecurityScheme:
    return pb2.HTTPAuthSecurityScheme(
        description=s.description or "",
        scheme=s.scheme,
        bearer_format=s.bearer_format or "",
    )


def _to_pb_mtls_scheme(
    s: v10.MutualTlsSecurityScheme,
) -> pb2.MutualTlsSecurityScheme:
    return pb2.MutualTlsSecurityScheme(description=s.description or "")


def _to_pb_openid_scheme(
    s: v10.OpenIdConnectSecurityScheme,
) -> pb2.OpenIdConnectSecurityScheme:
    return pb2.OpenIdConnectSecurityScheme(
        description=s.description or "",
        open_id_connect_url=s.open_id_connect_url,
    )


def _to_pb_authorization_code_flow(
    f: v10.AuthorizationCodeOAuthFlow,
) -> pb2.AuthorizationCodeOAuthFlow:
    out = pb2.AuthorizationCodeOAuthFlow(
        authorization_url=f.authorization_url,
        token_url=f.token_url,
        refresh_url=f.refresh_url or "",
    )
    if f.scopes:
        out.scopes.update(f.scopes)
    if f.pkce_required is not None:
        out.pkce_required = f.pkce_required
    return out


def _to_pb_client_credentials_flow(
    f: v10.ClientCredentialsOAuthFlow,
) -> pb2.ClientCredentialsOAuthFlow:
    out = pb2.ClientCredentialsOAuthFlow(
        token_url=f.token_url,
        refresh_url=f.refresh_url or "",
    )
    if f.scopes:
        out.scopes.update(f.scopes)
    return out


def _to_pb_implicit_flow(
    f: v10.ImplicitOAuthFlow,
) -> pb2.ImplicitOAuthFlow:
    out = pb2.ImplicitOAuthFlow(
        authorization_url=f.authorization_url,
        refresh_url=f.refresh_url or "",
    )
    if f.scopes:
        out.scopes.update(f.scopes)
    return out


def _to_pb_password_flow(
    f: v10.PasswordOAuthFlow,
) -> pb2.PasswordOAuthFlow:
    out = pb2.PasswordOAuthFlow(
        token_url=f.token_url,
        refresh_url=f.refresh_url or "",
    )
    if f.scopes:
        out.scopes.update(f.scopes)
    return out


def _to_pb_device_code_flow(
    f: v10.DeviceCodeOAuthFlow,
) -> pb2.DeviceCodeOAuthFlow:
    out = pb2.DeviceCodeOAuthFlow(
        device_authorization_url=f.device_authorization_url,
        token_url=f.token_url,
        refresh_url=f.refresh_url or "",
    )
    if f.scopes:
        out.scopes.update(f.scopes)
    return out


def _to_pb_oauth_flows(f: v10.OAuthFlows) -> pb2.OAuthFlows:
    populated = [
        n
        for n in (
            "authorization_code",
            "client_credentials",
            "implicit",
            "password",
            "device_code",
        )
        if getattr(f, n) is not None
    ]
    if len(populated) > 1:
        _warn_multi_oneof("v10.OAuthFlows", "flow", populated)
    out = pb2.OAuthFlows()
    if f.authorization_code is not None:
        out.authorization_code.CopyFrom(
            _to_pb_authorization_code_flow(f.authorization_code)
        )
    if f.client_credentials is not None:
        out.client_credentials.CopyFrom(
            _to_pb_client_credentials_flow(f.client_credentials)
        )
    if f.implicit is not None:
        out.implicit.CopyFrom(_to_pb_implicit_flow(f.implicit))
    if f.password is not None:
        out.password.CopyFrom(_to_pb_password_flow(f.password))
    if f.device_code is not None:
        out.device_code.CopyFrom(_to_pb_device_code_flow(f.device_code))
    return out


def _to_pb_oauth2_scheme(
    s: v10.OAuth2SecurityScheme,
) -> pb2.OAuth2SecurityScheme:
    return pb2.OAuth2SecurityScheme(
        description=s.description or "",
        flows=_to_pb_oauth_flows(s.flows),
        oauth2_metadata_url=s.oauth2_metadata_url or "",
    )


def _to_pb_security_scheme(
    s: v10.SecurityScheme,
) -> pb2.SecurityScheme:
    """Map v10 flat ``SecurityScheme`` envelope to pb2's oneof-backed scheme.

    Assignment to any of the five optional fields on pb2 ``SecurityScheme``
    is routed into the ``scheme`` oneof automatically; pb2 collapses to the
    last write if multiple are populated, so we warn in that case to match
    the v0.3 converter's strict one-of guarantee.
    """
    populated = [
        n
        for n in (
            "api_key_security_scheme",
            "http_auth_security_scheme",
            "oauth2_security_scheme",
            "open_id_connect_security_scheme",
            "mtls_security_scheme",
        )
        if getattr(s, n) is not None
    ]
    if len(populated) > 1:
        _warn_multi_oneof("v10.SecurityScheme", "scheme", populated)
    out = pb2.SecurityScheme()
    if s.api_key_security_scheme is not None:
        out.api_key_security_scheme.CopyFrom(
            _to_pb_api_key_scheme(s.api_key_security_scheme)
        )
    if s.http_auth_security_scheme is not None:
        out.http_auth_security_scheme.CopyFrom(
            _to_pb_http_auth_scheme(s.http_auth_security_scheme)
        )
    if s.oauth2_security_scheme is not None:
        out.oauth2_security_scheme.CopyFrom(
            _to_pb_oauth2_scheme(s.oauth2_security_scheme)
        )
    if s.open_id_connect_security_scheme is not None:
        out.open_id_connect_security_scheme.CopyFrom(
            _to_pb_openid_scheme(s.open_id_connect_security_scheme)
        )
    if s.mtls_security_scheme is not None:
        out.mtls_security_scheme.CopyFrom(
            _to_pb_mtls_scheme(s.mtls_security_scheme)
        )
    return out


def _to_pb_agent_skill(s: v10.AgentSkill) -> pb2.AgentSkill:
    out = pb2.AgentSkill(
        id=s.id,
        name=s.name,
        description=s.description,
    )
    out.tags.extend(s.tags)
    if s.examples:
        out.examples.extend(s.examples)
    if s.input_modes:
        out.input_modes.extend(s.input_modes)
    if s.output_modes:
        out.output_modes.extend(s.output_modes)
    if s.security_requirements:
        for req in s.security_requirements:
            out.security_requirements.append(_to_pb_security_requirement(req))
    return out


def _to_pb_agent_card_signature(
    s: v10.AgentCardSignature,
) -> pb2.AgentCardSignature:
    out = pb2.AgentCardSignature(
        protected=s.protected,
        signature=s.signature,
    )
    header = _struct_obj_to_pb(s.header)
    if header is not None:
        out.header.CopyFrom(header)
    return out


def _to_pb_agent_card(c: v10.AgentCard) -> pb2.AgentCard:
    out = pb2.AgentCard(
        name=c.name,
        description=c.description,
        version=c.version,
        capabilities=_to_pb_agent_capabilities(c.capabilities),
    )
    for iface in c.supported_interfaces:
        out.supported_interfaces.append(_to_pb_agent_interface(iface))
    if c.provider is not None:
        out.provider.CopyFrom(_to_pb_agent_provider(c.provider))
    if c.documentation_url is not None:
        out.documentation_url = c.documentation_url
    if c.icon_url is not None:
        out.icon_url = c.icon_url
    if c.default_input_modes:
        out.default_input_modes.extend(c.default_input_modes)
    if c.default_output_modes:
        out.default_output_modes.extend(c.default_output_modes)
    if c.security_schemes:
        for name, scheme in c.security_schemes.items():
            out.security_schemes[name].CopyFrom(_to_pb_security_scheme(scheme))
    if c.security_requirements:
        for req in c.security_requirements:
            out.security_requirements.append(_to_pb_security_requirement(req))
    for skill in c.skills:
        out.skills.append(_to_pb_agent_skill(skill))
    if c.signatures:
        for sig in c.signatures:
            out.signatures.append(_to_pb_agent_card_signature(sig))
    return out


def _to_pb_get_task_request(r: v10.GetTaskRequest) -> pb2.GetTaskRequest:
    out = pb2.GetTaskRequest(tenant=r.tenant or "", id=r.id)
    if r.history_length is not None:
        out.history_length = r.history_length
    return out


def _to_pb_list_tasks_request(
    r: v10.ListTasksRequest,
) -> pb2.ListTasksRequest:
    out = pb2.ListTasksRequest(
        tenant=r.tenant or "",
        context_id=r.context_id or "",
        page_token=r.page_token or "",
    )
    if r.status is not None:
        out.status = _TASK_STATE_TO_PROTO[r.status]
    if r.page_size is not None:
        out.page_size = r.page_size
    if r.history_length is not None:
        out.history_length = r.history_length
    if r.include_artifacts is not None:
        out.include_artifacts = r.include_artifacts
    ts = _timestamp_to_pb(r.status_timestamp_after)
    if ts is not None:
        out.status_timestamp_after.CopyFrom(ts)
    return out


def _to_pb_list_tasks_response(
    r: v10.ListTasksResponse,
) -> pb2.ListTasksResponse:
    out = pb2.ListTasksResponse(
        next_page_token=r.next_page_token,
        page_size=r.page_size,
        total_size=r.total_size,
    )
    for task in r.tasks:
        out.tasks.append(_to_pb_task(task))
    return out


def _to_pb_cancel_task_request(
    r: v10.CancelTaskRequest,
) -> pb2.CancelTaskRequest:
    out = pb2.CancelTaskRequest(tenant=r.tenant or "", id=r.id)
    meta = _struct_obj_to_pb(r.metadata)
    if meta is not None:
        out.metadata.CopyFrom(meta)
    return out


def _to_pb_get_task_push_notification_config_request(
    r: v10.GetTaskPushNotificationConfigRequest,
) -> pb2.GetTaskPushNotificationConfigRequest:
    return pb2.GetTaskPushNotificationConfigRequest(
        tenant=r.tenant or "",
        task_id=r.task_id,
        id=r.id,
    )


def _to_pb_delete_task_push_notification_config_request(
    r: v10.DeleteTaskPushNotificationConfigRequest,
) -> pb2.DeleteTaskPushNotificationConfigRequest:
    return pb2.DeleteTaskPushNotificationConfigRequest(
        tenant=r.tenant or "",
        task_id=r.task_id,
        id=r.id,
    )


def _to_pb_subscribe_to_task_request(
    r: v10.SubscribeToTaskRequest,
) -> pb2.SubscribeToTaskRequest:
    return pb2.SubscribeToTaskRequest(tenant=r.tenant or "", id=r.id)


def _to_pb_list_task_push_notification_configs_request(
    r: v10.ListTaskPushNotificationConfigsRequest,
) -> pb2.ListTaskPushNotificationConfigsRequest:
    out = pb2.ListTaskPushNotificationConfigsRequest(
        tenant=r.tenant or "",
        task_id=r.task_id,
        page_token=r.page_token or "",
    )
    if r.page_size is not None:
        out.page_size = r.page_size
    return out


def _to_pb_list_task_push_notification_configs_response(
    r: v10.ListTaskPushNotificationConfigsResponse,
) -> pb2.ListTaskPushNotificationConfigsResponse:
    out = pb2.ListTaskPushNotificationConfigsResponse(
        next_page_token=r.next_page_token or "",
    )
    if r.configs:
        for cfg in r.configs:
            out.configs.append(_to_pb_task_push_notification_config(cfg))
    return out


def _to_pb_get_extended_agent_card_request(
    r: v10.GetExtendedAgentCardRequest,
) -> pb2.GetExtendedAgentCardRequest:
    return pb2.GetExtendedAgentCardRequest(tenant=r.tenant or "")


@overload
def convert_to_proto(obj: v10.SendMessageRequest) -> pb2.SendMessageRequest: ...
@overload
def convert_to_proto(obj: v10.SendMessageResponse) -> pb2.SendMessageResponse: ...
@overload
def convert_to_proto(obj: v10.SendMessageConfiguration) -> pb2.SendMessageConfiguration: ...
@overload
def convert_to_proto(obj: v10.StreamResponse) -> pb2.StreamResponse: ...
@overload
def convert_to_proto(obj: v10.Message) -> pb2.Message: ...
@overload
def convert_to_proto(obj: v10.Part) -> pb2.Part: ...
@overload
def convert_to_proto(obj: v10.Artifact) -> pb2.Artifact: ...
@overload
def convert_to_proto(obj: v10.Task) -> pb2.Task: ...
@overload
def convert_to_proto(obj: v10.TaskStatus) -> pb2.TaskStatus: ...
@overload
def convert_to_proto(obj: v10.TaskStatusUpdateEvent) -> pb2.TaskStatusUpdateEvent: ...
@overload
def convert_to_proto(obj: v10.TaskArtifactUpdateEvent) -> pb2.TaskArtifactUpdateEvent: ...
@overload
def convert_to_proto(obj: v10.AuthenticationInfo) -> pb2.AuthenticationInfo: ...
@overload
def convert_to_proto(obj: v10.TaskPushNotificationConfig) -> pb2.TaskPushNotificationConfig: ...
@overload
def convert_to_proto(obj: v10.AgentCard) -> pb2.AgentCard: ...
@overload
def convert_to_proto(obj: v10.AgentCapabilities) -> pb2.AgentCapabilities: ...
@overload
def convert_to_proto(obj: v10.AgentInterface) -> pb2.AgentInterface: ...
@overload
def convert_to_proto(obj: v10.AgentProvider) -> pb2.AgentProvider: ...
@overload
def convert_to_proto(obj: v10.AgentExtension) -> pb2.AgentExtension: ...
@overload
def convert_to_proto(obj: v10.AgentSkill) -> pb2.AgentSkill: ...
@overload
def convert_to_proto(obj: v10.AgentCardSignature) -> pb2.AgentCardSignature: ...
@overload
def convert_to_proto(obj: v10.SecurityScheme) -> pb2.SecurityScheme: ...
@overload
def convert_to_proto(obj: v10.SecurityRequirement) -> pb2.SecurityRequirement: ...
@overload
def convert_to_proto(obj: v10.StringList) -> pb2.StringList: ...
@overload
def convert_to_proto(obj: v10.OAuthFlows) -> pb2.OAuthFlows: ...
@overload
def convert_to_proto(obj: v10.GetTaskRequest) -> pb2.GetTaskRequest: ...
@overload
def convert_to_proto(obj: v10.ListTasksRequest) -> pb2.ListTasksRequest: ...
@overload
def convert_to_proto(obj: v10.ListTasksResponse) -> pb2.ListTasksResponse: ...
@overload
def convert_to_proto(obj: v10.CancelTaskRequest) -> pb2.CancelTaskRequest: ...
@overload
def convert_to_proto(obj: v10.GetTaskPushNotificationConfigRequest) -> pb2.GetTaskPushNotificationConfigRequest: ...
@overload
def convert_to_proto(obj: v10.DeleteTaskPushNotificationConfigRequest) -> pb2.DeleteTaskPushNotificationConfigRequest: ...
@overload
def convert_to_proto(obj: v10.SubscribeToTaskRequest) -> pb2.SubscribeToTaskRequest: ...
@overload
def convert_to_proto(obj: v10.ListTaskPushNotificationConfigsRequest) -> pb2.ListTaskPushNotificationConfigsRequest: ...
@overload
def convert_to_proto(obj: v10.ListTaskPushNotificationConfigsResponse) -> pb2.ListTaskPushNotificationConfigsResponse: ...
@overload
def convert_to_proto(obj: v10.GetExtendedAgentCardRequest) -> pb2.GetExtendedAgentCardRequest: ...
@singledispatch
def convert_to_proto(obj: Any) -> Any:
    """Convert an a2a-pydantic v1.0 model to its a2a-sdk pb2 message.

    Dispatches on the runtime type of ``obj``. Raises :class:`TypeError`
    for unsupported types rather than silently returning the input, so
    callers notice when they hand in something the converter doesn't
    know about.

    Only v1.0 models are accepted — v0.3 has no direct proto counterpart.
    """
    raise TypeError(f"No v10 -> pb2 converter registered for {type(obj).__name__}")


for _v10_type, _fn in {
    v10.Part: _to_pb_part,
    v10.Message: _to_pb_message,
    v10.Artifact: _to_pb_artifact,
    v10.TaskStatus: _to_pb_task_status,
    v10.Task: _to_pb_task,
    v10.TaskStatusUpdateEvent: _to_pb_task_status_update_event,
    v10.TaskArtifactUpdateEvent: _to_pb_task_artifact_update_event,
    v10.AuthenticationInfo: _to_pb_authentication_info,
    v10.TaskPushNotificationConfig: _to_pb_task_push_notification_config,
    v10.SendMessageConfiguration: _to_pb_send_message_configuration,
    v10.SendMessageRequest: _to_pb_send_message_request,
    v10.SendMessageResponse: _to_pb_send_message_response,
    v10.StreamResponse: _to_pb_stream_response,
    v10.AgentExtension: _to_pb_agent_extension,
    v10.AgentCapabilities: _to_pb_agent_capabilities,
    v10.AgentInterface: _to_pb_agent_interface,
    v10.AgentProvider: _to_pb_agent_provider,
    v10.StringList: _to_pb_string_list,
    v10.SecurityRequirement: _to_pb_security_requirement,
    v10.OAuthFlows: _to_pb_oauth_flows,
    v10.SecurityScheme: _to_pb_security_scheme,
    v10.AgentSkill: _to_pb_agent_skill,
    v10.AgentCardSignature: _to_pb_agent_card_signature,
    v10.AgentCard: _to_pb_agent_card,
    v10.GetTaskRequest: _to_pb_get_task_request,
    v10.ListTasksRequest: _to_pb_list_tasks_request,
    v10.ListTasksResponse: _to_pb_list_tasks_response,
    v10.CancelTaskRequest: _to_pb_cancel_task_request,
    v10.GetTaskPushNotificationConfigRequest: _to_pb_get_task_push_notification_config_request,
    v10.DeleteTaskPushNotificationConfigRequest: _to_pb_delete_task_push_notification_config_request,
    v10.SubscribeToTaskRequest: _to_pb_subscribe_to_task_request,
    v10.ListTaskPushNotificationConfigsRequest: _to_pb_list_task_push_notification_configs_request,
    v10.ListTaskPushNotificationConfigsResponse: _to_pb_list_task_push_notification_configs_response,
    v10.GetExtendedAgentCardRequest: _to_pb_get_extended_agent_card_request,
}.items():
    convert_to_proto.register(_v10_type)(_fn)
