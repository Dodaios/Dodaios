"""Upgrade a Windows install in place: the previous release, then this build.

Most users never install from scratch: they run a new Setup.exe over the one
they have, or the in-app updater does it for them. A fresh-install check
cannot see an upgrade that breaks (a changed AppId installs side by side, a
renamed executable leaves the old one behind, a data migration fails on the
first boot). This installs the published release silently, boots it once and
leaves state behind (onboarding completed), installs the new setup over the
same directory, then proves the new executable reports the new version, boots,
and still sees that state.

The app runs with an isolated profile (check_frozen_browser.isolated_env): no
account keys, no inherited config, a data directory of its own that both
versions share, as a real user's data directory is shared across an upgrade.

Every wait here ends by itself. On release tags this check stopped for good
five times (v5.2.0 three times, v5.3.1, v5.3.2), each time until someone
cancelled the job, and a cancelled job keeps neither its log nor its
evidence, so the cause was never seen. Two calls could wait without end: the
download of the previous setup had no time limit, and reading the version
through a pipe waits for every process that still holds that pipe, also after
the app itself is gone. Now the download is limited and tried again, no call
reads a child through a pipe, a setup or app that is stopped is stopped with
its whole process tree, processes an app leaves behind in the install folder
are named in the report, and an overall deadline writes ``hang.log`` (what
every thread was doing, which processes were alive) before it ends the run.
"""

from __future__ import annotations

import argparse
import faulthandler
import http.client
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.ci.check_frozen_browser import isolated_env, stop_owned_tree  # noqa: E402

SILENT = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"]
# Executable names across releases: the current one first.
APP_NAMES = ("DodaiosApp.exe", "PersonalJarvisApp.exe", "JarvisApp.exe")
#: A silent setup takes about 40 s on a hosted runner.
SETUP_TIMEOUT_S = 600.0
#: The 400 MB setup downloads in a few seconds; a stalled transfer is tried again.
DOWNLOAD_TIMEOUT_S = 240.0
DOWNLOAD_TRIES = 3
#: The whole check takes about 90 s. Past this it is stuck, not slow.
OVERALL_DEADLINE_S = 20 * 60.0

_STARTED = time.monotonic()


def say(message: str) -> None:
    """One flushed line with the time since the start, so a log shows where it stopped."""
    print(f"[upgrade {time.monotonic() - _STARTED:6.1f} s] {message}", flush=True)


def kill_tree(pid: int, *, include_parent: bool = True) -> list[str]:
    """Kill *pid* and everything it started; the names of what was killed."""
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return []  # It ended by itself.
    killed: list[str] = []
    targets = [*reversed(parent.children(recursive=True))]
    if include_parent:
        targets.append(parent)
    for process in targets:
        try:
            killed.append(f"{process.name()} ({process.pid})")
            process.kill()
        except psutil.NoSuchProcess:
            continue  # It ended between the listing and the kill.
    return killed


def run_bounded(command: list[str], *, timeout: float, output: Path | None = None) -> int:
    """Run *command* to its end or kill its whole tree after *timeout* seconds.

    The child never gets a pipe of this process: its output goes to *output*
    (or nowhere) and its input is closed. A pipe is read until every process
    holding it is gone, which a child of the child can keep from happening
    for as long as it lives.
    """
    stream = output.open("wb") if output is not None else None
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=stream if stream is not None else subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            killed = kill_tree(process.pid)
            raise TimeoutError(
                f"{Path(command[0]).name} did not finish within {timeout:.0f} s; "
                f"stopped {', '.join(killed) or 'nothing'}"
            ) from None
    finally:
        if stream is not None:
            stream.close()


def log_tail(log: Path, lines: int = 25) -> str:
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"(no {log.name}: {exc})"
    return "\n".join(text.splitlines()[-lines:])


