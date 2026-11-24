"""The shell installers' terminal look degrades cleanly (Stage 1).

``install.sh`` and ``install.ps1`` run before Python exists, so each carries
its own copy of the installer look between ``installer-ui`` markers. These
tests run those real blocks in a real shell, the way the bootstrap meets real
terminals: captured output (no TTY), ``NO_COLOR``, no Unicode, a narrow
window, and ``FORCE_COLOR`` for a log that renders colour.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS

ROOT = Path(__file__).resolve().parents[3]
INSTALL_SH = ROOT / "install" / "install.sh"
INSTALL_PS1 = ROOT / "install" / "install.ps1"
BEGIN = "# --- installer-ui begin"
END = "# --- installer-ui end"
ESC = "\x1b"
HALF_BLOCKS = ("▀", "▄")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


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
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
needs_bash = pytest.mark.skipif(BASH is None, reason="no usable bash on this host")
needs_powershell = pytest.mark.skipif(POWERSHELL is None, reason="no PowerShell on this host")

SH_DRIVER = """set -euo pipefail
. "$UI_BLOCK"
ui_hero 'Installing on Testing 1.0 (x86_64)'
phase '1/6' 'Prerequisites'
ok 'Python 3.12.3' '' '/usr/bin/python3'
ok 'Downloaded Dodaios v5.7.0' 14
skip 'Node.js not found — optional'
warn 'The connection dropped → retrying…'
run_spin 'Virtual environment' true
err 'The download kept failing.'
note 'Check your connection · then run it again.'
stopped 'The install stopped here.'
"""

PS_DRIVER = """$ErrorActionPreference = 'Stop'
. $env:UI_BLOCK
Write-Hero 'Installing on Testing 1.0 (x64)' "Open source $GSkip MIT"
Write-Phase '1/6' 'Prerequisites'
Write-Ok 'Python 3.12.3' 0 'C:\\Python312\\python.exe'
Write-Ok 'Downloaded Dodaios v5.7.0' 14.2
Write-Skip 'Node.js not found: optional'
Write-Warn 'The connection dropped: retrying'
Write-Err 'The download kept failing.'
Write-Note 'Check your connection, then run it again.'
Write-Stopped 'The install stopped here.'
"""


def _base_env(**extra: str) -> dict[str, str]:
    env = {
        name: value
        for name, value in os.environ.items()
        if name not in {"NO_COLOR", "FORCE_COLOR", "COLORTERM", "COLUMNS", "TERM_PROGRAM",
                        "CI", "WT_SESSION", "WSL_DISTRO_NAME", "LC_ALL", "LC_CTYPE", "LANG"}
        and not name.upper().startswith(("JARVIS_", "DODAIOS_"))
    }
    env.update(extra)
    return env


def _block(path: Path, tmp_path: Path, suffix: str) -> Path:
    source = path.read_text(encoding="utf-8")
    assert BEGIN in source and END in source, f"the installer-ui markers vanished from {path.name}"
    block = tmp_path / f"ui_block{suffix}"
    # From the line after the begin marker (its own line names this test).
    body = source.split(BEGIN, 1)[1].split("\n", 1)[1].split(END, 1)[0]
    block.write_text(body, encoding="utf-8", newline="\n")
    return block


def _run_sh(tmp_path: Path, **env: str) -> str:
    assert BASH is not None
    driver = tmp_path / "driver.sh"
    driver.write_text(SH_DRIVER, encoding="utf-8", newline="\n")
    block = _block(INSTALL_SH, tmp_path, ".sh")
    result = subprocess.run(  # noqa: S603 - test-controlled command
        [BASH, str(driver)],
        capture_output=True,
        timeout=60,
        env=_base_env(UI_BLOCK=str(block).replace("\\", "/"), **env),
        creationflags=NO_WINDOW_CREATIONFLAGS,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout.decode("utf-8")


def _run_ps(tmp_path: Path, **env: str) -> str:
    assert POWERSHELL is not None
    driver = tmp_path / "driver.ps1"
    driver.write_text(PS_DRIVER, encoding="utf-8")
    block = _block(INSTALL_PS1, tmp_path, ".ps1")
    result = subprocess.run(  # noqa: S603 - test-controlled command
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(driver)],
        capture_output=True,
        timeout=120,
        env=_base_env(UI_BLOCK=str(block), **env),
        creationflags=NO_WINDOW_CREATIONFLAGS,
    )
    assert result.returncode == 0, (result.stderr + result.stdout).decode("utf-8", "replace")
    return result.stdout.decode("utf-8")


def _visible_lines(text: str) -> list[str]:
    return [ANSI.sub("", line) for line in text.replace("\r\n", "\n").split("\n")]


# ----------------------------------------------------------------- install.sh
@needs_bash
def test_sh_without_a_terminal_prints_no_escape_sequence(tmp_path: Path) -> None:
    out = _run_sh(tmp_path, LANG="C.UTF-8", COLUMNS="100")
    assert ESC not in out
    assert "[1/6] Prerequisites" in out
    assert "DODAIOS" in out and "[STOPPED]" in out


@needs_bash
def test_sh_no_color_wins_over_force_color(tmp_path: Path) -> None:
    out = _run_sh(tmp_path, LANG="C.UTF-8", COLUMNS="100", NO_COLOR="1", FORCE_COLOR="1")
    assert ESC not in out


@needs_bash
def test_sh_draws_the_hero_where_colour_unicode_and_room_allow(tmp_path: Path) -> None:
    out = _run_sh(
        tmp_path, LANG="C.UTF-8", COLUMNS="100", FORCE_COLOR="1", COLORTERM="truecolor"
    )
    assert ESC in out
    assert any(block in out for block in HALF_BLOCKS)
    assert "38;2;" in out  # 24-bit gold
    assert max(len(line) for line in _visible_lines(out)) <= 100


@pytest.mark.parametrize(
    "env",
    [
        {"LANG": "C"},
        {"LANG": "C.UTF-8", "JARVIS_INSTALL_ASCII": "1"},
        {"LANG": "C.UTF-8", "TERM": "linux"},
    ],
)
@needs_bash
def test_sh_without_unicode_prints_only_ascii(tmp_path: Path, env: dict[str, str]) -> None:
    out = _run_sh(tmp_path, COLUMNS="100", FORCE_COLOR="1", **env)
    assert out.isascii(), sorted({c for c in out if not c.isascii()})
    assert "->" in out and "..." in out  # the typography, spelled out


@pytest.mark.parametrize(("columns", "art"), [("100", "figure"), ("64", "wordmark"), ("40", None)])
@needs_bash
def test_sh_fits_a_narrow_window(tmp_path: Path, columns: str, art: str | None) -> None:
    out = _run_sh(tmp_path, LANG="C.UTF-8", COLUMNS=columns, FORCE_COLOR="1", COLORTERM="truecolor")
    hero = [line for line in _visible_lines(out) if any(b in line for b in HALF_BLOCKS)]
    if art is None:
        assert hero == []
        assert "DODAIOS" in out  # the plain title stands in
    else:
        assert hero, out
        assert max(len(line.rstrip()) for line in hero) <= int(columns)
    if art == "wordmark":
        # No room beside the figure: the wordmark alone, five rows of it.
        assert len(hero) == 5


# ----------------------------------------------------------------- install.ps1
@needs_powershell
def test_ps1_redirected_output_prints_no_escape_sequence(tmp_path: Path) -> None:
    out = _run_ps(tmp_path, COLUMNS="100")
    assert ESC not in out
    assert "[1/6] Prerequisites" in out
    assert "DODAIOS" in out and "[STOPPED]" in out


@needs_powershell
def test_ps1_no_color_wins_over_force_color(tmp_path: Path) -> None:
    out = _run_ps(tmp_path, COLUMNS="100", NO_COLOR="1", FORCE_COLOR="1")
    assert ESC not in out


@needs_powershell
def test_ps1_force_color_draws_the_hero(tmp_path: Path) -> None:
    out = _run_ps(tmp_path, COLUMNS="100", FORCE_COLOR="1", COLORTERM="truecolor")
    assert ESC in out
    assert any(block in out for block in HALF_BLOCKS)
    assert max(len(line) for line in _visible_lines(out)) <= 100


@needs_powershell
def test_ps1_ascii_switch_prints_only_ascii(tmp_path: Path) -> None:
    for env in ({"JARVIS_INSTALL_ASCII": "1"}, {"DODAIOS_INSTALL_ASCII": "1"}):
        out = _run_ps(tmp_path, COLUMNS="100", FORCE_COLOR="1", **env)
        assert out.isascii(), sorted({c for c in out if not c.isascii()})


@pytest.mark.parametrize(("columns", "rows"), [("64", 5), ("40", 0)])
@needs_powershell
def test_ps1_fits_a_narrow_window(tmp_path: Path, columns: str, rows: int) -> None:
    out = _run_ps(tmp_path, COLUMNS=columns, FORCE_COLOR="1", COLORTERM="truecolor")
    hero = [line for line in _visible_lines(out) if any(b in line for b in HALF_BLOCKS)]
    assert len(hero) == rows
    assert all(len(line.rstrip()) <= int(columns) for line in hero)


def _stop_early_env(tmp_path: Path) -> dict[str, str]:
    # A pinned interpreter that does not exist: the prerequisite step stops
    # the run before anything is downloaded or written.
    return _base_env(
        JARVIS_PYTHON=str(tmp_path / "no-such-python.exe"),
        JARVIS_INSTALL_PREREQS="never",
        JARVIS_INSTALL_DIR=str(tmp_path / "install"),
        INSTALL_PS1=str(INSTALL_PS1),
    )


@pytest.mark.skipif(sys.platform != "win32" or POWERSHELL is None, reason="Windows PowerShell")
def test_ps1_under_irm_iex_stops_without_closing_the_session(tmp_path: Path) -> None:
    # `irm | iex` runs the script inside the person's own session: a stop must
    # leave that session (and the error on screen) alive.
    result = subprocess.run(  # noqa: S603 - test-controlled command
        [POWERSHELL, "-NoProfile", "-NoExit", "-ExecutionPolicy", "Bypass", "-Command",
         "iex (Get-Content -Raw -LiteralPath $env:INSTALL_PS1)"],
        input=b"Write-Host SESSION-ALIVE; exit 0\n",
        capture_output=True,
        timeout=180,
        env=_stop_early_env(tmp_path),
        creationflags=NO_WINDOW_CREATIONFLAGS,
    )
    out = result.stdout.decode("utf-8", "replace")
    assert "[STOPPED]" in out, out
    assert "SESSION-ALIVE" in out, out
    assert not (tmp_path / "install").exists()


@pytest.mark.skipif(sys.platform != "win32" or POWERSHELL is None, reason="Windows PowerShell")
def test_ps1_run_as_a_file_still_exits_with_its_code(tmp_path: Path) -> None:
    # The verifying installer runs install.ps1 as a file and reads its exit code.
    result = subprocess.run(  # noqa: S603 - test-controlled command
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(INSTALL_PS1)],
        capture_output=True,
        timeout=180,
        env=_stop_early_env(tmp_path),
        creationflags=NO_WINDOW_CREATIONFLAGS,
    )
    assert result.returncode == 1, result.stdout.decode("utf-8", "replace")
    assert "[STOPPED]" in result.stdout.decode("utf-8", "replace")


# ----------------------------------------------------------------- one look
def _art(source: str, start: str) -> list[str]:
    body = source.split(start, 1)[1].split(")", 1)[0]
    return re.findall(r"'([.#s]+)'", body)


def test_both_shells_draw_the_same_figure_and_wordmark() -> None:
    sh = INSTALL_SH.read_text(encoding="utf-8")
    ps1 = INSTALL_PS1.read_text(encoding="utf-8")
    pairs = (("UI_MASCOT=(", "$UiMascot = @("), ("UI_WORDMARK=(", "$UiWordmark = @("))
    for sh_name, ps_name in pairs:
        sh_rows, ps_rows = _art(sh, sh_name), _art(ps1, ps_name)
        assert sh_rows and sh_rows == ps_rows
        assert len({len(row) for row in sh_rows}) == 1, "ragged rows"
    # Side by side: two indent + figure + three gap + wordmark fits 80 columns.
    assert 2 + len(_art(sh, "UI_MASCOT=(")[0]) + 3 + len(_art(sh, "UI_WORDMARK=(")[0]) < 80
