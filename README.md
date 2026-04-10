# a2a-pydantic

Pydantic models for the A2A protocol with dual v0.3 / v1.0 support and zero protobuf dependency.

```python
from a2a_pydantic import Message, Part, Role

msg = Message(
    role=Role.USER,
    parts=[Part(text="Translate to French")],
    message_id="msg-001",
)

msg.dump(version="0.3")  # v0.3 wire format
msg.dump(version="1.0")  # v1.0 wire format
```

The output version can also come from the `A2A_VERSION` environment variable
(`"0.3"` or `"1.0"`). If neither an explicit `version=` argument nor the env
var is set, `dump()` raises — there is no silent default.

## FastAPI: full v0.3 JSON-RPC endpoint

The package ships every v0.3 JSON-RPC envelope type, so a single FastAPI
endpoint can dispatch all A2A methods via a discriminated union:

```python
from fastapi import FastAPI
from a2a_pydantic import A2ARequest, SendMessageRequest, GetTaskRequest, ...

app = FastAPI()

@app.post("/")
async def jsonrpc(request: A2ARequest):
    match request.root:
        case SendMessageRequest():  ...
        case GetTaskRequest():      ...
        case CancelTaskRequest():   ...
        ...
```

`A2ARequest` is a Pydantic discriminated union over every method literal
(`message/send`, `tasks/get`, `tasks/cancel`, `tasks/pushNotificationConfig/*`,
…), so each match arm gets the correctly-typed `params`. See
[examples/fastapi_app.py](examples/fastapi_app.py) for a runnable demo with
both the JSON-RPC endpoint and the v0.3 / v1.0 single-method endpoints.

The 12 standard A2A error types (`TaskNotFoundError`, `InvalidParamsError`,
`MethodNotFoundError`, …) are also shipped with their literal JSON-RPC error
codes baked in, so building a `JSONRPCErrorResponse` is one line.

## Optional: convert to protobuf for use with `a2a-sdk`

The optional `[proto]` extra installs `protobuf` so `to_proto()` can convert
any supported model into a proto message — typically to feed an `a2a-sdk`
`AgentExecutor`:

```bash
pip install a2a-pydantic[proto]
```

```python
from a2a_pydantic import MessageSendParams
from a2a_pydantic.proto import to_proto

# In a FastAPI handler that received MessageSendParams from the client:
proto_request = to_proto(params)  # → a2a_pb2.SendMessageRequest
```

`to_proto(model)` auto-imports `a2a.grpc.a2a_pb2` if `a2a-sdk` is installed.
If you want to stay SDK-independent, pass your own proto module:

```python
from my_company import a2a_pb2
proto_request = to_proto(params, pb2=a2a_pb2)
```

The `[proto]` extra deliberately does NOT pull in `a2a-sdk` — `a2a-pydantic`
stays SDK-independent. The bridge supports 28 model types covering every
data primitive, the agent card and all its sub-types, every security scheme
(including the `SecurityScheme` oneof inside `AgentCard.security_schemes`),
push-notification config, and the `MessageSendParams` →
`SendMessageRequest` conversion that's the typical FastAPI →
`AgentExecutor` bridge.
