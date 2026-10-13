"""A re-run quick installer stops the running app before it replaces the checkout.

A release may move or delete files the live app still loads. Both shell
installers therefore stop every app running out of THIS install right before
its files change - after the download, so a failed download leaves a working
app behind - and refuse outright when they were started from inside that app,
because stopping it would end the installer too. The stop logic is run for
real here - the blocks extracted from ``install/install.sh`` and the functions
extracted from ``install/install.ps1`` - so the shipped scripts cannot drift
from what is tested, and the order of the steps is pinned from the scripts'
own text.
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
INSIDE_APP = "ERR|this installer was started from inside the running app."
GUARD_BEGIN = "# --- salvage-guard begin"
GUARD_END = "# --- salvage-guard end"
UNREACHABLE = "ERR|cannot reach the download server right now - nothing was changed."

SLEEPER = "import os, sys, time; print(os.getpid(), flush=True); time.sleep(300)"

# Every command the block reaches for is a recording stand-in, so the same
# logic runs on any host with bash - including Git Bash, which has no pkill.
# They record to a file, because the block silences some of them on stdout.
SH_STUB_DRIVER = """#!/usr/bin/env bash
set -euo pipefail
record() { printf '%s\\n' "$*" >> "$CALL_LOG"; }
note() { printf 'NOTE|%s\\n' "$*"; }
err() { printf 'ERR|%s\\n' "$*"; }
# ``ps [-ww] -o <field>= -p <pid>`` answered from FAKE_PS_TABLE (pid|ppid|args
# per line). SELF stands for this script, whose real pid the block starts from.
ps() {
    record "PS|$*"
    _ps_field=''
    _ps_pid=''
    while [ "$#" -gt 0 ]; do
        case "$1" in
            -o) _ps_field="$2"; shift ;;
            -p) _ps_pid="$2"; shift ;;
        esac
        shift
    done
    [ "$_ps_pid" = "$$" ] && _ps_pid=SELF
    printf '%s\\n' "${FAKE_PS_TABLE:-}" | while IFS='|' read -r _p _pp _a; do
        [ "$_p" = "$_ps_pid" ] || continue
        case "$_ps_field" in
            ppid=) printf '%s\\n' "$_pp" ;;
            args=) printf '%s\\n' "$_a" ;;
        esac
    done
}
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
err() { printf 'ERR|%s\\n' "$*"; }
launchctl() { printf 'LAUNCHCTL|%s\\n' "$*"; }
source "$BLOCK_FILE"
source "$BLOCK_FILE"
printf 'DONE\\n'
"""

# The salvage path asks the repository before it stops or moves anything.
SH_GUARD_DRIVER = """#!/usr/bin/env bash
set -euo pipefail
note() { printf 'NOTE|%s\\n' "$*"; }
err() { printf 'ERR|%s\\n' "$*"; }
git() { printf 'GIT|%s\\n' "$*" >> "$CALL_LOG"; [ "${FAKE_REMOTE_ANSWERS:-0}" = "1" ]; }
curl() { printf 'CURL|%s\\n' "$*" >> "$CALL_LOG"; [ "${FAKE_ARCHIVE_ANSWERS:-0}" = "1" ]; }
stop_running_app() { printf 'STOP|\\n' >> "$CALL_LOG"; }
GIT_NET_OPTS='-c http.lowSpeedLimit=1024'
source "$GUARD_FILE"
printf 'DONE\\n'
"""

PS_DRIVER = """$ErrorActionPreference = 'Stop'
function Write-Note([string]$Text) { Write-Host "NOTE|$Text" }
function Write-Err([string]$Text) { Write-Host "ERR|$Text" }
$InstallDir = $env:TEST_INSTALL_DIR
. $env:TEST_FUNCTION_FILE
Stop-RunningApp
Stop-RunningApp
Write-Host 'DONE'
"""

PS_REACHABLE_DRIVER = """$ErrorActionPreference = 'Stop'
$GitNetOpts = @('-c', 'http.lowSpeedLimit=1024')
$RepoUrl = $env:TEST_REPO_URL
if ($env:TEST_GIT_EXIT) {
    # Stand-ins for both transports: a function wins over a program of its name.
    function git { $global:LASTEXITCODE = [int]$env:TEST_GIT_EXIT }
    function curl.exe {
        Write-Host "CURL|$($args -join ' ')"
        $global:LASTEXITCODE = [int]$env:TEST_CURL_EXIT
    }
}
. $env:TEST_FUNCTION_FILE
Write-Host "REACHABLE|$(Test-RepositoryReachable)"
"""

# Runs the installer's stop function as a child of a process that lives in the
# install's venv - what a terminal inside the app looks like to the installer.
INSIDE_APP_LAUNCHER = (
    "import subprocess, sys; "
    "sys.exit(subprocess.run(sys.argv[2:], check=False).returncode)"
)

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
# Order: download, stop, then replace
# --------------------------------------------------------------------------- #
def test_sh_stops_the_app_after_the_fetch_and_before_the_reset() -> None:
    source = INSTALL_SH.read_text(encoding="utf-8")
    update = source.split('if [ -d "$INSTALL_DIR/.git" ]; then\n', 1)[1]
    update, rest = update.split('\nelif [ -e "$INSTALL_DIR" ]; then\n', 1)
    leftover = rest.split("\nelse\n", 1)[0]

    fetch = update.index(" fetch ")
    stop = update.index("&& stop_running_app")
    # A fetch only writes inside .git: a failed one must leave the app running.
    assert fetch < stop
    assert stop < update.index(" checkout ")
    assert stop < update.index("reset --quiet --hard")
    assert update.count("stop_running_app") == 1
    # A directory that is not a checkout goes through the salvage path, which
    # owns its own stop.
    assert "stop_running_app" not in leftover
    assert "salvage_reclone" in leftover


def test_sh_salvage_asks_the_repository_then_stops_then_moves() -> None:
    source = INSTALL_SH.read_text(encoding="utf-8")
    salvage = source.split("salvage_reclone() {\n", 1)[1].split("\n}\n", 1)[0]

    reachable = salvage.index("ls-remote")
    stop = salvage.index("stop_running_app")
    move = salvage.index('mv "$INSTALL_DIR"')
    assert reachable < stop < move
    assert move < salvage.index("fetch_payload")


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


def test_ps1_stops_the_app_after_the_fetch_and_before_the_reset() -> None:
    source = INSTALL_PS1.read_text(encoding="utf-8")
    update = source.split("if (Test-Path (Join-Path $InstallDir '.git')) {\n", 1)[1]
    update, rest = update.split("\n} else {\n", 1)
    leftover = rest.split("\n    } else {\n", 1)[0]
    attempt = update.split("\n    } finally {\n", 1)[0]

    fetch = attempt.index(" fetch ")
    stop = attempt.index("Stop-RunningApp")
    assert fetch < stop
    assert stop < attempt.index(" checkout ")
    assert stop < attempt.index("reset --quiet --hard")
    assert attempt.count("Stop-RunningApp") == 1
    # Only reached when the fetch succeeded.
    guarded = attempt[attempt.rindex("if ($UpdateOk) {", 0, stop) : stop]
    assert guarded.count("\n") == 1
    assert "Stop-RunningApp" not in leftover
    assert "Invoke-SalvageReclone" in leftover


def test_ps1_salvage_asks_the_repository_then_stops_then_moves() -> None:
    source = INSTALL_PS1.read_text(encoding="utf-8")
    salvage = source.split("function Invoke-SalvageReclone {\n", 1)[1].split("\n}\n", 1)[0]

    reachable = salvage.index("Test-RepositoryReachable")
    stop = salvage.index("Stop-RunningApp")
    move = salvage.index("Move-Item")
    assert reachable < stop < move
    assert move < salvage.index("Invoke-FetchPayload")


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


# --------------------------------------------------------------------------- #
# The installer never stops the process tree it runs in
# --------------------------------------------------------------------------- #
def _ps_table(*rows: tuple[str, str, str]) -> str:
    return "\n".join("|".join(row) for row in rows)


@needs_bash
@pytest.mark.parametrize(
    "ancestors",
    [
        # A terminal pane: the shell's parent is the app's terminal host.
        [("SELF", "100", "bash install.sh"), ("100", "1", "VENV/bin/python -m jarvis.terminal")],
        # Further up the chain counts just the same.
        [
            ("SELF", "100", "bash install.sh"),
            ("100", "200", "/bin/zsh -l"),
            ("200", "300", "VENV/bin/python -m jarvis.ui.web.launcher"),
            ("300", "1", "/sbin/launchd"),
        ],
        # The script itself was started with a path inside the environment.
        [("SELF", "100", "bash VENV/bin/some-wrapper"), ("100", "1", "/sbin/init")],
    ],
)
def test_sh_refuses_before_stopping_anything_when_started_inside_the_app(
    tmp_path: Path, ancestors: list[tuple[str, str, str]]
) -> None:
    install_dir = _fake_posix_venv(tmp_path)
    venv = _sh_path(install_dir / ".venv")
    table = _ps_table(*[(pid, ppid, args.replace("VENV", venv)) for pid, ppid, args in ancestors])

    proc = _run_sh(
        tmp_path, install_dir, SH_STUB_DRIVER, FAKE_APP_RUNNING="1", FAKE_PS_TABLE=table
    )

    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert INSIDE_APP in proc.stdout
    assert "normal" in proc.stdout and "terminal outside the app" in proc.stdout
    # Refused BEFORE the first signal: nothing was stopped, nothing unloaded.
    assert _calls(tmp_path, "PKILL|") == []
    assert _calls(tmp_path, "LAUNCHCTL|") == []
    assert "DONE" not in proc.stdout


@needs_bash
def test_sh_stops_the_app_when_started_from_an_ordinary_terminal(tmp_path: Path) -> None:
    install_dir = _fake_posix_venv(tmp_path)
    table = _ps_table(
        ("SELF", "100", "bash install.sh"),
        ("100", "200", "/bin/zsh -l"),
        ("200", "1", "/usr/bin/some-terminal"),
    )
    proc = _run_sh(
        tmp_path, install_dir, SH_STUB_DRIVER, FAKE_APP_RUNNING="1", FAKE_PS_TABLE=table
    )
    assert proc.returncode == 0, proc.stderr
    assert STOPPED_NOTE in proc.stdout
    assert len(_calls(tmp_path, "PKILL|")) == 2
    # The whole command line is asked for: BSD ps cuts it at the terminal
    # width otherwise, and pkill matches against all of it.
    looked_up = [call for call in _calls(tmp_path, "PS|") if "args=" in call]
    assert looked_up and all(call.startswith("PS|-ww ") for call in looked_up)


@needs_bash
@pytest.mark.parametrize(
    "table",
    [
        # A process reported as its own parent ends the walk at once.
        pytest.param(
            _ps_table(("SELF", "100", "bash install.sh"), ("100", "100", "/bin/odd")),
            id="own-parent",
        ),
        # A longer cycle runs into the depth bound. Dozens of subshells are
        # slow under Git Bash, so that one runs where forking is cheap.
        pytest.param(
            _ps_table(
                ("SELF", "100", "bash install.sh"),
                ("100", "200", "/bin/a"),
                ("200", "100", "/bin/b"),
            ),
            id="cycle",
            marks=pytest.mark.skipif(sys.platform == "win32", reason="slow under Git Bash"),
        ),
    ],
)
def test_sh_gives_up_on_a_process_table_that_loops(tmp_path: Path, table: str) -> None:
    install_dir = _fake_posix_venv(tmp_path)
    proc = _run_sh(
        tmp_path, install_dir, SH_STUB_DRIVER, FAKE_APP_RUNNING="1", FAKE_PS_TABLE=table
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().endswith("DONE")


@needs_bash
@posix_only
def test_sh_really_refuses_under_a_parent_from_this_install(tmp_path: Path) -> None:
    install_dir = tmp_path / "install"
    venv_python = install_dir / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.symlink_to(sys.executable)
    driver = tmp_path / "driver.sh"
    driver.write_text(SH_REAL_DRIVER, encoding="utf-8", newline="\n")
    env = dict(os.environ)
    env.update(
        BLOCK_FILE=str(_sh_block(tmp_path)),
        INSTALL_DIR=str(install_dir),
        MACOS_AUTOSTART_LABEL="com.example.autostart",
        HOME=str(tmp_path / "home"),
    )

    app, app_pid = _start_sleeper(sys.executable, str(venv_python))
    try:
        # The parent carries the venv path on its command line, as the app's
        # terminal host does; the installer block is its child.
        proc = _run(
            [sys.executable, "-c", INSIDE_APP_LAUNCHER, str(venv_python), str(BASH), str(driver)],
            env=env,
        )

        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert INSIDE_APP in proc.stdout
        assert STOPPED_NOTE not in proc.stdout
        # The app it would have stopped is untouched.
        assert pid_alive(app_pid)
        assert app.poll() is None
    finally:
        _end(app)


# --------------------------------------------------------------------------- #
# The salvage path changes nothing while the repository is out of reach
# --------------------------------------------------------------------------- #
def _run_sh_guard(tmp_path: Path, **overrides: str) -> subprocess.CompletedProcess[str]:
    source = INSTALL_SH.read_text(encoding="utf-8")
    assert GUARD_BEGIN in source and GUARD_END in source, (
        "the salvage-guard extraction markers vanished from install.sh"
    )
    guard = tmp_path / "guard.sh"
    guard.write_text(
        source.split(GUARD_BEGIN, 1)[1].split("\n", 1)[1].split(GUARD_END, 1)[0],
        encoding="utf-8",
        newline="\n",
    )
    driver = tmp_path / "driver.sh"
    driver.write_text(SH_GUARD_DRIVER, encoding="utf-8", newline="\n")
    (tmp_path / "calls.log").write_text("", encoding="utf-8")
    env = dict(os.environ)
    env.update(
        {
            "GUARD_FILE": _sh_path(guard),
            "CALL_LOG": _sh_path(tmp_path / "calls.log"),
            "REPO_URL": "https://example.invalid/owner/repo.git",
            **overrides,
        }
    )
    return _run([str(BASH), str(driver)], env=env)


@needs_bash
def test_sh_salvage_changes_nothing_when_the_repository_is_out_of_reach(
    tmp_path: Path,
) -> None:
    proc = _run_sh_guard(tmp_path)

    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert UNREACHABLE in proc.stdout
    assert _calls(tmp_path, "STOP|") == []
    assert "DONE" not in proc.stdout
    asked = _calls(tmp_path, "GIT|")
    assert len(asked) == 1
    assert asked[0].endswith("ls-remote --quiet --heads https://example.invalid/owner/repo.git")
    # The archive download only exists for the hosted repository.
    assert _calls(tmp_path, "CURL|") == []


@needs_bash
def test_sh_salvage_stops_the_app_once_the_repository_answers(tmp_path: Path) -> None:
    proc = _run_sh_guard(tmp_path, FAKE_REMOTE_ANSWERS="1")

    assert proc.returncode == 0, proc.stderr
    assert "ERR|" not in proc.stdout
    assert _calls(tmp_path, "STOP|") == ["STOP|"]
    assert proc.stdout.strip().endswith("DONE")


GITHUB_REPO_URL = "https://github.com/owner/repo.git"


@needs_bash
def test_sh_salvage_goes_on_when_only_the_archive_download_gets_through(
    tmp_path: Path,
) -> None:
    """git blocked, HTTPS open: an install that came from the archive still updates."""
    proc = _run_sh_guard(tmp_path, REPO_URL=GITHUB_REPO_URL, FAKE_ARCHIVE_ANSWERS="1")

    assert proc.returncode == 0, proc.stderr
    assert "ERR|" not in proc.stdout
    assert len(_calls(tmp_path, "GIT|")) == 1
    probes = _calls(tmp_path, "CURL|")
    assert len(probes) == 1
    assert probes[0].endswith(" https://github.com/owner/repo")
    assert _calls(tmp_path, "STOP|") == ["STOP|"]
    assert proc.stdout.strip().endswith("DONE")


@needs_bash
def test_sh_salvage_changes_nothing_when_neither_transport_answers(tmp_path: Path) -> None:
    proc = _run_sh_guard(tmp_path, REPO_URL=GITHUB_REPO_URL)

    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert UNREACHABLE in proc.stdout
    assert len(_calls(tmp_path, "CURL|")) == 1
    assert _calls(tmp_path, "STOP|") == []
    assert "DONE" not in proc.stdout


def _ps_function(name: str) -> str:
    source = INSTALL_PS1.read_text(encoding="utf-8")
    match = re.search(rf"^function {name} \{{\r?\n.*?^\}}\r?$", source, re.S | re.M)
    assert match is not None, f"{name} vanished from install.ps1"
    return match.group(0)


def _powershell(script: Path) -> list[str]:
    return [
        str(POWERSHELL),
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
    ]


@needs_powershell
@pytest.mark.skipif(GIT is None, reason="git is not installed")
def test_ps1_tells_a_reachable_repository_from_an_unreachable_one(tmp_path: Path) -> None:
    function_file = tmp_path / "function.ps1"
    function_file.write_text(_ps_function("Test-RepositoryReachable"), encoding="utf-8")
    driver = tmp_path / "driver.ps1"
    driver.write_text(PS_REACHABLE_DRIVER, encoding="utf-8")
    bare = tmp_path / "origin.git"
    assert _run([str(GIT), "init", "--quiet", "--bare", str(bare)]).returncode == 0

    answers = {}
    for label, url in (("there", str(bare)), ("gone", str(tmp_path / "no-such-repo.git"))):
        env = dict(os.environ)
        env.update(TEST_REPO_URL=url, TEST_FUNCTION_FILE=str(function_file))
        proc = _run(_powershell(driver), env=env)
        assert proc.returncode == 0, proc.stderr
        answers[label] = _lines(proc, "REACHABLE|")

    assert answers == {"there": ["REACHABLE|True"], "gone": ["REACHABLE|False"]}


@needs_powershell
@pytest.mark.parametrize(
    ("repo_url", "git_exit", "curl_exit", "reachable", "probes"),
    [
        # git answers: nothing else is asked.
        (GITHUB_REPO_URL, "0", "7", "True", 0),
        # git blocked, HTTPS open: the archive download would get through.
        (GITHUB_REPO_URL, "128", "0", "True", 1),
        (GITHUB_REPO_URL, "128", "7", "False", 1),
        # The archive download only exists for the hosted repository.
        ("https://example.invalid/owner/repo.git", "128", "0", "False", 0),
    ],
)
def test_ps1_counts_the_archive_download_as_a_way_to_reach_the_repository(
    tmp_path: Path, repo_url: str, git_exit: str, curl_exit: str, reachable: str, probes: int
) -> None:
    function_file = tmp_path / "function.ps1"
    function_file.write_text(_ps_function("Test-RepositoryReachable"), encoding="utf-8")
    driver = tmp_path / "driver.ps1"
    driver.write_text(PS_REACHABLE_DRIVER, encoding="utf-8")
    env = dict(os.environ)
    env.update(
        TEST_REPO_URL=repo_url,
        TEST_FUNCTION_FILE=str(function_file),
        TEST_GIT_EXIT=git_exit,
        TEST_CURL_EXIT=curl_exit,
    )

    proc = _run(_powershell(driver), env=env)

    assert proc.returncode == 0, proc.stderr
    assert _lines(proc, "REACHABLE|") == [f"REACHABLE|{reachable}"]
    asked = _lines(proc, "CURL|")
    assert len(asked) == probes
    for call in asked:
        assert call.endswith(" https://github.com/owner/repo")


@needs_powershell
@windows_only
def test_ps1_really_refuses_under_a_parent_from_this_install(tmp_path: Path) -> None:
    install_dir = tmp_path / "install"
    venv = install_dir / ".venv"
    created = _run([sys.executable, "-m", "venv", "--without-pip", str(venv)], timeout=300)
    assert created.returncode == 0, created.stderr
    function_file = tmp_path / "function.ps1"
    function_file.write_text(_ps_function("Stop-RunningApp"), encoding="utf-8")
    driver = tmp_path / "driver.ps1"
    driver.write_text(PS_DRIVER, encoding="utf-8")
    env = dict(os.environ)
    env.update(TEST_INSTALL_DIR=str(install_dir), TEST_FUNCTION_FILE=str(function_file))

    app, app_pid = _start_sleeper(venv / "Scripts" / "python.exe")
    try:
        # PowerShell runs as a child of the venv's interpreter - what a
        # terminal pane inside the app looks like to the installer.
        proc = _run(
            [
                str(venv / "Scripts" / "python.exe"),
                "-c",
                INSIDE_APP_LAUNCHER,
                "-",
                *_powershell(driver),
            ],
            env=env,
        )

        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert INSIDE_APP in proc.stdout
        assert "terminal outside the app" in proc.stdout
        assert STOPPED_NOTE not in proc.stdout
        assert "DONE" not in proc.stdout
        # Refused BEFORE the first kill: the app of this install still runs.
        assert pid_alive(app_pid)
        assert app.poll() is None
    finally:
        _end(app)
