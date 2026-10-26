"""Section windows: no section detaches; settings tabs share one identity."""

import re
from pathlib import Path

from dodaios.ui.desktop_app import DETACHABLE_VIEWS
from dodaios.ui.section_windows import WINDOW_GROUPS

FRONTEND = Path(__file__).parents[3] / "dodaios/ui/web/frontend/src"


def _ids(source: str, name: str) -> set[str]:
    block = re.search(rf"{name}[^=]*=\s*\[(.*?)\];", source, re.S)
    assert block, name
    return set(re.findall(r'"([a-z-]+)"', block[1]))


def test_no_section_is_offered_its_own_window():
    """Sections are tiled inside the main window; the detach list is gone."""
    assert not (FRONTEND / "lib/sectionWindows.ts").read_text(encoding="utf-8").count(
        "DETACHABLE_SECTIONS"
    )
    assert set(DETACHABLE_VIEWS) == {"appshot-editor", "jarvisx-editor"}


def test_settings_tabs_share_exactly_one_window_on_both_sides():
    source = (FRONTEND / "components/layout/navGroups.ts").read_text(encoding="utf-8")
    assert _ids(source, "SETTINGS_HUB_IDS") == set(WINDOW_GROUPS["settings"])
