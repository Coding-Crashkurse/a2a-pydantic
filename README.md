# a2a-pydantic

Pydantic models for the [A2A protocol](https://a2a-protocol.org/), covering
both **v0.3** and **v1.0** in a single package — plus a downward converter
that lets a v1.0 server still speak to v0.3 clients.

## Why this package

A2A exists in two incompatible versions that are both in the wild:

- **v0.3** is the original hand-written JSON Schema. Flat, JSON-RPC-shaped,
  lowercase enums (`user`, `submitted`), discriminated-union parts.
- **v1.0** is generated from `.proto` files. Protobuf-flavored enums
  (`ROLE_USER`, `TASK_STATE_SUBMITTED`), multi-tenant fields, flat `Part`
  with one payload slot per media kind, `google.protobuf.Struct`/`Value`
  placeholders for arbitrary JSON.

If your server only ships v1.0 models, every v0.3 client breaks. If you only
ship v0.3, you can't target the newer spec. This package gives you **both
sets of models as first-class Pydantic classes** and a **lossy-but-explicit
v1.0 → v0.3 converter**, so one backend can serve both with a single
`A2A-Version` header check.

The package has **zero runtime dependencies beyond Pydantic**. No
`a2a-sdk`, no `protobuf`, no grpc stack.

## Install

```bash
pip install a2a-pydantic
```

The PyPI distribution name uses a hyphen (`a2a-pydantic`), the Python
import name uses an underscore (`a2a_pydantic`). Standard Python
convention — same as e.g. `pydantic-settings` → `pydantic_settings`.

For the v1.0 → protobuf bridge (`convert_to_proto`), install with the
`[proto]` extra:

```bash
pip install a2a-pydantic[proto]
```

which pulls in `a2a-sdk>=1.0.0a0` for its `a2a_pb2` classes. Without
the extra, the rest of the package works as usual — the proto bridge
module is lazy-loaded and only imported when you actually call
`convert_to_proto`.

Requires Python 3.13+ and Pydantic 2.

## Basic usage — v1.0 models

```python
from a2a_pydantic import v10

req = v10.SendMessageRequest(
    message=v10.Message(
        message_id="m-1",
        role=v10.Role.role_user,
        parts=[v10.Part(text="Translate 'hello' to French")],
    ),
    tenant="acme",
)

print(req.model_dump_json(by_alias=True, exclude_none=True))
```

All model classes live under `a2a_pydantic.v10` and are generated from the
official A2A JSON Schema. Field names are snake_case in Python, camelCase
on the wire (via `A2ABaseModel`'s alias generator).

## Basic usage — v0.3 models

```python
from a2a_pydantic import v03

params = v03.MessageSendParams(
    message=v03.Message(
        message_id="m-1",
        role=v03.Role.user,
        parts=[v03.Part(root=v03.TextPart(text="Translate 'hello' to French"))],
    ),
)
```

v0.3 uses a strict discriminated-union `Part` (`TextPart | FilePart | DataPart`)
so you always wrap via `v03.Part(root=...)`.

## Downgrading v1.0 → v0.3

`convert_to_v03` is the single public entry point. It dispatches on the
runtime type of whatever v1.0 model you hand it and returns the matching
v0.3 model — fully type-checked via `@overload`, so your editor knows
`convert_to_v03(v10.SendMessageRequest)` returns `v03.MessageSendParams`,
`convert_to_v03(v10.Message)` returns `v03.Message`, etc.

```python
import warnings
from a2a_pydantic import convert_to_v03, v10

req = v10.SendMessageRequest(
    message=v10.Message(
        message_id="m-1",
        role=v10.Role.role_user,
        parts=[v10.Part(text="hi")],
    ),
    tenant="acme",  # v0.3 has no tenant concept
)

with warnings.catch_warnings(record=True) as captured:
    warnings.simplefilter("always")
    params = convert_to_v03(req)  # -> v03.MessageSendParams

for w in captured:
    print("LOSS:", w.message)
# LOSS: v10.SendMessageRequest.tenant='acme' is dropped (v0.3 has no tenant concept)
```

Pass an unsupported type and you get a `TypeError` instead of silent
garbage:

```python
convert_to_v03(42)
# TypeError: No v10 -> v03 converter registered for int
```

**Every lossy step raises a `UserWarning`**, so you can either log them,
surface them to clients, or fail fast in tests. Typical cases:

- `tenant` fields on requests / interfaces / push configs — v0.3 has no
  multi-tenancy
- `v10.Part` with more than one payload populated (`text` + `url`, ...) —
  v0.3's one-of parts can only carry one
- `TaskStatusUpdateEvent.final` — required in v0.3, missing in v1.0,
  defaulted to `False`
- `SecurityScheme` with multiple sub-schemes populated — v0.3 is strict
  one-of
- `DeviceCodeOAuthFlow`, `AuthorizationCodeOAuthFlow.pkce_required=True` —
  no v0.3 equivalent
- `AgentInterface.protocol_version != "0.3"` — dropped
- `APIKeySecurityScheme.location` outside `query|header|cookie` — coerced
  to `header` with warning

**Upward conversion (v0.3 → v1.0) is intentionally not provided.** v1.0
adds fields that have no v0.3 source (tenant, protocol_binding vs
protocol_version split, AwareDatetime timestamps, ...) and inventing
defaults for them would silently corrupt data.

### What's covered

`convert_to_v03` handles every data-carrying model pair:

| v1.0 | v0.3 | Notes |
|---|---|---|
| `SendMessageRequest` | `MessageSendParams` | v1.0 has no JSON-RPC envelope layer |
| `SendMessageConfiguration` | `MessageSendConfiguration` | `return_immediately` → `blocking` (inverted) |
| `Message`, `Part`, `Artifact`, `Task`, `TaskStatus` | same names | `Part` fan-out: `text > raw > url > data` |
| `TaskStatusUpdateEvent` | same | `final=False` default + warning |
| `TaskArtifactUpdateEvent` | same | – |
| `TaskPushNotificationConfig` | outer + inner `PushNotificationConfig` | flat → nested |
| `AuthenticationInfo` | `PushNotificationAuthenticationInfo` | `scheme: str` → `schemes: [scheme]` |
| `AgentCard` | `AgentCard` | `supported_interfaces[0]` → `url`/`preferred_transport`, rest → `additional_interfaces` |
| `AgentInterface/Provider/Extension/Capabilities/Skill/CardSignature` | same | – |
| `SecurityScheme` envelope | `SecurityScheme` RootModel | pick-one, warn on multi |
| `APIKeySecurityScheme` | same | `location: str` → `in_: In` enum |
| `OAuthFlows` + all flows | same | `device_code` dropped |
| `Role`, `TaskState` enums | same | Protobuf → lowercase mapping |

## Bridging v1.0 → a2a-sdk protobuf

`convert_to_proto` is the v1.0 → pb2 counterpart to `convert_to_v03`.
Requires `pip install a2a-pydantic[proto]` which pulls in `a2a-sdk>=1.0.0a0`
for the `a2a_pb2` module. Dispatches on the input type, returns the
matching pb2 `Message` instance, typed via `@overload` so the editor
knows `convert_to_proto(v10.SendMessageRequest)` returns
`a2a_pb2.SendMessageRequest`.

```python
from a2a_pydantic import convert_to_proto, v10
from a2a.types import a2a_pb2

req = v10.SendMessageRequest(
    message=v10.Message(
        message_id="m-1",
        role=v10.Role.role_user,
        parts=[v10.Part(text="hello")],
    ),
    tenant="acme",
)
pb_req = convert_to_proto(req)               # -> a2a_pb2.SendMessageRequest
wire = pb_req.SerializeToString()             # bytes, ready for gRPC
```

Only v1.0 types are supported — v0.3 has no direct proto counterpart.
Handing in something unsupported raises `TypeError`.

**Lazy loading:** `a2a_pydantic` top-level does NOT eagerly import
`to_proto`. It's only resolved the first time you access
`a2a_pydantic.convert_to_proto` (via PEP 562 `__getattr__`). If you
never call it, you never pay the `a2a-sdk` import cost — and if you
never installed the `[proto]` extra, the rest of the package still
works fine.

```python
# Without [proto] installed:
from a2a_pydantic import v03, v10, convert_to_v03   # OK, works
from a2a_pydantic import convert_to_proto           # ImportError: install with [proto]
```

**Oneof semantics:** pb2 `Part`, `SecurityScheme`, `OAuthFlows`,
`SendMessageResponse` and `StreamResponse` all use `oneof` fields
internally. Pydantic v1.0 models model these flat (multiple Optional
fields that could all be set). If you populate more than one at once,
`convert_to_proto` emits a `UserWarning` — pb2 would otherwise silently
collapse to the last write and drop your earlier data.

### What's covered

`convert_to_proto` handles every v1.0 model that has a pb2 counterpart
in `a2a.types.a2a_pb2` — 34 types in total:

- Messages: `Message`, `Part`, `Artifact`, `Task`, `TaskStatus`,
  `TaskStatusUpdateEvent`, `TaskArtifactUpdateEvent`
- Requests / responses: `SendMessageRequest`, `SendMessageResponse`,
  `SendMessageConfiguration`, `StreamResponse`, `GetTaskRequest`,
  `ListTasksRequest`, `ListTasksResponse`, `CancelTaskRequest`,
  `GetTaskPushNotificationConfigRequest`,
  `DeleteTaskPushNotificationConfigRequest`, `SubscribeToTaskRequest`,
  `ListTaskPushNotificationConfigsRequest`,
  `ListTaskPushNotificationConfigsResponse`,
  `GetExtendedAgentCardRequest`
- Config / metadata: `TaskPushNotificationConfig`, `AuthenticationInfo`,
  `AgentCard`, `AgentCapabilities`, `AgentInterface`, `AgentProvider`,
  `AgentExtension`, `AgentSkill`, `AgentCardSignature`
- Security: `SecurityScheme`, `SecurityRequirement`, `StringList`,
  `OAuthFlows`

`Struct` fields are encoded via `google.protobuf.struct_pb2.Struct`,
`Value` fields via `struct_pb2.Value`, `Timestamp` via
`timestamp_pb2.Timestamp`, and `Part.raw` is base64-decoded to pb2's
`bytes` field.

## FastAPI: version-header routing

One endpoint, both wire formats. Client picks via `A2A-Version` header, and
any conversion losses come back in the response so clients can act on them:

The full example in [examples/fastapi_version_header.py](examples/fastapi_version_header.py)
is ~80 lines. Core of the route:

```python
from a2a_pydantic import convert_to_v03, v10

@app.post("/message:send")
def message_send(
    request: v10.SendMessageRequest,
    a2a_version: Annotated[str | None, Header(alias="A2A-Version")] = None,
) -> dict[str, Any]:
    version = (a2a_version or "1.0").strip()

    if version == "1.0":
        return {"version": "1.0", "payload": request.model_dump(by_alias=True, exclude_none=True), "conversion_warnings": []}

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        converted = convert_to_v03(request)  # v03.MessageSendParams

    for w in captured:
        logger.warning("a2a v1.0->v0.3 conversion: %s", w.message)

    return {
        "version": "0.3",
        "payload": converted.model_dump(by_alias=True, exclude_none=True),
        "conversion_warnings": [str(w.message) for w in captured],
    }
```

Warnings are both logged via the `uvicorn.error` logger so they appear
in the server console alongside the access log, and echoed back in the
response body so clients can act on them.

Run it:

```bash
uv pip install fastapi uvicorn
uvicorn examples.fastapi_version_header:app --reload
```

```bash
curl -X POST localhost:8000/message:send \
  -H 'Content-Type: application/json' \
  -H 'A2A-Version: 0.3' \
  -d '{
    "message": {
      "messageId": "m-1",
      "role": "ROLE_USER",
      "parts": [{"text": "hello", "url": "https://x/y"}]
    },
    "tenant": "acme"
  }'
```

Response:

```json
{
  "version": "0.3",
  "payload": { "message": { "kind": "message", "messageId": "m-1", "role": "user", "parts": [...] } },
  "conversion_warnings": [
    "v10.SendMessageRequest.tenant='acme' is dropped (v0.3 has no tenant concept)",
    "v10.Part has multiple payloads ['text', 'url']; keeping 'text' and dropping the rest (v03 Part is strict one-of)"
  ]
}
```

## Project layout

```
src/a2a_pydantic/
├── base.py              # A2ABaseModel: shared config + camelCase aliases
├── converters.py        # v1.0 -> v0.3 converter (SDK-free)
├── to_proto.py          # v1.0 -> a2a-sdk pb2 bridge (requires [proto] extra)
├── v03/
│   └── models.py        # v0.3 models (A2A JSON Schema)
└── v10/
    └── models.py        # v1.0 models (A2A JSON Schema, extracted from .proto)
```

v10 models are regenerated via `scripts/generate_v10.ps1`, which pulls the
latest schema from `https://a2a-protocol.org/latest/spec/a2a.json` and runs
`datamodel-code-generator` against it.
