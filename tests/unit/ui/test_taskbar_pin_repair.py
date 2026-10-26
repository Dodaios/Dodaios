"""A taskbar pin made before a rename must follow the app to its new install.

Report 2026-10-26: the pinned taskbar button showed a blank page. The pin's
``.lnk`` still named ``jarvis\\assets\\icons\\jarvis.ico`` and
``-m jarvis.ui.web.launcher``, both gone after the rename to ``dodaios``.
Start-Menu and Desktop shortcuts were repaired on every start; the pin was not.

These tests write real shortcuts, but only into ``tmp_path``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from dodaios.ui import icon_utils

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="taskbar pins are Windows-only"
)

_AUMID = "PersonalJarvis.Test.TaskbarPin"


def _stale_pin(lnk: Path, aumid: str) -> None:
    lnk.parent.mkdir(parents=True, exist_ok=True)
    assert icon_utils._write_branded_shortcut(
        lnk,
        target=Path(sys.executable),
        ico=lnk.parent / "gone" / "jarvis.ico",
        aumid=aumid,
        display_name="Old name",
    )


def _read(lnk: Path) -> tuple[str, str, str]:
    from win32com.client import Dispatch

    sc = Dispatch("WScript.Shell").CreateShortcut(str(lnk))
    return sc.TargetPath, sc.Arguments, sc.IconLocation


@pytest.fixture
def pins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(icon_utils, "_installer_owns_shell_registration", lambda _w: False)
    monkeypatch.setattr(icon_utils, "_interpreter_may_own_the_launcher_shortcut", lambda: True)
    monkeypatch.setattr(icon_utils, "_shortcut_launch_target", lambda: Path(sys.executable))
    return tmp_path / "TaskBar"


def test_stale_pin_of_this_app_is_rewritten_in_place(pins: Path) -> None:
    lnk = pins / "Personal Jarvis.lnk"
    _stale_pin(lnk, _AUMID)
    ico = icon_utils.project_icon_path()

    assert icon_utils.repair_taskbar_pins(aumid=_AUMID, icon_path=ico, pins_dir=pins) == 1

    target, args, icon = _read(lnk)
    assert icon_utils._same_file_path(target, Path(sys.executable))
    assert args == icon_utils._launcher_arguments()
    assert icon_utils._same_file_path(icon.rsplit(",", 1)[0], ico)
    assert icon_utils._read_shortcut_aumid(lnk) == _AUMID
    # Second run finds nothing to do.
    assert icon_utils.repair_taskbar_pins(aumid=_AUMID, icon_path=ico, pins_dir=pins) == 0


def test_pins_of_other_apps_are_left_alone(pins: Path) -> None:
    lnk = pins / "Other.lnk"
    _stale_pin(lnk, "Someone.Else")
    before = _read(lnk)

    assert icon_utils.repair_taskbar_pins(
        aumid=_AUMID, icon_path=icon_utils.project_icon_path(), pins_dir=pins
    ) == 0
    assert _read(lnk) == before


def test_missing_pins_folder_is_a_no_op(tmp_path: Path, pins: Path) -> None:
    assert icon_utils.repair_taskbar_pins(aumid=_AUMID, pins_dir=tmp_path / "nope") == 0
