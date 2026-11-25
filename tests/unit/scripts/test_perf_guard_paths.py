"""Every guard that scripts/perf_guard.py lists must exist on disk."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _load():
    spec = importlib.util.spec_from_file_location("perf_guard", REPO / "scripts" / "perf_guard.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_every_listed_guard_file_exists():
    mod = _load()
    missing = [f for f in (*mod.PYTEST_FAST, *mod.PYTEST_FULL) if not (REPO / f).is_file()]
    assert not missing, f"perf_guard lists guard files that do not exist: {missing}"
