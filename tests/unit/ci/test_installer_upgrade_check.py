"""The Windows upgrade check ends by itself and says what was stuck.

On release tags it stopped for good five times, until someone cancelled the
job, and a cancelled job keeps neither its log nor its evidence. These tests
pin the properties that make that impossible: no wait without a limit, no
child read through a pipe, a stalled download tried again, and an overall
deadline that writes down what every thread and process was doing.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import psutil
import pytest

from scripts.ci import check_installer_upgrade as upgrade

ROOT = Path(__file__).resolve().parents[3]
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="stand-in apps are shell scripts")


def _script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + textwrap.dedent(body), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _wait_gone(pid: int, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return True
        except psutil.NoSuchProcess:
            return True
        time.sleep(0.05)
    return False


@posix_only
def test_the_version_is_read_although_a_child_of_the_app_still_holds_its_output(tmp_path):
    """The shape of the suspected stall: the app is gone, a child of it lives on.

    Read through a pipe, the version call waits for that child. Read from a
    file it returns as soon as the app itself has ended.
    """
    pid_file = tmp_path / "child.pid"
    app = _script(
        tmp_path / "App",
        f"""\
        echo "dodaios 9.9.9"
        sleep 30 &
        echo $! > "{pid_file}"
        exit 0
        """,
    )

    started = time.monotonic()
    try:
        version = upgrade.version_of(app, tmp_path / "version.log")
        elapsed = time.monotonic() - started
    finally:
        child = int(pid_file.read_text())
        upgrade.kill_tree(child)

    assert version == "dodaios 9.9.9"
    assert elapsed < 10


@posix_only
def test_a_command_that_never_ends_is_stopped_with_everything_it_started(tmp_path):
    pid_file = tmp_path / "child.pid"
    setup = _script(
        tmp_path / "Setup",
        f"""\
        sleep 60 &
        echo $! > "{pid_file}"
        wait
        """,
    )

    with pytest.raises(TimeoutError, match="Setup did not finish within 3 s; stopped "):
        upgrade.run_bounded([str(setup)], timeout=3)

    child = int(pid_file.read_text())
    assert _wait_gone(child), "the child of the stopped command is still running"


def test_a_stalled_download_is_tried_again(monkeypatch, tmp_path):
    calls: list[list[str]] = []

    def _gh(command, *, timeout, output=None):
        calls.append(command)
        if len(calls) == 1:
            raise TimeoutError("gh did not finish within 240 s; stopped gh (1)")
        (tmp_path / "Setup.exe").write_bytes(b"setup")
        return 0

    monkeypatch.setattr(upgrade, "run_bounded", _gh)

    setup = upgrade.download_previous("example/project", "Setup.exe", tmp_path)

    assert setup == tmp_path / "Setup.exe"
    assert len(calls) == 2
    assert calls[0][:3] == ["gh", "release", "download"]
    assert "example/project" in calls[0]


def test_a_download_that_keeps_failing_names_the_reason(monkeypatch, tmp_path):
    def _gh(command, *, timeout, output=None):
        output.write_text("release not found\n", encoding="utf-8")
        return 1

    monkeypatch.setattr(upgrade, "run_bounded", _gh)

    with pytest.raises(RuntimeError, match="release not found"):
        upgrade.download_previous("example/project", "Setup.exe", tmp_path)


def test_a_failed_setup_shows_the_end_of_its_own_log(monkeypatch, tmp_path):
    log = tmp_path / "install.log"
    log.write_text("line one\nRestartManager: file in use: App.exe\n", encoding="utf-8")
    monkeypatch.setattr(upgrade, "run_bounded", lambda command, *, timeout, output=None: 5)

    with pytest.raises(RuntimeError) as excinfo:
        upgrade.run_setup(tmp_path / "Setup.exe", tmp_path / "app", log)

    assert "exited with 5" in str(excinfo.value)
    assert "file in use: App.exe" in str(excinfo.value)


class _Process:
    """A stand-in for one psutil process."""

    def __init__(self, pid: int, exe: str | None) -> None:
        self.info = {
            "pid": pid,
            "ppid": 1,
            "name": Path(exe).name if exe else "system",
            "exe": exe,
            "cmdline": [exe, "--serve"] if exe else [],
        }
        self.killed = False

    def kill(self) -> None:
        self.killed = True


def test_a_process_left_in_the_install_folder_is_named_and_stopped(monkeypatch, tmp_path):
    """Only what runs from the install folder counts, whatever the path's case."""
    install_dir = tmp_path / "App"
    install_dir.mkdir()
    inside = _Process(41, str(install_dir.resolve() / "Helper.exe").upper())
    elsewhere = _Process(42, str(tmp_path / "Other" / "Helper.exe"))
    unreadable = _Process(43, None)
    monkeypatch.setattr(
        upgrade.psutil, "process_iter", lambda _attrs: [inside, elsewhere, unreadable]
    )

    found = upgrade.leftover_processes(install_dir)

    assert [row["pid"] for row in found] == [41]
    assert found[0]["name"] == "HELPER.EXE"
    assert "--serve" in found[0]["cmdline"]
    assert (inside.killed, elsewhere.killed, unreadable.killed) == (True, False, False)


