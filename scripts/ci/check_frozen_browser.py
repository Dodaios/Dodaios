"""Exercise requested browser provisioning and real frames in the frozen app.

Run after packaging, with --executable pointing at the built launcher. Two
headless boots share a fresh scratch profile; no source imports, account keys,
desktop input, or existing user state are passed to the child application. On
macOS each boot also asks the running app for its permission status, which is
the only way to see whether its pyobjc frameworks loaded (BUG-222).

Headless startup deliberately leaves the optional browser idle. The probe
requests installation through the same authenticated API as the product UI.

Each boot also calls the tools a chat draws and writes with (whiteboard,
document) over the MCP surface a chat's coding CLI uses, and the run first
feeds the secret-store guard hook the file and shell calls Claude Code hands
it (#1879).

On Windows a third start goes first: the bare executable, started detached
with its streams on NUL the way the background service's tray and a restart
start it, must boot instead of starting copies of itself (#1880).
"""

from __future__ import annotations

import argparse
import base64
import http.client
import io
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path

import psutil
from PIL import Image
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dodaios.core.config_writer import _WRITE_LOCK, _atomic_write  # noqa: E402
from dodaios.core.instance import DEV_PORT_OFFSET  # noqa: E402
from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS, wait_procs  # noqa: E402
from dodaios.platform.permissions import ACCEPTED_BUNDLE_IDS  # noqa: E402


def isolated_env(profile: Path, port: int, key: str) -> dict[str, str]:
    """Keep OS launch essentials, excluding inherited account/config secrets."""
    allowed = {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "TMPDIR",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROGRAMW6432",
        "LANG",
        "LANGUAGE",
        "LC_ALL",
        "LC_CTYPE",
    }
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    for name in (
        "HOME",
        "USERPROFILE",
        "LOCALAPPDATA",
        "APPDATA",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
    ):
        env[name] = str(profile)
    config = profile / "jarvis.toml"
    port_line = f"admin_api_port = {port - DEV_PORT_OFFSET}"
    port_re = re.compile(r"(?m)^admin_api_port\s*=.*$")
    with _WRITE_LOCK:
        # The restart boot keeps what the first boot saved (the setup name's
        # [trigger] section); only the port moves to this boot's free one.
        text = config.read_text(encoding="utf-8") if config.exists() else ""
        if port_re.search(text):
            text = port_re.sub(port_line, text, count=1)
        else:
            text = f"[ui]\n{port_line}\n" + text
        _atomic_write(config, text)
    env.update(
        JARVIS_INSTANCE="dev",
        JARVIS_CONFIG=str(config),
        JARVIS_DATA_DIR=str(profile / "data"),
        JARVIS_CONTROL_API_KEY=key,
        PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
        PYTHONIOENCODING="utf-8",
    )
    return env


def stop_owned_tree(process: subprocess.Popen) -> None:
    try:
        parent = psutil.Process(process.pid)
    except psutil.NoSuchProcess:
        return  # The application may have exited on its own.
    owned = [*reversed(parent.children(recursive=True)), parent]
    for child in owned:
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            pass  # Browser containment can close descendants concurrently.
    _, alive = wait_procs(owned, timeout=8)
    for child in alive:
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass  # A pending graceful shutdown may win the race.
    _, alive = wait_procs(alive, timeout=5)
    if alive:
        raise RuntimeError("Frozen app left owned processes running")
    process.wait(timeout=5)


class ProbeHTTPError(RuntimeError):
    def __init__(self, code: int):
        self.code = code
        super().__init__(f"Frozen probe request failed: HTTP {code}")


def request_json(port: int, path: str, key: str, *, method: str = "GET") -> dict:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(method, path, headers={"Authorization": f"Bearer {key}"})
        response = connection.getresponse()
        if response.status != 200:
            raise ProbeHTTPError(response.status)
        return json.loads(response.read())
    finally:
        connection.close()


#: The path a chat's coding CLI reaches the app's tools on (``--mcp-config``).
MCP_PATH = "/api/control/mcp/"
#: What a chat turn draws, writes and builds with (#1879).
CHAT_TOOLS = ("whiteboard", "node", "create_artifact")


