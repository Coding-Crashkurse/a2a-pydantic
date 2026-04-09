"""Part dual-accept and v0.3/v1.0 round-trips.

Mirrors the examples in the vision document, section "Unified Part".
"""

from __future__ import annotations

import base64

import pytest

from a2a_pydantic import Part


class TestPartConstructors:
    def test_text(self):
        p = Part(text="hello")
        assert p.text == "hello"
        assert p.data is None and p.url is None and p.raw is None

    def test_data(self):
        p = Part(data={"key": "value"})
        assert p.data == {"key": "value"}
        assert p.text is None

    def test_file_url(self):
        p = Part(url="https://example.com/doc.pdf", media_type="application/pdf")
        assert p.url == "https://example.com/doc.pdf"
        assert p.media_type == "application/pdf"
        assert p.raw is None

    def test_file_raw(self):
        p = Part(raw=b"\x00\x01\x02", media_type="image/png", filename="img.png")
        assert p.raw == b"\x00\x01\x02"
        assert p.media_type == "image/png"
        assert p.filename == "img.png"
        assert p.url is None

    def test_file_requires_one_of(self):
        with pytest.raises(ValueError, match="exactly one"):
            Part()
        with pytest.raises(ValueError, match="exactly one"):
            Part(url="https://x.com", raw=b"abc")


class TestPartV10Output:
    def test_text(self):
        assert Part(text="hello").dump(version="1.0") == {"text": "hello"}

    def test_data(self):
        assert Part(data={"k": "v"}).dump(version="1.0") == {"data": {"k": "v"}}

    def test_file_url(self):
        out = Part(
            url="https://example.com/doc.pdf", media_type="application/pdf"
        ).dump(version="1.0")
        assert out == {
            "url": "https://example.com/doc.pdf",
            "mediaType": "application/pdf",
        }

    def test_file_raw_base64(self):
        raw = b"\x00binary\x01"
        out = Part(raw=raw, media_type="application/octet-stream").dump(version="1.0")
        assert out["raw"] == base64.b64encode(raw).decode("ascii")
        assert out["mediaType"] == "application/octet-stream"


class TestPartV03Output:
    def test_text(self):
        assert Part(text="hello").dump(version="0.3") == {
            "kind": "text",
            "text": "hello",
        }

    def test_data(self):
        assert Part(data={"k": "v"}).dump(version="0.3") == {
            "kind": "data",
            "data": {"k": "v"},
        }

    def test_file_url(self):
        out = Part(
            url="https://example.com/doc.pdf", media_type="application/pdf"
        ).dump(version="0.3")
        assert out == {
            "kind": "file",
            "file": {
                "uri": "https://example.com/doc.pdf",
                "mimeType": "application/pdf",
            },
        }

    def test_file_raw(self):
        raw = b"\x00binary\x01"
        out = Part(
            raw=raw, media_type="application/octet-stream", filename="x.bin"
        ).dump(version="0.3")
        assert out == {
            "kind": "file",
            "file": {
                "bytes": base64.b64encode(raw).decode("ascii"),
                "mimeType": "application/octet-stream",
                "name": "x.bin",
            },
        }


class TestPartInputAcceptance:
    def test_v03_text_input(self):
        p = Part.model_validate({"kind": "text", "text": "hello"})
        assert p.text == "hello"

    def test_v10_text_input(self):
        p = Part.model_validate({"text": "hello"})
        assert p.text == "hello"

    def test_v03_file_uri_input(self):
        p = Part.model_validate(
            {
                "kind": "file",
                "file": {
                    "uri": "https://example.com/doc.pdf",
                    "mimeType": "application/pdf",
                },
            }
        )
        assert p.url == "https://example.com/doc.pdf"
        assert p.media_type == "application/pdf"

    def test_v10_file_input(self):
        p = Part.model_validate(
            {"url": "https://example.com/doc.pdf", "mediaType": "application/pdf"}
        )
        assert p.url == "https://example.com/doc.pdf"

    def test_v03_file_bytes_input(self):
        encoded = base64.b64encode(b"hello").decode("ascii")
        p = Part.model_validate(
            {
                "kind": "file",
                "file": {
                    "bytes": encoded,
                    "mimeType": "text/plain",
                    "name": "x.txt",
                },
            }
        )
        assert p.raw == b"hello"
        assert p.filename == "x.txt"

    def test_v03_data_input(self):
        p = Part.model_validate({"kind": "data", "data": {"k": "v"}})
        assert p.data == {"k": "v"}


class TestPartRoundTrip:
    @pytest.mark.parametrize(
        "v03_in",
        [
            {"kind": "text", "text": "hi"},
            {"kind": "data", "data": {"k": 1}},
            {
                "kind": "file",
                "file": {"uri": "https://x.com/a", "mimeType": "text/plain"},
            },
        ],
    )
    def test_v03_roundtrip(self, v03_in):
        p = Part.model_validate(v03_in)
        assert p.dump(version="0.3") == v03_in
