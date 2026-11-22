"""Unit tests for ``dodaios.setup.state`` (Phase B9.7 / Sub-Agent 6).

Pure-Python tests that never touch the real ``data/setup_state.json``;
every read and write happens under pytest's ``tmp_path``. Each test
covers a single property of the tiny JSON-backed first-run flag store:
missing file, corrupt JSON and the happy-path round trip. The
writers are covered in ``test_onboarding_state.py``.
"""
from __future__ import annotations

import json
from pathlib import Path

from dodaios.setup.state import load_setup_state


# ---------------------------------------------------------------------------
# (a) load_setup_state: missing file → {}
# ---------------------------------------------------------------------------
def test_load_setup_state_missing_file(tmp_path: Path) -> None:
    """Path that does not exist returns an empty dict, no exception."""
    target = tmp_path / "nope" / "setup_state.json"
    assert not target.exists()
    assert load_setup_state(target) == {}


# ---------------------------------------------------------------------------
# (b) load_setup_state: corrupt JSON → {}
# ---------------------------------------------------------------------------
def test_load_setup_state_corrupt_json(tmp_path: Path) -> None:
    """Malformed JSON content is treated as an empty state silently."""
    target = tmp_path / "setup_state.json"
    target.write_text("{not valid", encoding="utf-8")
    # Must not raise.
    assert load_setup_state(target) == {}


# ---------------------------------------------------------------------------
# (c) load_setup_state: valid JSON → matching dict
# ---------------------------------------------------------------------------
def test_load_setup_state_happy_path(tmp_path: Path) -> None:
    """A well-formed JSON object round-trips byte-for-byte into a dict."""
    target = tmp_path / "setup_state.json"
    payload = {"onboarding_step": "voice", "other": 42}
    target.write_text(json.dumps(payload), encoding="utf-8")
    assert load_setup_state(target) == payload
