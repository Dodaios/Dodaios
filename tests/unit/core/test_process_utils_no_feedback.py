"""Background helpers must not flash the Windows busy cursor (issue #714)."""
from __future__ import annotations

import sys

import pytest

from dodaios.core import process_utils


@pytest.mark.skipif(sys.platform != "win32", reason="STARTUPINFO exists only on Windows")
def test_startupinfo_turns_launch_feedback_off_on_windows() -> None:
    info = process_utils.no_feedback_startupinfo()

    assert info is not None
    assert info.dwFlags & 0x00000080, "STARTF_FORCEOFFFEEDBACK must be set"


def test_startupinfo_is_none_off_windows(monkeypatch) -> None:
    # subprocess rejects any non-None startupinfo outside Windows.
    monkeypatch.setattr(process_utils.sys, "platform", "linux")

    assert process_utils.no_feedback_startupinfo() is None
