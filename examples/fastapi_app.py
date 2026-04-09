"""FastAPI app exposing ``message/send`` for both A2A v0.3 and v1.0.

The same ``MessageSendParams`` model handles both wire formats. The endpoint:

1. Accepts the request body as a raw dict and validates it through
   ``MessageSendParams.model_validate`` (dual-accept does the heavy lifting).
2. Decides which version the *client* spoke by sniffing for v0.3 markers
   (top-level ``kind: "message"`` on the message, or v0.3 enum strings).
3. Echoes the message back inside a freshly built completed Task, dumped
   in the same version the client used.

Run::

    uv pip install fastapi uvicorn
    uv run --extra dev uvicorn examples.fastapi_app:app --reload

Try it::

    # v0.3 client
    curl -X POST http://localhost:8000/message:send \\
        -H "Content-Type: application/json" \\
        -d '{
          "message": {
            "kind": "message",
            "messageId": "m1",
            "role": "user",
            "parts": [{"kind": "text", "text": "Hi from a v0.3 client"}]
          }
        }'

    # v1.0 client
    curl -X POST http://localhost:8000/message:send \\
        -H "Content-Type: application/json" \\
        -d '{
          "message": {
            "messageId": "m1",
            "role": "ROLE_USER",
            "parts": [{"text": "Hi from a v1.0 client"}]
          }
        }'

Both responses contain the same Task object — but in the wire format the
caller used.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import Body, FastAPI

from a2a_pydantic import (
    Artifact,
    Message,
    MessageSendParams,
    Part,
    Role,
    Task,
    TaskState,
    TaskStatus,
    Version,
)

app = FastAPI(title="a2a-pydantic FastAPI demo", version="0.1.0")


def detect_wire_version(payload: dict[str, Any]) -> Version:
    """Look at a raw request body and decide if the client spoke v0.3 or v1.0.

    Heuristics, in order:

    - A top-level ``kind: "message"`` on ``message`` is v0.3-only.
    - A v0.3-style ``role: "user" | "agent"`` (lower-case, no ``ROLE_`` prefix).
    - A v0.3 ``parts[*].kind`` discriminator anywhere in the message.

    Default is v1.0 if no v0.3 markers are present.
    """
    msg = payload.get("message")
    if not isinstance(msg, dict):
        return "1.0"
    if msg.get("kind") == "message":
        return "0.3"
    role = msg.get("role")
    if isinstance(role, str) and role in ("user", "agent"):
        return "0.3"
    parts = msg.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if isinstance(part, dict) and "kind" in part:
                return "0.3"
    return "1.0"


def build_completed_task(request_message: Message) -> Task:
    """Pretend the agent did some work and finished the task."""
    echo_text = (
        f"Echo from a2a-pydantic. Your message had "
        f"{len(request_message.parts)} part(s)."
    )
    echo_data = {
        "received_message_id": request_message.message_id,
        "received_part_count": len(request_message.parts),
    }
    return Task(
        id=f"task-{uuid.uuid4().hex[:12]}",
        context_id=request_message.context_id or f"ctx-{uuid.uuid4().hex[:12]}",
        status=TaskStatus(
            state=TaskState.COMPLETED,
            timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            message=Message(
                message_id=f"msg-{uuid.uuid4().hex[:12]}",
                role=Role.AGENT,
                context_id=request_message.context_id,
                parts=[Part(text=echo_text)],
            ),
        ),
        artifacts=[
            Artifact(
                artifact_id="echo",
                name="echo",
                parts=[Part(data=echo_data)],
            )
        ],
        history=[request_message],
    )


@app.post("/message:send")
async def message_send(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """v1.0 endpoint path; also handles v0.3 payloads transparently."""
    version = detect_wire_version(payload)
    params = MessageSendParams.model_validate(payload)
    task = build_completed_task(params.message)
    return task.dump(version=version)


@app.post("/v1/message:send")
async def message_send_v03(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """v0.3 endpoint path. Forces v0.3 output regardless of client format."""
    params = MessageSendParams.model_validate(payload)
    task = build_completed_task(params.message)
    return task.dump(version="0.3")


@app.get("/")
async def index() -> dict[str, Any]:
    return {
        "name": "a2a-pydantic FastAPI demo",
        "endpoints": {
            "POST /message:send": "v1.0-style URL, auto-detects request version",
            "POST /v1/message:send": "v0.3-style URL, always responds in v0.3",
        },
    }
