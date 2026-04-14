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
from pathlib import Path


def slugify(name: str) -> str:
    return name.replace(" ", "")


def rename_definitions(schema: dict) -> None:
    """Rename definition keys to remove spaces, and rewrite internal $refs."""
    defs = schema.get("definitions", {})
    rename_map: dict[str, str] = {}
    for old in list(defs.keys()):
        new = slugify(old)
        if new != old:
            rename_map[old] = new
    if not rename_map:
        return

    new_defs: dict = {}
    for old, body in defs.items():
        new_defs[rename_map.get(old, old)] = body
    schema["definitions"] = new_defs

    def rewrite(obj):
        if isinstance(obj, dict):
            if "$ref" in obj and isinstance(obj["$ref"], str):
                ref = obj["$ref"]
                if ref.startswith("#/definitions/"):
                    key = ref[len("#/definitions/"):]
                    if key in rename_map:
                        obj["$ref"] = f"#/definitions/{rename_map[key]}"
            for v in obj.values():
                rewrite(v)
        elif isinstance(obj, list):
            for item in obj:
                rewrite(item)

    rewrite(schema)


def build_ref_map(definitions: dict) -> dict[str, str]:
    ref_map: dict[str, str] = {}
    for def_name in definitions:
        for prefix in ("lf.a2a.v1.", "google.protobuf."):
            ref_map[f"{prefix}{def_name}.jsonschema.json"] = f"#/definitions/{def_name}"
    return ref_map


def resolve_refs(obj, ref_map: dict[str, str]):
    if isinstance(obj, dict):
        if "$ref" in obj and obj["$ref"] in ref_map:
            obj["$ref"] = ref_map[obj["$ref"]]
        for v in obj.values():
            resolve_refs(v, ref_map)
    elif isinstance(obj, list):
        for item in obj:
            resolve_refs(item, ref_map)


def strip_additional_properties(obj):
    if isinstance(obj, dict):
        if obj.get("additionalProperties") is False:
            del obj["additionalProperties"]
        for v in obj.values():
            strip_additional_properties(v)
    elif isinstance(obj, list):
        for item in obj:
            strip_additional_properties(item)


def strip_pattern_properties(obj):
    if isinstance(obj, dict):
        obj.pop("patternProperties", None)
        for v in obj.values():
            strip_pattern_properties(v)
    elif isinstance(obj, list):
        for item in obj:
            strip_pattern_properties(item)


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
    values = []
    for v in any_of:
        if isinstance(v, dict) and "enum" in v:
            values.extend(v["enum"])
    return values


def simplify_anyof(obj):
    if isinstance(obj, dict):
        if "anyOf" in obj and isinstance(obj["anyOf"], list):
            any_of = obj["anyOf"]

            if _is_proto_enum_anyof(any_of):
                enum_vals = _extract_enum_values(any_of)
                desc = obj.get("description", "")
                title = obj.get("title")
                default = obj.get("default")
                obj.clear()
                obj["type"] = "string"
                obj["enum"] = enum_vals
                if desc:
                    obj["description"] = desc
                if title:
                    obj["title"] = title
                # Proto enums default to integer 0 (= UNSPECIFIED). We drop
                # UNSPECIFIED from the Python enum because Python already has
                # `None` for "unset", so an integer default has no valid target
                # on our side — keep the field unset. String defaults are
                # preserved only when they actually match one of the kept enum
                # values; an unmappable string is almost certainly a schema
                # drift we want to hear about, so we log it loudly instead of
                # silently dropping (silent drops are what produced the
                # `default: 0 -> "TASK_STATE_SUBMITTED"` bug in the first place).
                if default is None or isinstance(default, int):
                    pass
                elif isinstance(default, str) and default in enum_vals:
                    obj["default"] = default
                else:
                    print(
                        f"resolve_refs: dropping unmappable enum default "
                        f"{default!r} (kept enum values: {enum_vals})",
                        file=sys.stderr,
                    )

            elif _is_proto_int_anyof(any_of):
                int_schema = next(
                    v for v in any_of if isinstance(v, dict) and v.get("type") == "integer"
                )
                desc = obj.get("description", "")
                default = obj.get("default")
                obj.clear()
                obj["type"] = "integer"
                if desc:
                    obj["description"] = desc
                if default is not None:
                    obj["default"] = default

        for v in obj.values():
            simplify_anyof(v)
    elif isinstance(obj, list):
        for item in obj:
            simplify_anyof(item)


