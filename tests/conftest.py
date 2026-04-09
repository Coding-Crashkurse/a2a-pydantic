"""Test fixtures and import-path setup.

The project root has stale ``a2a_pb2*.py`` reference files alongside the
package; we need the package directory itself to be importable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pytest_configure(config):  # noqa: ARG001
    # Ensure no stray env-var leaks across tests.
    os.environ.pop("A2A_VERSION", None)
    os.environ.pop("A2A_PROTOCOL_VERSION", None)
