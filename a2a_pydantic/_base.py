"""Base class for all a2a-pydantic models.

Centralises:
- camelCase JSON aliases (matching both v0.3 and v1.0 wire formats)
- ``populate_by_name`` so users can construct with snake_case Python names
- the public ``dump()`` method that resolves the protocol version and
  threads it into ``model_dump`` via the serialization context
- ``get_version()`` for the per-model wrap serialisers to read back the
  active version from the context
"""

from __future__ import annotations

from typing import Any, Final

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from pydantic_core.core_schema import SerializationInfo

from a2a_pydantic._config import (
    Version,
    normalize_version,
    resolve_version,
)


class A2ABaseModel(BaseModel):
    """Common configuration + ``dump()`` for every model in the package."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        # Forbid unknown keys would be too strict for forward compatibility:
        # the A2A spec is still evolving and unknown fields should round-trip.
        extra="ignore",
    )

    def dump(
        self,
        version: str | None = None,
        *,
        exclude_none: bool = True,
        by_alias: bool = True,
    ) -> dict[str, Any]:
        """Serialise to a plain dict in the requested protocol version.

        ``version`` follows the resolution chain documented in
        :mod:`a2a_pydantic._config`.
        """
        resolved: Version = resolve_version(version)
        return self.model_dump(
            mode="json",
            by_alias=by_alias,
            exclude_none=exclude_none,
            context={CONTEXT_KEY: resolved},
        )

    def dump_json(self, version: str | None = None) -> str:
        """Same as :meth:`dump`, but returns a JSON string."""
        import json

        return json.dumps(self.dump(version=version), separators=(",", ":"))


CONTEXT_KEY: Final[str] = "a2a_version"


def get_version(info: SerializationInfo) -> Version:
    """Read the active protocol version from a serializer's context.

    Strict: if the context has no usable version, fall back to
    :func:`resolve_version` (which itself reads the env var and raises
    :class:`A2AVersionError` if nothing is set). Direct ``model_dump()``
    callers must therefore either pass ``context={"a2a_version": ...}``
    or set the env var.
    """
    ctx = info.context or {}
    from_context = normalize_version(ctx.get(CONTEXT_KEY))
    if from_context is not None:
        return from_context
    return resolve_version()
