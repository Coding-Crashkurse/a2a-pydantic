"""Construction and extraction helpers for :class:`v10.Part`.

v1.0 ``Part`` is a flat model with one optional payload field per media
kind (``text``, ``raw``, ``url``, ``data``) plus cross-cutting
``media_type`` / ``filename`` / ``metadata``. Constructing one is not
hard, but every call site ends up doing the same dance:

* wrapping dicts in :class:`v10.Value` for ``data`` parts
* base64-encoding bytes for ``raw`` parts
* flipping empty-string ``filename`` / ``media_type`` back to ``None``
  on the way out

These helpers centralize those conversions so downstream code reads as
``text_part("hi")`` instead of ``v10.Part(text="hi")`` and
``file_part_bytes(b"...")`` instead of hand-coded base64. Extractors
(``extract_text``, ``extract_files``) do the reverse normalization in
one place.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from a2a_pydantic.v10 import models as _models

__all__ = [
    "FileInfo",
    "data_part",
    "extract_data",
    "extract_files",
    "extract_text",
    "file_part_bytes",
    "file_part_url",
    "part_kind",
    "text_part",
]


@dataclass(frozen=True)
class FileInfo:
    """Normalized view of a file payload from a :class:`v10.Part`.

    Exactly one of ``content`` or ``url`` is set. ``filename`` and
    ``media_type`` are ``None`` (not ``""``) when the source didn't
    provide them, so downstream code can use the natural
    ``if file.filename:`` idiom without the ``or None`` hedge.
    """

    content: bytes | None
    url: str | None
    filename: str | None
    media_type: str | None


def text_part(
    text: str,
    *,
    media_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> _models.Part:
    """Build a text :class:`v10.Part`.

    ``media_type`` defaults to ``None`` (sent as ``""`` on the wire per
    proto3 semantics) so callers don't need to think about it for plain
    text. Pass e.g. ``"text/markdown"`` when it matters.
    """
    return _models.Part(
        text=text,
        media_type=media_type if media_type is not None else "",
        metadata=_dict_to_struct(metadata),
    )


def data_part(
    data: Any,
    *,
    media_type: str = "application/json",
    metadata: dict[str, Any] | None = None,
) -> _models.Part:
    """Build a structured-data :class:`v10.Part`.

    Wraps ``data`` in :class:`v10.Value` automatically — callers pass
    plain Python values (dicts, lists, scalars). Default ``media_type``
    is ``application/json`` since that is the overwhelmingly common case.
    """
    return _models.Part(
        data=_models.Value(root=data),
        media_type=media_type,
        metadata=_dict_to_struct(metadata),
    )


def file_part_bytes(
    content: bytes,
    *,
    media_type: str | None = None,
    filename: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> _models.Part:
    """Build a file :class:`v10.Part` from raw bytes.

    The bytes are base64-encoded into ``Part.raw`` on your behalf; the
    v1.0 schema requires ASCII-safe base64 for the ``raw`` field.
    """
    encoded = base64.b64encode(content).decode("ascii")
    return _models.Part(
        raw=encoded,
        media_type=media_type if media_type is not None else "",
        filename=filename if filename is not None else "",
        metadata=_dict_to_struct(metadata),
    )


def file_part_url(
    url: str,
    *,
    media_type: str | None = None,
    filename: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> _models.Part:
    """Build a file :class:`v10.Part` pointing at an external URL."""
    return _models.Part(
        url=url,
        media_type=media_type if media_type is not None else "",
        filename=filename if filename is not None else "",
        metadata=_dict_to_struct(metadata),
    )


def part_kind(part: _models.Part) -> str:
    """Return the populated payload kind: one of
    ``"text" | "raw" | "url" | "data" | "empty"``.

    Useful for match/switch dispatch without re-implementing the same
    "which field is set" scan at every call site.
    """
    if part.text is not None:
        return "text"
    if part.raw is not None:
        return "raw"
    if part.url is not None:
        return "url"
    if part.data is not None:
        return "data"
    return "empty"


def extract_text(parts: list[_models.Part]) -> str:
    """Concatenate text from all text-kind parts, in order.

    Non-text parts are skipped. Returns ``""`` if nothing matches.
    """
    return "".join(p.text or "" for p in parts if p.text is not None)


def extract_data(parts: list[_models.Part]) -> list[Any]:
    """Return unwrapped :attr:`v10.Part.data` payloads from data-kind parts."""
    return [p.data.root for p in parts if p.data is not None]


def extract_files(parts: list[_models.Part]) -> list[FileInfo]:
    """Return a :class:`FileInfo` for every file-kind part.

    Base64-decodes ``raw`` back to bytes and normalizes empty-string
    ``filename`` / ``media_type`` defaults to ``None`` so callers can
    use ``if file.filename:`` naturally.
    """
    out: list[FileInfo] = []
    for p in parts:
        if p.raw is not None:
            out.append(
                FileInfo(
                    content=base64.b64decode(p.raw),
                    url=None,
                    filename=p.filename or None,
                    media_type=p.media_type or None,
                )
            )
        elif p.url is not None:
            out.append(
                FileInfo(
                    content=None,
                    url=p.url,
                    filename=p.filename or None,
                    media_type=p.media_type or None,
                )
            )
    return out


def _dict_to_struct(data: dict[str, Any] | None) -> _models.Struct | None:
    if not data:
        return None
    return _models.Struct.model_validate(data)
