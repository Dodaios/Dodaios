"""The shell installers answer to ``DODAIOS_INSTALL_*`` as well as ``JARVIS_INSTALL_*``.

``install.sh`` and ``install.ps1`` run before Python exists, so they cannot use
``jarvis.core.env_prefix``. Each carries one small block that folds the new
spelling into the old one the rest of the script reads. These tests run those
real blocks, extracted from the scripts, in a real shell.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from jarvis.core import env_prefix
from jarvis.core.process_utils import NO_WINDOW_CREATIONFLAGS

_ROOT = Path(__file__).resolve().parents[3]
INSTALL_SH = _ROOT / "install" / "install.sh"
INSTALL_PS1 = _ROOT / "install" / "install.ps1"
UNINSTALL_SH = _ROOT / "install" / "uninstall.sh"
UNINSTALL_PS1 = _ROOT / "install" / "uninstall.ps1"

BLOCK_BEGIN = "# --- install-option-names begin"
BLOCK_END = "# --- install-option-names end"
SH_OPTIONS = ("REPO", "REF", "DIR", "PREREQS", "YES")
PS_OPTIONS = ("REPO", "REF", "DIR", "PREREQS")

SH_DRIVER = """#!/usr/bin/env bash
set -euo pipefail
source "$BLOCK_FILE"
for option in REPO REF DIR PREREQS YES; do
    name="JARVIS_INSTALL_$option"
    printf 'VALUE|%s|%s\\n' "$option" "${!name:-}"
done
bash -c 'printf "CHILD|%s\\n" "${JARVIS_INSTALL_DIR:-}"'
"""

PS_DRIVER = """$ErrorActionPreference = 'Stop'
function Write-Note([string]$Text) { Write-Host "NOTE|$Text" }
. $env:TEST_FUNCTION_FILE
Use-InstallOptionNames
foreach ($Option in 'REPO', 'REF', 'DIR', 'PREREQS') {
    $Value = [Environment]::GetEnvironmentVariable("JARVIS_INSTALL_$Option")
    Write-Host "VALUE|$Option|$Value"
}
"""


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
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")

needs_bash = pytest.mark.skipif(BASH is None, reason="no usable bash on this host")
needs_powershell = pytest.mark.skipif(POWERSHELL is None, reason="no PowerShell on this host")


def _base_env() -> dict[str, str]:
    """This process's environment without any prefixed variable or sync record."""
    return {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith(("JARVIS_", "DODAIOS_"))
    }


def _run(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - test-controlled command
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=env,
        creationflags=NO_WINDOW_CREATIONFLAGS,
    )


