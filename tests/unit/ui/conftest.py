"""Fixtures shared by the desktop overlay tests."""

from __future__ import annotations

from pathlib import Path

import pytest

_MASCOT_IMAGE = Path(__file__).resolve().parents[3] / "assets" / "icons" / "jarvis-gigi-256.png"


@pytest.fixture
def still_picture_mascot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the mascot style the still picture, as a configured image does.

    Without one the mascot is a pet (``MASCOT_PET_ID``); the tests of the
    picture's own window, drag and boot behaviour ask for it by name.
    """
    monkeypatch.setenv("JARVIS_ORB_MASCOT_PATH", str(_MASCOT_IMAGE))
