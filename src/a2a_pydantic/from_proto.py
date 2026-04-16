"""Convert a2a-sdk protobuf messages to a2a-pydantic v1.0 models.

Public API is exactly one function: :func:`convert_from_proto`. It takes
any supported ``a2a_pb2`` message and returns the matching v1.0 Pydantic
model, dispatching on the input type.

This is the inverse of :func:`a2a_pydantic.convert_to_proto` and lets
you turn SDK response objects back into typed Pydantic models — useful
for building FastAPI endpoints with typed request *and* response bodies
that delegate to the SDK's ``DefaultRequestHandler`` underneath.

**Requires the optional [proto] extra:**

    pip install a2a-pydantic[proto]

which pulls in ``a2a-sdk>=1.0.0a1`` for the ``a2a.types.a2a_pb2`` module.
Importing this module without the extra raises a clear ``ImportError``
pointing at the install command.

``metadata``, ``params`` and similar ``Struct``-typed fields round-trip
lossless in both directions — ``v10.Struct`` is generated with
``model_config.extra='allow'``, so arbitrary key/value payloads survive
the Pydantic → pb2 → Pydantic cycle.
"""

from __future__ import annotations

try:
    from a2a.types import a2a_pb2 as pb2
    from google.protobuf import struct_pb2, timestamp_pb2
except ImportError as e:
    raise ImportError(
        "a2a_pydantic.from_proto requires the [proto] optional extra.\n"
        "Install with:  pip install a2a-pydantic[proto]"
    ) from e

import base64
import datetime
from functools import singledispatch
from typing import Any, overload

from a2a_pydantic import v10

__all__ = ["convert_from_proto"]


def _pb_value_to_any(v: struct_pb2.Value) -> Any:
    """Unwrap a ``google.protobuf.Value`` back to a plain Python JSON value."""
    kind = v.WhichOneof("kind")
    if kind == "null_value":
        return None
    if kind == "number_value":
        return v.number_value
    if kind == "string_value":
        return v.string_value
    if kind == "bool_value":
        return v.bool_value
    if kind == "struct_value":
        return {k: _pb_value_to_any(val) for k, val in v.struct_value.fields.items()}
    if kind == "list_value":
        return [_pb_value_to_any(item) for item in v.list_value.values]
    return None


def _pb_struct_to_v10(s: struct_pb2.Struct | None) -> v10.Struct | None:
    """Convert a pb2 ``Struct`` to ``v10.Struct``, preserving all keys.

    ``v10.Struct`` uses ``model_config.extra='allow'`` so we can stuff
    the full pb2 payload in via ``model_validate`` and every key/value
    pair round-trips.
    """
    if s is None or not s.fields:
        return None
    data = {k: _pb_value_to_any(v) for k, v in s.fields.items()}
    return v10.Struct.model_validate(data)


def _pb_value_to_v10(v: struct_pb2.Value | None) -> v10.Value | None:
    if v is None:
        return None
    kind = v.WhichOneof("kind")
    if kind is None:
        return None
    return v10.Value(root=_pb_value_to_any(v))


def _pb_timestamp_to_v10(
    ts: timestamp_pb2.Timestamp | None,
) -> v10.Timestamp | None:
    if ts is None:
        return None
    if ts.seconds == 0 and ts.nanos == 0:
        return None
    return v10.Timestamp(root=ts.ToDatetime(tzinfo=datetime.UTC))


_PROTO_TO_ROLE: dict[int, v10.Role] = {
    int(pb2.ROLE_USER): v10.Role.role_user,
    int(pb2.ROLE_AGENT): v10.Role.role_agent,
}

_PROTO_TO_TASK_STATE: dict[int, v10.TaskState] = {
    int(pb2.TASK_STATE_SUBMITTED): v10.TaskState.task_state_submitted,
    int(pb2.TASK_STATE_WORKING): v10.TaskState.task_state_working,
    int(pb2.TASK_STATE_COMPLETED): v10.TaskState.task_state_completed,
    int(pb2.TASK_STATE_FAILED): v10.TaskState.task_state_failed,
    int(pb2.TASK_STATE_CANCELED): v10.TaskState.task_state_canceled,
    int(pb2.TASK_STATE_INPUT_REQUIRED): v10.TaskState.task_state_input_required,
    int(pb2.TASK_STATE_REJECTED): v10.TaskState.task_state_rejected,
    int(pb2.TASK_STATE_AUTH_REQUIRED): v10.TaskState.task_state_auth_required,
}