def strip_nested_schema(obj):
    if isinstance(obj, dict):
        if "$schema" in obj and "definitions" not in obj:
            del obj["$schema"]
        for v in obj.values():
            strip_nested_schema(v)
    elif isinstance(obj, list):
        for item in obj:
            strip_nested_schema(item)


def strip_title_spaces(schema: dict) -> None:
    """Remove spaces from `title` fields inside definitions (cosmetic)."""
    for body in schema.get("definitions", {}).values():
        if isinstance(body, dict) and isinstance(body.get("title"), str):
            body["title"] = slugify(body["title"])


def strip_string_patterns(obj):
    """Drop `pattern` constraints on string fields - we don't want `constr()` wrappers."""
    if isinstance(obj, dict):
        if obj.get("type") == "string" and "pattern" in obj:
            del obj["pattern"]
        for v in obj.values():
            strip_string_patterns(v)
    elif isinstance(obj, list):
        for item in obj:
            strip_string_patterns(item)


def clean_descriptions(obj):
    """Trim per-line leading space inherited from proto `//` comments.

    The proto->jsonschema step produces descriptions like:
        "AgentCardSignature represents a JWS signature of an AgentCard.\n This follows ..."
    where every continuation line starts with a single space. Strip that leading
    space so the rendered docstrings match the v0.3 style.
    """
    if isinstance(obj, dict):
        desc = obj.get("description")
        if isinstance(desc, str) and "\n " in desc:
            obj["description"] = "\n".join(line.lstrip() for line in desc.split("\n"))
        for v in obj.values():
            clean_descriptions(v)
    elif isinstance(obj, list):
        for item in obj:
            clean_descriptions(item)


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


def extract_task_state(schema: dict) -> None:
    """Promote the inline TaskState enum to a shared definition so Status/State
    collapse into a single `TaskState` class in the generated models."""
    task_state_set = set(_TASK_STATE_VALUES)

    def rewrite(obj):
        if isinstance(obj, dict):
            if (
                obj.get("type") == "string"
                and isinstance(obj.get("enum"), list)
                and set(obj["enum"]) == task_state_set
            ):
                desc = obj.get("description")
                default = obj.get("default")
                obj.clear()
                obj["$ref"] = "#/definitions/TaskState"
                if desc:
                    obj["description"] = desc
                if default is not None:
                    obj["default"] = default
                return
            for v in obj.values():
                rewrite(v)
        elif isinstance(obj, list):
            for item in obj:
                rewrite(item)

    # Walk existing definitions first so we don't rewrite the enum we're about to add.
    rewrite(schema)

    schema.setdefault("definitions", {})["TaskState"] = {
        "title": "TaskState",
        "description": "Defines the lifecycle states of a Task.",
        "type": "string",
        "enum": _TASK_STATE_VALUES,
    }


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <schema.json> [output.json]")
        sys.exit(1)

    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src

    schema = json.loads(src.read_text(encoding="utf-8"))

    rename_definitions(schema)
    definitions = schema.get("definitions", {})

    ref_map = build_ref_map(definitions)
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
    apply_required_fields(schema)

    raw = json.dumps(schema)
    remaining = re.findall(r'"[^"]*\.jsonschema\.json"', raw)
    if remaining:
        print(f"WARNING: {len(remaining)} unresolved refs: {remaining[:5]}", file=sys.stderr)

    dst.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Preprocessed schema -> {dst}")


if __name__ == "__main__":
    main()
