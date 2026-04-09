"""Message, TaskStatus, Task, Artifact round-trips."""

from __future__ import annotations

from a2a_pydantic import (
    Message,
    Part,
    Role,
    Task,
    TaskState,
    TaskStatus,
)


class TestMessage:
    def test_construct(self):
        msg = Message(
            role=Role.USER,
            parts=[Part(text="hello")],
            message_id="msg-001",
            context_id="ctx-001",
        )
        assert msg.role is Role.USER

    def test_v10_dump(self):
        msg = Message(
            role=Role.USER,
            parts=[Part(text="hello")],
            message_id="msg-001",
        )
        out = msg.dump(version="1.0")
        assert out == {
            "messageId": "msg-001",
            "role": "ROLE_USER",
            "parts": [{"text": "hello"}],
        }

    def test_v03_dump(self):
        msg = Message(
            role=Role.USER,
            parts=[Part(text="hello")],
            message_id="msg-001",
        )
        out = msg.dump(version="0.3")
        assert out == {
            "kind": "message",
            "messageId": "msg-001",
            "role": "user",
            "parts": [{"kind": "text", "text": "hello"}],
        }

    def test_v03_input(self):
        msg = Message.model_validate(
            {
                "kind": "message",
                "messageId": "msg-001",
                "role": "user",
                "parts": [{"kind": "text", "text": "hi"}],
            }
        )
        assert msg.role is Role.USER
        assert msg.parts[0].text == "hi"

    def test_v10_input(self):
        msg = Message.model_validate(
            {
                "messageId": "msg-001",
                "role": "ROLE_USER",
                "parts": [{"text": "hi"}],
            }
        )
        assert msg.role is Role.USER


class TestTaskStatus:
    def test_v10_dump(self):
        status = TaskStatus(state=TaskState.COMPLETED, timestamp="2024-03-15T10:15:00Z")
        assert status.dump(version="1.0") == {
            "state": "TASK_STATE_COMPLETED",
            "timestamp": "2024-03-15T10:15:00Z",
        }

    def test_v03_dump(self):
        status = TaskStatus(state=TaskState.COMPLETED, timestamp="2024-03-15T10:15:00Z")
        assert status.dump(version="0.3") == {
            "state": "completed",
            "timestamp": "2024-03-15T10:15:00Z",
        }

    def test_v03_input(self):
        status = TaskStatus.model_validate(
            {"state": "completed", "timestamp": "2024-03-15T10:15:00Z"}
        )
        assert status.state is TaskState.COMPLETED


class TestTask:
    def test_v03_input_auto_upgrade(self):
        # Vision example: v0.3 response should auto-upgrade.
        task = Task.model_validate(
            {
                "id": "task-001",
                "contextId": "ctx-001",
                "status": {
                    "state": "completed",
                    "timestamp": "2024-03-15T10:15:00Z",
                },
                "artifacts": [
                    {
                        "artifactId": "result",
                        "parts": [{"kind": "text", "text": "Traduit en français"}],
                    }
                ],
            }
        )
        assert task.status.state is TaskState.COMPLETED
        assert task.artifacts[0].parts[0].text == "Traduit en français"

    def test_v10_input(self):
        task = Task.model_validate(
            {
                "id": "task-001",
                "contextId": "ctx-001",
                "status": {
                    "state": "TASK_STATE_COMPLETED",
                    "timestamp": "2024-03-15T10:15:00.000Z",
                },
                "artifacts": [
                    {
                        "artifactId": "result",
                        "parts": [{"text": "Traduit en français"}],
                    }
                ],
            }
        )
        assert task.status.state is TaskState.COMPLETED

    def test_v03_dump_has_kind(self):
        task = Task(
            id="task-001",
            context_id="ctx-001",
            status=TaskStatus(state=TaskState.COMPLETED),
        )
        out = task.dump(version="0.3")
        assert out["kind"] == "task"
        assert out["status"]["state"] == "completed"

    def test_v10_dump_no_kind(self):
        task = Task(
            id="task-001",
            context_id="ctx-001",
            status=TaskStatus(state=TaskState.COMPLETED),
        )
        out = task.dump(version="1.0")
        assert "kind" not in out
        assert out["status"]["state"] == "TASK_STATE_COMPLETED"