def _role_from_proto(role_int: int) -> v10.Role:
    return _PROTO_TO_ROLE.get(role_int, v10.Role.role_user)


def _task_state_from_proto(state_int: int) -> v10.TaskState:
    return _PROTO_TO_TASK_STATE.get(state_int, v10.TaskState.task_state_submitted)


def _from_pb_part(p: pb2.Part) -> v10.Part:
    """Collapse a pb2 ``Part`` (oneof ``content``) back to a flat v10 Part.

    The oneof tag on pb2 tells us exactly which payload is set; we route
    it into the matching flat field on v10.Part and leave the others as
    ``None``.
    """
    content = p.WhichOneof("content")
    kwargs: dict[str, Any] = {}
    if content == "text":
        kwargs["text"] = p.text
    elif content == "raw":
        kwargs["raw"] = base64.b64encode(p.raw).decode("ascii")
    elif content == "url":
        kwargs["url"] = p.url
    elif content == "data":
        kwargs["data"] = _pb_value_to_v10(p.data)
    if p.filename:
        kwargs["filename"] = p.filename
    if p.media_type:
        kwargs["media_type"] = p.media_type
    metadata = _pb_struct_to_v10(p.metadata)
    if metadata is not None:
        kwargs["metadata"] = metadata
    return v10.Part(**kwargs)


def _from_pb_message(m: pb2.Message) -> v10.Message:
    return v10.Message(
        message_id=m.message_id,
        context_id=m.context_id or None,
        task_id=m.task_id or None,
        role=_role_from_proto(m.role),
        parts=[_from_pb_part(p) for p in m.parts],
        metadata=_pb_struct_to_v10(m.metadata),
        extensions=list(m.extensions) if m.extensions else None,
        reference_task_ids=(list(m.reference_task_ids) if m.reference_task_ids else None),
    )


def _from_pb_artifact(a: pb2.Artifact) -> v10.Artifact:
    return v10.Artifact(
        artifact_id=a.artifact_id,
        name=a.name or None,
        description=a.description or None,
        parts=[_from_pb_part(p) for p in a.parts],
        metadata=_pb_struct_to_v10(a.metadata),
        extensions=list(a.extensions) if a.extensions else None,
    )


def _from_pb_task_status(s: pb2.TaskStatus) -> v10.TaskStatus:
    return v10.TaskStatus(
        state=_task_state_from_proto(s.state),
        message=_from_pb_message(s.message) if s.HasField("message") else None,
        timestamp=_pb_timestamp_to_v10(s.timestamp) if s.HasField("timestamp") else None,
    )


def _from_pb_task(t: pb2.Task) -> v10.Task:
    return v10.Task(
        id=t.id,
        context_id=t.context_id or "",
        status=_from_pb_task_status(t.status),
        artifacts=[_from_pb_artifact(a) for a in t.artifacts] if t.artifacts else None,
        history=[_from_pb_message(m) for m in t.history] if t.history else None,
        metadata=_pb_struct_to_v10(t.metadata),
    )


def _from_pb_task_status_update_event(
    e: pb2.TaskStatusUpdateEvent,
) -> v10.TaskStatusUpdateEvent:
    return v10.TaskStatusUpdateEvent(
        task_id=e.task_id,
        context_id=e.context_id,
        status=_from_pb_task_status(e.status),
        metadata=_pb_struct_to_v10(e.metadata),
    )


def _from_pb_task_artifact_update_event(
    e: pb2.TaskArtifactUpdateEvent,
) -> v10.TaskArtifactUpdateEvent:
    return v10.TaskArtifactUpdateEvent(
        task_id=e.task_id,
        context_id=e.context_id,
        artifact=_from_pb_artifact(e.artifact),
        append=e.append,
        last_chunk=e.last_chunk,
        metadata=_pb_struct_to_v10(e.metadata),
    )


def _from_pb_authentication_info(
    a: pb2.AuthenticationInfo,
) -> v10.AuthenticationInfo:
    return v10.AuthenticationInfo(
        scheme=a.scheme,
        credentials=a.credentials or None,
    )