def _values(output: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in output.splitlines():
        if line.startswith("VALUE|"):
            _tag, option, value = line.split("|", 2)
            found[option] = value
    return found


def _run_sh(tmp_path: Path, **variables: str) -> subprocess.CompletedProcess[str]:
    source = INSTALL_SH.read_text(encoding="utf-8")
    assert BLOCK_BEGIN in source and BLOCK_END in source, (
        "the install-option-names extraction markers vanished from install.sh"
    )
    block = tmp_path / "block.sh"
    block.write_text(
        source.split(BLOCK_BEGIN, 1)[1].split(BLOCK_END, 1)[0], encoding="utf-8", newline="\n"
    )
    driver = tmp_path / "driver.sh"
    driver.write_text(SH_DRIVER, encoding="utf-8", newline="\n")
    env = {**_base_env(), "BLOCK_FILE": str(block).replace("\\", "/"), **variables}
    result = _run([BASH, str(driver)], env)
    assert result.returncode == 0, result.stderr
    return result


def _run_ps(tmp_path: Path, **variables: str) -> subprocess.CompletedProcess[str]:
    source = INSTALL_PS1.read_text(encoding="utf-8")
    match = re.search(r"^function Use-InstallOptionNames \{\r?\n.*?^\}\r?$", source, re.S | re.M)
    assert match is not None, "Use-InstallOptionNames vanished from install.ps1"
    assert re.search(r"^Use-InstallOptionNames\r?$", source, re.M), "the function is not called"
    function_file = tmp_path / "function.ps1"
    function_file.write_text(match.group(0), encoding="utf-8")
    driver = tmp_path / "driver.ps1"
    driver.write_text(PS_DRIVER, encoding="utf-8")
    env = {**_base_env(), "TEST_FUNCTION_FILE": str(function_file), **variables}
    result = _run(
        [
            POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(driver),
        ],
        env,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return result


# ---------------------------------------------------------------------------
# install.sh
# ---------------------------------------------------------------------------


@needs_bash
def test_install_sh_reads_every_option_under_the_new_prefix(tmp_path: Path) -> None:
    result = _run_sh(
        tmp_path, **{f"DODAIOS_INSTALL_{option}": f"new-{option}" for option in SH_OPTIONS}
    )

    assert _values(result.stdout) == {option: f"new-{option}" for option in SH_OPTIONS}
    # installer.py and every other child read the old spelling too.
    assert "CHILD|new-DIR" in result.stdout
    assert result.stderr == ""


@needs_bash
def test_install_sh_keeps_reading_the_old_prefix(tmp_path: Path) -> None:
    result = _run_sh(tmp_path, JARVIS_INSTALL_DIR="old-dir", JARVIS_INSTALL_REF="old-ref")

    values = _values(result.stdout)
    assert values["DIR"] == "old-dir" and values["REF"] == "old-ref"
    assert values["REPO"] == "" and result.stderr == ""


@needs_bash
def test_install_sh_lets_the_new_name_win_and_names_the_clash(tmp_path: Path) -> None:
    result = _run_sh(
        tmp_path, JARVIS_INSTALL_DIR="old-secret-dir", DODAIOS_INSTALL_DIR="new-secret-dir"
    )

    assert _values(result.stdout)["DIR"] == "new-secret-dir"
    assert "DODAIOS_INSTALL_DIR" in result.stderr and "JARVIS_INSTALL_DIR" in result.stderr
    assert "secret" not in result.stderr



# ---------------------------------------------------------------------------
# install.ps1
# ---------------------------------------------------------------------------


@needs_powershell
def test_install_ps1_reads_every_option_under_the_new_prefix(tmp_path: Path) -> None:
    result = _run_ps(
        tmp_path, **{f"DODAIOS_INSTALL_{option}": f"new-{option}" for option in PS_OPTIONS}
    )

    assert _values(result.stdout) == {option: f"new-{option}" for option in PS_OPTIONS}
    assert "NOTE|" not in result.stdout


@needs_powershell
def test_install_ps1_keeps_reading_the_old_prefix(tmp_path: Path) -> None:
    result = _run_ps(tmp_path, JARVIS_INSTALL_DIR="old-dir")

    assert _values(result.stdout)["DIR"] == "old-dir"
    assert "NOTE|" not in result.stdout


@needs_powershell
def test_install_ps1_lets_the_new_name_win_and_names_the_clash(tmp_path: Path) -> None:
    result = _run_ps(
        tmp_path, JARVIS_INSTALL_DIR="old-secret-dir", DODAIOS_INSTALL_DIR="new-secret-dir"
    )

    assert _values(result.stdout)["DIR"] == "new-secret-dir"
    notes = [line for line in result.stdout.splitlines() if line.startswith("NOTE|")]
    assert len(notes) == 1
    assert "DODAIOS_INSTALL_DIR" in notes[0] and "JARVIS_INSTALL_DIR" in notes[0]
    assert "secret" not in notes[0]



# ---------------------------------------------------------------------------
# Both scripts, and the uninstallers, spell the same contract
# ---------------------------------------------------------------------------


def test_the_two_installers_adopt_the_options_each_one_reads() -> None:
    shell = INSTALL_SH.read_text(encoding="utf-8")
    powershell = INSTALL_PS1.read_text(encoding="utf-8")
    assert f"for option in {' '.join(SH_OPTIONS)}; do" in shell
    assert "foreach ($Option in " + ", ".join(f"'{o}'" for o in PS_OPTIONS) + ")" in powershell
    # Every JARVIS_INSTALL_* option a script reads is one it also adopts.
    for source, adopted in ((shell, SH_OPTIONS), (powershell, PS_OPTIONS)):
        read = set(re.findall(r"JARVIS_INSTALL_([A-Z_]+)", source))
        assert read <= set(adopted), sorted(read - set(adopted))


@pytest.mark.parametrize("path", [INSTALL_SH, INSTALL_PS1, UNINSTALL_SH, UNINSTALL_PS1])
def test_the_scripts_spell_the_prefixes_the_app_uses(path: Path) -> None:
    new_prefix, old_prefix = env_prefix._PREFIXES[0]
    source = path.read_text(encoding="utf-8")
    assert f"{new_prefix}INSTALL_" in source
    assert f"{old_prefix}INSTALL_" in source


@needs_bash
@pytest.mark.parametrize(
    ("variables", "expected"),
    [
        ({"DODAIOS_INSTALL_DIR": "new-dir"}, "new-dir"),
        ({"JARVIS_INSTALL_DIR": "old-dir"}, "old-dir"),
        ({"JARVIS_INSTALL_DIR": "old-dir", "DODAIOS_INSTALL_DIR": "new-dir"}, "new-dir"),
        ({}, "HOME/.default"),
    ],
)
def test_the_shell_uninstaller_targets_the_directory_either_name_gives(
    tmp_path: Path, variables: dict[str, str], expected: str
) -> None:
    # The line that picks the directory: run exactly that, never the removal
    # below it.
    source = UNINSTALL_SH.read_text(encoding="utf-8")
    match = re.search(r"^INSTALL_DIR=[^\n]*\n", source, re.M)
    assert match is not None, "uninstall.sh no longer resolves INSTALL_DIR the tested way"
    script = tmp_path / "resolve.sh"
    script.write_text(
        "set -euo pipefail\n"
        'HOME="HOME"\n'
        'DEFAULT_INSTALL_DIR_NAME=".default"\n'
        + match.group(0)
        + 'printf "%s\\n" "$INSTALL_DIR"\n',
        encoding="utf-8",
        newline="\n",
    )

    result = _run([BASH, str(script)], {**_base_env(), **variables})

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected
