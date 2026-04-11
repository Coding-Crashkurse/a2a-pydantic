# a2apydantic

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
pip install a2apydantic
```

Requires Python 3.13+ and Pydantic 2.

## Basic usage — v1.0 models

```python
from a2apydantic import v10

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

All model classes live under `a2apydantic.v10` and are generated from the
official A2A JSON Schema. Field names are snake_case in Python, camelCase
on the wire (via `A2ABaseModel`'s alias generator).

## Basic usage — v0.3 models

```python
from a2apydantic import v03

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

`from_v10_to_v03` is a `singledispatch` entry point that picks the right
converter for whatever v1.0 model you hand it:

```python
import warnings
from a2apydantic import v10, from_v10_to_v03

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
    params = from_v10_to_v03(req)  # -> v03.MessageSendParams

for w in captured:
    print("LOSS:", w.message)
# LOSS: v10.SendMessageRequest.tenant='acme' is dropped (v0.3 has no tenant concept)
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

The dispatcher handles every data-carrying model pair:

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

## FastAPI: version-header routing

One endpoint, both wire formats. Client picks via `A2A-Version` header, and
any conversion losses come back in the response so clients can act on them:

```python
# examples/fastapi_version_header.py
import warnings
from typing import Annotated, Any
from fastapi import FastAPI, Header, HTTPException

from a2apydantic import v10
from a2apydantic.converters import send_message_request

app = FastAPI()

@app.post("/message:send")
def message_send(
    request: v10.SendMessageRequest,
    a2a_version: Annotated[str | None, Header(alias="A2A-Version")] = None,
) -> dict[str, Any]:
    version = (a2a_version or "1.0").strip()
    if version == "1.0":
        return {
            "version": "1.0",
            "payload": request.model_dump(by_alias=True, exclude_none=True),
            "conversion_warnings": [],
        }
    if version == "0.3":
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            params = send_message_request(request)
        return {
            "version": "0.3",
            "payload": params.model_dump(by_alias=True, exclude_none=True),
            "conversion_warnings": [str(w.message) for w in captured],
        }
    raise HTTPException(400, f"Unsupported A2A-Version {version!r}")
```

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
src/a2apydantic/
├── base.py              # A2ABaseModel: shared config + camelCase aliases
├── converters.py        # v1.0 -> v0.3 converter + singledispatch entry point
├── v03/
│   └── models.py        # v0.3 models (A2A JSON Schema)
└── v10/
    └── models.py        # v1.0 models (A2A JSON Schema, extracted from .proto)
```

v10 models are regenerated via `scripts/generate_v10.ps1`, which pulls the
latest schema from `https://a2a-protocol.org/latest/spec/a2a.json` and runs
`datamodel-code-generator` against it.
