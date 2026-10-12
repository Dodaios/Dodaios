"""A re-run quick installer stops the running app before it replaces the checkout.

A release may move or delete files the live app still loads. Both shell
installers therefore stop every app running out of THIS install first, and only
then fetch and reset. The stop logic is run for real here - the block extracted
from ``install/install.sh`` and the function extracted from
``install/install.ps1`` - so the shipped scripts cannot drift from what is
tested, and the order of the steps is pinned from the scripts' own text.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from jarvis.core.process_utils import NO_WINDOW_CREATIONFLAGS
from jarvis.ui.relauncher import pid_alive

REPO = Path(__file__).resolve().parents[3]
INSTALL_SH = REPO / "install" / "install.sh"
INSTALL_PS1 = REPO / "install" / "install.ps1"

BLOCK_BEGIN = "# --- stop-running-app begin"
BLOCK_END = "# --- stop-running-app end"
STOPPED_NOTE = "NOTE|stopped the running Jarvis app for the update"

SLEEPER = "import os, sys, time; print(os.getpid(), flush=True); time.sleep(300)"

# Every command the block reaches for is a recording stand-in, so the same
# logic runs on any host with bash - including Git Bash, which has no pkill.
# They record to a file, because the block silences some of them on stdout.
SH_STUB_DRIVER = """#!/usr/bin/env bash
set -euo pipefail
record() { printf '%s\\n' "$*" >> "$CALL_LOG"; }
note() { printf 'NOTE|%s\\n' "$*"; }
pkill() { record "PKILL|$*"; [ "${FAKE_APP_RUNNING:-0}" = "1" ]; }
pgrep() { record "PGREP|$*"; [ "${FAKE_APP_LINGERS:-0}" = "1" ]; }
sleep() { record "SLEEP|$*"; }
uname() { printf '%s\\n' "${FAKE_UNAME:-Linux}"; }
launchctl() { record "LAUNCHCTL|$*"; }
source "$BLOCK_FILE"
source "$BLOCK_FILE"
printf 'DONE\\n'
"""

# Real pkill/pgrep against real processes. ``launchctl`` stays a stand-in on
# purpose: the real one would unload the developer's own autostart agent.
SH_REAL_DRIVER = """#!/usr/bin/env bash
set -euo pipefail
note() { printf 'NOTE|%s\\n' "$*"; }
launchctl() { printf 'LAUNCHCTL|%s\\n' "$*"; }
source "$BLOCK_FILE"
source "$BLOCK_FILE"
printf 'DONE\\n'
"""

PS_DRIVER = """$ErrorActionPreference = 'Stop'
function Write-Note([string]$Text) { Write-Host "NOTE|$Text" }
$InstallDir = $env:TEST_INSTALL_DIR
. $env:TEST_FUNCTION_FILE
Stop-RunningApp
Stop-RunningApp
Write-Host 'DONE'
"""

PS_PARSE = """$errors = $null
$tokens = $null
[void][System.Management.Automation.Language.Parser]::ParseFile(
    $env:TEST_SCRIPT, [ref]$tokens, [ref]$errors)
