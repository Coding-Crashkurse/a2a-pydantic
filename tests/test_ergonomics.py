"""Regression tests for the v0.0.5 ergonomics fixes.

Covers the four changes shipped in v0.0.5:

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
"""

from __future__ import annotations

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
