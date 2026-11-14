"""The orb's windows stay above other apps on macOS after a hide and reveal.

Aqua-Tk 9 drops a window's floating level when it is withdrawn and mapped
again: ``wm attributes -topmost`` still reads 1, but the window comes back at
the normal level and sinks behind the browser. The orb hides and reveals its
windows all the time, so it would vanish while the app reports it as shown.
Every reveal therefore sets the attribute again.
"""

from __future__ import annotations

import re
import tkinter as tk
from pathlib import Path

import pytest

from ui.orb import overlay

_REPO = Path(__file__).resolve().parents[3]


class _Window:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, object]] = []
        self._fail = fail

    def wm_attributes(self, name: str, value: object) -> None:
        if self._fail:
            raise tk.TclError("window gone")
        self.calls.append((name, value))


def test_sets_topmost_again_on_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(overlay.sys, "platform", "darwin")
    window = _Window()
    overlay.reassert_macos_topmost(window)
    assert window.calls == [("-topmost", True)]


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_does_nothing_elsewhere(monkeypatch: pytest.MonkeyPatch, platform: str) -> None:
    monkeypatch.setattr(overlay.sys, "platform", platform)
    window = _Window()
    overlay.reassert_macos_topmost(window)
    assert window.calls == []


def test_a_destroyed_window_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(overlay.sys, "platform", "darwin")
    overlay.reassert_macos_topmost(_Window(fail=True))
    overlay.reassert_macos_topmost(None)


@pytest.mark.parametrize("rel", ["ui/orb/overlay.py"])
def test_every_reveal_restores_the_level(rel: str) -> None:
    """Each ``deiconify()`` is followed by the re-assert on the same window."""
    lines = (_REPO / rel).read_text(encoding="utf-8").splitlines()
    reveals = [i for i, line in enumerate(lines) if re.search(r"\.deiconify\(\)", line)]
    assert reveals, f"no reveal found in {rel}"
    for i in reveals:
        target = re.search(r"([\w.]+)\.deiconify\(\)", lines[i]).group(1)
        follow = lines[i + 1].strip()
        assert re.fullmatch(
            rf"(self\._ov\.)?reassert_macos_topmost\({re.escape(target)}\)", follow
        ), f"{rel}:{i + 1}: reveal of {target} is not followed by reassert_macos_topmost"
