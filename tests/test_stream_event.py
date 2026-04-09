"""StreamEvent dual format: v0.3 kind-tag vs v1.0 wrapper."""

from __future__ import annotations

from a2a_pydantic import (
    StreamEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)


class TestStreamEventV03Input:
    def test_status_update(self):
        evt = StreamEvent.model_validate(
            {
                "kind": "status-update",
                "taskId": "abc",
                "contextId": "ctx",
                "status": {"state": "completed"},
                "final": True,
            }
        )
        assert evt.status_update is not None
        assert evt.status_update.task_id == "abc"
        assert evt.status_update.status.state is TaskState.COMPLETED
        assert evt.status_update.final is True

    def test_artifact_update(self):
        evt = StreamEvent.model_validate(
            {
                "kind": "artifact-update",
                "taskId": "abc",
                "contextId": "ctx",
                "artifact": {
                    "artifactId": "a1",
                    "parts": [{"kind": "text", "text": "chunk"}],
                },
            }
        )
        assert evt.artifact_update is not None
        assert evt.artifact_update.artifact.artifact_id == "a1"


class TestStreamEventV10Input:
    def test_wrapper_status(self):
        evt = StreamEvent.model_validate(
            {
                "taskStatusUpdate": {
                    "taskId": "abc",
                    "contextId": "ctx",
                    "status": {"state": "TASK_STATE_COMPLETED"},
                }
            }
        )
        assert evt.status_update is not None
        assert evt.status_update.status.state is TaskState.COMPLETED


class TestStreamEventOutput:
    def _build(self) -> StreamEvent:
        return StreamEvent(
            status_update=TaskStatusUpdateEvent(
                task_id="abc",
                context_id="ctx",
                status=TaskStatus(state=TaskState.COMPLETED),
                final=True,
            )
        )

    def test_v03_dump(self):
        out = self._build().dump(version="0.3")
        assert out["kind"] == "status-update"
        assert out["taskId"] == "abc"
        assert out["status"]["state"] == "completed"
        assert out["final"] is True

    def test_v10_dump(self):
        out = self._build().dump(version="1.0")
        # v1.0 wraps in "taskStatusUpdate" and has no kind / final.
        assert "taskStatusUpdate" in out
        assert out["taskStatusUpdate"]["taskId"] == "abc"
        assert out["taskStatusUpdate"]["status"]["state"] == "TASK_STATE_COMPLETED"
        assert "kind" not in out["taskStatusUpdate"]
        assert "final" not in out["taskStatusUpdate"]


class TestStatusUpdateOnly:
    def test_v10_dropped_final(self):
        e = TaskStatusUpdateEvent(
            task_id="t",
            context_id="c",
            status=TaskStatus(state=TaskState.WORKING),
            final=False,
        )
        out = e.dump(version="1.0")
        assert "final" not in out
