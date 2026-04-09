# Examples

Two runnable examples that exercise `a2a-pydantic` against realistic A2A payloads.

## `round_trip.py`

Builds a multi-part `MessageSendParams` and a completed `Task` (with two artifacts and a conversation history), then dumps both in v0.3 and v1.0 wire formats and verifies the round-trip:

```
v0.3 -> model -> v1.0 matches direct v1.0 dump  OK
v1.0 -> model -> v0.3 matches direct v0.3 dump  OK
```

Run:

```bash
uv run --extra dev python examples/round_trip.py
```

## `fastapi_app.py`

A FastAPI service that exposes `message/send` and **auto-detects which A2A version the client is speaking** by inspecting the request body. The same Python `MessageSendParams` model handles both formats; the response is dumped in whichever version the caller used.

Endpoints:

| Path | Behaviour |
|---|---|
| `POST /message:send` | v1.0-style URL. Accepts both v0.3 and v1.0 bodies; responds in matching format. |
| `POST /v1/message:send` | v0.3-style URL. Always responds in v0.3 (regardless of input). |
| `GET /` | Index. |

Install fastapi + uvicorn (not part of the package extras), then run:

```bash
uv pip install fastapi uvicorn
uv run --extra dev uvicorn examples.fastapi_app:app --reload
```

Try it with curl:

```bash
# v0.3 client
curl -X POST http://localhost:8000/message:send \
    -H "Content-Type: application/json" \
    -d '{
      "message": {
        "kind": "message",
        "messageId": "m1",
        "role": "user",
        "parts": [{"kind": "text", "text": "Hi from a v0.3 client"}]
      }
    }'

# v1.0 client
curl -X POST http://localhost:8000/message:send \
    -H "Content-Type: application/json" \
    -d '{
      "message": {
        "messageId": "m1",
        "role": "ROLE_USER",
        "parts": [{"text": "Hi from a v1.0 client"}]
      }
    }'
```

The first call returns a v0.3-shaped Task (`"state": "completed"`, `"kind": "task"`); the second returns a v1.0-shaped Task (`"state": "TASK_STATE_COMPLETED"`, no `kind`).
