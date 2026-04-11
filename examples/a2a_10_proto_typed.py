"""Typed mirror of examples/a2a_10_proto.py.

The reference example (a2a_10_proto.py) builds its ``AgentCard``,
``AgentSkill``, ``AgentInterface``, ``Part`` and friends directly from
``a2a.types`` — which are protobuf classes. Those classes give you zero
IDE autocomplete, zero static type checking, and will happily accept a
typo'd field name at runtime and silently drop it.

This version builds exactly the same agent, exactly the same way, but
uses **a2a-pydantic v1.0 Pydantic models** for everything we construct
ourselves and only bridges to pb2 at the SDK boundary via
``convert_to_proto``. The ``a2a-sdk`` side (request handler, task store,
FastAPI app wiring) is unchanged — we only swap the type-unsafe
construction calls.

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
  the JSON-RPC / REST route wiring all come from ``a2a-sdk`` as-is
* The agent's behavior is byte-identical — same greeting logic, same
  artifact shape, same lifecycle events

Install & run (from the repo root, with the venv active)::

    uv pip install -e ".[example]"
    python examples/a2a_10_proto_typed.py

The ``[example]`` extra pulls in ``a2a-sdk[http-server]``, ``fastapi``,
``uvicorn`` and ``sse-starlette``. The core package stays minimal —
``pip install a2a-pydantic`` alone only depends on ``pydantic``.

Then send a JSON-RPC ``message/send`` to
``http://127.0.0.1:41241/a2a/jsonrpc``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

import uvicorn
from fastapi import FastAPI

from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.apps.jsonrpc import A2AFastAPIApplication
from a2a.server.apps.rest import A2ARESTFastAPIApplication
from a2a.server.events.event_queue import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
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


def build_typed_agent_card(
    host: str, port: int
) -> v10.AgentCard:
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
                protocol_binding="JSONRPC",
                protocol_version="1.0",
                url=f"http://{host}:{port}/a2a/jsonrpc",
            ),
            v10.AgentInterface(
                protocol_binding="JSONRPC",
                protocol_version="0.3",
                url=f"http://{host}:{port}/a2a/jsonrpc",
            ),
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


async def serve(
    host: str = "127.0.0.1",
    port: int = 41241,
) -> None:
    """Run the typed Sample Agent server on JSON-RPC + REST."""
    typed_card = build_typed_agent_card(host, port)
    pb_card = convert_to_proto(typed_card)

    task_store = InMemoryTaskStore()
    request_handler = DefaultRequestHandler(
        agent_executor=SampleAgentExecutor(),
        task_store=task_store,
    )

    app = FastAPI(title="Sample Agent (typed)")

    jsonrpc_app = A2AFastAPIApplication(
        agent_card=pb_card,
        http_handler=request_handler,
        enable_v0_3_compat=True,
    )
    jsonrpc_app.add_routes_to_app(app, rpc_url="/a2a/jsonrpc")

    rest_app = A2ARESTFastAPIApplication(
        agent_card=pb_card,
        http_handler=request_handler,
        enable_v0_3_compat=True,
    )
    rest_fastapi = rest_app.build(rpc_url="/a2a/rest")
    for route in rest_fastapi.routes:
        app.routes.append(route)

    config = uvicorn.Config(app, host=host, port=port)
    uvicorn_server = uvicorn.Server(config)

    logger.info("Starting Sample Agent (typed) on http://%s:%s", host, port)
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
