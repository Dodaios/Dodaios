"""The shell uninstaller's fallback removes only this install's Linux entries.

Without a working virtual environment ``install/uninstall.sh`` cannot ask the
tested Python cleanup, so it removes the desktop entries itself: the login
autostart entry under the current and the earlier file name, and the
application-menu entry under the earlier name. An entry under the earlier name
can belong to another install on the same machine, so each one goes only when
its working folder is this install's folder, also through the link the install
folder move left at the earlier path. The block runs in a real bash against a
real temporary home.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from dodaios.core import branding
from dodaios.core.identity_migration import create_directory_link
from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS

_ROOT = Path(__file__).resolve().parents[3]
UNINSTALL_SH = _ROOT / "install" / "uninstall.sh"
CURRENT_ENTRY = branding.LINUX_DESKTOP_ENTRY_FILE_NAME
LEGACY_ENTRY = branding.LEGACY_LINUX_DESKTOP_ENTRY_FILE_NAMES[0]


def _find_bash() -> str | None:
    git = shutil.which("git")
    if git:
        for rel in ("../bin/bash.exe", "../../bin/bash.exe", "../usr/bin/bash.exe"):
            candidate = (Path(git).parent / rel).resolve()
            if candidate.exists():
                return str(candidate)
    bash = shutil.which("bash")
    # On Windows the first ``bash`` on PATH can be the WSL launcher stub.
    if bash and not any(part in bash.lower() for part in ("windowsapps", "system32")):
        return bash
    return None


BASH = _find_bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="no usable bash on this host")

DRIVER = """set -euo pipefail
note() { printf 'NOTE|%s\\n' "$1"; }
LINUX_DESKTOP_ENTRY_FILE_NAME="$TEST_CURRENT_ENTRY"
LEGACY_LINUX_DESKTOP_ENTRY_FILE_NAMES="$TEST_LEGACY_ENTRY"
remove_linux_entries_of_install() {
. "$BLOCK_FILE"
}
remove_linux_entries_of_install "$TEST_INSTALL_DIR"
printf 'DONE\\n'
"""


def _sh_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _block() -> str:
    text = UNINSTALL_SH.read_text(encoding="utf-8")
    begin = "# --- uninstall-linux-entries begin"
    end = "# --- uninstall-linux-entries end"
    assert begin in text and end in text, "the uninstall-linux-entries markers vanished"
    body = text.split(begin, 1)[1].split(end, 1)[0]
    return body.split("\n", 1)[1]


def _entry(path: Path, working_dir: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Desktop Entry]\nType=Application\nName=Personal Jarvis\n"
        "Exec=/usr/bin/python3 -m jarvis.ui.web.launcher\n"
        f"Path={_sh_path(working_dir)}\n",
        encoding="utf-8",
    )
    return path


def _run(tmp_path: Path, home: Path, install_dir: Path) -> subprocess.CompletedProcess[str]:
    block = tmp_path / "linux-entries.sh"
    block.write_text(_block(), encoding="utf-8", newline="\n")
    driver = tmp_path / "linux-entries-driver.sh"
    driver.write_text(DRIVER, encoding="utf-8", newline="\n")
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("XDG_DATA_HOME", "XDG_CONFIG_HOME")
    }
    env.update(
        HOME=_sh_path(home),
        BLOCK_FILE=_sh_path(block),
        TEST_INSTALL_DIR=_sh_path(install_dir),
        TEST_CURRENT_ENTRY=CURRENT_ENTRY,
        TEST_LEGACY_ENTRY=LEGACY_ENTRY,
    )
    return subprocess.run(  # noqa: S603 - test-controlled command
        [str(BASH), str(driver)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=env,
        creationflags=NO_WINDOW_CREATIONFLAGS,
    )


def test_the_fallback_removes_this_installs_entries_under_both_names(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    install = home / branding.DEFAULT_INSTALL_DIR_NAME
    install.mkdir(parents=True)
    earlier_folder = home / branding.LEGACY_DEFAULT_INSTALL_DIR_NAMES[0]
    create_directory_link(earlier_folder, install)
    autostart = home / ".config" / "autostart"
    apps = home / ".local" / "share" / "applications"

    # Written before the folder moved: the earlier name, through the link.
    ours_earlier = _entry(autostart / LEGACY_ENTRY, earlier_folder)
    ours_current = _entry(autostart / CURRENT_ENTRY, install)
    ours_menu = _entry(apps / LEGACY_ENTRY, install)

    result = _run(tmp_path, home, install)

    assert result.returncode == 0, result.stderr + result.stdout
    assert "DONE" in result.stdout
    assert not ours_earlier.exists()
    assert not ours_current.exists()
    assert not ours_menu.exists()


def test_the_fallback_keeps_an_earlier_entry_of_another_install(tmp_path: Path) -> None:
    home = tmp_path / "home"
    install = home / branding.DEFAULT_INSTALL_DIR_NAME
    install.mkdir(parents=True)
    other_install = tmp_path / "another checkout"
    other_install.mkdir()
    autostart = home / ".config" / "autostart"
    apps = home / ".local" / "share" / "applications"
    theirs_autostart = _entry(autostart / LEGACY_ENTRY, other_install)
    theirs_menu = _entry(apps / LEGACY_ENTRY, other_install)

    result = _run(tmp_path, home, install)

    assert result.returncode == 0, result.stderr + result.stdout
    assert theirs_autostart.exists()
    assert theirs_menu.exists()
    assert "it starts another install" in result.stdout
