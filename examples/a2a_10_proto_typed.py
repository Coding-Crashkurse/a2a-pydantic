"""Typed twin of examples/a2a_10_proto.py — typed FastAPI facade.

The companion file ``a2a_10_proto.py`` shows the SDK-native way: import
``AgentCard``, ``AgentSkill``, ``Part`` etc. directly from ``a2a.types``
(protobuf classes) and hand them to the request handler. That works,
but every field you touch is unchecked — no IDE autocomplete, no type
errors, no validation, typos silently dropped by pb2. On top of that,
the SDK's own routes are plain ``starlette.routing.Route`` instances,
so FastAPI's OpenAPI generator cannot see them and ``/docs`` shows
"No operations defined in spec".

This file fixes both problems with a typed FastAPI facade in front of
``DefaultRequestHandler``:

* Every construction call that used pb2 directly now uses
  ``a2a_pydantic.v10`` Pydantic models (autocomplete, type checking,
  Pydantic validation at construction time).
* Every HTTP endpoint is a real ``@app.post`` / ``@app.get`` decorator
  with typed request and response models, so they show up in
  ``/docs`` with full schema, request validation, and response
  serialization via Pydantic.
* At the SDK boundary we flip to pb2 via :func:`convert_to_proto`,
  call ``DefaultRequestHandler.on_message_send`` / ``on_get_task`` /
  ``on_cancel_task``, and flip back to v10 via
  :func:`convert_from_proto`.

The result: typed-in, typed-out, with the SDK doing all the actual
work underneath. The SDK's own framework-agnostic ``create_rest_routes``
is intentionally NOT used here — we re-expose the subset of endpoints
we care about as first-class FastAPI routes so ``/docs`` works.

Install & run (from the repo root, with the venv active)::

    uv pip install -e ".[example]"
    python examples/a2a_10_proto_typed.py

Then open http://127.0.0.1:8000/docs and try the endpoints from
Swagger UI. Compare with ``a2a_10_proto.py`` on the same port (after
stopping this one) to see the empty-Swagger SDK-native version.

Requires ``a2a-sdk>=1.0.0a1``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

import uvicorn
from fastapi import Depends, FastAPI, HTTPException

from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.context import ServerCallContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types import a2a_pb2

from a2a_pydantic import convert_from_proto, convert_to_proto, v10

logger = logging.getLogger(__name__)


class SampleAgentExecutor(AgentExecutor):
    """Typed sample executor — constructs all outgoing parts as v10.Part."""

    def __init__(self) -> None:
        self.running_tasks: set[str] = set()

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        task_id = context.task_id
        if task_id and task_id in self.running_tasks:
            self.running_tasks.remove(task_id)

        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=task_id or "",
            context_id=context.context_id or "",
        )
        await updater.cancel()

    async def execute(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        user_message = context.message
        task_id = context.task_id
        context_id = context.context_id

        if not user_message or not task_id or not context_id:
            return

        self.running_tasks.add(task_id)

        logger.info(
            "[SampleAgentExecutor] Processing message %s for task %s (context: %s)",
            user_message.message_id,
            task_id,
            context_id,
        )

        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=task_id,
            context_id=context_id,
        )

        working_part = v10.Part(text="Processing your question...")
        working_message = updater.new_agent_message(
            parts=[convert_to_proto(working_part)],
        )
        await updater.start_work(message=working_message)

        query = context.get_user_input()
        agent_reply_text = self._parse_input(query)
        await asyncio.sleep(1)

        if task_id not in self.running_tasks:
            return

        reply_part = v10.Part(text=agent_reply_text)
        await updater.add_artifact(
            parts=[convert_to_proto(reply_part)],
            name="response",
            last_chunk=True,
        )
        await updater.complete()

        logger.info(
            "[SampleAgentExecutor] Task %s finished with state: completed",
            task_id,
        )

    def _parse_input(self, query: str) -> str:
        if not query:
            return "Hello! Please provide a message for me to respond to."
        ql = query.lower()
        if "hello" in ql or "hi" in ql:
            return "Hello World! Nice to meet you!"
        if "how are you" in ql:
            return "I'm doing great! Thanks for asking. How can I help you today?"
        if "goodbye" in ql or "bye" in ql:
            return "Goodbye! Have a wonderful day!"
        return f"Hello World! You said: '{query}'. Thanks for your message!"


def build_typed_agent_card(host: str, port: int) -> v10.AgentCard:
    """Build the agent card as a fully typed ``v10.AgentCard``.

    Every constructor argument here is statically checked by pyright /
    mypy, autocompleted in the editor, and validated by Pydantic at
    construction time. Compare with the equivalent pb2-based
    construction in ``a2a_10_proto.py`` where you get none of that.
    """
    return v10.AgentCard(
        name="Sample Agent",
        description="A sample agent to test the stream functionality.",
        provider=v10.AgentProvider(
            organization="A2A Samples",
            url="https://example.com",
        ),
        version="1.0.0",
        capabilities=v10.AgentCapabilities(
            streaming=True,
            push_notifications=False,
        ),
        default_input_modes=["text"],
        default_output_modes=["text", "task-status"],
        skills=[
            v10.AgentSkill(
                id="sample_agent",
                name="Sample Agent",
                description="Say hi.",
                tags=["sample"],
                examples=["hi"],
                input_modes=["text"],
                output_modes=["text", "task-status"],
            ),
        ],
        supported_interfaces=[
            v10.AgentInterface(
                protocol_binding="HTTP+JSON",
                protocol_version="1.0",
                url=f"http://{host}:{port}/a2a",
            ),
        ],
    )


def build_app(
    agent_card: v10.AgentCard,
    request_handler: DefaultRequestHandler,
) -> FastAPI:
    """Wire the typed facade endpoints on top of ``DefaultRequestHandler``.

    Every endpoint:

    1. accepts a typed ``v10.*`` request body (FastAPI validates via Pydantic
       before our code runs),
    2. bridges to pb2 via :func:`convert_to_proto`,
    3. calls the matching ``on_*`` method on the SDK request handler,
    4. bridges the pb2 result back to a typed ``v10.*`` via
       :func:`convert_from_proto`,
    5. returns the typed model — FastAPI re-serializes it via Pydantic.

    The ``response_model=`` kwarg on each route is what makes Swagger /
    ``/docs`` show the full request + response schema.
    """
    app = FastAPI(
        title="Sample Agent (typed facade)",
        description=(
            "A2A v1.0 sample agent with typed Pydantic request and response "
            "bodies, backed by a2a-sdk's DefaultRequestHandler underneath."
        ),
        version="1.0.0",
    )

    def get_handler() -> DefaultRequestHandler:
        return request_handler

    def get_call_context() -> ServerCallContext:
        return ServerCallContext()

    @app.get(
        "/.well-known/agent-card.json",
        response_model=v10.AgentCard,
        summary="Get the agent's public card",
    )
    def get_agent_card() -> v10.AgentCard:
        return agent_card

    @app.post(
        "/a2a/message:send",
        response_model=v10.SendMessageResponse,
        summary="Send a message to the agent",
    )
    async def send_message(
        request: v10.SendMessageRequest,
        handler: DefaultRequestHandler = Depends(get_handler),
        ctx: ServerCallContext = Depends(get_call_context),
    ) -> v10.SendMessageResponse:
        pb_req = convert_to_proto(request)
        result = await handler.on_message_send(pb_req, ctx)
        if isinstance(result, a2a_pb2.Task):
            return v10.SendMessageResponse(task=convert_from_proto(result))
        if isinstance(result, a2a_pb2.Message):
            return v10.SendMessageResponse(message=convert_from_proto(result))
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected on_message_send result type: {type(result).__name__}",
        )

    @app.get(
        "/a2a/tasks/{task_id}",
        response_model=v10.Task,
        summary="Get a task by id",
        responses={404: {"description": "Task not found"}},
    )
    async def get_task(
        task_id: str,
        history_length: int | None = None,
        handler: DefaultRequestHandler = Depends(get_handler),
        ctx: ServerCallContext = Depends(get_call_context),
    ) -> v10.Task:
        typed_req = v10.GetTaskRequest(id=task_id, history_length=history_length)
        pb_req = convert_to_proto(typed_req)
        result = await handler.on_get_task(pb_req, ctx)
        if result is None:
            raise HTTPException(status_code=404, detail=f"Task {task_id!r} not found")
        return convert_from_proto(result)

    @app.post(
        "/a2a/tasks/{task_id}:cancel",
        response_model=v10.Task,
        summary="Cancel a task",
        responses={404: {"description": "Task not found"}},
    )
    async def cancel_task(
        task_id: str,
        handler: DefaultRequestHandler = Depends(get_handler),
        ctx: ServerCallContext = Depends(get_call_context),
    ) -> v10.Task:
        typed_req = v10.CancelTaskRequest(id=task_id)
        pb_req = convert_to_proto(typed_req)
        result = await handler.on_cancel_task(pb_req, ctx)
        if result is None:
            raise HTTPException(status_code=404, detail=f"Task {task_id!r} not found")
        return convert_from_proto(result)

    return app


async def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the typed Sample Agent on HTTP+JSON REST only."""
    typed_card = build_typed_agent_card(host, port)
    pb_card = convert_to_proto(typed_card)

    task_store = InMemoryTaskStore()
    request_handler = DefaultRequestHandler(
        agent_executor=SampleAgentExecutor(),
        task_store=task_store,
        agent_card=pb_card,
    )

    app = build_app(typed_card, request_handler)

    config = uvicorn.Config(app, host=host, port=port)
    uvicorn_server = uvicorn.Server(config)

    logger.info("Starting typed Sample Agent on http://%s:%s", host, port)
    logger.info(
        "OpenAPI / Swagger UI at http://%s:%s/docs",
        host,
        port,
    )

    await uvicorn_server.serve()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(serve())
