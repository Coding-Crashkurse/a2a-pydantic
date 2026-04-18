"""Regression tests for the v0.0.5 and v0.0.7 ergonomics fixes.

v0.0.5 — four changes:

* ``A2ABaseModel`` now runs ``validate_assignment=True`` so that
  ``task.metadata = {"a": 1}`` is coerced back to :class:`v10.Struct`
  instead of silently stored as a raw dict (which later crashes
  ``convert_to_v03`` on ``metadata.model_dump``).
* :class:`v10.Timestamp` supports ordering (``<``, ``<=``, ``>``, ``>=``)
  so tasks can be sorted by ``task.status.timestamp`` without manual key
  functions.
* :class:`v10.TaskState` accepts case-insensitive strings and the short
  form (``"submitted"``, ``"Submitted"``, ``"TASK_STATE_SUBMITTED"`` all
  resolve to ``TaskState.task_state_submitted``).
* ``convert_to_v03`` accepts an ``assume_final`` kwarg that overrides the
  synthetic ``final`` flag on v0.3 ``TaskStatusUpdateEvent`` AND suppresses
  the "defaulting final=False" warning when the caller has already decided.

v0.0.7 — :class:`v10.Part` ergonomics:

* ``filename`` and ``media_type`` default to ``None`` (was ``""``), so the
  natural ``if p.filename:`` idiom works without the ``or None`` hedge.
* ``v10.Part(data={"k": "v"})`` auto-wraps the dict in :class:`v10.Value`.
* ``v10.Part(raw=b"...")`` auto-base64-encodes the bytes; assignment
  (``part.raw = b"..."``) does the same, so Pydantic's default
  ``bytes -> str`` UTF-8 coercion can't silently corrupt binary payloads.
"""

from __future__ import annotations

import base64
import warnings
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from a2a_pydantic import convert_to_v03, v10


class TestValidateAssignment:
    def test_dict_reassigned_to_metadata_coerces_to_struct(self) -> None:
        task = v10.Task(
            id="t-1",
            status=v10.TaskStatus(state=v10.TaskState.task_state_submitted),
            metadata=v10.Struct(trace="abc"),
        )
        task.metadata = {"trace": "xyz", "retries": 2}  # type: ignore[assignment]
        assert isinstance(task.metadata, v10.Struct)
        dumped = task.metadata.model_dump(by_alias=False, exclude_none=True)
        assert dumped == {"trace": "xyz", "retries": 2}

    def test_dict_metadata_survives_convert_to_v03(self) -> None:
        task = v10.Task(
            id="t-1",
            status=v10.TaskStatus(state=v10.TaskState.task_state_completed),
        )
        task.metadata = {"trace": "abc"}  # type: ignore[assignment]
        out = convert_to_v03(task)
        assert out.metadata == {"trace": "abc"}

    def test_invalid_assignment_raises(self) -> None:
        msg = v10.Message(
            message_id="m-1",
            role=v10.Role.role_user,
            parts=[v10.Part(text="hi")],
        )
        with pytest.raises(ValidationError):
            msg.role = "not-a-role"  # type: ignore[assignment]


class TestTimestampOrdering:
    def _ts(self, iso: str) -> v10.Timestamp:
        return v10.Timestamp(root=datetime.fromisoformat(iso))

    def test_lt_gt_by_root(self) -> None:
        earlier = self._ts("2026-01-01T00:00:00+00:00")
        later = self._ts("2026-01-02T00:00:00+00:00")
        assert earlier < later
        assert later > earlier
        assert earlier <= later
        assert later >= earlier

    def test_sortable(self) -> None:
        t_a = self._ts("2026-03-01T00:00:00+00:00")
        t_b = self._ts("2026-01-01T00:00:00+00:00")
        t_c = self._ts("2026-02-01T00:00:00+00:00")
        assert sorted([t_a, t_b, t_c]) == [t_b, t_c, t_a]

    def test_sort_tasks_by_status_timestamp(self) -> None:
        def task(id_: str, iso: str) -> v10.Task:
            return v10.Task(
                id=id_,
                status=v10.TaskStatus(
                    state=v10.TaskState.task_state_completed,
                    timestamp=self._ts(iso),
                ),
            )

        tasks = [
            task("t-late", "2026-03-01T00:00:00+00:00"),
            task("t-early", "2026-01-01T00:00:00+00:00"),
            task("t-mid", "2026-02-01T00:00:00+00:00"),
        ]
        ordered = sorted(tasks, key=lambda t: t.status.timestamp)  # type: ignore[arg-type,return-value]
        assert [t.id for t in ordered] == ["t-early", "t-mid", "t-late"]

    def test_comparison_with_non_timestamp_returns_not_implemented(self) -> None:
        ts = self._ts("2026-01-01T00:00:00+00:00")
        naive = datetime(2026, 1, 1, tzinfo=UTC)
        # TypeError is the correct behavior when the other side is not a
        # Timestamp — __lt__ returning NotImplemented triggers Python's
        # fallback, which raises because datetime has no reverse.
        with pytest.raises(TypeError):
            _ = ts < naive  # type: ignore[operator]