foreach ($e in $errors) { Write-Host "PARSE|$($e.Extent.StartLineNumber)|$($e.Message)" }
Write-Host "ERRORS|$($errors.Count)"
"""

GIT = shutil.which("git")


def _find_bash() -> str | None:
    if GIT:
        for rel in ("../bin/bash.exe", "../../bin/bash.exe", "../usr/bin/bash.exe"):
            cand = (Path(GIT).parent / rel).resolve()
            if cand.exists():
                return str(cand)
    bash = shutil.which("bash")
    if bash and not any(t in bash.lower() for t in ("windowsapps", "system32")):
        return bash
    return None


BASH = _find_bash()
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")

needs_bash = pytest.mark.skipif(BASH is None, reason="no usable bash on this host")
needs_powershell = pytest.mark.skipif(POWERSHELL is None, reason="no PowerShell on this host")
posix_only = pytest.mark.skipif(
    os.name != "posix" or shutil.which("pkill") is None or shutil.which("pgrep") is None,
    reason="needs a POSIX host with pkill and pgrep",
)
windows_only = pytest.mark.skipif(
    sys.platform != "win32", reason="process lookup by image path is Windows-only"
)


def _run(
    args: list[str], *, env: dict[str, str] | None = None, timeout: float = 120
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- test-controlled command
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
        creationflags=NO_WINDOW_CREATIONFLAGS,
    )


def _sh_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _sh_block(tmp_path: Path) -> Path:
    source = INSTALL_SH.read_text(encoding="utf-8")
    assert BLOCK_BEGIN in source and BLOCK_END in source, (
        "the stop-running-app extraction markers vanished from install.sh"
    )
    block = tmp_path / "block.sh"
    block.write_text(
        source.split(BLOCK_BEGIN, 1)[1].split("\n", 1)[1].split(BLOCK_END, 1)[0],
        encoding="utf-8",
        newline="\n",
    )
    return block


def _run_sh(
    tmp_path: Path, install_dir: Path, driver_text: str, **overrides: str
) -> subprocess.CompletedProcess[str]:
    driver = tmp_path / "driver.sh"
    driver.write_text(driver_text, encoding="utf-8", newline="\n")
    env = dict(os.environ)
    (tmp_path / "calls.log").write_text("", encoding="utf-8")
    env.update(
        BLOCK_FILE=_sh_path(_sh_block(tmp_path)),
        CALL_LOG=_sh_path(tmp_path / "calls.log"),
        INSTALL_DIR=_sh_path(install_dir),
        MACOS_AUTOSTART_LABEL="com.example.autostart",
        HOME=_sh_path(tmp_path / "home"),
        **overrides,
    )
    return _run([str(BASH), str(driver)], env=env)


def _fake_posix_venv(tmp_path: Path) -> Path:
    """An install dir whose venv has an executable ``bin/python``."""
    install_dir = tmp_path / "install"
    python = install_dir / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n")
    python.chmod(0o755)
    return install_dir


def _lines(proc: subprocess.CompletedProcess[str], prefix: str) -> list[str]:
    return [line for line in proc.stdout.splitlines() if line.startswith(prefix)]


def _calls(tmp_path: Path, prefix: str) -> list[str]:
    """What the stand-in commands were asked to do, in order."""
    log = (tmp_path / "calls.log").read_text(encoding="utf-8")
    return [line for line in log.splitlines() if line.startswith(prefix)]


# --------------------------------------------------------------------------- #
# Order: stop, then replace
# --------------------------------------------------------------------------- #
def test_sh_stops_the_app_before_it_fetches_and_resets() -> None:
    source = INSTALL_SH.read_text(encoding="utf-8")
    update = source.split('if [ -d "$INSTALL_DIR/.git" ]; then\n', 1)[1]
    update, rest = update.split('\nelif [ -e "$INSTALL_DIR" ]; then\n', 1)
    leftover = rest.split("\nelse\n", 1)[0]

    stop = update.index("stop_running_app")
    assert stop < update.index(" fetch ")
    assert stop < update.index("reset --quiet --hard")
    # A directory that is not a checkout is moved aside whole - same rule.
    assert leftover.index("stop_running_app") < leftover.index("salvage_reclone")


def test_sh_still_stops_the_app_before_the_environment_is_rebuilt() -> None:
    source = INSTALL_SH.read_text(encoding="utf-8")
    environment = source.split("phase '3/6' 'Python environment'", 1)[1]
    stop = environment.index("\nstop_running_app\n")
    assert stop < environment.index('rm -rf "$VENV_PATH"')
    assert stop < environment.index("-m venv")
    assert stop < environment.index("pip install")


def test_sh_keeps_one_copy_of_the_stop_logic() -> None:
    source = INSTALL_SH.read_text(encoding="utf-8")
    assert source.count("pkill ") == 1
    assert source.count("launchctl unload") == 1
    assert source.count("stop_running_app() {") == 1


def test_ps1_stops_the_app_before_it_fetches_and_resets() -> None:
    source = INSTALL_PS1.read_text(encoding="utf-8")
    update = source.split("if (Test-Path (Join-Path $InstallDir '.git')) {\n", 1)[1]
    update, rest = update.split("\n} else {\n", 1)
    leftover = rest.split("\n    } else {\n", 1)[0]

    stop = update.index("Stop-RunningApp")
    assert stop < update.index(" fetch ")
    assert stop < update.index("reset --quiet --hard")
    assert leftover.index("Stop-RunningApp") < leftover.index("Invoke-SalvageReclone")


def test_ps1_still_stops_the_app_before_the_environment_is_rebuilt() -> None:
    source = INSTALL_PS1.read_text(encoding="utf-8")
    environment = source.split("Write-Phase '3/6' 'Python environment'", 1)[1]
    stop = environment.index("\nStop-RunningApp\n")
    assert stop < environment.index("-m venv")
    assert stop < environment.index("pip install")


def test_ps1_keeps_one_copy_of_the_stop_logic() -> None:
    source = INSTALL_PS1.read_text(encoding="utf-8")
    assert source.count("Stop-Process ") == 1
    assert source.count("function Stop-RunningApp {") == 1


# --------------------------------------------------------------------------- #
# The scripts still parse
# --------------------------------------------------------------------------- #
@needs_bash
def test_install_sh_is_valid_bash() -> None:
    proc = _run([str(BASH), "-n", str(INSTALL_SH)])
    assert proc.returncode == 0, proc.stderr


@needs_powershell
def test_install_ps1_parses_without_errors(tmp_path: Path) -> None:
    script = tmp_path / "parse.ps1"
    script.write_text(PS_PARSE, encoding="utf-8")
    env = dict(os.environ)
    env["TEST_SCRIPT"] = str(INSTALL_PS1)
    proc = _run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert "ERRORS|0" in proc.stdout, proc.stdout


# --------------------------------------------------------------------------- #
# install.sh: the extracted block, on every host with bash
# --------------------------------------------------------------------------- #
@needs_bash
def test_sh_does_nothing_for_a_directory_without_an_environment(tmp_path: Path) -> None:
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    proc = _run_sh(tmp_path, install_dir, SH_STUB_DRIVER, FAKE_APP_RUNNING="1")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "DONE"


@needs_bash
def test_sh_stops_a_running_app_and_waits_for_it_to_be_gone(tmp_path: Path) -> None:
    install_dir = _fake_posix_venv(tmp_path)
    proc = _run_sh(tmp_path, install_dir, SH_STUB_DRIVER, FAKE_APP_RUNNING="1")

    assert proc.returncode == 0, proc.stderr
    venv = _sh_path(install_dir / ".venv")
    # Scoped to THIS install: the pattern is its venv, nothing broader.
    assert set(_calls(tmp_path, "PKILL|")) == {f"PKILL|-f {venv}"}
    assert set(_calls(tmp_path, "PGREP|")) == {f"PGREP|-f {venv}"}
    assert STOPPED_NOTE in proc.stdout
    assert _calls(tmp_path, "SLEEP|") == []  # it was gone at the first look
    assert _calls(tmp_path, "LAUNCHCTL|") == []  # not macOS
    assert proc.stdout.strip().endswith("DONE")


@needs_bash
def test_sh_gives_up_waiting_for_an_app_that_ignores_the_signal(tmp_path: Path) -> None:
    install_dir = _fake_posix_venv(tmp_path)
    proc = _run_sh(
        tmp_path, install_dir, SH_STUB_DRIVER, FAKE_APP_RUNNING="1", FAKE_APP_LINGERS="1"
    )
    assert proc.returncode == 0, proc.stderr
    # Two calls of the block, fifty short waits each - bounded, then it moves on.
    assert len(_calls(tmp_path, "SLEEP|")) == 100
    assert proc.stdout.strip().endswith("DONE")


@needs_bash
def test_sh_is_quiet_when_no_app_is_running(tmp_path: Path) -> None:
    install_dir = _fake_posix_venv(tmp_path)
    proc = _run_sh(tmp_path, install_dir, SH_STUB_DRIVER)
    assert proc.returncode == 0, proc.stderr
    assert len(_calls(tmp_path, "PKILL|")) == 2  # asked both times, found nothing
    assert "NOTE|" not in proc.stdout
    assert _calls(tmp_path, "PGREP|") == []
    assert proc.stdout.strip().endswith("DONE")


@needs_bash
def test_sh_unloads_the_macos_autostart_agent(tmp_path: Path) -> None:
    install_dir = _fake_posix_venv(tmp_path)
    proc = _run_sh(tmp_path, install_dir, SH_STUB_DRIVER, FAKE_UNAME="Darwin")
    assert proc.returncode == 0, proc.stderr
    # Unloaded whether or not a process was found: launchd would start it again.
    unloads = _calls(tmp_path, "LAUNCHCTL|")
    assert len(unloads) == 2
    for call in unloads:
        # Compared by its tail: Git Bash rewrites the drive part of $HOME.
        assert call.startswith("LAUNCHCTL|unload ")
        assert call.endswith("/home/Library/LaunchAgents/com.example.autostart.plist")


def _start_sleeper(python: Path | str, *args: str) -> tuple[subprocess.Popen[str], int]:
    """Start a long sleep and return ``(process, pid of the interpreter)``."""
    proc = subprocess.Popen(  # noqa: S603 -- test-controlled command
        [str(python), "-c", SLEEPER, *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        creationflags=NO_WINDOW_CREATIONFLAGS,
    )
    assert proc.stdout is not None
    return proc, int(proc.stdout.readline().strip())


def _wait_until_gone(pid: int, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.1)
    return not pid_alive(pid)


def _end(*procs: subprocess.Popen[str]) -> None:
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=15)
        if proc.stdout is not None:
            proc.stdout.close()


@needs_bash
@posix_only
def test_sh_really_stops_a_process_of_this_install_and_no_other(tmp_path: Path) -> None:
    install_dir = tmp_path / "install"
    venv_python = install_dir / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.symlink_to(sys.executable)

    # The app is found by the venv path on its command line. This interpreter
    # carries it as an argument, so the test does not depend on how a symlinked
    # Python locates its standard library on the host.
    app, app_pid = _start_sleeper(sys.executable, str(venv_python))
    bystander, bystander_pid = _start_sleeper(sys.executable)
    try:
        proc = _run_sh(tmp_path, install_dir, SH_REAL_DRIVER)

        assert proc.returncode == 0, proc.stderr
        assert STOPPED_NOTE in proc.stdout
        assert app.wait(timeout=15) is not None
        assert _wait_until_gone(app_pid)
        # Another interpreter on the machine is none of the installer's business.
        assert pid_alive(bystander_pid)
        assert bystander.poll() is None
    finally:
        _end(app, bystander)


# --------------------------------------------------------------------------- #
# install.ps1: the extracted function
# --------------------------------------------------------------------------- #
def _run_ps(tmp_path: Path, install_dir: Path) -> subprocess.CompletedProcess[str]:
    source = INSTALL_PS1.read_text(encoding="utf-8")
    match = re.search(r"^function Stop-RunningApp \{\r?\n.*?^\}\r?$", source, re.S | re.M)
    assert match is not None, "Stop-RunningApp vanished from install.ps1"
    function_file = tmp_path / "function.ps1"
    function_file.write_text(match.group(0), encoding="utf-8")
    driver = tmp_path / "driver.ps1"
    driver.write_text(PS_DRIVER, encoding="utf-8")
    env = dict(os.environ)
    env.update(TEST_INSTALL_DIR=str(install_dir), TEST_FUNCTION_FILE=str(function_file))
    return _run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(driver),
        ],
        env=env,
    )


@needs_powershell
def test_ps1_does_nothing_for_a_directory_without_an_environment(tmp_path: Path) -> None:
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    proc = _run_ps(tmp_path, install_dir)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "DONE"


@needs_powershell
@windows_only
def test_ps1_really_stops_processes_of_this_install_and_no_other(tmp_path: Path) -> None:
    install_dir = tmp_path / "install"
    venv = install_dir / ".venv"
    created = _run([sys.executable, "-m", "venv", "--without-pip", str(venv)], timeout=300)
    assert created.returncode == 0, created.stderr
    scripts = venv / "Scripts"
    # The desktop app usually runs as a renamed copy of the venv launcher, so
    # the image name must not decide what belongs to this install.
    branded = scripts / "RenamedLauncher.exe"
    shutil.copy2(scripts / "python.exe", branded)

    app, app_pid = _start_sleeper(scripts / "python.exe")
    renamed, renamed_pid = _start_sleeper(branded)
    bystander, bystander_pid = _start_sleeper(sys.executable)
    try:
        proc = _run_ps(tmp_path, install_dir)

        assert proc.returncode == 0, proc.stderr
        # Stopped on the first call; the second finds nothing and says nothing.
        assert _lines(proc, "NOTE|") == [STOPPED_NOTE]
        assert proc.stdout.strip().endswith("DONE")
        for stopped, pid in ((app, app_pid), (renamed, renamed_pid)):
            assert stopped.wait(timeout=15) is not None
            # The interpreter behind the venv launcher goes down with it.
            assert _wait_until_gone(pid)
        assert pid_alive(bystander_pid)
        assert bystander.poll() is None
    finally:
        _end(app, renamed, bystander)
