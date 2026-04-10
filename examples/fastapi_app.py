"""FastAPI app exposing ``message/send`` for both A2A v0.3 and v1.0.

The endpoints take ``MessageSendParams`` directly as a typed parameter —
FastAPI runs our ``model_validator(mode="before")`` automatically, so a
v0.3 OR v1.0 request body validates without any manual ``model_validate``
call. The handler echoes the message back as a completed ``Task``, dumped
in the wire version that matches the URL the client hit.

Why ``JSONResponse`` instead of ``-> Task``? FastAPI auto-serialises typed
return values via ``jsonable_encoder``, which calls ``model_dump()`` with
no context — and our strict version resolution then raises
``A2AVersionError``. Returning a ``Response`` instance bypasses
``jsonable_encoder`` entirely, so we control the version explicitly via
``task.dump(version=...)``.

Run::

    uv pip install fastapi uvicorn
    uv run --extra dev uvicorn examples.fastapi_app:app --reload

Try it::

    # v1.0 endpoint, v1.0 client
    curl -X POST http://localhost:8000/message:send \\
        -H "Content-Type: application/json" \\
        -d '{
          "message": {
            "messageId": "m1",
            "role": "ROLE_USER",
            "parts": [{"text": "Hi from a v1.0 client"}]
          }
        }'

    # v0.3 endpoint, v0.3 client (note the /v1 prefix is the v0.3-era URL)
    curl -X POST http://localhost:8000/v1/message:send \\
        -H "Content-Type: application/json" \\
        -d '{
          "message": {
            "kind": "message",
            "messageId": "m1",
            "role": "user",
            "parts": [{"kind": "text", "text": "Hi from a v0.3 client"}]
          }
        }'

Either endpoint also accepts the *other* version's input shape — the
response is always in the version the URL declares.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from a2a_pydantic import (
    A2ARequest,
    Artifact,
    CancelTaskRequest,
    CancelTaskSuccessResponse,
    GetTaskRequest,
    GetTaskSuccessResponse,
    JSONRPCErrorResponse,
    Message,
    MessageSendParams,
    MethodNotFoundError,
    Part,
    Role,
    SendMessageRequest,
    SendMessageSuccessResponse,
    Task,
    TaskNotFoundError,
    TaskState,
    TaskStatus,
)

app = FastAPI(title="a2a-pydantic FastAPI demo", version="0.1.0")


def build_completed_task(request_message: Message) -> Task:
    """Pretend the agent did some work and finished the task."""
    echo_text = (
        "Echo from a2a-pydantic. Your message had "
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
async def message_send_v10(params: MessageSendParams) -> JSONResponse:
    """v1.0 endpoint. Accepts either wire shape, always responds in v1.0.

    Returning a ``JSONResponse`` directly bypasses FastAPI's
    ``jsonable_encoder``, which would otherwise call ``model_dump()`` with
    no context and trip the strict-mode ``A2AVersionError``. We always go
    through our ``Task.dump(version=...)`` to keep version control explicit.
    """
    task = build_completed_task(params.message)
    return JSONResponse(task.dump(version="1.0"))


@app.post("/v1/message:send")
async def message_send_v03(params: MessageSendParams) -> JSONResponse:
    """v0.3 endpoint. Accepts either wire shape, always responds in v0.3."""
    task = build_completed_task(params.message)
    return JSONResponse(task.dump(version="0.3"))


_TASK_STORE: dict[str, Task] = {}


@app.post("/")
async def jsonrpc(request: A2ARequest) -> JSONResponse:
    """Single JSON-RPC v0.3 endpoint that dispatches by ``method``.

    FastAPI validates the body against the :class:`A2ARequest` discriminated
    union, so by the time we ``match`` on ``request.root`` we already know
    each variant has the correct ``params`` type — no manual parsing.
    """
    rpc_id = request.root.id
    match request.root:
        case SendMessageRequest():
            task = build_completed_task(request.root.params.message)
            _TASK_STORE[task.id] = task
            response = SendMessageSuccessResponse(id=rpc_id, result=task)
        case GetTaskRequest():
            task = _TASK_STORE.get(request.root.params.id)
            if task is None:
                error = JSONRPCErrorResponse(
                    id=rpc_id,
                    error=TaskNotFoundError(
                        data={"taskId": request.root.params.id}
                    ),
                )
                return JSONResponse(error.dump(version="0.3"))
            response = GetTaskSuccessResponse(id=rpc_id, result=task)
        case CancelTaskRequest():
            task = _TASK_STORE.get(request.root.params.id)
            if task is None:
                error = JSONRPCErrorResponse(
                    id=rpc_id,
                    error=TaskNotFoundError(
                        data={"taskId": request.root.params.id}
                    ),
                )
                return JSONResponse(error.dump(version="0.3"))
            response = CancelTaskSuccessResponse(id=rpc_id, result=task)
        case _:
            error = JSONRPCErrorResponse(id=rpc_id, error=MethodNotFoundError())
            return JSONResponse(error.dump(version="0.3"))
    return JSONResponse(response.dump(version="0.3"))


@app.get("/")
async def index() -> dict[str, Any]:
    return {
        "name": "a2a-pydantic FastAPI demo",
        "endpoints": {
            "POST /": "v0.3 JSON-RPC endpoint (dispatches by method)",
            "POST /message:send": "v1.0 endpoint (responds in v1.0)",
            "POST /v1/message:send": "v0.3 endpoint (responds in v0.3)",
        },
    }