def _from_pb_task_push_notification_config(
    c: pb2.TaskPushNotificationConfig,
) -> v10.TaskPushNotificationConfig:
    return v10.TaskPushNotificationConfig(
        tenant=c.tenant or None,
        id=c.id or None,
        task_id=c.task_id,
        url=c.url,
        token=c.token or None,
        authentication=_from_pb_authentication_info(c.authentication)
        if c.HasField("authentication")
        else None,
    )


def _from_pb_send_message_configuration(
    c: pb2.SendMessageConfiguration,
) -> v10.SendMessageConfiguration:
    return v10.SendMessageConfiguration(
        accepted_output_modes=list(c.accepted_output_modes) or None,
        task_push_notification_config=_from_pb_task_push_notification_config(
            c.task_push_notification_config
        )
        if c.HasField("task_push_notification_config")
        else None,
        history_length=c.history_length if c.HasField("history_length") else None,
        return_immediately=c.return_immediately,
    )


def _from_pb_send_message_request(
    r: pb2.SendMessageRequest,
) -> v10.SendMessageRequest:
    return v10.SendMessageRequest(
        tenant=r.tenant or None,
        message=_from_pb_message(r.message),
        configuration=_from_pb_send_message_configuration(r.configuration)
        if r.HasField("configuration")
        else None,
        metadata=_pb_struct_to_v10(r.metadata),
    )


def _from_pb_send_message_response(
    r: pb2.SendMessageResponse,
) -> v10.SendMessageResponse:
    payload = r.WhichOneof("payload")
    return v10.SendMessageResponse(
        task=_from_pb_task(r.task) if payload == "task" else None,
        message=_from_pb_message(r.message) if payload == "message" else None,
    )


def _from_pb_stream_response(r: pb2.StreamResponse) -> v10.StreamResponse:
    payload = r.WhichOneof("payload")
    return v10.StreamResponse(
        task=_from_pb_task(r.task) if payload == "task" else None,
        message=_from_pb_message(r.message) if payload == "message" else None,
        status_update=_from_pb_task_status_update_event(r.status_update)
        if payload == "status_update"
        else None,
        artifact_update=_from_pb_task_artifact_update_event(r.artifact_update)
        if payload == "artifact_update"
        else None,
    )


def _from_pb_agent_extension(
    e: pb2.AgentExtension,
) -> v10.AgentExtension:
    return v10.AgentExtension(
        uri=e.uri or None,
        description=e.description or None,
        required=e.required,
        params=_pb_struct_to_v10(e.params),
    )


def _from_pb_agent_capabilities(
    c: pb2.AgentCapabilities,
) -> v10.AgentCapabilities:
    return v10.AgentCapabilities(
        streaming=c.streaming if c.HasField("streaming") else None,
        push_notifications=c.push_notifications if c.HasField("push_notifications") else None,
        extensions=[_from_pb_agent_extension(e) for e in c.extensions] if c.extensions else None,
        extended_agent_card=c.extended_agent_card if c.HasField("extended_agent_card") else None,
    )


def _from_pb_agent_interface(
    i: pb2.AgentInterface,
) -> v10.AgentInterface:
    return v10.AgentInterface(
        url=i.url,
        protocol_binding=i.protocol_binding,
        tenant=i.tenant or None,
        protocol_version=i.protocol_version,
    )


def _from_pb_agent_provider(
    p: pb2.AgentProvider,
) -> v10.AgentProvider:
    return v10.AgentProvider(url=p.url, organization=p.organization)


def _from_pb_string_list(s: pb2.StringList) -> v10.StringList:
    return v10.StringList(strings=list(s.list))


def _from_pb_security_requirement(
    r: pb2.SecurityRequirement,
) -> v10.SecurityRequirement:
    return v10.SecurityRequirement(
        schemes={name: _from_pb_string_list(sl) for name, sl in r.schemes.items()}
    )


def _from_pb_api_key_scheme(
    s: pb2.APIKeySecurityScheme,
) -> v10.APIKeySecurityScheme:
    return v10.APIKeySecurityScheme(
        description=s.description or None,
        location=s.location,
        name=s.name,
    )


def _from_pb_http_auth_scheme(
    s: pb2.HTTPAuthSecurityScheme,
) -> v10.HTTPAuthSecurityScheme:
    return v10.HTTPAuthSecurityScheme(
        description=s.description or None,
        scheme=s.scheme,
        bearer_format=s.bearer_format or None,
    )


