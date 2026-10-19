"""An autostart entry written before the install folder moved still counts as current.

The move leaves a link (a junction on Windows, a symlink elsewhere) at the
earlier path, so an entry that names the interpreter and working folder by
that path still starts this install. Judged by its text alone it looked like
"a different install": on Windows the boot repair cannot rewrite the logon task
without an elevation prompt, writes the startup shortcut instead, and the app
then starts twice at every login. Real links on the real filesystem; the task
and shortcut read-backs are the existing injected fakes.
"""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

import dodaios.autostart.macos as macos
from dodaios.autostart.linux import LinuxAutostart
from dodaios.autostart.macos import MacOSAutostart
from dodaios.autostart.paths import same_path
from dodaios.autostart.protocol import LaunchSpec
from dodaios.autostart.windows import WindowsAutostart, _TaskInfo
from dodaios.core.identity_migration import create_directory_link

ARGS = ("-m", "dodaios.ui.web.launcher")


def _moved_install(tmp_path: Path) -> tuple[Path, Path]:
    """``(current, legacy)``: the install folder and the link at its earlier name."""
    current = tmp_path / ".dodaios"
    for folder in ("Scripts", "bin"):
        (current / ".venv" / folder).mkdir(parents=True)
    (current / ".venv" / "Scripts" / "pythonw.exe").write_bytes(b"")
    (current / ".venv" / "bin" / "python").write_bytes(b"")
    legacy = tmp_path / ".personal-jarvis"
    create_directory_link(legacy, current)
    return current, legacy


# --------------------------------------------------------------------------- #
# The comparison                                                               #
# --------------------------------------------------------------------------- #
def test_same_path_matches_text_case_blind_on_windows_only() -> None:
    assert same_path(r"C:\A\B", "c:/a/b", windows=True)
    assert not same_path("/A/B", "/a/b")


def test_same_path_matches_through_a_link(tmp_path: Path) -> None:
    current, legacy = _moved_install(tmp_path)
    python = Path(".venv") / "bin" / "python"
    assert same_path(str(legacy / python), str(current / python))
    assert same_path(str(legacy), str(current), windows=True)


def test_same_path_never_matches_a_missing_path_by_identity(tmp_path: Path) -> None:
    assert not same_path(str(tmp_path / "gone"), str(tmp_path))
    assert same_path("", "")
    assert not same_path("", str(tmp_path))


# --------------------------------------------------------------------------- #
# Windows: the logon task and the startup shortcut                             #
# --------------------------------------------------------------------------- #
def _windows(task: _TaskInfo | None, *, shortcut_present: bool = False):
    calls: list[str] = []
    manager = WindowsAutostart(
        task_probe=lambda: task,
        run_elevated=lambda script: calls.append("elevate") or False,
        shortcut_present=lambda: shortcut_present,
        shortcut_matches=lambda spec: False,
        write_shortcut=lambda spec: calls.append("write_shortcut"),
        remove_shortcut=lambda: calls.append("remove_shortcut"),
    )
    return manager, calls


def test_a_task_reached_through_the_earlier_folder_name_is_current(tmp_path: Path) -> None:
    current, legacy = _moved_install(tmp_path)
    spec = LaunchSpec(
        program=str(current / ".venv" / "Scripts" / "pythonw.exe"),
        args=ARGS,
        working_dir=str(current),
    )
    task = _TaskInfo(
        execute=str(legacy / ".venv" / "Scripts" / "pythonw.exe"),
        arguments=" ".join(ARGS),
        working_dir=str(legacy),
    )
    manager, calls = _windows(task)

    assert manager.status(spec).matches_spec is True
    # The boot repair (never interactive) leaves it alone: no second entry.
    manager.install(spec, interactive=False)
    assert "write_shortcut" not in calls
    assert "elevate" not in calls


def test_a_task_pointing_at_another_folder_is_still_stale(tmp_path: Path) -> None:
    current, _legacy = _moved_install(tmp_path)
    other = tmp_path / "other"
    (other / ".venv" / "Scripts").mkdir(parents=True)
    (other / ".venv" / "Scripts" / "pythonw.exe").write_bytes(b"")
    spec = LaunchSpec(
        program=str(current / ".venv" / "Scripts" / "pythonw.exe"),
        args=ARGS,
        working_dir=str(current),
    )
    task = _TaskInfo(
        execute=str(other / ".venv" / "Scripts" / "pythonw.exe"),
        arguments=" ".join(ARGS),
        working_dir=str(other),
    )
    manager, _calls = _windows(task)

    assert manager.status(spec).matches_spec is False


# --------------------------------------------------------------------------- #
# macOS: the LaunchAgent                                                       #
# --------------------------------------------------------------------------- #
def test_a_launch_agent_written_from_the_earlier_folder_name_is_current(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    current, legacy = _moved_install(tmp_path)
    agents = tmp_path / "LaunchAgents"
    monkeypatch.setattr(macos, "_agents_dir", lambda: agents)
    manager = MacOSAutostart()
    bundle_args = ("-W", "-a", "/Users/u/Applications/Personal Jarvis.app")
    manager.install(LaunchSpec("/usr/bin/open", bundle_args, str(legacy)))

    now = LaunchSpec("/usr/bin/open", bundle_args, str(current))
    assert manager.status(now).matches_spec is True

    # Another folder is another install.
    plist = next(agents.iterdir())
    data = plistlib.loads(plist.read_bytes())
    data["WorkingDirectory"] = str(tmp_path)
    plist.write_bytes(plistlib.dumps(data))
    assert manager.status(now).matches_spec is False


# --------------------------------------------------------------------------- #
# Linux: the XDG autostart entry                                               #
# --------------------------------------------------------------------------- #
def test_a_desktop_entry_written_from_the_earlier_folder_name_is_current(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    current, legacy = _moved_install(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    manager = LinuxAutostart()
    manager.install(LaunchSpec(str(legacy / ".venv" / "bin" / "python"), ARGS, str(legacy)))

    now = LaunchSpec(str(current / ".venv" / "bin" / "python"), ARGS, str(current))
    assert manager.status(now).matches_spec is True
    # A different command in the same folder is a different entry.
    other_args = LaunchSpec(now.program, (*ARGS, "--background-service"), now.working_dir)
    assert manager.status(other_args).matches_spec is False