def test_the_deadline_writes_what_was_stuck_and_ends_the_run(tmp_path):
    """A stall ends red after the deadline, with the phase, the threads and the processes."""
    driver = tmp_path / "driver.py"
    driver.write_text(
        textwrap.dedent(
            f"""\
            import sys, time
            from pathlib import Path
            sys.path.insert(0, {str(ROOT)!r})
            from scripts.ci import check_installer_upgrade as upgrade

            output = Path({str(tmp_path / "proof")!r})
            output.mkdir()
            report = {{"passed": False, "phase": "read this build's version"}}
            upgrade.arm_deadline(output, Path({str(tmp_path / "app")!r}), report, 0.5)
            time.sleep(60)  # the wait that never ends
            """
        ),
        encoding="utf-8",
    )

    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, str(driver)],
        capture_output=True,
        text=True,
        timeout=50,
        check=False,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert time.monotonic() - started < 45
    hang = (tmp_path / "proof" / "hang.log").read_text(encoding="utf-8")
    assert "in phase: read this build's version" in hang
    assert "driver.py" in hang  # the stack of the thread that was waiting
    assert "Processes (pid, parent, age, name, command):" in hang
    report = json.loads((tmp_path / "proof" / "report.json").read_text(encoding="utf-8"))
    assert report["passed"] is False
    assert "no result after 0 s" in report["failure"] or "no result after 1 s" in report["failure"]
    assert "see hang.log" in report["failure"]


_STAND_IN_APP = '''\
#!{python}
"""A stand-in for the installed app: --version, and serve with the two probes."""
import http.server, json, os, socketserver, sys, tomllib
from pathlib import Path

VERSION = "{version}"
if "--version" in sys.argv:
    print("dodaios " + VERSION)
    raise SystemExit(0)
config = tomllib.loads(Path(os.environ["JARVIS_CONFIG"]).read_text())
port = config["ui"]["admin_api_port"] + {offset}
mark = Path(os.environ["JARVIS_DATA_DIR"]) / "onboarded"


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/health":
            self._send({{"ok": True}})
        else:
            self._send({{"completed": mark.exists()}})

    def do_POST(self):
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.write_text("yes")
        self._send({{}})

    def log_message(self, *args):
        pass


class Server(http.server.HTTPServer):
    # HTTPServer looks up the host's full name on bind (socket.getfqdn). On
    # the hosted macOS runners that reverse lookup took longer than the 30 s
    # boot window, so the stand-in never answered. The name is not needed.
    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


Server(("127.0.0.1", port), Handler).serve_forever()
'''


def _stand_in_setup(folder: Path, version: str) -> Path:
    """A "Setup" that puts the stand-in app of *version* into its /DIR= folder."""
    from dodaios.core.instance import DEV_PORT_OFFSET

    app = folder / f"app-{version}.py"
    app.write_text(
        _STAND_IN_APP.format(python=sys.executable, version=version, offset=DEV_PORT_OFFSET),
        encoding="utf-8",
    )
    return _script(
        folder / f"Setup-{version}",
        f"""\
        for argument in "$@"; do
          case "$argument" in
            /DIR=*) target="${{argument#/DIR=}}" ;;
            /LOG=*) echo "installed {version}" > "${{argument#/LOG=}}" ;;
          esac
        done
        mkdir -p "$target"
        cp "{app}" "$target/DodaiosApp.exe"
        chmod +x "$target/DodaiosApp.exe"
        """,
    )


@posix_only
def test_the_whole_check_passes_for_an_upgrade_that_keeps_the_state(monkeypatch, tmp_path, capsys):
    """Both stand-in setups, both boots, both version reads: the real ``main``."""
    previous = _stand_in_setup(tmp_path, "1.0.0")
    current = _stand_in_setup(tmp_path, "2.0.0")
    proof = tmp_path / "proof"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_installer_upgrade.py",
            "--previous", str(previous),
            "--current", str(current),
            "--expect-version", "2.0.0",
            "--install-dir", str(tmp_path / "installed"),
            "--output", str(proof),
            "--timeout", "30",
        ],
    )  # fmt: skip

    assert upgrade.main() == 0, capsys.readouterr().err

    report = json.loads((proof / "report.json").read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert report["phase"] == "done"
    assert report["previous"]["version"] == "dodaios 1.0.0"
    assert report["previous"]["onboarding_completed"] is False
    assert report["current"]["version"] == "dodaios 2.0.0"
    assert report["current"]["onboarding_completed"] is True
    assert report["current"]["left_behind"] == []
    assert not (proof / "hang.log").exists()


@posix_only
def test_an_upgrade_to_the_wrong_version_fails_with_the_reason(monkeypatch, tmp_path, capsys):
    previous = _stand_in_setup(tmp_path, "1.0.0")
    proof = tmp_path / "proof"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_installer_upgrade.py",
            "--previous", str(previous),
            "--current", str(previous),
            "--expect-version", "2.0.0",
            "--install-dir", str(tmp_path / "installed"),
            "--output", str(proof),
            "--timeout", "30",
        ],
    )  # fmt: skip

    assert upgrade.main() == 1

    report = json.loads((proof / "report.json").read_text(encoding="utf-8"))
    assert report["passed"] is False
    assert "reports 'dodaios 1.0.0', not 2.0.0" in report["failure"]
    assert report["phase"] == "read this build's version"