def download_previous(repo: str, asset: str, folder: Path) -> Path:
    """Fetch *asset* of the latest published release; a stalled transfer is retried."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / asset
    command = [
        "gh", "release", "download", "--repo", repo, "--dir", str(folder),
        "--pattern", asset, "--clobber",
    ]  # fmt: skip
    problem = ""
    for attempt in range(1, DOWNLOAD_TRIES + 1):
        say(f"download the published {asset} (try {attempt}/{DOWNLOAD_TRIES})")
        output = folder / f"download-{attempt}.log"
        try:
            code = run_bounded(command, timeout=DOWNLOAD_TIMEOUT_S, output=output)
        except TimeoutError as exc:
            problem = str(exc)
            continue
        if code == 0 and target.is_file():
            return target
        problem = f"gh exited with {code}: {log_tail(output, 5)}"
    raise RuntimeError(f"The latest release carries no {asset} to upgrade from ({problem})")


def run_setup(setup: Path, install_dir: Path, log: Path) -> None:
    command = [str(setup), *SILENT, f"/DIR={install_dir}", f"/LOG={log}"]
    say("+ " + " ".join(command))
    try:
        code = run_bounded(command, timeout=SETUP_TIMEOUT_S)
    except TimeoutError as exc:
        raise RuntimeError(f"{exc}. End of {log.name}:\n{log_tail(log)}") from None
    if code != 0:
        raise RuntimeError(
            f"{setup.name} exited with {code}. End of {log.name}:\n{log_tail(log)}"
        )


def leftover_processes(install_dir: Path) -> list[dict]:
    """Processes still running from the install folder; each is killed.

    A stopped app must leave nothing behind there: the next setup has to
    replace those files. What is found goes into the report by name, so a
    process that outlives the app is seen instead of only suspected.
    """
    root = str(install_dir.resolve()).lower()
    found: list[dict] = []
    for process in psutil.process_iter(["pid", "ppid", "name", "exe", "cmdline"]):
        exe = (process.info.get("exe") or "").lower()
        if not exe.startswith(root):
            continue
        found.append(
            {
                "pid": process.info["pid"],
                "ppid": process.info["ppid"],
                "name": process.info["name"],
                "cmdline": " ".join(process.info.get("cmdline") or [])[:300],
            }
        )
        try:
            process.kill()
        except psutil.NoSuchProcess:
            continue  # It ended by itself in the meantime.
    return found


def note_leftovers(install_dir: Path) -> list[dict]:
    """Report (and stop) what a stopped app left running; a warning names each."""
    found = leftover_processes(install_dir)
    for row in found:
        print(
            f"::warning::The stopped app left {row['name']} ({row['pid']}) running "
            f"in {install_dir}: {row['cmdline']}",
            flush=True,
        )
    return found


def process_table() -> str:
    """Every process on the machine, for the hang report."""
    rows = []
    for process in psutil.process_iter(["pid", "ppid", "name", "exe", "cmdline", "create_time"]):
        info = process.info
        age = time.time() - (info.get("create_time") or time.time())
        command = " ".join(info.get("cmdline") or [])[:200] or (info.get("exe") or "")
        rows.append(
            f"{info['pid']:>7} {info['ppid'] or 0:>7} {age:>8.0f}s {info['name']} {command}"
        )
    return "\n".join(rows)


def arm_deadline(output: Path, install_dir: Path, report: dict, seconds: float) -> threading.Timer:
    """After *seconds*, write what is stuck to ``hang.log`` and end the run red."""

    def _expired() -> None:
        hang = output / "hang.log"
        try:
            with hang.open("w", encoding="utf-8") as stream:
                stream.write(f"No result after {seconds:.0f} s, in phase: {report.get('phase')}\n")
                stream.write("\n")
                stream.write("Threads of the check:\n")
                stream.flush()
                faulthandler.dump_traceback(file=stream, all_threads=True)
                stream.write("\nProcesses (pid, parent, age, name, command):\n")
                stream.write(process_table() + "\n")
            report["leftover_at_deadline"] = leftover_processes(install_dir)
            report["failure"] = (
                f"TimeoutError: no result after {seconds:.0f} s in phase "
                f"{report.get('phase')!r}; see hang.log"
            )
            (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
            print(f"Installer upgrade check failed: {report['failure']}", file=sys.stderr)
            print(hang.read_text(encoding="utf-8", errors="replace")[-6000:], flush=True)
            kill_tree(os.getpid(), include_parent=False)
        finally:
            os._exit(1)

    timer = threading.Timer(seconds, _expired)
    timer.daemon = True
    timer.start()
    return timer


def find_app(install_dir: Path) -> Path:
    for name in APP_NAMES:
        candidate = install_dir / name
        if candidate.is_file():
            return candidate
    found = sorted(path.name for path in install_dir.glob("*.exe"))
    raise RuntimeError(f"No app executable in {install_dir}: {found}")


def request(
    port: int, path: str, key: str, *, method: str = "GET", as_browser: bool = False
) -> tuple[int, dict]:
    """Call the app as the Control API (Bearer) or as the desktop UI would.

    Completing onboarding is a desktop action: a Bearer is refused as proof
    that no click authorized it, and the auth-exempt first-boot route wants
    the same-origin header a browser attaches instead (lifecycle_guard.py).
    """
    if as_browser:
        headers = {"Origin": f"http://127.0.0.1:{port}"}
    else:
        headers = {"Authorization": f"Bearer {key}"}
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        body = response.read()
        try:
            return response.status, json.loads(body or b"{}")
        except ValueError:
            return response.status, {}
    finally:
        connection.close()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def boot(app: Path, profile: Path, log: Path, key: str, timeout: float, *, complete: bool) -> dict:
    """Boot `serve`, wait for health, read (and optionally complete) onboarding."""
    port = free_port()
    env = isolated_env(profile, port, key)
    started = time.monotonic()
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(
            [str(app), "serve"],
            cwd=profile,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=stream,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            while time.monotonic() - started < timeout:
                if process.poll() is not None:
                    raise RuntimeError(f"{app.name} exited during boot: {process.returncode}")
                try:
                    status, health = request(port, "/api/health", key)
                except (OSError, http.client.HTTPException):
                    time.sleep(1)
                    continue
                if status == 200 and health.get("ok"):
                    break
                time.sleep(1)
            else:
                stream.flush()
                raise TimeoutError(
                    f"{app.name} was not healthy within {timeout:.0f} s. "
                    f"End of {log.name}:\n{log_tail(log)}"
                )
            row = {"healthy_seconds": round(time.monotonic() - started, 3)}
            status, state = request(port, "/api/onboarding/state", key)
            if status != 200:
                raise RuntimeError(f"onboarding state answered HTTP {status}")
            row["onboarding_completed"] = bool(state.get("completed"))
            if complete:
                status, _ = request(
                    port, "/api/onboarding/complete", key, method="POST", as_browser=True
                )
                if status != 200:
                    raise RuntimeError(f"completing onboarding answered HTTP {status}")
            return row
        finally:
            stop_owned_tree(process)


def version_of(app: Path, log: Path) -> str:
    """What ``<app> --version`` prints, read from a file and not from a pipe."""
    code = run_bounded([str(app), "--version"], timeout=120, output=log)
    text = log.read_text(encoding="utf-8", errors="replace").strip()
    if code != 0 and not text:
        raise RuntimeError(f"{app.name} --version exited with {code} and printed nothing")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--previous", type=Path, help="The published Setup.exe, already on disk")
    source.add_argument(
        "--previous-release",
        metavar="OWNER/REPO",
        help="Download the setup from this repository's latest published release",
    )
    parser.add_argument("--asset", default="Dodaios-Setup-x64.exe", help="Name of that setup")
    parser.add_argument("--current", type=Path, required=True, help="The Setup.exe just built")
    parser.add_argument("--expect-version", required=True)
    parser.add_argument("--install-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--deadline", type=float, default=OVERALL_DEADLINE_S)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    profile = output / "profile"
    profile.mkdir(exist_ok=False)
    key = "jctl_" + secrets.token_urlsafe(32)
    report: dict = {"passed": False, "phase": "start"}
    deadline = arm_deadline(output, args.install_dir, report, args.deadline)

    def phase(name: str) -> None:
        report["phase"] = name
        say(name)

    try:
        if args.previous_release:
            phase("download the published setup")
            previous = download_previous(args.previous_release, args.asset, output / "previous")
        else:
            previous = args.previous.resolve(strict=True)
        phase("install the published release")
        run_setup(previous, args.install_dir, output / "install-previous.log")
        old_app = find_app(args.install_dir)
        phase("read the published release's version")
        report["previous"] = {
            "app": old_app.name,
            "version": version_of(old_app, output / "version-previous.log"),
        }
        phase("boot the published release")
        report["previous"].update(
            boot(old_app, profile, output / "boot-previous.log", key, args.timeout, complete=True)
        )
        report["previous"]["left_behind"] = note_leftovers(args.install_dir)

        current = args.current.resolve(strict=True)
        phase("install this build over it")
        run_setup(current, args.install_dir, output / "install-current.log")
        new_app = find_app(args.install_dir)
        phase("read this build's version")
        version = version_of(new_app, output / "version-current.log")
        report["current"] = {"app": new_app.name, "version": version}
        if args.expect_version not in version:
            raise RuntimeError(
                f"After the upgrade {new_app.name} reports {version!r}, not {args.expect_version}"
            )
        phase("boot this build")
        row = boot(new_app, profile, output / "boot-current.log", key, args.timeout, complete=False)
        report["current"].update(row)
        report["current"]["left_behind"] = note_leftovers(args.install_dir)
        if not row["onboarding_completed"]:
            raise RuntimeError("The upgrade lost the state the previous release wrote")
        report["passed"] = True
        phase("done")
        return 0
    except Exception as exc:
        report["failure"] = f"{type(exc).__name__}: {exc}"
        print(f"Installer upgrade check failed: {report['failure']}", file=sys.stderr)
        return 1
    finally:
        deadline.cancel()
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
