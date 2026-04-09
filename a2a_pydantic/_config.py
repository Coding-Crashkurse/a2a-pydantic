"""Version resolution for the dual v0.3 / v1.0 protocol output.

The package is internally always v1.0. The *output* version of ``dump()``
must be specified explicitly: there is no silent default. The resolution
chain is:

1. Explicit ``version=`` argument passed to ``dump()``.
2. The ``A2A_VERSION`` environment variable.
3. **Raise** :class:`A2AVersionError`.

This forces every serialisation to make a deliberate choice between v0.3
and v1.0 — silent defaults have a habit of producing wire payloads in the
wrong format and shipping to the wrong server.
"""

from __future__ import annotations

import os
from typing import Final, Literal

Version = Literal["0.3", "1.0"]

ENV_VAR: Final[str] = "A2A_VERSION"


class A2AVersionError(RuntimeError):
    """Raised when no protocol version can be resolved.

    Attribute ``env_var`` is the name of the environment variable the user
    can set to provide a default; included so error messages stay accurate
    if the variable is ever renamed.
    """

    env_var: str = ENV_VAR

    def __init__(self) -> None:
        super().__init__(
            "No A2A protocol version specified. Either pass an explicit "
            f"version=... to dump() or set the {ENV_VAR} environment "
            'variable to "0.3" or "1.0".'
        )


_NORMALIZE: Final[dict[str, Version]] = {
    "0.3": "0.3",
    "0.3.0": "0.3",
    "0.3.1": "0.3",
    "0.3.2": "0.3",
    "1.0": "1.0",
    "1.0.0": "1.0",
    "1": "1.0",
}


def normalize_version(value: str | None) -> Version | None:
    """Map any user-supplied version string to a canonical literal.

    Returns ``None`` for empty / unrecognised input so the caller can fall
    through to the next source in the resolution chain. We accept anything
    starting with ``"0.3"`` or ``"1."`` as forward-compatible aliases.
    """
    if not value:
        return None
    v = value.strip()
    if v in _NORMALIZE:
        return _NORMALIZE[v]
    if v.startswith("0.3"):
        return "0.3"
    if v.startswith("1."):
        return "1.0"
    return None


def resolve_version(explicit: str | None = None) -> Version:
    """Apply the strict resolution chain: explicit > env var > raise.

    Raises :class:`A2AVersionError` if neither source yields a valid version.
    """
    resolved = normalize_version(explicit) or normalize_version(os.environ.get(ENV_VAR))
    if resolved is None:
        raise A2AVersionError()
    return resolved
