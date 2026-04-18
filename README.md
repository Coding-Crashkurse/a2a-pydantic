# a2a-pydantic

Pydantic models for the [A2A protocol](https://a2a-protocol.org/), covering
both **v0.3** and **v1.0** in a single package, plus typed bridges in
every direction:

- a **v1.0 → v0.3 downward converter** so a v1.0 server can still speak
  to v0.3 clients
- a **v0.3 → v1.0 upward converter** so a v1.0 internal pipeline can
  ingest v0.3 wire input
- a **v1.0 ↔ a2a-sdk protobuf bridge** so you can put typed Pydantic
  request and response models in front of the SDK's
  `DefaultRequestHandler` and get a real FastAPI `/docs` page with full
  schemas instead of the SDK's framework-agnostic Starlette routes that
  don't render in OpenAPI

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

Requires Python 3.11+ and Pydantic 2. The core package has **zero
runtime dependencies beyond Pydantic**.

Two optional extras are available:

| Extra | Pulls in | For |
|---|---|---|
| `[proto]` | `a2a-sdk>=1.0.0a1` | `convert_to_proto` / `convert_from_proto` (v1.0 ↔ pb2 bridge) |
| `[example]` | `a2a-sdk[http-server]`, `fastapi`, `uvicorn`, `sse-starlette` | Running the example apps in `examples/` |

```bash
pip install a2a-pydantic[proto]       # + a2a-sdk for convert_to_proto / convert_from_proto
pip install a2a-pydantic[example]     # + full stack for the example servers
```

Without any extra, `convert_to_proto` and `convert_from_proto` are both
still importable (via PEP 562 lazy attribute loading) but raise a clear
`ImportError` when you call them, pointing at the `[proto]` install
command. The `[example]` extra is only needed if you actually want to
run [examples/fastapi_version_header.py](examples/fastapi_version_header.py)
or
[examples/a2a_10_proto_typed.py](examples/a2a_10_proto_typed.py).

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

> **Note on optional string defaults.** Many v1.0 string fields are typed
> as `str | None = ''` rather than `str | None = None`. That looks odd,
> but it mirrors proto3 semantics: proto3 does not distinguish "unset"
> from "empty string" for scalar `string` fields, so we keep the
> generator output faithful to preserve round-trip fidelity with pb2.
> Treat `''` and `None` as equivalent for serialization purposes.

### Ergonomics

A few small things the package does to make the generated models less
painful to work with day to day:

**Assigning a plain dict to `metadata` works.** `task.metadata` is typed
as `v10.Struct | None`, but `validate_assignment=True` on the base class
re-validates on every attribute set, so the dict is coerced back to
`Struct` transparently:

```python
task.metadata = {"trace_id": "abc", "retries": 2}
assert isinstance(task.metadata, v10.Struct)   # auto-coerced
convert_to_v03(task)                           # still works
```

Before 0.0.5 this stored the raw dict and later crashed `convert_to_v03`
with `AttributeError: 'dict' object has no attribute 'model_dump'`.

**`v10.Timestamp` is orderable.** `__lt__`/`__le__`/`__gt__`/`__ge__`
forward to the underlying `AwareDatetime`, so you can sort tasks by
status timestamp directly:

```python
sorted(tasks, key=lambda t: t.status.timestamp)
```

**`v10.TaskState` takes case-insensitive values.** The canonical wire
form is uppercase (`TASK_STATE_SUBMITTED`), but the short/mixed/lowercase
forms all resolve to the same member — handy when you store states in
Redis/SQL and don't want a normalization pass at every I/O boundary:

```python
v10.TaskState("TASK_STATE_SUBMITTED")   # canonical
v10.TaskState("submitted")              # short lowercase
v10.TaskState("Submitted")              # short mixed case
# ... all return TaskState.task_state_submitted
```

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

**Overriding the synthetic `final` flag on status events.** v1.0
`TaskStatusUpdateEvent` has no `final` field but v0.3 requires one, so
the converter defaults to `False` and emits a warning. If your
framework already knows whether the event is terminal (e.g. from a
wrapper marker) you can pass `assume_final=True/False` to set the value
AND suppress the warning. Useful in streaming servers where the default
warning would otherwise fire once per SSE event:

```python
out = convert_to_v03(event, assume_final=is_terminal)
# out.final == is_terminal, no "defaulting final=False" warning
```

## Upgrading v0.3 → v1.0

`convert_to_v10` is the upward counterpart to `convert_to_v03`. Same
`@singledispatch + @overload` architecture. Fields that v1.0 introduces
(`tenant`, `protocol_binding` vs `protocol_version` split, AwareDatetime
timestamps, `pkce_required`, ...) default to `None` / `[]` / `""` unless
you supply a context kwarg:

```python
import warnings
from a2a_pydantic import convert_to_v10, v03

params = v03.MessageSendParams(
    message=v03.Message(
        message_id="m-1",
        role=v03.Role.user,
        parts=[v03.Part(root=v03.TextPart(text="hi"))],
    ),
)

with warnings.catch_warnings(record=True) as captured:
    warnings.simplefilter("always")
    req = convert_to_v10(
        params,
        tenant="acme-corp",                    # fills v10.SendMessageRequest.tenant
        message_extensions=["urn:ext:foo"],    # fills v10.Message.extensions
    )
# req: v10.SendMessageRequest
```

The two context kwargs propagate through nested conversions via a
`ContextVar`, so you only set them at the top-level call:

| Kwarg | Fills |
|---|---|
| `tenant` | `v10.SendMessageRequest.tenant`, `v10.AgentInterface.tenant`, `v10.TaskPushNotificationConfig.tenant` |
| `message_extensions` | `v10.Message.extensions` (overrides `v03.Message.extensions` when passed) |

Every lossy step emits a `UserWarning`. Typical cases:

- `v03.TaskState.unknown` — no v1.0 equivalent, coerced to
  `task_state_submitted`
- `PushNotificationAuthenticationInfo.schemes` with more than one
  entry — v1.0's `AuthenticationInfo.scheme` is a single string, first
  kept
- `v03.OAuthFlows` with multiple flows — v1.0 enforces exactly one-of,
  first kept
- `AgentCapabilities.state_transition_history` — dropped (no v1.0
  counterpart)

### What's covered

| v0.3 | v1.0 | Notes |
|---|---|---|
| `Role`, `TaskState` enums | same names | lowercase → protobuf `ROLE_*` / `TASK_STATE_*` |
| `Part` (RootModel union) | `Part` (flat) | `TextPart`/`FilePart`/`DataPart` folded into `text`/`raw`/`url`/`data` |
| `Message`, `Artifact`, `TaskStatus`, `Task` | same names | metadata dicts wrap into `Struct`, ISO timestamps parse into `Timestamp` |
| `MessageSendConfiguration` | `SendMessageConfiguration` | `blocking` → `return_immediately` (inverted) |
| `MessageSendParams` | `SendMessageRequest` | v0.3 has no JSON-RPC envelope layer on the params side |
| `PushNotificationAuthenticationInfo` | `AuthenticationInfo` | `schemes: list[str]` → `scheme: str` (pick first) |
| `PushNotificationConfig` | `TaskPushNotificationConfig` | flat synthesis with `task_id=""` when standalone |
| `TaskPushNotificationConfig` | same name | nested → flat |
| `AgentInterface` | same name | `transport` → `protocol_binding`, `protocol_version="0.3"` |
| `AgentCard` | same name | `url`+`preferred_transport`+`additional_interfaces` → `supported_interfaces` list |
| `AgentExtension/Capabilities/Skill/Provider/CardSignature` | same | `supports_authenticated_extended_card` → `capabilities.extended_agent_card` |
| `SecurityScheme` (RootModel) | `SecurityScheme` (envelope) | one-of dispatch, five variants |
| `APIKey/HTTPAuth/MutualTLS/OAuth2/OpenIdConnect` schemes | same | `In` enum → lowercase string |
| `OAuthFlows` + all 4 flows | same | `pkce_required=False` injected on auth-code flow |

## v10.Part construction / extraction helpers

Building a `v10.Part` from scratch means either wrapping dicts in
`v10.Value`, base64-encoding bytes, or remembering the flat-oneof shape.
`a2a_pydantic.v10.parts` provides the obvious shortcuts so call sites
read as natural Python:

```python
from a2a_pydantic.v10.parts import (
    text_part, data_part, file_part_bytes, file_part_url,
    extract_text, extract_data, extract_files, part_kind, FileInfo,
)

msg = v10.Message(
    message_id="m-1",
    role=v10.Role.role_user,
    parts=[
        text_part("Analyze this invoice."),
        file_part_bytes(pdf_bytes, media_type="application/pdf", filename="inv.pdf"),
        data_part({"currency": "EUR", "total": 42.0}),
    ],
)
```

Construction helpers handle the conversions automatically:

| Helper | Does |
|---|---|
| `text_part(text, *, media_type=None, metadata=None)` | direct `Part(text=...)` |
| `data_part(data, *, media_type="application/json", metadata=None)` | wraps `data` in `v10.Value` |
| `file_part_bytes(content, *, media_type=None, filename=None, metadata=None)` | base64-encodes `content` into `Part.raw` |
| `file_part_url(url, *, media_type=None, filename=None, metadata=None)` | direct `Part(url=...)` |

Extractors go the other way, including base64-decoding and empty-string
normalization:

```python
# Agent-side inbox processing
if part_kind(msg.parts[0]) == "text":
    text = extract_text(msg.parts)         # concatenated strings
    blobs = extract_data(msg.parts)        # unwrapped from Value
    files = extract_files(msg.parts)       # list[FileInfo]

for f in files:
    if f.content is not None:
        save(f.content, name=f.filename)   # filename is None, not ""
    elif f.url is not None:
        download(f.url)
```

`FileInfo` is a frozen dataclass `(content, url, filename, media_type)`
with the empty-string proto3 defaults flipped back to `None`, so the
natural `if f.filename:` idiom works.

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
| `GetTaskRequest` | `TaskQueryParams` | – |
| `CancelTaskRequest` | `TaskIdParams` | – |
| `SubscribeToTaskRequest` | `TaskIdParams` | – |
| `GetTaskPushNotificationConfigRequest` | `GetTaskPushNotificationConfigParams` | `task_id`/`id` flattened |
| `DeleteTaskPushNotificationConfigRequest` | `DeleteTaskPushNotificationConfigParams` | `task_id`/`id` flattened |
| `ListTaskPushNotificationConfigsRequest` | `ListTaskPushNotificationConfigParams` | pagination fields dropped with warning |

## Bridging v1.0 → a2a-sdk protobuf

`convert_to_proto` is the v1.0 → pb2 counterpart to `convert_to_v03`.
Requires `pip install a2a-pydantic[proto]` which pulls in `a2a-sdk>=1.0.0a1`
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

## Bridging a2a-sdk protobuf → v1.0

`convert_from_proto` is the reverse direction — pb2 back to typed
Pydantic v1.0 — and completes the round-trip. Same `[proto]` extra,
same `@singledispatch + @overload` architecture, same 34 types.

```python
from a2a_pydantic import convert_from_proto, convert_to_proto, v10
from a2a.types import a2a_pb2

# Forward: v10 -> pb2 -> wire
req = v10.SendMessageRequest(
    message=v10.Message(
        message_id="m-1",
        role=v10.Role.role_user,
        parts=[v10.Part(text="hello")],
    ),
)
pb_req = convert_to_proto(req)
wire = pb_req.SerializeToString()

# Reverse: wire -> pb2 -> v10
pb_req2 = a2a_pb2.SendMessageRequest()
pb_req2.ParseFromString(wire)
typed_req = convert_from_proto(pb_req2)        # -> v10.SendMessageRequest
assert typed_req.message.parts[0].text == "hello"
```

The main use case: you call a SDK request handler that returns pb2
(`handler.on_message_send(pb_req, ctx)` → `pb2.Task | pb2.Message`),
and you want to serialize the result as a typed v1.0 model in a
FastAPI endpoint. `convert_from_proto` closes that loop. See the
**typed FastAPI facade** example below for the full pattern.

**Known limitation — `Struct` metadata:** the generated v10 `Struct`
model is an empty-schema stub with no extra-field support, so pb2
`metadata` / `Struct` payloads cannot round-trip faithfully — the
key/value pairs are dropped and you get back an empty `v10.Struct()`
instance. This is symmetric in both directions (`convert_to_proto`
has the same limitation on the forward path). Fix would require
changing the v10 codegen to allow extras on `Struct`.

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

## Sample agent: SDK-native vs. typed facade

A side-by-side pair of minimal A2A sample agents showing what you get
with and without `a2a-pydantic`:

### [examples/a2a_10_proto.py](examples/a2a_10_proto.py) — the SDK-native way

Builds `AgentCard`, `AgentSkill`, `Part` etc. directly from `a2a.types`
(pb2 classes) and mounts the SDK's `create_rest_routes` into a FastAPI
app. Works, but:

- ❌ **No autocomplete** — `a2a_pb2.AgentCard` has no `__init__` type
  hints for the IDE
- ❌ **No type checking** — a typo'd field name is silently dropped by
  pb2 at runtime
- ❌ **No validation** — wrong enum values surface as silent defaults
- ❌ **Empty `/docs`** — `create_rest_routes` returns
  `starlette.routing.Route` instances, which FastAPI's OpenAPI
  generator can't see. Swagger UI says "No operations defined in
  spec!" even though the routes work.

### [examples/a2a_10_proto_typed.py](examples/a2a_10_proto_typed.py) — the typed facade

Builds the same agent, runs the same `DefaultRequestHandler`
underneath, but everything is Pydantic on the outside:

- ✅ **Typed construction** — `v10.AgentCard(...)` with full IDE
  autocomplete, pyright/mypy coverage, Pydantic validation
- ✅ **Typed endpoints** — real `@app.post` / `@app.get` FastAPI
  decorators with `response_model=v10.Task` etc., so the routes show
  up in `/docs` with full request **and** response schemas
- ✅ **422 before the handler** — FastAPI/Pydantic rejects invalid
  requests with a detailed error message before the SDK sees them
- ✅ **Typed-in, typed-out** — request body parsed as v10 Pydantic,
  `convert_to_proto` at the SDK boundary, handler returns pb2,
  `convert_from_proto` on the way back, FastAPI serializes the v10
  response via Pydantic

The facade exposes three endpoints (plus the agent card):

| Route | Request | Response |
|---|---|---|
| `GET  /.well-known/agent-card.json` | – | `v10.AgentCard` |
| `POST /a2a/message:send` | `v10.SendMessageRequest` | `v10.SendMessageResponse` |
| `GET  /a2a/tasks/{task_id}` | path param | `v10.Task` |
| `POST /a2a/tasks/{task_id}:cancel` | path param | `v10.Task` |

Core of the pattern:

```python
from a2a_pydantic import convert_from_proto, convert_to_proto, v10
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.context import ServerCallContext
from a2a.types import a2a_pb2
from fastapi import FastAPI, HTTPException

app = FastAPI()

@app.post("/a2a/message:send", response_model=v10.SendMessageResponse)
async def send_message(
    request: v10.SendMessageRequest,
) -> v10.SendMessageResponse:
    pb_req = convert_to_proto(request)
    result = await handler.on_message_send(pb_req, ServerCallContext())
    if isinstance(result, a2a_pb2.Task):
        return v10.SendMessageResponse(task=convert_from_proto(result))
    if isinstance(result, a2a_pb2.Message):
        return v10.SendMessageResponse(message=convert_from_proto(result))
    raise HTTPException(500, "unexpected handler result type")
```

### Running the comparison

Both run against `a2a-sdk>=1.0.0a1` on port 8000:

```bash
uv pip install -e ".[example]"
python examples/a2a_10_proto.py          # SDK-native (empty /docs)
python examples/a2a_10_proto_typed.py    # typed facade (full /docs)
```

Stop one before starting the other — they share the port. Visit
`http://127.0.0.1:8000/docs` for each and see the difference.

## Project layout

```
src/a2a_pydantic/
├── base.py              # A2ABaseModel: shared config + camelCase aliases
├── converters.py        # v1.0 -> v0.3 converter (SDK-free)
├── converters_v10.py    # v0.3 -> v1.0 converter (SDK-free)
├── to_proto.py          # v1.0 -> a2a-sdk pb2 bridge (requires [proto] extra)
├── from_proto.py        # a2a-sdk pb2 -> v1.0 bridge (requires [proto] extra)
├── v03/
│   └── models.py        # v0.3 models (A2A JSON Schema)
└── v10/
    ├── models.py        # v1.0 models (A2A JSON Schema, extracted from .proto)
    └── parts.py         # v10.Part construction / extraction helpers
```

v10 models are regenerated via `scripts/generate_v10.ps1`, which pulls the
latest schema from `https://a2a-protocol.org/latest/spec/a2a.json` and runs
`datamodel-code-generator` against it.