"""Realistic round-trip example: building a Task and serialising it for both
A2A wire formats.

Run::

    uv run --extra dev examples/round_trip.py

The script builds a multi-part user message, the agent's intermediate
"working" status, the final completed status with two artifacts, and prints
the same Task in v1.0 and v0.3 wire formats side by side.
"""

from __future__ import annotations

import json

from a2a_pydantic import (
    Artifact,
    Message,
    MessageSendParams,
    Part,
    Role,
    Task,
    TaskState,
    TaskStatus,
)


def build_user_request() -> MessageSendParams:
    return MessageSendParams(
        message=Message(
            message_id="msg-9d4b3c12",
            context_id="ctx-trip-planner-2026-04",
            role=Role.USER,
            parts=[
                Part(
                    text="Plan a 5-day trip to Lisbon for two adults in late May. "
                    "Budget around 2,500 EUR total. We like food markets and "
                    "modern art."
                ),
                Part(
                    data={
                        "preferences": {
                            "dietary": ["pescatarian"],
                            "mobility": "walking_ok",
                            "languages": ["en", "de"],
                        },
                        "must_see": ["MAAT", "Time Out Market"],
                    }
                ),
                Part(
                    url="https://files.example.com/itinerary-template.pdf",
                    media_type="application/pdf",
                    filename="itinerary-template.pdf",
                ),
            ],
        )
    )


def build_completed_task() -> Task:
    return Task(
        id="task-7e1b9f20",
        context_id="ctx-trip-planner-2026-04",
        status=TaskStatus(
            state=TaskState.COMPLETED,
            timestamp="2026-04-09T14:32:18Z",
            message=Message(
                message_id="msg-agent-final",
                context_id="ctx-trip-planner-2026-04",
                role=Role.AGENT,
                parts=[
                    Part(
                        text="Done! I built a 5-day Lisbon itinerary that comes "
                        "in at 2,380 EUR. See the attached PDF and the "
                        "structured day-by-day plan."
                    )
                ],
            ),
        ),
        artifacts=[
            Artifact(
                artifact_id="lisbon-itinerary.pdf",
                name="Lisbon itinerary",
                description="5-day plan with bookings, walking routes, and budget breakdown.",
                parts=[
                    Part(
                        url="https://files.example.com/out/lisbon-itinerary.pdf",
                        media_type="application/pdf",
                        filename="lisbon-itinerary.pdf",
                    )
                ],
            ),
            Artifact(
                artifact_id="lisbon-itinerary.json",
                name="Structured plan",
                parts=[
                    Part(
                        data={
                            "total_eur": 2380,
                            "days": [
                                {
                                    "day": 1,
                                    "neighbourhood": "Alfama",
                                    "highlights": [
                                        "Castelo de S. Jorge",
                                        "Fado dinner",
                                    ],
                                },
                                {
                                    "day": 2,
                                    "neighbourhood": "Belém",
                                    "highlights": [
                                        "MAAT",
                                        "Pastéis de Belém",
                                    ],
                                },
                            ],
                        }
                    )
                ],
            ),
        ],
        history=[
            Message(
                message_id="msg-9d4b3c12",
                context_id="ctx-trip-planner-2026-04",
                role=Role.USER,
                parts=[Part(text="Plan a 5-day trip to Lisbon for two adults...")],
            ),
            Message(
                message_id="msg-agent-thinking",
                context_id="ctx-trip-planner-2026-04",
                role=Role.AGENT,
                parts=[
                    Part(
                        text="Looking at your dates, MAAT will be open every day "
                        "except Tuesday. Drafting now."
                    )
                ],
            ),
        ],
    )


def section(title: str) -> None:
    bar = "-" * 72
    print(f"\n{bar}\n{title}\n{bar}")


def main() -> None:
    request = build_user_request()
    task = build_completed_task()

    section("USER REQUEST  ->v1.0 wire")
    print(json.dumps(request.dump(version="1.0"), indent=2))

    section("USER REQUEST  ->v0.3 wire")
    print(json.dumps(request.dump(version="0.3"), indent=2))

    section("COMPLETED TASK  ->v1.0 wire")
    print(json.dumps(task.dump(version="1.0"), indent=2))

    section("COMPLETED TASK  ->v0.3 wire")
    print(json.dumps(task.dump(version="0.3"), indent=2))

    section("ROUND-TRIP CHECK")
    v03 = task.dump(version="0.3")
    v10 = task.dump(version="1.0")
    rebuilt_from_v03 = Task.model_validate(v03)
    rebuilt_from_v10 = Task.model_validate(v10)
    assert rebuilt_from_v03.dump(version="1.0") == v10
    assert rebuilt_from_v10.dump(version="0.3") == v03
    print("v0.3 -> model -> v1.0 matches direct v1.0 dump  OK")
    print("v1.0 -> model -> v0.3 matches direct v0.3 dump  OK")


if __name__ == "__main__":
    main()
