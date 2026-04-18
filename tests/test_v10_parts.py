"""Tests for :mod:`a2a_pydantic.v10.parts` construction / extraction helpers."""

from __future__ import annotations

import base64

from a2a_pydantic import v10
from a2a_pydantic.v10.parts import (
    FileInfo,
    data_part,
    extract_data,
    extract_files,
    extract_text,
    file_part_bytes,
    file_part_url,
    part_kind,
    text_part,
)


class TestConstructors:
    def test_text_part(self) -> None:
        p = text_part("hello")
        assert isinstance(p, v10.Part)
        assert p.text == "hello"
        assert part_kind(p) == "text"

    def test_text_part_with_media_type(self) -> None:
        p = text_part("# title", media_type="text/markdown")
        assert p.media_type == "text/markdown"

    def test_data_part_wraps_value_automatically(self) -> None:
        p = data_part({"k": "v", "n": 2})
        assert p.data is not None
        assert isinstance(p.data, v10.Value)
        assert p.data.root == {"k": "v", "n": 2}
        assert p.media_type == "application/json"

    def test_file_part_bytes_base64_encodes(self) -> None:
        payload = b"hello world"
        p = file_part_bytes(payload, media_type="text/plain", filename="h.txt")
        assert p.raw == base64.b64encode(payload).decode("ascii")
        assert p.media_type == "text/plain"
        assert p.filename == "h.txt"

    def test_file_part_url(self) -> None:
        p = file_part_url("https://x/y.pdf", media_type="application/pdf")
        assert p.url == "https://x/y.pdf"
        assert p.media_type == "application/pdf"

    def test_metadata_dict_wraps_in_struct(self) -> None:
        p = text_part("hi", metadata={"trace": "abc"})
        assert isinstance(p.metadata, v10.Struct)
        assert p.metadata.model_dump(by_alias=False, exclude_none=True) == {"trace": "abc"}


class TestPartKind:
    def test_text(self) -> None:
        assert part_kind(text_part("hi")) == "text"

    def test_data(self) -> None:
        assert part_kind(data_part({"k": 1})) == "data"

    def test_raw(self) -> None:
        assert part_kind(file_part_bytes(b"x")) == "raw"

    def test_url(self) -> None:
        assert part_kind(file_part_url("https://x/y")) == "url"


class TestExtractors:
    def test_extract_text_concatenates_in_order(self) -> None:
        parts = [text_part("hello "), data_part({"k": 1}), text_part("world")]
        assert extract_text(parts) == "hello world"

    def test_extract_text_empty_on_no_match(self) -> None:
        assert extract_text([data_part({"k": 1}), file_part_url("https://x/y")]) == ""

    def test_extract_data_unwraps_value(self) -> None:
        parts = [text_part("skip me"), data_part({"k": 1}), data_part([1, 2, 3])]
        assert extract_data(parts) == [{"k": 1}, [1, 2, 3]]

    def test_extract_files_bytes_is_decoded(self) -> None:
        payload = b"hello world"
        parts = [file_part_bytes(payload, media_type="text/plain", filename="h.txt")]
        files = extract_files(parts)
        assert len(files) == 1
        assert files[0] == FileInfo(
            content=payload, url=None, filename="h.txt", media_type="text/plain"
        )

    def test_extract_files_url_has_no_content(self) -> None:
        parts = [file_part_url("https://x/y.pdf")]
        files = extract_files(parts)
        assert files == [FileInfo(content=None, url="https://x/y.pdf", filename=None, media_type=None)]

    def test_extract_files_normalizes_empty_strings_to_none(self) -> None:
        # Raw Part construction without helper defaults media_type / filename
        # to ''. The extractor must flip those back to None so downstream
        # `if file.filename:` works naturally.
        p = v10.Part(url="https://x/y")  # media_type='', filename='' by default
        files = extract_files([p])
        assert files[0].filename is None
        assert files[0].media_type is None

    def test_extract_files_skips_non_file_parts(self) -> None:
        parts = [text_part("hi"), data_part({"k": 1}), file_part_url("https://x/y")]
        assert len(extract_files(parts)) == 1
