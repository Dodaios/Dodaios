"""UIConfig selects the jarvis bar by default and carries its flags."""
from __future__ import annotations

from dodaios.core.config import UIConfig


def test_defaults_select_jarvis_bar():
    c = UIConfig()
    assert c.orb_style == "jarvis_bar"
    assert c.bar_persistent is True
    assert c.bar_accent == "#e7c46e"


def test_legacy_and_none_still_accepted():
    # The removed desktop pet styles load as the bar (docs/pets.md).
    assert UIConfig(orb_style="mascot").orb_style == "jarvis_bar"
    assert UIConfig(orb_style="pet").orb_style == "jarvis_bar"
    assert UIConfig(orb_style="voice_orb").orb_style == "voice_orb"
    assert UIConfig(orb_style="none").orb_style == "none"


def test_bar_flags_overridable():
    c = UIConfig(bar_persistent=False, bar_accent="#ffffff")
    assert c.bar_persistent is False
    assert c.bar_accent == "#ffffff"
