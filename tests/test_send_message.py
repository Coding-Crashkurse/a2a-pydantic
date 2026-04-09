"""MessageSendParams + MessageSendConfiguration full round-trip.

Mirrors the largest example block in the vision document.
"""

from __future__ import annotations

from a2a_pydantic import (
    Message,
    MessageSendConfiguration,
    MessageSendParams,
    Part,
    PushNotificationConfig,
    Role,
)


def _build_params() -> MessageSendParams:
    return MessageSendParams(
        message=Message(
            role=Role.USER,
            parts=[
                Part(text="Translate to French"),
                Part(
                    url="https://example.com/doc.pdf",
                    media_type="application/pdf",
                ),
            ],
            message_id="msg-001",
            context_id="ctx-001",
        )
    )


class TestMessageSendParams:
    def test_v03_dump(self):
        out = _build_params().dump(version="0.3")
        assert out == {
            "message": {
                "kind": "message",
                "role": "user",
                "parts": [
                    {"kind": "text", "text": "Translate to French"},
                    {
                        "kind": "file",
                        "file": {
                            "uri": "https://example.com/doc.pdf",
                            "mimeType": "application/pdf",
                        },
                    },
                ],
                "messageId": "msg-001",
                "contextId": "ctx-001",
            }
        }

    def test_v10_dump(self):
        out = _build_params().dump(version="1.0")
        assert out == {
            "message": {
                "role": "ROLE_USER",
                "parts": [
                    {"text": "Translate to French"},
                    {
                        "url": "https://example.com/doc.pdf",
                        "mediaType": "application/pdf",
                    },
                ],
                "messageId": "msg-001",
                "contextId": "ctx-001",
            }
        }


class TestMessageSendConfiguration:
    def test_v03_blocking_to_v10_return_immediately(self):
        cfg = MessageSendConfiguration.model_validate({"blocking": True})
        # blocking=True means the client wants to wait → return_immediately=False
        assert cfg.return_immediately is False

    def test_v10_return_immediately_to_v03_blocking(self):
        cfg = MessageSendConfiguration(return_immediately=False)
        out = cfg.dump(version="0.3")
        assert out["blocking"] is True
        assert "returnImmediately" not in out

    def test_v10_dump(self):
        cfg = MessageSendConfiguration(return_immediately=True)
        out = cfg.dump(version="1.0")
        assert out == {"returnImmediately": True}

    def test_v03_push_notification_field_name(self):
        push = PushNotificationConfig(url="https://hook.example.com")
        cfg = MessageSendConfiguration(task_push_notification_config=push)
        out_v03 = cfg.dump(version="0.3")
        out_v10 = cfg.dump(version="1.0")
        assert "pushNotificationConfig" in out_v03
        assert "taskPushNotificationConfig" in out_v10


class TestPushNotificationAuth:
    def test_v03_schemes_list_to_v10_scheme_string(self):
        cfg = PushNotificationConfig.model_validate(
            {
                "url": "https://hook.example.com",
                "authentication": {"schemes": ["Bearer"], "credentials": "tok"},
            }
        )
        assert cfg.authentication.scheme == "Bearer"

    def test_v10_scheme_to_v03_schemes(self):
        cfg = PushNotificationConfig(
            url="https://hook.example.com",
            authentication={"scheme": "Bearer", "credentials": "tok"},
        )
        out = cfg.dump(version="0.3")
        assert out["authentication"]["schemes"] == ["Bearer"]
        assert "scheme" not in out["authentication"]