class TestTaskStateCaseInsensitiveLookup:
    def test_canonical_uppercase_still_works(self) -> None:
        assert v10.TaskState("TASK_STATE_SUBMITTED") is v10.TaskState.task_state_submitted

    def test_short_lowercase(self) -> None:
        assert v10.TaskState("submitted") is v10.TaskState.task_state_submitted
        assert v10.TaskState("completed") is v10.TaskState.task_state_completed

    def test_short_mixed_case(self) -> None:
        assert v10.TaskState("Submitted") is v10.TaskState.task_state_submitted
        assert v10.TaskState("Input_Required") is v10.TaskState.task_state_input_required

    def test_full_mixed_case(self) -> None:
        assert v10.TaskState("task_state_submitted") is v10.TaskState.task_state_submitted
        assert v10.TaskState("Task_State_Working") is v10.TaskState.task_state_working

    def test_unknown_still_raises(self) -> None:
        with pytest.raises(ValueError):
            v10.TaskState("nope")


class TestPartDefaults:
    def test_filename_defaults_to_none(self) -> None:
        p = v10.Part(text="hi")
        assert p.filename is None

    def test_media_type_defaults_to_none(self) -> None:
        p = v10.Part(text="hi")
        assert p.media_type is None

    def test_explicit_filename_preserved(self) -> None:
        p = v10.Part(url="https://x/y.pdf", filename="y.pdf")
        assert p.filename == "y.pdf"


class TestPartRawBytesCoercion:
    def test_construction_with_bytes_base64_encodes(self) -> None:
        payload = b"hello world"
        p = v10.Part(raw=payload, media_type="text/plain")
        assert p.raw == base64.b64encode(payload).decode("ascii")

    def test_construction_with_binary_bytes_does_not_utf8_decode(self) -> None:
        # The whole point: silent UTF-8 decoding would corrupt binary data.
        payload = b"\x00\x01\x02\xff"
        p = v10.Part(raw=payload)
        assert base64.b64decode(p.raw) == payload

    def test_assignment_with_bytes_base64_encodes(self) -> None:
        # validate_assignment is a separate pydantic path; the __setattr__
        # override on Part must catch bytes on assignment too, not just
        # construction.
        p = v10.Part(raw=base64.b64encode(b"aaa").decode("ascii"))
        p.raw = b"bbb"
        assert p.raw == base64.b64encode(b"bbb").decode("ascii")

    def test_already_encoded_string_passes_through(self) -> None:
        already = base64.b64encode(b"x").decode("ascii")
        p = v10.Part(raw=already)
        assert p.raw == already


class TestPartDataWrappingCoercion:
    def test_construction_with_dict_wraps_in_value(self) -> None:
        p = v10.Part(data={"k": 1, "nested": {"m": 2}})
        assert isinstance(p.data, v10.Value)
        assert p.data.root == {"k": 1, "nested": {"m": 2}}

    def test_construction_with_list_wraps_in_value(self) -> None:
        p = v10.Part(data=[1, 2, 3])
        assert isinstance(p.data, v10.Value)
        assert p.data.root == [1, 2, 3]

    def test_construction_with_scalar_wraps_in_value(self) -> None:
        p = v10.Part(data=42)
        assert isinstance(p.data, v10.Value)
        assert p.data.root == 42

    def test_already_wrapped_value_passes_through(self) -> None:
        wrapped = v10.Value(root={"k": 1})
        p = v10.Part(data=wrapped)
        assert p.data is wrapped

    def test_assignment_with_dict_wraps(self) -> None:
        p = v10.Part(data={"x": 1})
        p.data = {"y": 2}
        assert isinstance(p.data, v10.Value)
        assert p.data.root == {"y": 2}