def _from_pb_mtls_scheme(
    s: pb2.MutualTlsSecurityScheme,
) -> v10.MutualTlsSecurityScheme:
    return v10.MutualTlsSecurityScheme(description=s.description or None)


def _from_pb_openid_scheme(
    s: pb2.OpenIdConnectSecurityScheme,
) -> v10.OpenIdConnectSecurityScheme:
    return v10.OpenIdConnectSecurityScheme(
        description=s.description or None,
        open_id_connect_url=s.open_id_connect_url,
    )


def _from_pb_authorization_code_flow(
    f: pb2.AuthorizationCodeOAuthFlow,
) -> v10.AuthorizationCodeOAuthFlow:
    return v10.AuthorizationCodeOAuthFlow(
        authorization_url=f.authorization_url,
        token_url=f.token_url,
        refresh_url=f.refresh_url or None,
        scopes=dict(f.scopes),
        pkce_required=f.pkce_required,
    )


def _from_pb_client_credentials_flow(
    f: pb2.ClientCredentialsOAuthFlow,
) -> v10.ClientCredentialsOAuthFlow:
    return v10.ClientCredentialsOAuthFlow(
        token_url=f.token_url,
        refresh_url=f.refresh_url or None,
        scopes=dict(f.scopes),
    )


def _from_pb_implicit_flow(
    f: pb2.ImplicitOAuthFlow,
) -> v10.ImplicitOAuthFlow:
    return v10.ImplicitOAuthFlow(
        authorization_url=f.authorization_url,
        refresh_url=f.refresh_url or None,
        scopes=dict(f.scopes),
    )


def _from_pb_password_flow(
    f: pb2.PasswordOAuthFlow,
) -> v10.PasswordOAuthFlow:
    return v10.PasswordOAuthFlow(
        token_url=f.token_url,
        refresh_url=f.refresh_url or None,
        scopes=dict(f.scopes),
    )


def _from_pb_device_code_flow(
    f: pb2.DeviceCodeOAuthFlow,
) -> v10.DeviceCodeOAuthFlow:
    return v10.DeviceCodeOAuthFlow(
        device_authorization_url=f.device_authorization_url,
        token_url=f.token_url,
        refresh_url=f.refresh_url or None,
        scopes=dict(f.scopes),
    )


def _from_pb_oauth_flows(f: pb2.OAuthFlows) -> v10.OAuthFlows:
    flow = f.WhichOneof("flow")
    return v10.OAuthFlows(
        authorization_code=_from_pb_authorization_code_flow(f.authorization_code)
        if flow == "authorization_code"
        else None,
        client_credentials=_from_pb_client_credentials_flow(f.client_credentials)
        if flow == "client_credentials"
        else None,
        implicit=_from_pb_implicit_flow(f.implicit) if flow == "implicit" else None,
        password=_from_pb_password_flow(f.password) if flow == "password" else None,
        device_code=_from_pb_device_code_flow(f.device_code) if flow == "device_code" else None,
    )


def _from_pb_oauth2_scheme(
    s: pb2.OAuth2SecurityScheme,
) -> v10.OAuth2SecurityScheme:
    return v10.OAuth2SecurityScheme(
        description=s.description or None,
        flows=_from_pb_oauth_flows(s.flows),
        oauth2_metadata_url=s.oauth2_metadata_url or None,
    )


def _from_pb_security_scheme(
    s: pb2.SecurityScheme,
) -> v10.SecurityScheme:
    scheme = s.WhichOneof("scheme")
    return v10.SecurityScheme(
        api_key_security_scheme=_from_pb_api_key_scheme(s.api_key_security_scheme)
        if scheme == "api_key_security_scheme"
        else None,
        http_auth_security_scheme=_from_pb_http_auth_scheme(s.http_auth_security_scheme)
        if scheme == "http_auth_security_scheme"
        else None,
        oauth2_security_scheme=_from_pb_oauth2_scheme(s.oauth2_security_scheme)
        if scheme == "oauth2_security_scheme"
        else None,
        open_id_connect_security_scheme=_from_pb_openid_scheme(s.open_id_connect_security_scheme)
        if scheme == "open_id_connect_security_scheme"
        else None,
        mtls_security_scheme=_from_pb_mtls_scheme(s.mtls_security_scheme)
        if scheme == "mtls_security_scheme"
        else None,
    )


