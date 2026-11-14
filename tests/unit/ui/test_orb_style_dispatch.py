"""The orb window paints the voice orb, and never a magenta box.

The voice orb lives in one frameless always-on-top window, which is what makes
it draggable to any monitor instead of being trapped inside the app. These
tests pin that seam: every style resolves to the voice orb (the removed mascot
and pet looks included), and a desktop session without per-pixel transparency
degrades to nothing visible instead of an opaque key-coloured square.
"""
from __future__ import annotations

import tkinter as tk

import pytest

import ui.orb.overlay as overlay_mod
from ui.orb.overlay import OrbOverlay, _apply_color_key, _coerce_style
from ui.orb.voice_orb import VoiceOrbRenderer


def test_the_orb_window_builds_the_voice_orb_renderer() -> None:
    overlay = OrbOverlay(style="voice_orb")

    assert overlay._style == "voice_orb"
    assert isinstance(overlay._build_renderer(), VoiceOrbRenderer)


@pytest.mark.parametrize("style", ["mascot", "pet", "orb", "nonsense", None, ""])
def test_every_other_style_becomes_the_voice_orb(style: str | None) -> None:
    # A jarvis.toml written by an older or newer build must not leave the
    # desktop without an overlay, and set_style() is called from a REST route,
    # where an exception would surface as a 500 on a cosmetic setting.
    assert _coerce_style(style) == "voice_orb"
    assert OrbOverlay(style=style)._style == "voice_orb"
    OrbOverlay().set_style(style or "")  # no raise


class _FakeRoot:
    """Minimal Tk stand-in: refuses the colour key like a bare X11 session."""

    def __init__(self, *, supported: bool) -> None:
        self.supported = supported
        self.background: str | None = None

    def wm_attributes(self, name: str, value: str) -> None:
        if not self.supported:
            raise tk.TclError(f"bad attribute {name}")

    def configure(self, **kwargs: object) -> None:
        self.background = str(kwargs.get("bg"))


def test_color_key_applied_when_the_session_supports_it() -> None:
    root = _FakeRoot(supported=True)

    assert _apply_color_key(root) is True
    assert root.background == overlay_mod.COLOR_KEY_HEX


def test_color_key_refusal_is_reported_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    root = _FakeRoot(supported=False)

    with caplog.at_level("WARNING", logger="jarvis.orb"):
        supported = _apply_color_key(root)

    assert supported is False
    # AP-30: the window will not appear, so the reason has to be visible.
    assert any("colour key" in record.message for record in caplog.records)
