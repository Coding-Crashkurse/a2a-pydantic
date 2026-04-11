"""FastAPI example: serve MessageSendParams in both A2A versions.

Run with::

    uv pip install fastapi uvicorn
    PYTHONPATH=src uvicorn examples.fastapi_version_header:app --reload

Send a v1.0 SendMessageRequest body. Use the ``A2A-Version`` header to pick
the response format:

* ``A2A-Version: 1.0`` (default) -> echoes the v1.0 SendMessageRequest
* ``A2A-Version: 0.3``           -> converts to v0.3 MessageSendParams via
  :mod:`a2apydantic.converters` and returns that instead

The whole negotiation + conversion is wrapped in a FastAPI dependency
(``negotiate_send_message``), so the route handler itself is a one-liner
that just serializes the already-negotiated payload. Any other endpoint
that wants the same v1.0<->v0.3 downgrade behavior can reuse the same
dependency by ``Depends``-ing on it.

Conversion warnings are:

1. logged via the ``uvicorn.error`` logger so they show up alongside the
   INFO access log in the terminal, and
2. included in the response body under ``conversion_warnings`` for
   programmatic consumers.

Example request body::

    {
      "message": {
        "messageId": "m-1",
        "role": "ROLE_USER",
        "parts": [{"text": "hello"}]
      },
      "tenant": "acme"
    }
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException

from a2apydantic import convert_to_v03, v03, v10

logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="a2apydantic version-header demo")

SUPPORTED_VERSIONS = frozenset({"0.3", "1.0"})


@dataclass
class NegotiatedSendMessage:
    """Outcome of :func:`negotiate_send_message`.

    ``version`` is the wire version the client asked for, ``payload`` is
    the already-correctly-shaped model (v1.0 ``SendMessageRequest`` or
    v0.3 ``MessageSendParams``), and ``conversion_warnings`` lists any
    fields that could not be represented in the chosen version.
    """

    version: str
    payload: v10.SendMessageRequest | v03.MessageSendParams
    conversion_warnings: list[str] = field(default_factory=list)


def _require_supported_version(header_value: str | None) -> str:
    version = (header_value or "1.0").strip()
    if version not in SUPPORTED_VERSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported A2A-Version {version!r}. "
                f"Supported: {sorted(SUPPORTED_VERSIONS)}"
            ),
        )
    return version


def negotiate_send_message(
    request: v10.SendMessageRequest,
    a2a_version: Annotated[str | None, Header(alias="A2A-Version")] = None,
) -> NegotiatedSendMessage:
    """FastAPI dependency that turns a v1.0 request + header into a versioned payload.

    The server's canonical representation is v1.0. If the client asks for
    v0.3 via the ``A2A-Version`` header, this dependency runs the
    downward converter, captures every ``UserWarning`` it emits, logs
    them, and hands the route a ready-to-serialize
    ``NegotiatedSendMessage``.
    """
    version = _require_supported_version(a2a_version)

    if version == "1.0":
        return NegotiatedSendMessage(version=version, payload=request)

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        converted: v03.MessageSendParams = convert_to_v03(request)

    warning_messages = [str(w.message) for w in captured]
    for msg in warning_messages:
        logger.warning("a2a v1.0->v0.3 conversion: %s", msg)

    logger.info(
        "a2a v1.0->v0.3 converted to %s:\n%s",
        type(converted).__name__,
        converted.model_dump_json(by_alias=True, exclude_none=True, indent=2),
    )

    return NegotiatedSendMessage(
        version="0.3",
        payload=converted,
        conversion_warnings=warning_messages,
    )


@app.post("/message:send")
def message_send(
    negotiated: Annotated[NegotiatedSendMessage, Depends(negotiate_send_message)],
) -> dict[str, Any]:
    return {
        "version": negotiated.version,
        "payload": negotiated.payload.model_dump(by_alias=True, exclude_none=True),
        "conversion_warnings": negotiated.conversion_warnings,
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "supported_versions": sorted(SUPPORTED_VERSIONS)}
