"""install.sh keeps headless Linux venvs isolated from host packages (#456, #1018).

The venv block of install.sh runs on its own with stubbed helpers: ``uname``
answers Linux, ``run_spin`` records the venv command instead of running it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

INSTALL_SH = Path(__file__).resolve().parents[3] / "install" / "install.sh"
BLOCK_START = "# Linux DESKTOP venvs include system site-packages"
BLOCK_END = "ok 'virtual environment ready'"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="runs the POSIX shell block",
)


def _venv_block() -> str:
    text = INSTALL_SH.read_text(encoding="utf-8")
    start = text.index(BLOCK_START)
    return text[start : text.index(BLOCK_END, start)]


def _run(tmp_path: Path, args: list[str], existing: str | None) -> tuple[str, bool]:
    venv = tmp_path / ".venv"
    venv_python = venv / "bin" / "python"
    if existing is not None:
        venv_python.parent.mkdir(parents=True, exist_ok=True)
        venv_python.write_text("#!/bin/sh\n", encoding="utf-8")
        venv_python.chmod(0o755)
        (venv / "pyvenv.cfg").write_text(
            f"home = /usr/bin\ninclude-system-site-packages = {existing}\n",
            encoding="utf-8",
        )
    script = (
        "set -euo pipefail\n"
        "uname() { echo Linux; }\n"
        "note() { echo \"NOTE: $1\"; }\n"
        "run_spin() { shift; echo \"VENV: $*\"; }\n"
        f'VENV_PATH="{venv}"\n'
        f'VENV_PYTHON="{venv_python}"\n'
        'PYTHON_EXE="python3"\n'
        + _venv_block()
    )
    result = subprocess.run(
        ["bash", "-s", "--", *args],
        input=script,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return result.stdout, venv_python.exists()


def _created(out: str) -> str | None:
    for line in out.splitlines():
        if line.startswith("VENV: "):
            return line[len("VENV: ") :]
    return None


def test_headless_creates_an_isolated_venv(tmp_path: Path) -> None:
    out, _ = _run(tmp_path, ["--headless", "--no-launch"], existing=None)
    created = _created(out)
    assert created is not None and "-m venv" in created
    assert "--system-site-packages" not in created


def test_desktop_links_system_site_packages(tmp_path: Path) -> None:
    out, _ = _run(tmp_path, ["--no-launch"], existing=None)
    assert "--system-site-packages" in (_created(out) or "")


def test_with_desktop_wins_over_headless(tmp_path: Path) -> None:
    out, _ = _run(tmp_path, ["--headless", "--with-desktop"], existing=None)
    assert "--system-site-packages" in (_created(out) or "")


def test_headless_rebuilds_a_venv_that_links_host_packages(tmp_path: Path) -> None:
    out, still_there = _run(tmp_path, ["--headless"], existing="true")
    assert not still_there
    assert "isolated from host packages" in out
    assert "--system-site-packages" not in (_created(out) or "")


def test_headless_keeps_an_already_isolated_venv(tmp_path: Path) -> None:
    out, still_there = _run(tmp_path, ["--headless"], existing="false")
    assert still_there
    assert _created(out) is None
    assert "rebuilding" not in out


def test_desktop_keeps_a_matching_venv_and_rebuilds_an_isolated_one(tmp_path: Path) -> None:
    out, still_there = _run(tmp_path, [], existing="true")
    assert still_there and _created(out) is None
    out, still_there = _run(tmp_path, [], existing="false")
    assert not still_there
    assert "--system-site-packages" in (_created(out) or "")