def _from_pb_agent_skill(s: pb2.AgentSkill) -> v10.AgentSkill:
    return v10.AgentSkill(
        id=s.id,
        name=s.name,
        description=s.description,
        tags=list(s.tags),
        examples=list(s.examples) if s.examples else None,
        input_modes=list(s.input_modes) if s.input_modes else None,
        output_modes=list(s.output_modes) if s.output_modes else None,
        security_requirements=[_from_pb_security_requirement(r) for r in s.security_requirements]
        if s.security_requirements
        else None,
    )


def _from_pb_agent_card_signature(
    s: pb2.AgentCardSignature,
) -> v10.AgentCardSignature:
    return v10.AgentCardSignature(
        protected=s.protected,
        signature=s.signature,
        header=_pb_struct_to_v10(s.header),
    )


def _from_pb_agent_card(c: pb2.AgentCard) -> v10.AgentCard:
    return v10.AgentCard(
        name=c.name,
        description=c.description,
        supported_interfaces=[_from_pb_agent_interface(i) for i in c.supported_interfaces],
        provider=_from_pb_agent_provider(c.provider) if c.HasField("provider") else None,
        version=c.version,
        documentation_url=c.documentation_url if c.HasField("documentation_url") else None,
        capabilities=_from_pb_agent_capabilities(c.capabilities),
        security_schemes={
            name: _from_pb_security_scheme(scheme) for name, scheme in c.security_schemes.items()
        }
        if c.security_schemes
        else None,
        security_requirements=[_from_pb_security_requirement(r) for r in c.security_requirements]
        if c.security_requirements
        else None,
        default_input_modes=list(c.default_input_modes),
        default_output_modes=list(c.default_output_modes),
        skills=[_from_pb_agent_skill(s) for s in c.skills],
        signatures=[_from_pb_agent_card_signature(s) for s in c.signatures]
        if c.signatures
        else None,
        icon_url=c.icon_url if c.HasField("icon_url") else None,
    )


def _from_pb_get_task_request(r: pb2.GetTaskRequest) -> v10.GetTaskRequest:
    return v10.GetTaskRequest(
        tenant=r.tenant or None,
        id=r.id,
        history_length=r.history_length if r.HasField("history_length") else None,
    )


def _from_pb_list_tasks_request(
    r: pb2.ListTasksRequest,
) -> v10.ListTasksRequest:
    return v10.ListTasksRequest(
        tenant=r.tenant or None,
        context_id=r.context_id or None,
        status=_task_state_from_proto(r.status) if r.status else None,
        page_size=r.page_size if r.HasField("page_size") else None,
        page_token=r.page_token or None,
        history_length=r.history_length if r.HasField("history_length") else None,
        status_timestamp_after=_pb_timestamp_to_v10(r.status_timestamp_after)
        if r.HasField("status_timestamp_after")
        else None,
        include_artifacts=r.include_artifacts if r.HasField("include_artifacts") else None,
    )


def _from_pb_list_tasks_response(
    r: pb2.ListTasksResponse,
) -> v10.ListTasksResponse:
    return v10.ListTasksResponse(
        tasks=[_from_pb_task(t) for t in r.tasks],
        next_page_token=r.next_page_token,
        page_size=r.page_size,
        total_size=r.total_size,
    )


def _from_pb_cancel_task_request(
    r: pb2.CancelTaskRequest,
) -> v10.CancelTaskRequest:
    return v10.CancelTaskRequest(
        tenant=r.tenant or None,
        id=r.id,
        metadata=_pb_struct_to_v10(r.metadata),
    )


def _from_pb_get_task_push_notification_config_request(
    r: pb2.GetTaskPushNotificationConfigRequest,
) -> v10.GetTaskPushNotificationConfigRequest:
    return v10.GetTaskPushNotificationConfigRequest(
        tenant=r.tenant or None,
        task_id=r.task_id,
        id=r.id,
    )


def _from_pb_delete_task_push_notification_config_request(
    r: pb2.DeleteTaskPushNotificationConfigRequest,
) -> v10.DeleteTaskPushNotificationConfigRequest:
    return v10.DeleteTaskPushNotificationConfigRequest(
        tenant=r.tenant or None,
        task_id=r.task_id,
        id=r.id,
    )


