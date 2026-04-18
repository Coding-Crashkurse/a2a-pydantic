"""Pre-process the proto-generated A2A JSON Schema bundle for datamodel-codegen.

Fixes applied:
1. Rename definition keys to strip spaces (proto generator puts spaces between words).
2. Resolve external $ref file pointers to internal #/definitions/ pointers.
3. Strip "additionalProperties": false  ->  no extra='forbid'.
4. Strip "patternProperties"  ->  removes snake_case duplicates of camelCase fields.
5. Simplify proto-style anyOf[int, string-pattern] to plain integer.
6. Simplify proto-style anyOf[enum-string, pattern-string, int] to a string enum.
7. Remove per-definition "$schema" keys (not needed inside a bundle).
8. Strip spaces from "title" fields so datamodel-codegen emits clean class names.
"""

import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def walk_dicts(obj: Any) -> Iterator[dict]:
    """Pre-order DFS yielding every dict node in the tree.

    Callers that mutate nodes must materialize the iterator first
    (``list(walk_dicts(schema))``); mutating a dict's keys while its
    ``.values()`` view is being iterated raises ``RuntimeError``.
    """
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk_dicts(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from walk_dicts(item)


def slugify(name: str) -> str:
    return name.replace(" ", "")


def rename_definitions(schema: dict) -> None:
    """Rename definition keys to remove spaces, and rewrite internal $refs."""
    defs = schema.get("definitions", {})
    rename_map = {old: slugify(old) for old in defs if slugify(old) != old}
    if not rename_map:
        return

    schema["definitions"] = {rename_map.get(k, k): v for k, v in defs.items()}

    for node in list(walk_dicts(schema)):
        ref = node.get("$ref")
        if not isinstance(ref, str) or not ref.startswith("#/definitions/"):
            continue
        key = ref[len("#/definitions/"):]
        if key in rename_map:
            node["$ref"] = f"#/definitions/{rename_map[key]}"


def build_ref_map(definitions: dict) -> dict[str, str]:
    return {
        f"{prefix}{name}.jsonschema.json": f"#/definitions/{name}"
        for name in definitions
        for prefix in ("lf.a2a.v1.", "google.protobuf.")
    }


def resolve_refs(obj, ref_map: dict[str, str]) -> None:
    for node in list(walk_dicts(obj)):
        ref = node.get("$ref")
        if ref in ref_map:
            node["$ref"] = ref_map[ref]


def strip_additional_properties(obj) -> None:
    for node in list(walk_dicts(obj)):
        if node.get("additionalProperties") is False:
            del node["additionalProperties"]


def strip_pattern_properties(obj) -> None:
    for node in list(walk_dicts(obj)):
        node.pop("patternProperties", None)


def _is_proto_int_anyof(any_of: list) -> bool:
    if len(any_of) != 2:
        return False
    types = {v.get("type") for v in any_of if isinstance(v, dict)}
    return types == {"integer", "string"}


def _is_proto_enum_anyof(any_of: list) -> bool:
    if len(any_of) < 2:
        return False
    has_enum = any(isinstance(v, dict) and "enum" in v for v in any_of)
    has_int = any(isinstance(v, dict) and v.get("type") == "integer" for v in any_of)
    return has_enum and has_int


def _extract_enum_values(any_of: list) -> list[str]:
    values: list[str] = []
    for v in any_of:
        if isinstance(v, dict) and "enum" in v:
            values.extend(v["enum"])
    return values


def _collapse_enum_anyof(node: dict) -> None:
    any_of = node["anyOf"]
    enum_vals = _extract_enum_values(any_of)
    desc = node.get("description", "")
    title = node.get("title")
    default = node.get("default")
    node.clear()
    node["type"] = "string"
    node["enum"] = enum_vals
    if desc:
        node["description"] = desc
    if title:
        node["title"] = title
    # Proto enums default to integer 0 (= UNSPECIFIED). We drop UNSPECIFIED
    # from the Python enum because Python already has `None` for "unset", so
    # an integer default has no valid target on our side — keep the field
    # unset. String defaults are preserved only when they actually match one
    # of the kept enum values; an unmappable string is almost certainly a
    # schema drift we want to hear about, so we log it loudly instead of
    # silently dropping (silent drops are what produced the
    # `default: 0 -> "TASK_STATE_SUBMITTED"` bug in the first place).
    if default is None or isinstance(default, int):
        return
    if isinstance(default, str) and default in enum_vals:
        node["default"] = default
        return
    print(
        f"resolve_refs: dropping unmappable enum default "
        f"{default!r} (kept enum values: {enum_vals})",
        file=sys.stderr,
    )


def _collapse_int_anyof(node: dict) -> None:
    desc = node.get("description", "")
    default = node.get("default")
    node.clear()
    node["type"] = "integer"
    if desc:
        node["description"] = desc
    if default is not None:
        node["default"] = default


def simplify_anyof(obj) -> None:
    for node in list(walk_dicts(obj)):
        any_of = node.get("anyOf")
        if not isinstance(any_of, list):
            continue
        if _is_proto_enum_anyof(any_of):
            _collapse_enum_anyof(node)
        elif _is_proto_int_anyof(any_of):
            _collapse_int_anyof(node)


def strip_nested_schema(obj) -> None:
    for node in list(walk_dicts(obj)):
        if "$schema" in node and "definitions" not in node:
            del node["$schema"]


def strip_title_spaces(schema: dict) -> None:
    """Remove spaces from `title` fields inside definitions (cosmetic)."""
    for body in schema.get("definitions", {}).values():
        if isinstance(body, dict) and isinstance(body.get("title"), str):
            body["title"] = slugify(body["title"])


def strip_string_patterns(obj) -> None:
    """Drop `pattern` on string fields — we don't want `constr()` wrappers."""
    for node in list(walk_dicts(obj)):
        if node.get("type") == "string" and "pattern" in node:
            del node["pattern"]


def clean_descriptions(obj) -> None:
    """Trim per-line leading space inherited from proto `//` comments.

    The proto->jsonschema step produces descriptions like:
        "AgentCardSignature represents a JWS signature of an AgentCard.\n This follows ..."
    where every continuation line starts with a single space. Strip that leading
    space so the rendered docstrings match the v0.3 style.
    """
    for node in list(walk_dicts(obj)):
        desc = node.get("description")
        if isinstance(desc, str) and "\n " in desc:
            node["description"] = "\n".join(line.lstrip() for line in desc.split("\n"))


# Proto3 JSON Schema has no `required` arrays - every field is emitted as
# optional with a default. This table mirrors the "Required" columns from the
# A2A v1.0 spec's Section 3 (Operations) and Section 4 (Protocol Data Model).
# https://a2a-protocol.org/v1.0.0/specification/
#
# Keys are the renamed definition names (no spaces); values are the camelCase
# property names that must be set.
_REQUIRED_FIELDS: dict[str, list[str]] = {
    # 4.5.2
    "APIKeySecurityScheme": ["location", "name"],
    # 4.4.1
    "AgentCard": [
        "name",
        "description",
        "version",
        "capabilities",
        "defaultInputModes",
        "defaultOutputModes",
        "skills",
        "supportedInterfaces",
    ],
    # 4.4.7
    "AgentCardSignature": ["protected", "signature"],
    # 4.4.6
    "AgentInterface": ["url", "protocolBinding", "protocolVersion"],
    # 4.4.2
    "AgentProvider": ["organization", "url"],
    # 4.4.5
    "AgentSkill": ["id", "name", "description", "tags"],
    # 4.1.7
    "Artifact": ["artifactId", "parts"],
    # 4.3.2
    "AuthenticationInfo": ["scheme"],
    # 4.4.3 — spec table marks `uri` as "No" but the prose in 4.6.1/4.6.3 treats
    # it as the unique extension identifier. v0.3 agrees and lists it required.
    # Following the prose and v0.3 parity here.
    "AgentExtension": ["uri"],
    # 4.5.8
    "AuthorizationCodeOAuthFlow": ["authorizationUrl", "scopes", "tokenUrl"],
    # 3.1.5
    "CancelTaskRequest": ["id"],
    # 4.5.9
    "ClientCredentialsOAuthFlow": ["scopes", "tokenUrl"],
    # 3.1.10
    "DeleteTaskPushNotificationConfigRequest": ["id", "taskId"],
    # 4.5.10
    "DeviceCodeOAuthFlow": ["deviceAuthorizationUrl", "scopes", "tokenUrl"],
    # 3.1.8
    "GetTaskPushNotificationConfigRequest": ["id", "taskId"],
    # 3.1.3
    "GetTaskRequest": ["id"],
    # 4.5.3
    "HTTPAuthSecurityScheme": ["scheme"],
    # Deprecated but still present in schema; mirror Authorization Code flow requirements.
    "ImplicitOAuthFlow": ["authorizationUrl", "scopes"],
    # 3.1.9
    "ListTaskPushNotificationConfigsRequest": ["taskId"],
    # 3.1.4 - spec table marks all four as Yes
    "ListTasksResponse": ["tasks", "nextPageToken", "pageSize", "totalSize"],
    # 4.1.4
    "Message": ["role", "parts", "messageId"],
    # 4.5.4
    "OAuth2SecurityScheme": ["flows"],
    # 4.5.5
    "OpenIdConnectSecurityScheme": ["openIdConnectUrl"],
    # Deprecated but still present in schema.
    "PasswordOAuthFlow": ["scopes", "tokenUrl"],
    # v0.3 parity - a SecurityRequirement without schemes is meaningless.
    "SecurityRequirement": ["schemes"],
    # 3.2.1
    "SendMessageRequest": ["message"],
    # Helper type for proto's `repeated string`; the list itself is the payload.
    "StringList": ["strings"],
    # 3.1.6
    "SubscribeToTaskRequest": ["id"],
    # 4.1.1 - contextId is explicitly No per spec table
    "Task": ["id", "status"],
    # 4.2.2
    "TaskArtifactUpdateEvent": ["artifact", "contextId", "taskId"],
    # v0.3 parity; spec table for TaskPushNotificationConfig is broken (Error:
    # Message ... not found) so we keep the v0.3 invariant: a config must at
    # least identify its target task and webhook URL.
    "TaskPushNotificationConfig": ["taskId", "url"],
    # 4.1.2
    "TaskStatus": ["state"],
    # 4.2.1
    "TaskStatusUpdateEvent": ["contextId", "status", "taskId"],
}


def apply_required_fields(schema: dict) -> None:
    """Inject required-field lists the proto3 bundle left out.

    For each required field we also strip the synthetic `default` so pydantic
    doesn't fall back to an empty sentinel when the caller forgets to set it.

    Any entry that references a class or property not present in the schema is
    a bug in _REQUIRED_FIELDS - fail loudly so the table and the spec stay in
    sync when upstream renames something.
    """
    defs = schema.get("definitions", {})
    errors: list[str] = []
    for cls_name, props in _REQUIRED_FIELDS.items():
        body = defs.get(cls_name)
        if not isinstance(body, dict):
            errors.append(f"{cls_name}: definition not found in schema")
            continue
        schema_props = body.get("properties")
        if not isinstance(schema_props, dict):
            errors.append(f"{cls_name}: has no `properties` object")
            continue
        for p in props:
            if p not in schema_props:
                errors.append(
                    f"{cls_name}.{p}: property not in schema (available: "
                    f"{sorted(schema_props)})"
                )
        existing = set(body.get("required", []))
        existing.update(props)
        body["required"] = [p for p in schema_props if p in existing]
        for p in props:
            prop = schema_props.get(p)
            if isinstance(prop, dict) and "default" in prop:
                del prop["default"]

    if errors:
        msg = "\n  - ".join(errors)
        raise SystemExit(
            f"_REQUIRED_FIELDS is out of sync with the schema:\n  - {msg}"
        )


_TASK_STATE_VALUES = [
    "TASK_STATE_SUBMITTED",
    "TASK_STATE_WORKING",
    "TASK_STATE_COMPLETED",
    "TASK_STATE_FAILED",
    "TASK_STATE_CANCELED",
    "TASK_STATE_INPUT_REQUIRED",
    "TASK_STATE_REJECTED",
    "TASK_STATE_AUTH_REQUIRED",
]


def rename_reserved_properties(schema: dict) -> None:
    """Rename schema properties that collide with Python keywords/builtins.

    datamodel-codegen combined with --no-alias produces corrupt `import  as ...`
    lines when a property named `list` (or similar) needs renaming. Sidestep the
    issue by renaming the property in the schema itself.
    """
    rename_map = {"list": "strings"}
    for body in schema.get("definitions", {}).values():
        if not isinstance(body, dict):
            continue
        props = body.get("properties")
        if not isinstance(props, dict):
            continue
        for old, new in rename_map.items():
            if old in props and new not in props:
                props[new] = props.pop(old)
        required = body.get("required")
        if isinstance(required, list):
            body["required"] = [rename_map.get(r, r) for r in required]


def make_struct_a_dict_wrapper(schema: dict) -> None:
    """Let ``Struct`` accept arbitrary key/value payloads.

    Upstream declares ``Struct`` as ``{"type": "object"}`` with no properties.
    datamodel-codegen turns that into an empty ``class Struct(A2ABaseModel)``
    that silently drops every key/value pair assigned to it — which made
    ``metadata`` / ``params`` / ``header`` round-trips lossy on both the v0.3
    and pb2 bridges. Adding ``additionalProperties: True`` makes the generator
    emit ``Struct`` with ``model_config.extra='allow'`` (NOT ``RootModel``),
    which gives us free-form key/value storage without a ``.root`` unwrap.

    Note on aliasing: ``alias_generator=to_camel_custom`` on ``A2ABaseModel``
    applies to *declared* fields only, not to the ``extra='allow'`` payload.
    That means user-chosen metadata keys are preserved verbatim through
    serialization — ``Struct(trace_id="x").model_dump(by_alias=True)`` yields
    ``{"trace_id": "x"}``, not ``{"traceId": "x"}``. This is the correct
    behavior: metadata is free-form user payload, not a spec-defined field
    whose name should be canonicalized.
    """
    defs = schema.get("definitions", {})
    struct = defs.get("Struct")
    if isinstance(struct, dict):
        struct["additionalProperties"] = True


def extract_task_state(schema: dict) -> None:
    """Promote the inline TaskState enum to a shared definition so Status/State
    collapse into a single `TaskState` class in the generated models."""
    task_state_set = set(_TASK_STATE_VALUES)

    # Materialize before adding the TaskState definition below so we don't
    # rewrite the enum we're about to add.
    for node in list(walk_dicts(schema)):
        if not (
            node.get("type") == "string"
            and isinstance(node.get("enum"), list)
            and set(node["enum"]) == task_state_set
        ):
            continue
        desc = node.get("description")
        default = node.get("default")
        node.clear()
        node["$ref"] = "#/definitions/TaskState"
        if desc:
            node["description"] = desc
        if default is not None:
            node["default"] = default

    schema.setdefault("definitions", {})["TaskState"] = {
        "title": "TaskState",
        "description": "Defines the lifecycle states of a Task.",
        "type": "string",
        "enum": _TASK_STATE_VALUES,
    }


def process_schema(schema: dict) -> None:
    """Run the full preprocessing pipeline on ``schema`` in place.

    Raises ``SystemExit`` if the output still contains unresolved external
    refs (``*.jsonschema.json``) — that means upstream added definition
    names we don't know how to rewrite, and silently shipping a schema
    with unresolved refs would produce broken generated models.
    """
    rename_definitions(schema)
    ref_map = build_ref_map(schema.get("definitions", {}))
    resolve_refs(schema, ref_map)
    strip_additional_properties(schema)
    strip_pattern_properties(schema)
    simplify_anyof(schema)
    strip_nested_schema(schema)
    strip_title_spaces(schema)
    strip_string_patterns(schema)
    clean_descriptions(schema)
    rename_reserved_properties(schema)
    extract_task_state(schema)
    make_struct_a_dict_wrapper(schema)
    apply_required_fields(schema)

    remaining = re.findall(r'"[^"]*\.jsonschema\.json"', json.dumps(schema))
    if remaining:
        raise SystemExit(
            f"resolve_refs: {len(remaining)} unresolved external refs remain "
            f"after the pipeline. First 5: {remaining[:5]}. Either upstream "
            "added a new definition name we don't know how to rewrite, or "
            "build_ref_map is missing a prefix."
        )


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <schema.json> [output.json]")
        sys.exit(1)

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src

    schema = json.loads(src.read_text(encoding="utf-8"))
    process_schema(schema)
    dst.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Preprocessed schema -> {dst}")


if __name__ == "__main__":
    main()
