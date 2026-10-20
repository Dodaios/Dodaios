"""The shell installers move an install from ``~/.personal-jarvis`` to ``~/.dodaios``.

Which folder an install run uses, and the one-time move on an update run, are
run for real here: the blocks extracted from ``install/install.sh`` and the
functions extracted from ``install/install.ps1`` and the two uninstallers, in a
real shell, against a real git checkout, a real Python running the migration
engine from the fetched commit, and real directory links (a junction on
Windows, a symlink elsewhere). The order of the steps is pinned from the
scripts' own text.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from dodaios.core import branding
from dodaios.core.identity_migration import create_directory_link, is_directory_link
from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS

REPO = Path(__file__).resolve().parents[3]
INSTALL_SH = REPO / "install" / "install.sh"
INSTALL_PS1 = REPO / "install" / "install.ps1"
UNINSTALL_SH = REPO / "install" / "uninstall.sh"
UNINSTALL_PS1 = REPO / "install" / "uninstall.ps1"
ENGINE = REPO / "dodaios" / "core" / "identity_migration.py"
ENGINE_PATH = "dodaios/core/identity_migration.py"

CURRENT = branding.DEFAULT_INSTALL_DIR_NAME
LEGACY = branding.LEGACY_DEFAULT_INSTALL_DIR_NAMES[0]
OVERRIDES = ("JARVIS_INSTALL_DIR", "DODAIOS_INSTALL_DIR")

GIT = shutil.which("git")


def _find_bash() -> str | None:
    if GIT:
        for rel in ("../bin/bash.exe", "../../bin/bash.exe", "../usr/bin/bash.exe"):
            candidate = (Path(GIT).parent / rel).resolve()
            if candidate.exists():
                return str(candidate)
    bash = shutil.which("bash")
    # On Windows the first ``bash`` on PATH can be the WSL launcher stub.
    if bash and not any(part in bash.lower() for part in ("windowsapps", "system32")):
        return bash
    return None


BASH = _find_bash()
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")

needs_git = pytest.mark.skipif(GIT is None, reason="git is not installed")
needs_bash = pytest.mark.skipif(BASH is None, reason="no usable bash on this host")
needs_powershell = pytest.mark.skipif(POWERSHELL is None, reason="no PowerShell on this host")


def _sh_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _native(path: str | Path) -> str:
    """A path as this OS spells it; Git Bash reports ``C:`` as ``/c``."""
    text = str(path)
    match = re.fullmatch(r"/([a-zA-Z])(/.*)?", text)
    if sys.platform == "win32" and match:
        text = f"{match.group(1)}:{match.group(2) or '/'}"
    return text


def _same(a: str | Path, b: str | Path) -> bool:
    return os.path.normcase(os.path.abspath(_native(a))) == os.path.normcase(
        os.path.abspath(_native(b))
    )


def _run(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - test-controlled command
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        env=env,
        creationflags=NO_WINDOW_CREATIONFLAGS,
    )


def _base_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key not in OVERRIDES}


def _block(source: Path, name: str) -> str:
    text = source.read_text(encoding="utf-8")
    begin = f"# --- {name} begin"
    end = f"# --- {name} end"
    assert begin in text and end in text, f"the {name} markers vanished from {source.name}"
    body = text.split(begin, 1)[1].split(end, 1)[0]
    # The marker line's own tail (the "(extracted by ...)" note) is not code.
    return body.split("\n", 1)[1]


def _ps_function(source: Path, name: str) -> str:
    match = re.search(
        rf"^function {re.escape(name)} *(\([^)]*\))? *\{{\r?\n.*?^\}}\r?$",
        source.read_text(encoding="utf-8"),
        re.S | re.M,
    )
    assert match is not None, f"{name} vanished from {source.name}"
    return match.group(0)


def _values(output: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in output.splitlines():
        if line.startswith("VALUE|"):
            _tag, key, value = line.split("|", 2)
            found[key] = value
    return found


def _run_powershell(script: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    assert POWERSHELL is not None
    return _run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
         str(script)],
        env,
    )


# --------------------------------------------------------------------------- #
# Order and shape, read from the scripts                                       #
# --------------------------------------------------------------------------- #
def test_sh_moves_the_folder_after_the_stop_and_before_the_checkout() -> None:
    source = INSTALL_SH.read_text(encoding="utf-8")
    update = source.split('if [ -d "$INSTALL_DIR/.git" ]; then\n', 1)[1]
    update = update.split('\nelif [ -e "$INSTALL_DIR" ]; then\n', 1)[0]
    stop = update.index("&& stop_running_app")
    move = update.index("&& migrate_install_dir")
    assert update.index(" fetch ") < stop < move < update.index(" checkout ")
    assert move < update.index("reset --quiet --hard")
    assert update.count("migrate_install_dir") == 1


def test_ps1_moves_the_folder_after_the_stop_and_before_the_checkout() -> None:
    source = INSTALL_PS1.read_text(encoding="utf-8")
    update = source.split("if (Test-Path (Join-Path $InstallDir '.git')) {\n", 1)[1]
    attempt = update.split("\n    } finally {\n", 1)[0]
    stop = attempt.index("Stop-RunningApp")
    move = attempt.index("Invoke-InstallDirMigration")
    # The git commands that follow run in the folder the move reports.
    relocate = attempt.index("Set-Location -LiteralPath $InstallDir")
    assert stop < move < relocate < attempt.index(" checkout ")
    assert attempt.count("Invoke-InstallDirMigration") == 1


def test_sh_runs_the_fetched_engine_isolated_from_the_home_directory() -> None:
    block = _block(INSTALL_SH, "migrate-install-dir")
    assert 'git -C "$INSTALL_DIR" show "origin/$BRANCH:$IDENTITY_ENGINE_PATH"' in block
    assert 'mktemp "${TMPDIR:-/tmp}/' in block
    assert '(cd "$HOME" && "$PYTHON_EXE" -I -B "$_mig_engine" migrate' in block
    assert '"$LEGACY_INSTALL_DIR" "$CURRENT_INSTALL_DIR"' in block
    assert 'rm -f "$_mig_engine"' in block


def test_ps1_writes_the_engine_byte_for_byte_and_runs_it_isolated() -> None:
    function = _ps_function(INSTALL_PS1, "Invoke-InstallDirMigration")
    # Raw bytes from git's stdout to the file: no PowerShell pipeline, which
    # would decode and re-encode the program text.
    assert "RedirectStandardOutput = $true" in function
    assert "StandardOutput.BaseStream.CopyTo($Bytes)" in function
    assert "[IO.File]::WriteAllBytes($Engine, $Bytes.ToArray())" in function
    for re_encoding in ("Out-File", "Set-Content", "Add-Content", " > "):
        assert re_encoding not in function, re_encoding
    assert "'show \"origin/' + $Branch + ':' + $IdentityEnginePath + '\"'" in function
    assert "& $pythonExe -I -B $Engine migrate $LegacyInstallDir $CurrentInstallDir" in function
    assert "[Environment]::CurrentDirectory = $env:USERPROFILE" in function
    assert "Remove-Item -LiteralPath $Engine" in function


def test_the_engine_source_is_ascii_so_no_code_page_can_alter_it() -> None:
    ENGINE.read_bytes().decode("ascii")


@pytest.mark.parametrize("source", [INSTALL_SH, INSTALL_PS1])
def test_the_archive_download_tries_the_current_name_first(source: Path) -> None:
    text = source.read_text(encoding="utf-8")
    current = text.index("dodaios-src.tar.gz")
    legacy = text.index("personal-jarvis-src.tar.gz")
    assert current < legacy
    # Both on one line: one list, tried in order.
    assert text.count("dodaios-src.tar.gz") == 1
    assert text.count("personal-jarvis-src.tar.gz") == 1
    assert text[current:legacy].count("\n") == 0


# --------------------------------------------------------------------------- #
# Which folder a run uses                                                      #
# --------------------------------------------------------------------------- #
def _home(tmp_path: Path, legacy_state: str) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    if legacy_state == "real":
        (home / LEGACY).mkdir()
    elif legacy_state == "link":
        (home / CURRENT).mkdir()
        create_directory_link(home / LEGACY, home / CURRENT)
    return home


SH_CHOICE_DRIVER = """#!/usr/bin/env bash
set -euo pipefail
source "$BLOCK_FILE"
printf 'VALUE|dir|%s\\n' "$INSTALL_DIR"
printf 'VALUE|migrate|%s\\n' "$MIGRATE_LEGACY_INSTALL_DIR"
"""

CHOICE_CASES = [
    # (legacy state, explicit dir, expected name or "explicit", migrate)
    ("absent", None, CURRENT, "0"),
    ("real", None, LEGACY, "1"),
    ("link", None, CURRENT, "0"),
    ("real", "explicit", "explicit", "0"),
]


@needs_bash
@pytest.mark.parametrize(("legacy_state", "explicit", "expected", "migrate"), CHOICE_CASES)
def test_sh_picks_the_earlier_folder_only_while_it_is_a_real_directory(
    tmp_path: Path, legacy_state: str, explicit: str | None, expected: str, migrate: str
) -> None:
    home = _home(tmp_path, legacy_state)
    block = tmp_path / "block.sh"
    block.write_text(_block(INSTALL_SH, "install-dir-choice"), encoding="utf-8", newline="\n")
    driver = tmp_path / "driver.sh"
    driver.write_text(SH_CHOICE_DRIVER, encoding="utf-8", newline="\n")
    env = {**_base_env(), "HOME": _sh_path(home), "BLOCK_FILE": _sh_path(block)}
    if explicit:
        env["JARVIS_INSTALL_DIR"] = _sh_path(tmp_path / explicit)

    result = _run([str(BASH), str(driver)], env)

    assert result.returncode == 0, result.stderr
    values = _values(result.stdout)
    wanted = tmp_path / explicit if explicit else home / expected
    assert _same(values["dir"], wanted), values
    assert values["migrate"] == migrate


PS_CHOICE_DRIVER = """$ErrorActionPreference = 'Stop'
. $env:TEST_BLOCK_FILE
Write-Host "VALUE|dir|$InstallDir"
Write-Host "VALUE|migrate|$([int]$MigrateLegacyInstallDir)"
"""


@needs_powershell
@pytest.mark.parametrize(("legacy_state", "explicit", "expected", "migrate"), CHOICE_CASES)
def test_ps1_picks_the_earlier_folder_only_while_it_is_a_real_directory(
    tmp_path: Path, legacy_state: str, explicit: str | None, expected: str, migrate: str
) -> None:
    home = _home(tmp_path, legacy_state)
    block = tmp_path / "block.ps1"
    block.write_text(_block(INSTALL_PS1, "install-dir-choice"), encoding="utf-8")
    driver = tmp_path / "driver.ps1"
    driver.write_text(PS_CHOICE_DRIVER, encoding="utf-8")
    env = {**_base_env(), "USERPROFILE": str(home), "TEST_BLOCK_FILE": str(block)}
    if explicit:
        env["JARVIS_INSTALL_DIR"] = str(tmp_path / explicit)

    result = _run_powershell(driver, env)

    assert result.returncode == 0, result.stderr + result.stdout
    values = _values(result.stdout)
    wanted = tmp_path / explicit if explicit else home / expected
    assert _same(values["dir"], wanted), values
    assert values["migrate"] == migrate


# --------------------------------------------------------------------------- #
# The move on an update run                                                    #
# --------------------------------------------------------------------------- #
# Deep temporary directories exceed the classic Windows path limit inside
# ``.git/objects``; every git run here, the scripts' included, lifts it.
_LONG_PATHS = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.longpaths",
               "GIT_CONFIG_VALUE_0": "true"}


def _git(args: list[str], cwd: Path) -> None:
    assert GIT is not None
    done = subprocess.run(  # noqa: S603 - test-controlled command
        [GIT, *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **_LONG_PATHS},
    )
    assert done.returncode == 0, done.stderr


def _legacy_checkout(tmp_path: Path, *, with_engine: bool = True) -> Path:
    """``~/.personal-jarvis`` cloned from a release whose main carries the engine."""
    home = tmp_path / "home"
    home.mkdir()
    seed = tmp_path / "seed"
    _git(["init", "--quiet", "-b", "main", str(seed)], tmp_path)
    _git(["config", "user.email", "t@example.com"], seed)
    _git(["config", "user.name", "Tester"], seed)
    if with_engine:
        target = seed / ENGINE_PATH
        target.parent.mkdir(parents=True)
        shutil.copyfile(ENGINE, target)
    (seed / "README.md").write_text("release\n", encoding="utf-8")
    _git(["add", "-A"], seed)
    _git(["commit", "--quiet", "-m", "release"], seed)
    install = home / LEGACY
    _git(["clone", "--quiet", str(seed), str(install)], tmp_path)
    (install / "data").mkdir()
    (install / "data" / "keep.txt").write_text("user data\n", encoding="utf-8")
    return home


SH_MOVE_DRIVER = """#!/usr/bin/env bash
set -euo pipefail
note() { printf 'NOTE|%s\\n' "$*"; }
source "$BLOCK_FILE"
printf 'VALUE|dir|%s\\n' "$INSTALL_DIR"
printf 'VALUE|migrate|%s\\n' "$MIGRATE_LEGACY_INSTALL_DIR"
"""


def _run_sh_move(tmp_path: Path, home: Path, *, migrate: str = "1") -> dict[str, str]:
    block = tmp_path / "move.sh"
    # Sourced at the top level, the block's early ``return 0`` ends the source
    # exactly as it ends the function in the script.
    block.write_text(_block(INSTALL_SH, "migrate-install-dir"), encoding="utf-8", newline="\n")
    driver = tmp_path / "move-driver.sh"
    driver.write_text(SH_MOVE_DRIVER, encoding="utf-8", newline="\n")
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    env = {
        **_base_env(),
        "BLOCK_FILE": _sh_path(block),
        "HOME": _sh_path(home),
        "TMPDIR": _sh_path(scratch),
        "PYTHON_EXE": sys.executable,
        "BRANCH": "main",
        "IDENTITY_ENGINE_PATH": ENGINE_PATH,
        "INSTALL_DIR": _sh_path(home / LEGACY),
        "LEGACY_INSTALL_DIR": _sh_path(home / LEGACY),
        "CURRENT_INSTALL_DIR": _sh_path(home / CURRENT),
        "MIGRATE_LEGACY_INSTALL_DIR": migrate,
        **_LONG_PATHS,
    }
    result = _run([str(BASH), str(driver)], env)
    assert result.returncode == 0, result.stderr + result.stdout
    # The engine's temporary copy is gone again.
    assert list(scratch.iterdir()) == []
    return {**_values(result.stdout), "stdout": result.stdout}


@needs_bash
@needs_git
def test_sh_moves_the_install_and_leaves_a_link_at_the_earlier_name(tmp_path: Path) -> None:
    home = _legacy_checkout(tmp_path)

    values = _run_sh_move(tmp_path, home)

    assert _same(values["dir"], home / CURRENT), values["stdout"]
    assert (home / CURRENT / "data" / "keep.txt").read_text(encoding="utf-8") == "user data\n"
    assert is_directory_link(home / LEGACY)
    assert (home / LEGACY / "data" / "keep.txt").is_file()
    assert values["migrate"] == "0"
    assert "moved the install to" in values["stdout"]


@needs_bash
@needs_git
def test_sh_keeps_the_install_in_place_when_the_new_name_is_taken(tmp_path: Path) -> None:
    home = _legacy_checkout(tmp_path)
    (home / CURRENT).mkdir()

    values = _run_sh_move(tmp_path, home)

    assert _same(values["dir"], home / LEGACY), values["stdout"]
    assert not is_directory_link(home / LEGACY)
    assert "kept the install in" in values["stdout"]
    assert "both_exist" in values["stdout"]


@needs_bash
@needs_git
def test_sh_keeps_the_install_in_place_when_the_release_has_no_engine(tmp_path: Path) -> None:
    home = _legacy_checkout(tmp_path, with_engine=False)

    values = _run_sh_move(tmp_path, home)

    assert _same(values["dir"], home / LEGACY), values["stdout"]
    assert not (home / CURRENT).exists()
    assert "did not run" in values["stdout"]


@needs_bash
@needs_git
def test_sh_leaves_an_install_it_did_not_choose_alone(tmp_path: Path) -> None:
    home = _legacy_checkout(tmp_path)

    values = _run_sh_move(tmp_path, home, migrate="0")

    assert _same(values["dir"], home / LEGACY)
    assert not (home / CURRENT).exists()
    assert "NOTE|" not in values["stdout"]


PS_MOVE_DRIVER = """$ErrorActionPreference = 'Stop'
function Write-Note([string]$Text) { Write-Host "NOTE|$Text" }
$InstallDir = $env:TEST_INSTALL_DIR
$LegacyInstallDir = $env:TEST_LEGACY_DIR
$CurrentInstallDir = $env:TEST_CURRENT_DIR
$Branch = 'main'
$IdentityEnginePath = $env:TEST_ENGINE_PATH
$pythonExe = $env:TEST_PYTHON
$MigrateLegacyInstallDir = [bool][int]$env:TEST_MIGRATE
. $env:TEST_FUNCTION_FILE
$InstallDir = [string](Invoke-InstallDirMigration)
Write-Host "VALUE|dir|$InstallDir"
"""


def _run_ps_move(tmp_path: Path, home: Path, *, migrate: str = "1") -> dict[str, str]:
    function = tmp_path / "move.ps1"
    function.write_text(_ps_function(INSTALL_PS1, "Invoke-InstallDirMigration"), encoding="utf-8")
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    driver = tmp_path / "move-driver.ps1"
    driver.write_text(PS_MOVE_DRIVER, encoding="utf-8")
    env = {
        **_base_env(),
        "USERPROFILE": str(home),
        "TEST_FUNCTION_FILE": str(function),
        "TEST_INSTALL_DIR": str(home / LEGACY),
        "TEST_LEGACY_DIR": str(home / LEGACY),
        "TEST_CURRENT_DIR": str(home / CURRENT),
        "TEST_ENGINE_PATH": ENGINE_PATH,
        "TEST_PYTHON": sys.executable,
        "TEST_MIGRATE": migrate,
        # Where the engine's temporary copy goes ([IO.Path]::GetTempPath()).
        "TEMP": str(scratch),
        "TMP": str(scratch),
        **_LONG_PATHS,
    }
    result = _run_powershell(driver, env)
    assert result.returncode == 0, result.stderr + result.stdout
    # The engine's temporary copy is gone again.
    assert list(scratch.iterdir()) == []
    return {**_values(result.stdout), "stdout": result.stdout}


@needs_powershell
@needs_git
def test_ps1_moves_the_install_and_leaves_a_link_at_the_earlier_name(tmp_path: Path) -> None:
    home = _legacy_checkout(tmp_path)

    values = _run_ps_move(tmp_path, home)

    assert _same(values["dir"], home / CURRENT), values["stdout"]
    assert (home / CURRENT / "data" / "keep.txt").read_text(encoding="utf-8") == "user data\n"
    assert is_directory_link(home / LEGACY)
    # The engine ran from a byte-exact copy of the fetched file.
    assert "moved the install to" in values["stdout"]


@needs_powershell
@needs_git
def test_ps1_leaves_an_install_it_did_not_choose_alone(tmp_path: Path) -> None:
    home = _legacy_checkout(tmp_path)

    values = _run_ps_move(tmp_path, home, migrate="0")

    assert _same(values["dir"], home / LEGACY)
    assert not (home / CURRENT).exists()
    assert "NOTE|" not in values["stdout"]


@needs_powershell
@needs_git
def test_ps1_keeps_the_install_in_place_when_the_release_has_no_engine(tmp_path: Path) -> None:
    home = _legacy_checkout(tmp_path, with_engine=False)

    values = _run_ps_move(tmp_path, home)

    assert _same(values["dir"], home / LEGACY), values["stdout"]
    assert not (home / CURRENT).exists()
    assert "did not run" in values["stdout"]


# --------------------------------------------------------------------------- #
# Uninstall: the folder, never through a link                                  #
# --------------------------------------------------------------------------- #
SH_UNINSTALL_CHOICE_DRIVER = """#!/usr/bin/env bash
set -euo pipefail
DEFAULT_INSTALL_DIR_NAME="$TEST_CURRENT_NAME"
LEGACY_INSTALL_DIR_NAME="$TEST_LEGACY_NAME"
source "$BLOCK_FILE"
printf 'VALUE|dir|%s\\n' "$INSTALL_DIR"
"""


@needs_bash
@pytest.mark.parametrize(
    ("legacy_state", "variables", "expected"),
    [
        ("absent", {}, CURRENT),
        ("real", {}, LEGACY),
        ("link", {}, CURRENT),
        ("real", {"JARVIS_INSTALL_DIR": "old-option"}, "old-option"),
        ("real", {"DODAIOS_INSTALL_DIR": "new-option"}, "new-option"),
        ("real", {"JARVIS_INSTALL_DIR": "old-option", "DODAIOS_INSTALL_DIR": "new-option"},
         "new-option"),
    ],
)
def test_the_shell_uninstaller_targets_the_folder_an_install_uses(
    tmp_path: Path, legacy_state: str, variables: dict[str, str], expected: str
) -> None:
    home = _home(tmp_path, legacy_state)
    block = tmp_path / "block.sh"
    block.write_text(_block(UNINSTALL_SH, "uninstall-dir"), encoding="utf-8", newline="\n")
    driver = tmp_path / "driver.sh"
    driver.write_text(SH_UNINSTALL_CHOICE_DRIVER, encoding="utf-8", newline="\n")
    env = {
        **_base_env(),
        "HOME": _sh_path(home),
        "BLOCK_FILE": _sh_path(block),
        "TEST_CURRENT_NAME": CURRENT,
        "TEST_LEGACY_NAME": LEGACY,
        **{name: _sh_path(tmp_path / value) for name, value in variables.items()},
    }

    result = _run([str(BASH), str(driver)], env)

    assert result.returncode == 0, result.stderr
    wanted = tmp_path / expected if variables else home / expected
    assert _same(_values(result.stdout)["dir"], wanted)


def _moved_install(tmp_path: Path) -> tuple[Path, Path]:
    """``~/.dodaios`` with a link at ``~/.personal-jarvis``, and an unrelated folder."""
    home = tmp_path / "home"
    (home / CURRENT / "data").mkdir(parents=True)
    (home / CURRENT / "data" / "keep.txt").write_text("x\n", encoding="utf-8")
    create_directory_link(home / LEGACY, home / CURRENT)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "canary.txt").write_text("not ours\n", encoding="utf-8")
    return home, elsewhere


SH_REMOVE_DRIVER = """#!/usr/bin/env bash
set -euo pipefail
note() { printf 'NOTE|%s\\n' "$*"; }
err() { printf 'ERR|%s\\n' "$*"; }
stop_running_instances() { printf 'STOP|%s\\n' "$1"; }
DEFAULT_INSTALL_DIR_NAME="$TEST_CURRENT_NAME"
LEGACY_INSTALL_DIR_NAME="$TEST_LEGACY_NAME"
remove_install_dir() {
    source "$BLOCK_FILE"
}
remove_install_dir "$TEST_GIVEN"
printf 'DONE\\n'
"""


def _run_sh_remove(tmp_path: Path, home: Path, given: Path) -> subprocess.CompletedProcess[str]:
    block = tmp_path / "remove.sh"
    block.write_text(_block(UNINSTALL_SH, "uninstall-remove"), encoding="utf-8", newline="\n")
    driver = tmp_path / "remove-driver.sh"
    driver.write_text(SH_REMOVE_DRIVER, encoding="utf-8", newline="\n")
    env = {
        **_base_env(),
        "HOME": _sh_path(home),
        "BLOCK_FILE": _sh_path(block),
        "TEST_GIVEN": _sh_path(given),
        "TEST_CURRENT_NAME": CURRENT,
        "TEST_LEGACY_NAME": LEGACY,
    }
    return _run([str(BASH), str(driver)], env)


@needs_bash
@pytest.mark.parametrize("given_name", [CURRENT, LEGACY])
def test_the_shell_uninstaller_removes_the_link_as_a_link_then_the_folder(
    tmp_path: Path, given_name: str
) -> None:
    home, _elsewhere = _moved_install(tmp_path)

    result = _run_sh_remove(tmp_path, home, home / given_name)

    assert result.returncode == 0, result.stderr + result.stdout
    assert "DONE" in result.stdout
    assert not os.path.lexists(home / LEGACY)
    assert not os.path.lexists(home / CURRENT)


@needs_bash
def test_the_shell_uninstaller_never_touches_a_link_that_leads_elsewhere(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / CURRENT).mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "canary.txt").write_text("not ours\n", encoding="utf-8")
    create_directory_link(home / LEGACY, elsewhere)

    result = _run_sh_remove(tmp_path, home, home / CURRENT)

    assert result.returncode == 0, result.stderr + result.stdout
    assert not os.path.lexists(home / CURRENT)
    assert is_directory_link(home / LEGACY)
    assert (elsewhere / "canary.txt").read_text(encoding="utf-8") == "not ours\n"


PS_REMOVE_DRIVER = """$ErrorActionPreference = 'Stop'
function Write-Note([string]$Text) { Write-Host "NOTE|$Text" }
function Write-Ok([string]$Text) { Write-Host "OK|$Text" }
function Write-Err([string]$Text) { Write-Host "ERR|$Text" }
function Stop-JarvisProcesses([string]$Root) { Write-Host "STOP|$Root" }
$DefaultInstallDirName = $env:TEST_CURRENT_NAME
$LegacyInstallDirName = $env:TEST_LEGACY_NAME
. $env:TEST_CHOICE_FILE
. $env:TEST_REMOVE_FILE
Write-Host 'DONE'
"""


def _run_ps_remove(
    tmp_path: Path, home: Path, given: Path | None
) -> subprocess.CompletedProcess[str]:
    choice = tmp_path / "choice.ps1"
    choice.write_text(_block(UNINSTALL_PS1, "uninstall-dir"), encoding="utf-8")
    remove = tmp_path / "remove.ps1"
    remove.write_text(_block(UNINSTALL_PS1, "uninstall-remove"), encoding="utf-8")
    driver = tmp_path / "remove-driver.ps1"
    driver.write_text(PS_REMOVE_DRIVER, encoding="utf-8")
    env = {
        **_base_env(),
        "USERPROFILE": str(home),
        "TEST_CHOICE_FILE": str(choice),
        "TEST_REMOVE_FILE": str(remove),
        "TEST_CURRENT_NAME": CURRENT,
        "TEST_LEGACY_NAME": LEGACY,
    }
    if given is not None:
        env["JARVIS_INSTALL_DIR"] = str(given)
    return _run_powershell(driver, env)


@needs_powershell
@pytest.mark.parametrize("given_name", [None, LEGACY])
def test_the_powershell_uninstaller_removes_the_junction_as_a_link_then_the_folder(
    tmp_path: Path, given_name: str | None
) -> None:
    home, elsewhere = _moved_install(tmp_path)

    result = _run_ps_remove(tmp_path, home, home / given_name if given_name else None)

    assert result.returncode == 0, result.stderr + result.stdout
    assert "DONE" in result.stdout
    assert f"OK|Removed the link {home / LEGACY}" in result.stdout
    assert not os.path.lexists(home / LEGACY)
    assert not os.path.lexists(home / CURRENT)
    assert (elsewhere / "canary.txt").is_file()


@needs_powershell
def test_the_powershell_uninstaller_never_touches_a_link_that_leads_elsewhere(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    (home / CURRENT).mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "canary.txt").write_text("not ours\n", encoding="utf-8")
    create_directory_link(home / LEGACY, elsewhere)

    result = _run_ps_remove(tmp_path, home, None)

    assert result.returncode == 0, result.stderr + result.stdout
    assert not os.path.lexists(home / CURRENT)
    assert is_directory_link(home / LEGACY)
    assert (elsewhere / "canary.txt").read_text(encoding="utf-8") == "not ours\n"
