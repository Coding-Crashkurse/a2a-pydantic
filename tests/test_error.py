"""A2AError dual JSON-RPC v0.3 / google.rpc.Status v1.0."""

from __future__ import annotations

from a2a_pydantic import A2AError, ErrorInfo


class TestA2AErrorInput:
    def test_v10_wrapped_form(self):
        err = A2AError.model_validate(
            {
                "error": {
                    "code": 404,
                    "status": "NOT_FOUND",
                    "message": "Task not found",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                            "reason": "TASK_NOT_FOUND",
                            "domain": "a2a-protocol.org",
                        }
                    ],
                }
            }
        )
        assert err.code == 404
        assert err.status == "NOT_FOUND"
        assert err.message == "Task not found"
        assert err.details[0].reason == "TASK_NOT_FOUND"

    def test_v03_jsonrpc_form(self):
        err = A2AError.model_validate({"code": -32001, "message": "Task not found"})
        assert err.code == -32001
        assert err.message == "Task not found"
        assert err.status is None


class TestA2AErrorOutput:
    def test_v03_dump_jsonrpc_form(self):
        err = A2AError(code=-32001, message="Task not found")
        out = err.dump(version="0.3")
        assert out == {"code": -32001, "message": "Task not found"}

    def test_v10_dump_wraps_in_error(self):
        err = A2AError(
            code=404,
            message="Task not found",
            status="NOT_FOUND",
            details=[
                ErrorInfo(
                    type_="type.googleapis.com/google.rpc.ErrorInfo",
                    reason="TASK_NOT_FOUND",
                    domain="a2a-protocol.org",
                )
            ],
        )
        out = err.dump(version="1.0")
        assert "error" in out
        assert out["error"]["code"] == 404
        assert out["error"]["status"] == "NOT_FOUND"
        assert out["error"]["details"][0]["@type"] == (
            "type.googleapis.com/google.rpc.ErrorInfo"
        )
        assert out["error"]["details"][0]["reason"] == "TASK_NOT_FOUND"