class TestStructMappingAPI:
    def test_get_with_existing_key(self) -> None:
        s = v10.Struct(trace="abc", retries=2)
        assert s.get("trace") == "abc"
        assert s.get("retries") == 2

    def test_get_missing_returns_none(self) -> None:
        s = v10.Struct(trace="abc")
        assert s.get("nope") is None

    def test_get_missing_returns_default(self) -> None:
        s = v10.Struct()
        assert s.get("nope", "fallback") == "fallback"

    def test_getitem_existing(self) -> None:
        s = v10.Struct(k="v")
        assert s["k"] == "v"

    def test_getitem_missing_raises_keyerror(self) -> None:
        s = v10.Struct()
        with pytest.raises(KeyError):
            s["nope"]

    def test_contains(self) -> None:
        s = v10.Struct(present=1)
        assert "present" in s
        assert "absent" not in s

    def test_setitem_adds_key(self) -> None:
        s = v10.Struct()
        s["new"] = 42
        assert s["new"] == 42

    def test_delitem_removes_key(self) -> None:
        s = v10.Struct(gone=1, stays=2)
        del s["gone"]
        assert "gone" not in s
        assert s["stays"] == 2

    def test_delitem_missing_raises_keyerror(self) -> None:
        s = v10.Struct()
        with pytest.raises(KeyError):
            del s["nope"]

    def test_iter_yields_keys(self) -> None:
        s = v10.Struct(a=1, b=2, c=3)
        # Mapping convention: iter yields keys, not (key, value) tuples.
        assert sorted(list(s)) == ["a", "b", "c"]

    def test_len(self) -> None:
        assert len(v10.Struct()) == 0
        assert len(v10.Struct(a=1, b=2)) == 2

    def test_keys_values_items(self) -> None:
        s = v10.Struct(a=1, b=2)
        assert sorted(s.keys()) == ["a", "b"]
        assert sorted(s.values()) == [1, 2]
        assert sorted(s.items()) == [("a", 1), ("b", 2)]

    def test_update_with_dict(self) -> None:
        s = v10.Struct(a=1)
        s.update({"b": 2, "c": 3})
        assert s["a"] == 1 and s["b"] == 2 and s["c"] == 3

    def test_update_with_kwargs(self) -> None:
        s = v10.Struct()
        s.update(x=1, y=2)
        assert s["x"] == 1 and s["y"] == 2

    def test_setdefault_existing_returns_current(self) -> None:
        s = v10.Struct(k="original")
        assert s.setdefault("k", "new") == "original"
        assert s["k"] == "original"

    def test_setdefault_missing_inserts_and_returns(self) -> None:
        s = v10.Struct()
        assert s.setdefault("k", "v") == "v"
        assert s["k"] == "v"

    def test_pop_existing(self) -> None:
        s = v10.Struct(gone=1, stays=2)
        assert s.pop("gone") == 1
        assert "gone" not in s

    def test_pop_missing_raises(self) -> None:
        s = v10.Struct()
        with pytest.raises(KeyError):
            s.pop("nope")

    def test_pop_missing_with_default_returns_default(self) -> None:
        s = v10.Struct()
        assert s.pop("nope", "fallback") == "fallback"

    def test_dict_roundtrip(self) -> None:
        s = v10.Struct(trace="abc", retries=2)
        # Mapping protocol (keys + __getitem__) makes dict(struct) work.
        assert dict(s) == {"trace": "abc", "retries": 2}

    def test_survives_convert_to_v03(self) -> None:
        # Mutation through MutableMapping API must not desynchronize
        # __pydantic_extra__ from what model_dump sees. convert_to_v03
        # calls struct.model_dump() internally.
        task = v10.Task(
            id="t-1",
            status=v10.TaskStatus(state=v10.TaskState.task_state_submitted),
            metadata=v10.Struct(trace="abc"),
        )
        assert task.metadata is not None
        task.metadata["retries"] = 3
        out = convert_to_v03(task)
        assert out.metadata == {"trace": "abc", "retries": 3}


class TestAssumeFinalKwarg:
    def _event(self) -> v10.TaskStatusUpdateEvent:
        return v10.TaskStatusUpdateEvent(
            context_id="c-1",
            task_id="t-1",
            status=v10.TaskStatus(state=v10.TaskState.task_state_working),
        )

    def test_default_behavior_warns_and_sets_false(self) -> None:
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            out = convert_to_v03(self._event())
        assert out.final is False
        assert any("defaulting" in str(w.message) for w in captured)

    def test_assume_final_true_sets_true_and_silent(self) -> None:
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            out = convert_to_v03(self._event(), assume_final=True)
        assert out.final is True
        assert not any("defaulting" in str(w.message) for w in captured)

    def test_assume_final_false_sets_false_and_silent(self) -> None:
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            out = convert_to_v03(self._event(), assume_final=False)
        assert out.final is False
        assert not any("defaulting" in str(w.message) for w in captured)

    def test_kwarg_is_scoped_per_call(self) -> None:
        # A prior call with assume_final=True must not leak into a later
        # call with the kwarg omitted (ContextVar token reset).
        convert_to_v03(self._event(), assume_final=True)
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            out = convert_to_v03(self._event())
        assert out.final is False
        assert any("defaulting" in str(w.message) for w in captured)
