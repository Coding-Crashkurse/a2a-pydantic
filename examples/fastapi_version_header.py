"""FastAPI example: serve MessageSendParams in both A2A versions.

Run with::

    uv pip install fastapi uvicorn
    PYTHONPATH=src uvicorn examples.fastapi_version_header:app --reload

Send a v1.0 SendMessageRequest body. Use the ``A2A-Version`` header to pick
the response format:

* ``A2A-Version: 1.0`` (default) -> echoes the v1.0 SendMessageRequest
* ``A2A-Version: 0.3``           -> converts to v0.3 MessageSendParams via
  :func:`a2a_pydantic.convert_to_v03` and returns that instead

Conversion warnings are logged via the ``uvicorn.error`` logger so they
show up alongside the INFO access log, and also echoed back in the
response body under ``conversion_warnings`` for programmatic consumers.

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
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException

from a2a_pydantic import convert_to_v03, v10

logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="a2a_pydantic version-header demo")

SUPPORTED_VERSIONS = frozenset({"0.3", "1.0"})


@app.post("/message:send")
def message_send(
    request: v10.SendMessageRequest,
    a2a_version: Annotated[str | None, Header(alias="A2A-Version")] = None,
) -> dict[str, Any]:
    version = (a2a_version or "1.0").strip()
    if version not in SUPPORTED_VERSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported A2A-Version {version!r}. "
                f"Supported: {sorted(SUPPORTED_VERSIONS)}"
            ),
        )

    if version == "1.0":
        return {
            "version": "1.0",
            "payload": request.model_dump(by_alias=True, exclude_none=True),
            "conversion_warnings": [],
        }

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        converted = convert_to_v03(request)

    warning_messages = [str(w.message) for w in captured]
    for msg in warning_messages:
        logger.warning("a2a v1.0->v0.3 conversion: %s", msg)
    logger.info(
        "a2a v1.0->v0.3 converted to %s:\n%s",
        type(converted).__name__,
        converted.model_dump_json(by_alias=True, exclude_none=True, indent=2),
    )

    return {
        "version": "0.3",
        "payload": converted.model_dump(by_alias=True, exclude_none=True),
        "conversion_warnings": warning_messages,
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "supported_versions": sorted(SUPPORTED_VERSIONS)}