def _from_pb_subscribe_to_task_request(
    r: pb2.SubscribeToTaskRequest,
) -> v10.SubscribeToTaskRequest:
    return v10.SubscribeToTaskRequest(tenant=r.tenant or None, id=r.id)


def _from_pb_list_task_push_notification_configs_request(
    r: pb2.ListTaskPushNotificationConfigsRequest,
) -> v10.ListTaskPushNotificationConfigsRequest:
    return v10.ListTaskPushNotificationConfigsRequest(
        tenant=r.tenant or None,
        task_id=r.task_id,
        page_size=r.page_size,
        page_token=r.page_token or None,
    )


def _from_pb_list_task_push_notification_configs_response(
    r: pb2.ListTaskPushNotificationConfigsResponse,
) -> v10.ListTaskPushNotificationConfigsResponse:
    return v10.ListTaskPushNotificationConfigsResponse(
        configs=[_from_pb_task_push_notification_config(c) for c in r.configs]
        if r.configs
        else None,
        next_page_token=r.next_page_token or None,
    )


def _from_pb_get_extended_agent_card_request(
    r: pb2.GetExtendedAgentCardRequest,
) -> v10.GetExtendedAgentCardRequest:
    return v10.GetExtendedAgentCardRequest(tenant=r.tenant or None)


@overload
def convert_from_proto(obj: pb2.SendMessageRequest) -> v10.SendMessageRequest: ...
@overload
def convert_from_proto(obj: pb2.SendMessageResponse) -> v10.SendMessageResponse: ...
@overload
def convert_from_proto(obj: pb2.SendMessageConfiguration) -> v10.SendMessageConfiguration: ...
@overload
def convert_from_proto(obj: pb2.StreamResponse) -> v10.StreamResponse: ...
@overload
def convert_from_proto(obj: pb2.Message) -> v10.Message: ...
@overload
def convert_from_proto(obj: pb2.Part) -> v10.Part: ...
@overload
def convert_from_proto(obj: pb2.Artifact) -> v10.Artifact: ...
@overload
def convert_from_proto(obj: pb2.Task) -> v10.Task: ...
@overload
def convert_from_proto(obj: pb2.TaskStatus) -> v10.TaskStatus: ...
@overload
def convert_from_proto(obj: pb2.TaskStatusUpdateEvent) -> v10.TaskStatusUpdateEvent: ...
@overload
def convert_from_proto(obj: pb2.TaskArtifactUpdateEvent) -> v10.TaskArtifactUpdateEvent: ...
@overload
def convert_from_proto(obj: pb2.AuthenticationInfo) -> v10.AuthenticationInfo: ...
@overload
def convert_from_proto(obj: pb2.TaskPushNotificationConfig) -> v10.TaskPushNotificationConfig: ...
@overload
def convert_from_proto(obj: pb2.AgentCard) -> v10.AgentCard: ...
@overload
def convert_from_proto(obj: pb2.AgentCapabilities) -> v10.AgentCapabilities: ...
@overload
def convert_from_proto(obj: pb2.AgentInterface) -> v10.AgentInterface: ...
@overload
def convert_from_proto(obj: pb2.AgentProvider) -> v10.AgentProvider: ...
@overload
def convert_from_proto(obj: pb2.AgentExtension) -> v10.AgentExtension: ...
@overload
def convert_from_proto(obj: pb2.AgentSkill) -> v10.AgentSkill: ...
@overload
def convert_from_proto(obj: pb2.AgentCardSignature) -> v10.AgentCardSignature: ...
@overload
def convert_from_proto(obj: pb2.SecurityScheme) -> v10.SecurityScheme: ...
@overload
def convert_from_proto(obj: pb2.SecurityRequirement) -> v10.SecurityRequirement: ...
@overload
def convert_from_proto(obj: pb2.StringList) -> v10.StringList: ...
@overload
def convert_from_proto(obj: pb2.OAuthFlows) -> v10.OAuthFlows: ...
@overload
def convert_from_proto(obj: pb2.GetTaskRequest) -> v10.GetTaskRequest: ...
@overload
def convert_from_proto(obj: pb2.ListTasksRequest) -> v10.ListTasksRequest: ...
@overload
def convert_from_proto(obj: pb2.ListTasksResponse) -> v10.ListTasksResponse: ...
@overload
def convert_from_proto(obj: pb2.CancelTaskRequest) -> v10.CancelTaskRequest: ...
@overload
def convert_from_proto(
    obj: pb2.GetTaskPushNotificationConfigRequest,
) -> v10.GetTaskPushNotificationConfigRequest: ...
@overload
def convert_from_proto(
    obj: pb2.DeleteTaskPushNotificationConfigRequest,
) -> v10.DeleteTaskPushNotificationConfigRequest: ...
@overload
def convert_from_proto(obj: pb2.SubscribeToTaskRequest) -> v10.SubscribeToTaskRequest: ...
@overload
def convert_from_proto(
    obj: pb2.ListTaskPushNotificationConfigsRequest,
) -> v10.ListTaskPushNotificationConfigsRequest: ...
@overload
def convert_from_proto(
    obj: pb2.ListTaskPushNotificationConfigsResponse,
) -> v10.ListTaskPushNotificationConfigsResponse: ...
@overload
def convert_from_proto(obj: pb2.GetExtendedAgentCardRequest) -> v10.GetExtendedAgentCardRequest: ...
@singledispatch
def convert_from_proto(obj: Any) -> Any:
    """Convert an a2a-sdk pb2 message to its a2a-pydantic v1.0 equivalent.

    Dispatches on the runtime type of ``obj``. Raises :class:`TypeError`
    for unsupported types rather than silently returning the input, so
    callers notice when they hand in something the converter doesn't
    know about.
    """
    raise TypeError(f"No pb2 -> v10 converter registered for {type(obj).__name__}")


