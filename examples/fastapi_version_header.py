"""FastAPI example: serve MessageSendParams in both A2A versions.

Run with::

    uv pip install fastapi uvicorn
    PYTHONPATH=src uvicorn examples.fastapi_version_header:app --reload

Send a v1.0 SendMessageRequest body. Use the ``A2A-Version`` header to pick
the response format:

* ``A2A-Version: 1.0`` (default) -> echoes the v1.0 SendMessageRequest
* ``A2A-Version: 0.3``           -> converts to v0.3 MessageSendParams via
  :mod:`a2apydantic.converters` and returns that instead

Any field that cannot be represented in v0.3 (``tenant`` on the request,
multi-payload parts, ``pkce_required`` on OAuth flows, ...) triggers a
``UserWarning`` inside the converter. This example captures those warnings
and returns them under ``conversion_warnings`` so clients can see exactly
what was lost.

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

import warnings
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException

from a2apydantic import v03, v10
from a2apydantic.converters import send_message_request

app = FastAPI(title="a2apydantic version-header demo")

SUPPORTED_VERSIONS = frozenset({"0.3", "1.0"})


def _negotiate(header_value: str | None) -> str:
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


@app.post("/message:send")
def message_send(
    request: v10.SendMessageRequest,
    a2a_version: Annotated[str | None, Header(alias="A2A-Version")] = None,
) -> dict[str, Any]:
    """Accept a v1.0 SendMessageRequest and return the shape the client asks for.

    The server's canonical representation is v1.0. Clients that still speak
    v0.3 opt in via the ``A2A-Version`` header and get a downgraded
    ``MessageSendParams`` back, with any lost-in-translation fields listed
    under ``conversion_warnings``.
    """
    version = _negotiate(a2a_version)

    if version == "1.0":
        return {
            "version": "1.0",
            "payload": request.model_dump(by_alias=True, exclude_none=True),
            "conversion_warnings": [],
        }

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        converted: v03.MessageSendParams = send_message_request(request)

    return {
        "version": "0.3",
        "payload": converted.model_dump(by_alias=True, exclude_none=True),
        "conversion_warnings": [str(w.message) for w in captured],
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "supported_versions": sorted(SUPPORTED_VERSIONS)}
