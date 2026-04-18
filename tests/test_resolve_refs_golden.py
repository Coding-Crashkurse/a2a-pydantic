"""Golden-file regression test for scripts/resolve_refs.py.

Locks the full pipeline output against a committed snapshot so any
upstream schema change (or any change in resolve_refs.py) surfaces as
a test failure requiring conscious review — catching drift that the
narrow unit tests in ``test_resolve_refs.py`` wouldn't see, like a
renamed enum member silently skipping ``extract_task_state``.

When the upstream schema really does change:

    1. Replace tests/fixtures/schema_raw.json with the new raw bundle.
    2. Regenerate the golden output::

        python scripts/resolve_refs.py \\
            tests/fixtures/schema_raw.json \\
            tests/fixtures/schema_resolved.json

    3. Review the diff carefully (new types, renamed fields, dropped
       enum variants) and commit both files together.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from resolve_refs import process_schema

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_full_pipeline_matches_golden() -> None:
    raw = json.loads((FIXTURE_DIR / "schema_raw.json").read_text(encoding="utf-8"))
    expected = json.loads((FIXTURE_DIR / "schema_resolved.json").read_text(encoding="utf-8"))

    actual = copy.deepcopy(raw)
    process_schema(actual)

    assert actual == expected, (
        "Pipeline output diverged from golden fixture. If upstream schema "
        "really changed, regenerate tests/fixtures/schema_resolved.json and "
        "review the diff before committing. See module docstring for the "
        "exact command."
    )