for _pb_type, _fn in {
    pb2.Part: _from_pb_part,
    pb2.Message: _from_pb_message,
    pb2.Artifact: _from_pb_artifact,
    pb2.TaskStatus: _from_pb_task_status,
    pb2.Task: _from_pb_task,
    pb2.TaskStatusUpdateEvent: _from_pb_task_status_update_event,
    pb2.TaskArtifactUpdateEvent: _from_pb_task_artifact_update_event,
    pb2.AuthenticationInfo: _from_pb_authentication_info,
    pb2.TaskPushNotificationConfig: _from_pb_task_push_notification_config,
    pb2.SendMessageConfiguration: _from_pb_send_message_configuration,
    pb2.SendMessageRequest: _from_pb_send_message_request,
    pb2.SendMessageResponse: _from_pb_send_message_response,
    pb2.StreamResponse: _from_pb_stream_response,
    pb2.AgentExtension: _from_pb_agent_extension,
    pb2.AgentCapabilities: _from_pb_agent_capabilities,
    pb2.AgentInterface: _from_pb_agent_interface,
    pb2.AgentProvider: _from_pb_agent_provider,
    pb2.StringList: _from_pb_string_list,
    pb2.SecurityRequirement: _from_pb_security_requirement,
    pb2.OAuthFlows: _from_pb_oauth_flows,
    pb2.SecurityScheme: _from_pb_security_scheme,
    pb2.AgentSkill: _from_pb_agent_skill,
    pb2.AgentCardSignature: _from_pb_agent_card_signature,
    pb2.AgentCard: _from_pb_agent_card,
    pb2.GetTaskRequest: _from_pb_get_task_request,
    pb2.ListTasksRequest: _from_pb_list_tasks_request,
    pb2.ListTasksResponse: _from_pb_list_tasks_response,
    pb2.CancelTaskRequest: _from_pb_cancel_task_request,
    pb2.GetTaskPushNotificationConfigRequest: _from_pb_get_task_push_notification_config_request,
    pb2.DeleteTaskPushNotificationConfigRequest: _from_pb_delete_task_push_notification_config_request,
    pb2.SubscribeToTaskRequest: _from_pb_subscribe_to_task_request,
    pb2.ListTaskPushNotificationConfigsRequest: _from_pb_list_task_push_notification_configs_request,
    pb2.ListTaskPushNotificationConfigsResponse: _from_pb_list_task_push_notification_configs_response,
    pb2.GetExtendedAgentCardRequest: _from_pb_get_extended_agent_card_request,
}.items():
    convert_from_proto.register(_pb_type)(_fn)  # type: ignore[attr-defined]
