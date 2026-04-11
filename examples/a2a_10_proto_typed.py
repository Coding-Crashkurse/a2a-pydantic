"""Typed twin of examples/a2a_10_proto.py — same agent, full static typing.

The companion file ``a2a_10_proto.py`` shows the SDK-native way: import
``AgentCard``, ``AgentSkill``, ``Part`` etc. directly from ``a2a.types``
(protobuf classes) and hand them to the request handler. That works,
but every field you touch is unchecked — no IDE autocomplete, no type
errors, no validation, typos silently dropped by pb2.

This version builds the same agent using **a2a-pydantic v1.0 Pydantic
models** for everything we construct ourselves and only bridges to pb2
at the SDK boundary via ``convert_to_proto``. The ``a2a-sdk`` side
(request handler, task store, REST route factories) is unchanged — we
only swap the type-unsafe construction calls.

Compared to the reference sample this version drops the JSON-RPC and
gRPC transports — only HTTP+JSON REST is exposed, because the point of
the demo is "typed v10 models on the way in, pb2 at the SDK boundary",
not transport coverage. Adding JSON-RPC or gRPC back is a matter of
mounting the respective routes / starting a ``grpc.aio.server`` — the
typed construction patterns carry over unchanged.

What you gain:

* autocomplete for every field on ``AgentCard``, ``AgentSkill``,
  ``AgentInterface``, ``Part``, ``Message``, ``AgentCapabilities``, ...
* ``pyright`` / ``mypy`` catches typos and missing-required-field errors
  before runtime
* Pydantic validates values at construction time (wrong enum value →
  ``ValidationError`` immediately, not a silent pb2 default)
* ``convert_to_proto`` is ``@overload``-typed, so the result of
  ``convert_to_proto(v10.AgentCard)`` is inferred as ``pb2.AgentCard``

What stays the same:

* The ``AgentExecutor`` subclass structure, ``TaskUpdater`` usage, and
  REST route wiring all come from ``a2a-sdk`` as-is
* The agent's behavior is byte-identical to the reference — same
  greeting logic, same artifact shape, same lifecycle events

Install & run (from the repo root, with the venv active)::

    uv pip install -e ".[example]"
    python examples/a2a_10_proto_typed.py

Requires ``a2a-sdk>=1.0.0a1`` (earlier alphas used a different API
surface that no longer exists).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

import uvicorn
from fastapi import FastAPI

from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_rest_routes
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.server.tasks.task_updater import TaskUpdater

from a2a_pydantic import convert_to_proto, v10

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
                url=f"http://{host}:{port}/a2a/rest",
            ),
            v10.AgentInterface(
                protocol_binding="HTTP+JSON",
                protocol_version="0.3",
                url=f"http://{host}:{port}/a2a/rest",
            ),
        ],
    )


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

    rest_routes = create_rest_routes(
        request_handler=request_handler,
        path_prefix="/a2a/rest",
        enable_v0_3_compat=True,
    )
    agent_card_routes = create_agent_card_routes(agent_card=pb_card)

    app = FastAPI(title="Sample Agent (typed, REST only)")
    app.routes.extend(agent_card_routes)
    app.routes.extend(rest_routes)

    config = uvicorn.Config(app, host=host, port=port)
    uvicorn_server = uvicorn.Server(config)

    logger.info("Starting typed Sample Agent on http://%s:%s", host, port)
    logger.info(
        "Agent Card available at http://%s:%s/.well-known/agent-card.json",
        host,
        port,
    )

    await uvicorn_server.serve()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(serve())