def mcp_request(port: int, key: str, method: str, params: dict, *, timeout: float = 60) -> dict:
    """One JSON-RPC call on the app's own MCP tools surface, as a chat's CLI makes it."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request(
            "POST",
            MCP_PATH,
            body=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            raise ProbeHTTPError(response.status)
        payload = json.loads(response.read())
    finally:
        connection.close()
    if "error" in payload:
        raise RuntimeError(f"MCP {method} failed: {payload['error']}")
    return payload["result"]


def _tool_text(result: dict) -> str:
    parts = [part for part in result.get("content") or [] if isinstance(part, dict)]
    return " ".join(str(part.get("text") or "") for part in parts)


def check_chat_tools(port: int, key: str, *, wait_s: float = 180) -> dict:
    """The tools a chat draws and writes with answer in the frozen app (#1879).

    The same MCP calls the chat's coding CLI makes: the catalog offers the
    whiteboard, node and artifact tools, a whiteboard is drawn and a document
    is written. A tool that fails here fails in every chat of the build.
    """
    # The app answers its health check before its tools are registered.
    deadline = time.monotonic() + wait_s
    while True:
        listed = {tool["name"] for tool in mcp_request(port, key, "tools/list", {})["tools"]}
        missing = [name for name in CHAT_TOOLS if name not in listed]
        if not missing:
            break
        if time.monotonic() > deadline:
            raise RuntimeError(f"The frozen app's MCP catalog lacks {', '.join(missing)}")
        time.sleep(1)
    calls = {
        "whiteboard": {
            "operation": "create",
            "title": "Frozen check board",
            "mermaid": "flowchart LR\n  A[TEST] --> B[Done]",
        },
        "node": {
            "operation": "create",
            "type": "docs",
            "title": "Frozen check document",
            "spec": {"summary": "A check.", "markdown": "# Frozen check\n\nIt writes documents."},
        },
        # create_artifact is only required in the catalog: a call starts a
        # background build that needs a model and comes back with the restart.
    }
    report: dict = {"mcp_tools": len(listed)}
    for name, arguments in calls.items():
        result = mcp_request(port, key, "tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise RuntimeError(f"The frozen app's {name} tool failed: {_tool_text(result)[:500]}")
        report[f"{name}_ok"] = True
    return report


def check_vault_guard_hook(executable: Path, timeout: float = 30) -> dict:
    """The secret-store guard a chat's Claude Code runs before every file call (#1879).

    Claude Code runs ``"<app>" --vault-guard-hook`` with the call on stdin and
    blocks the call when the hook exits 2. A build whose hook pointed at a
    ``.py`` file it does not ship exited 2 for EVERY Read, Grep, Glob and Bash
    call, so a chat could read no file and no picture.
    """
    cases = {
        "read": ({"tool_name": "Read", "tool_input": {"file_path": "README.md"}}, 0),
        "image": ({"tool_name": "Read", "tool_input": {"file_path": "picture.png"}}, 0),
        "shell": ({"tool_name": "Bash", "tool_input": {"command": "git status"}}, 0),
        "vault": (
            {"tool_name": "Bash", "tool_input": {"command": "keyring get dodaios owner"}},
            2,
        ),
    }
    report: dict = {}
    for name, (call, expected) in cases.items():
        started = time.monotonic()
        done = subprocess.run(  # noqa: S603 - the built app, a fixed flag
            [str(executable), "--vault-guard-hook"],
            input=json.dumps(call).encode("utf-8"),
            capture_output=True,
            timeout=timeout,
            creationflags=NO_WINDOW_CREATIONFLAGS,
            check=False,
        )
        seconds = round(time.monotonic() - started, 2)
        if done.returncode != expected:
            raise RuntimeError(
                f"The vault guard hook answered {done.returncode} for a {name} call "
                f"(expected {expected}): {done.stderr.decode('utf-8', 'replace')[:300]}"
            )
        report[f"vault_guard_{name}_seconds"] = seconds
    return report


def check_macos_permissions(port: int, key: str) -> dict:
    """On macOS, prove the running app can read its own microphone permission.

    The permission port loads its pyobjc frameworks by NAME, which a freezer
    cannot follow, and reports a framework that did not load as "unavailable"
    without any error: the v2.5.0 .dmg shipped without AVFoundation and could
    never read its microphone permission (BUG-222). Whether the module is in
    the archive is checked statically by check_frozen_macos_app.py; this asks
    the app itself, which also catches a framework whose own dependencies were
    left out. Elsewhere there is nothing to ask.

    The status route is passive (it never raises a system dialog), and this
    reads only keys that survive in the snapshot: ``permissions[].id/status``
    and ``app_identity.bundle_id``.
    """
    if sys.platform != "darwin":
        return {}
    try:
        snapshot = request_json(port, "/api/permissions/status", key)
    except ProbeHTTPError as exc:
        if exc.code == 404:
            # Not "still starting": waiting for the deadline would only hide it.
            raise RuntimeError("Frozen app does not serve /api/permissions/status") from None
        raise
    rows = [row for row in snapshot.get("permissions", []) if isinstance(row, dict)]
    microphone = next((row.get("status") for row in rows if row.get("id") == "microphone"), None)
    if microphone in (None, "unavailable"):
        raise RuntimeError(
            f"Frozen app cannot read its microphone permission (status {microphone!r}): "
            "the pyobjc AVFoundation framework did not load"
        )
    bundle_id = (snapshot.get("app_identity") or {}).get("bundle_id")
    if bundle_id not in ACCEPTED_BUNDLE_IDS:
        raise RuntimeError(
            f"Frozen app runs as {bundle_id!r}, which the permission port does not accept "
            f"(expected one of {', '.join(ACCEPTED_BUNDLE_IDS)})"
        )
    return {"microphone_permission": microphone, "bundle_id": bundle_id}


def capture_frame(port: int, key: str, output: Path) -> dict:
    started = time.monotonic()
    with connect(
        f"ws://127.0.0.1:{port}/api/society/agents/jarvis/browser/live",
        additional_headers={"Authorization": f"Bearer {key}"},
        open_timeout=10,
    ) as viewer:
        while time.monotonic() - started < 60:
            event = json.loads(viewer.recv(timeout=15))
            if event.get("kind") in {"error", "disconnected"}:
                raise RuntimeError("Frozen browser stream failed before its first frame")
            if event.get("kind") != "frame":
                continue
            content = base64.b64decode(event["data"], validate=True)
            with Image.open(io.BytesIO(content)) as frame:
                frame.load()
                width, height = frame.size
                if width < 320 or height < 200:
                    raise RuntimeError("Frozen browser frame is too small")
            output.write_bytes(content)
            return {
                "first_frame_seconds": round(time.monotonic() - started, 3),
                "width": width,
                "height": height,
                "full_window": bool(event.get("full_window")),
            }
    raise TimeoutError("Frozen browser did not produce a frame within 60 seconds")


def check_setup_name_save(port: int, key: str) -> dict:
    """The setup wizard's first step on a fresh install: save the name.

    The name is the wake word, so the wizard PUTs it to the wake-word route.
    A frozen app once answered that with HTTP 500 (issue #1734); the status and
    the body land in the report so a failure says what broke.
    """
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    try:
        connection.request(
            "PUT",
            "/api/settings/wake-word",
            body=json.dumps({"persist": True, "phrase": "Jarvis", "engine": "auto"}),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Origin": f"http://127.0.0.1:{port}",
            },
        )
        response = connection.getresponse()
        body = response.read().decode("utf-8", "replace")
    finally:
        connection.close()
    print(f"setup name save: HTTP {response.status} {body[:600]}", flush=True)
    if response.status != 200:
        raise RuntimeError(f"Saving the setup name failed: HTTP {response.status} {body[:600]}")
    return {"setup_name_save": json.loads(body).get("resolved_engine", "")}


def boot(
    executable: Path, profile: Path, output: Path, key: str, timeout: float, *, tools: bool = True
) -> dict:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = isolated_env(profile, port, key)
    started = time.monotonic()
    report: dict = {"browser_install_requested": False}
    with output.with_suffix(".log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [str(executable), "serve"],
            cwd=profile,
            env=env,
            stdout=log,
            stderr=log,
            creationflags=NO_WINDOW_CREATIONFLAGS,
        )
        try:
            last_phase = None
            while time.monotonic() - started < timeout:
                if process.poll() is not None:
                    raise RuntimeError(
                        f"Frozen app exited before browser readiness: {process.returncode}"
                    )
                try:
                    health = request_json(port, "/api/health", key)
                    if health.get("ok") and "healthy_seconds" not in report:
                        if health.get("instance") != "dev":
                            raise RuntimeError("Frozen probe reached the wrong app instance")
                        report["healthy_seconds"] = round(time.monotonic() - started, 3)
                        report.update(check_setup_name_save(port, key))
                    if "permissions" not in report and "healthy_seconds" in report:
                        report["permissions"] = check_macos_permissions(port, key)
                    if tools and "mcp_tools" not in report and "healthy_seconds" in report:
                        # Asked again after a 503: the tools surface may come up later.
                        report.update(check_chat_tools(port, key))
                    status = request_json(port, "/api/society/browser/status", key)
                except ProbeHTTPError as exc:
                    if exc.code not in {503, 404}:
                        raise RuntimeError(
                            f"Frozen probe request failed: HTTP {exc.code}"
                        ) from None
                    time.sleep(1)
                    continue
                except (OSError, http.client.HTTPException):
                    time.sleep(1)
                    continue
                if (
                    "healthy_seconds" in report
                    and not report["browser_install_requested"]
                    and not status.get("installed")
                    and not status.get("running")
                    and status.get("phase") == "idle"
                ):
                    status = request_json(
                        port, "/api/society/browser/install", key, method="POST"
                    )
                    if not any(status.get(field) for field in ("started", "running", "installed")):
                        raise RuntimeError("Frozen app declined the requested browser setup")
                    report["browser_install_requested"] = True
                phase = status.get("phase")
                if phase != last_phase:
                    print(f"{output.name}: browser phase={phase}", flush=True)
                    last_phase = phase
                if status.get("error"):
                    raise RuntimeError(
                        "Frozen app browser provisioning failed; inspect its log"
                    )
                if status.get("installed") and "healthy_seconds" in report:
                    report["browser_ready_seconds"] = round(time.monotonic() - started, 3)
                    report.update(capture_frame(port, key, output.with_suffix(".jpg")))
                    return report
                time.sleep(1)
            raise TimeoutError(
                "Frozen app did not prepare the requested browser before the deadline"
            )
        finally:
            stop_owned_tree(process)


def _bare_copies(executable: Path, since: float) -> dict[int, float]:
    """Processes of ``executable`` started since ``since`` with no arguments."""
    found: dict[int, float] = {}
    for proc in psutil.process_iter(["exe", "cmdline", "create_time"]):
        info = proc.info
        try:
            if not info["exe"] or Path(info["exe"]).resolve() != executable:
                continue
        except OSError:
            continue  # an exe path that cannot be resolved is not ours
        if len(info["cmdline"] or []) == 1 and (info["create_time"] or 0) >= since - 1:
            found[proc.pid] = info["create_time"]
    return found


def check_bare_start_settles(executable: Path, profile: Path, watch_s: float = 25.0) -> dict:
    """Windows: a bare start on NUL streams boots instead of starting a copy (#1880).

    The background service's tray "Open" and every restart start the bare GUI
    executable detached, with its streams on NUL. Windows calls NUL a terminal
    (``isatty()``), and the start took itself for one typed into a console: it
    started one more detached copy and exited, every two seconds, for good.
    Started here exactly that way, the copy count must stay at one.
    """
    profile.mkdir(exist_ok=False)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = isolated_env(profile, port, "jctl_" + secrets.token_urlsafe(32))
    # A CI runner is elevated: stay in this process instead of the unelevated hand-over.
    env["JARVIS_KEEP_ELEVATION"] = "1"
    detached = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    started = time.time()
    process = subprocess.Popen(
        [str(executable)],
        cwd=profile,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=detached | NO_WINDOW_CREATIONFLAGS,
    )
    seen: dict[int, float] = {}
    try:
        deadline = time.monotonic() + watch_s
        while time.monotonic() < deadline:
            seen.update(_bare_copies(executable, started))
            if len(seen) > 1:
                break
            time.sleep(0.25)
        exited = process.poll()
    finally:
        for pid in seen:
            if pid != process.pid:
                try:
                    psutil.Process(pid).kill()
                except psutil.Error:
                    pass  # the copy ended on its own
        stop_owned_tree(process)
    report = {"bare_copies": len(seen), "first_exited_with": exited}
    if len(seen) > 1:
        raise RuntimeError(
            f"A bare start on NUL streams started {len(seen) - 1} more bare copies "
            "of itself instead of booting (#1880)"
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()
    executable = args.executable.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    # A fresh path is mandatory: accidentally reusing a prior runtime would
    # turn a failed provisioning path into a passing warm-start test.
    profile = output / "profile"
    profile.mkdir(exist_ok=False)
    key = "jctl_" + secrets.token_urlsafe(32)
    report = {"platform": sys.platform, "passed": False, "boots": []}
    try:
        report["vault_guard"] = check_vault_guard_hook(executable)
        if sys.platform == "win32":
            report["bare_start"] = check_bare_start_settles(executable, output / "bare-profile")
        for name in ("first-install", "restart"):
            # The tools once: the restart boot proves the browser comes back.
            tools = name == "first-install"
            row = boot(executable, profile, output / name, key, args.timeout, tools=tools)
            report["boots"].append({"name": name, **row})
        report["passed"] = True
        return 0
    except Exception as exc:
        report["failure"] = type(exc).__name__
        print(f"Frozen browser smoke failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        # The type alone ("OSError: [Errno 22]") does not say which step broke.
        traceback.print_exc(file=sys.stderr)
        return 1
    finally:
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
