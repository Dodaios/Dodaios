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
"""

from __future__ import annotations

import argparse
import http.client
import json
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.ci.check_frozen_browser import isolated_env, stop_owned_tree  # noqa: E402

SILENT = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"]
# Executable names across releases: the current one first.
APP_NAMES = ("DodaiosApp.exe", "PersonalJarvisApp.exe", "JarvisApp.exe")


def run_setup(setup: Path, install_dir: Path, log: Path) -> None:
    command = [str(setup), *SILENT, f"/DIR={install_dir}", f"/LOG={log}"]
    print("+", " ".join(command), flush=True)
    result = subprocess.run(command, timeout=900, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"{setup.name} exited with {result.returncode}; see {log.name}")


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
                raise TimeoutError(f"{app.name} was not healthy within {timeout:.0f} s")
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


def version_of(app: Path) -> str:
    result = subprocess.run(
        [str(app), "--version"], capture_output=True, text=True, timeout=120, check=False
    )
    return (result.stdout or result.stderr).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True, help="The published Setup.exe")
    parser.add_argument("--current", type=Path, required=True, help="The Setup.exe just built")
    parser.add_argument("--expect-version", required=True)
    parser.add_argument("--install-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    profile = output / "profile"
    profile.mkdir(exist_ok=False)
    key = "jctl_" + secrets.token_urlsafe(32)
    report: dict = {"passed": False}
    try:
        previous = args.previous.resolve(strict=True)
        run_setup(previous, args.install_dir, output / "install-previous.log")
        old_app = find_app(args.install_dir)
        report["previous"] = {"app": old_app.name, "version": version_of(old_app)}
        report["previous"].update(
            boot(old_app, profile, output / "boot-previous.log", key, args.timeout, complete=True)
        )

        current = args.current.resolve(strict=True)
        run_setup(current, args.install_dir, output / "install-current.log")
        new_app = find_app(args.install_dir)
        version = version_of(new_app)
        report["current"] = {"app": new_app.name, "version": version}
        if args.expect_version not in version:
            raise RuntimeError(
                f"After the upgrade {new_app.name} reports {version!r}, not {args.expect_version}"
            )
        row = boot(new_app, profile, output / "boot-current.log", key, args.timeout, complete=False)
        report["current"].update(row)
        if not row["onboarding_completed"]:
            raise RuntimeError("The upgrade lost the state the previous release wrote")
        report["passed"] = True
        return 0
    except Exception as exc:
        report["failure"] = f"{type(exc).__name__}: {exc}"
        print(f"Installer upgrade check failed: {report['failure']}", file=sys.stderr)
        return 1
    finally:
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
