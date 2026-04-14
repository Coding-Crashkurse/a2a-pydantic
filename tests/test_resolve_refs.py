"""Regression tests for scripts/resolve_refs.py.

The upstream A2A JSON Schema ships enums as a proto-flavored three-branch
``anyOf`` (``{pattern: "^X_UNSPECIFIED$"} | {enum: [...other values]} |
{type: "integer"}``) with ``"default": 0`` pointing at the integer
``UNSPECIFIED`` slot. ``simplify_anyof`` collapses that into a plain
string enum, but for a long time it also blindly rewrote ``default: 0``
into ``enum_vals[0]`` — which, after dropping ``UNSPECIFIED`` from the
enum, meant e.g. ``ListTasksRequest.status`` silently defaulted to
``TASK_STATE_SUBMITTED``. These tests lock the fix in so the next schema
refresh does not resurrect the bug.
"""

from __future__ import annotations

from resolve_refs import simplify_anyof


def _upstream_task_state_anyof() -> dict:
    """Recreate the shape ``TaskStatus.state`` has in ``a2a_raw.json``."""
    return {
        "anyOf": [
            {"pattern": "^TASK_STATE_UNSPECIFIED$", "type": "string"},
            {
                "enum": [
                    "TASK_STATE_SUBMITTED",
                    "TASK_STATE_WORKING",
                    "TASK_STATE_COMPLETED",
                ],
                "type": "string",
            },
            {"type": "integer", "minimum": -2147483648, "maximum": 2147483647},
        ],
        "default": 0,
        "description": "The current state of this task.",
        "title": "TaskState",
    }


def test_simplify_anyof_drops_integer_default() -> None:
    obj = _upstream_task_state_anyof()
    simplify_anyof(obj)
    assert obj.get("type") == "string"
    assert obj.get("enum") == [
        "TASK_STATE_SUBMITTED",
        "TASK_STATE_WORKING",
        "TASK_STATE_COMPLETED",
    ]
    assert "default" not in obj, (
        "integer default 0 (proto UNSPECIFIED sentinel) must be dropped, "
        "not rewritten to the first retained enum value"
    )


def test_simplify_anyof_preserves_valid_string_default() -> None:
    obj = _upstream_task_state_anyof()
    obj["default"] = "TASK_STATE_WORKING"
    simplify_anyof(obj)
    assert obj.get("default") == "TASK_STATE_WORKING"


def test_simplify_anyof_drops_unmappable_string_default(
    capsys,
) -> None:
    obj = _upstream_task_state_anyof()
    obj["default"] = "TASK_STATE_UNSPECIFIED"
    simplify_anyof(obj)
    assert "default" not in obj
    captured = capsys.readouterr()
    assert "unmappable enum default" in captured.err
    assert "TASK_STATE_UNSPECIFIED" in captured.err


def test_simplify_anyof_drops_unspecified_pattern() -> None:
    """The ``X_UNSPECIFIED`` pattern branch is intentionally not re-injected."""
    obj = _upstream_task_state_anyof()
    simplify_anyof(obj)
    assert "TASK_STATE_UNSPECIFIED" not in obj["enum"]
