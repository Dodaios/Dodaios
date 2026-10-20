"""Drive an interactive Blender through the Blender MCP add-on's TCP server.

The add-on (`blender_mcp.py` in Blender's user add-ons) listens on
localhost:<port> and takes one JSON object per request,
`{"type": <command>, "params": {...}}`, answering with one JSON object
`{"status": "success"|"error", "result"|"message": ...}`. This bridge lets
pipeline agents use it without an MCP client:

    python scripts/verse/mcp_bridge.py launch [--port 9876] [--blend FILE]
    python scripts/verse/mcp_bridge.py exec <file.py> [--port 9876]
    python scripts/verse/mcp_bridge.py scene [--port 9876]
    python scripts/verse/mcp_bridge.py screenshot <out.png> [--camera] [--shading material]
    python scripts/verse/mcp_bridge.py stop [--port 9876]

`launch` starts Blender with its GUI (not factory settings, so user add-ons
load), enables the add-on for this session only, starts its server on the
port and waits until it answers. Code run with `exec` can `import lib.scene`.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import blender  # noqa: E402

DEFAULT_PORT = 9876
STATE_DIR = blender.CACHE_ROOT / "mcp"
ADDON_MODULE = "blender_mcp"

_STARTUP = """
import sys, bpy, addon_utils
for path in ({art!r}, {tools!r}):
    if path not in sys.path:
        sys.path.insert(0, path)
addon_utils.enable({module!r}, default_set=False)
import {module} as _mcp

def _verse_start_server():
    server = getattr(bpy.types, "blendermcp_server", None)
    if server is not None and (server.port != {port} or not server.running):
        server.stop()
        del bpy.types.blendermcp_server
        server = None
    if server is None:
        bpy.types.blendermcp_server = _mcp.BlenderMCPServer(port={port})
        bpy.types.blendermcp_server.start()
    print("[verse] mcp server on port {port}:", bpy.types.blendermcp_server.running, flush=True)
    return None

bpy.app.timers.register(_verse_start_server, first_interval=1.0)
"""


class BridgeError(RuntimeError):
    """The add-on server is unreachable or answered with an error."""


def call(
    command: str, params: dict | None = None, port: int = DEFAULT_PORT, timeout: float = 120.0
):
    """Send one command and return its `result`; raise BridgeError on errors."""
    request = json.dumps({"type": command, "params": params or {}}).encode("utf-8")
    try:
        with socket.create_connection(("localhost", port), timeout=timeout) as connection:
            connection.sendall(request)
            response = _read_json(connection, timeout)
    except OSError as error:
        raise BridgeError(f"Blender MCP server on port {port} unreachable: {error}") from None
    if response.get("status") != "success":
        raise BridgeError(response.get("message", f"unexpected response: {response}"))
    return response.get("result")


def _read_json(connection: socket.socket, timeout: float) -> dict:
    """Read until the bytes form one complete JSON object (the add-on sends no framing)."""
    connection.settimeout(timeout)
    buffer = b""
    while True:
        chunk = connection.recv(65536)
        if not chunk:
            raise BridgeError("connection closed before a complete response arrived")
        buffer += chunk
        try:
            return json.loads(buffer.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue


def is_up(port: int = DEFAULT_PORT) -> bool:
    try:
        return call("ping", port=port, timeout=3.0) == {"pong": True}
    except BridgeError:
        return False


def _state_path(port: int) -> Path:
    return STATE_DIR / f"{port}.json"


def launch(port: int = DEFAULT_PORT, blend: Path | None = None, timeout: float = 120.0) -> int:
    """Start Blender with the MCP server on `port`; return its process id."""
    if is_up(port):
        raise BridgeError(f"a Blender MCP server already answers on port {port}")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    expr = _STARTUP.format(
        art=str(blender.ART_ROOT),
        tools=str(Path(__file__).resolve().parent),
        module=ADDON_MODULE,
        port=port,
    )
    command = [str(blender.find_blender())]
    if blend is not None:
        command.append(str(blend.resolve()))
    command += ["--python-expr", expr]
    log = open(STATE_DIR / f"{port}.log", "w", encoding="utf-8")  # noqa: SIM115 - owned by Blender
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    process = subprocess.Popen(
        command,
        stdout=log,
        stderr=subprocess.STDOUT,
        cwd=str(blender.REPO_ROOT),
        creationflags=flags,
    )
    _state_path(port).write_text(
        json.dumps({"pid": process.pid, "blend": str(blend or "")}), encoding="utf-8"
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise BridgeError(
                f"Blender exited with {process.returncode} (log: {STATE_DIR / f'{port}.log'})"
            )
        if is_up(port):
            return process.pid
        time.sleep(1.0)
    raise BridgeError(f"Blender MCP server did not answer on port {port} within {timeout:.0f} s")


def exec_code(code: str, port: int = DEFAULT_PORT) -> str:
    """Run Python inside the interactive Blender; return what it printed."""
    result = call("execute_code", {"code": code}, port=port)
    return result.get("result", "") if isinstance(result, dict) else str(result)


_VIEW_CODE = """
import bpy

def _hide_ceilings(layer):
    for child in layer.children:
        if child.name == "Ceiling":
            child.hide_viewport = {camera}
        _hide_ceilings(child)

_hide_ceilings(bpy.context.view_layer.layer_collection)
for window in bpy.context.window_manager.windows:
    for area in window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        space = area.spaces.active
        space.shading.type = {shading!r}
        space.overlay.show_overlays = {overlays}
        if {camera}:
            space.region_3d.view_perspective = "CAMERA"
            space.lock_camera = False
        region = next(r for r in area.regions if r.type == "WINDOW")
        if {camera}:
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.view3d.view_center_camera()
"""


def screenshot(
    out: Path,
    port: int = DEFAULT_PORT,
    max_size: int = 1600,
    camera: bool = False,
    shading: str | None = None,
) -> dict:
    """Save a viewport screenshot to `out` (optionally through the scene camera)."""
    if camera or shading:
        exec_code(
            _VIEW_CODE.format(
                shading=(shading or "MATERIAL").upper(), overlays=not camera, camera=camera
            ),
            port,
        )
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    result = call(
        "get_viewport_screenshot",
        {"max_size": max_size, "filepath": str(out), "format": "png"},
        port,
    )
    if not isinstance(result, dict) or result.get("error"):
        raise BridgeError(f"screenshot failed: {result}")
    return result


_QUIT_CODE = """
import bpy
bpy.app.timers.register(lambda: bpy.ops.wm.quit_blender(), first_interval=0.3)
"""


def stop(port: int = DEFAULT_PORT, timeout: float = 20.0) -> None:
    """Quit the Blender started by `launch` on `port` (by its recorded pid only)."""
    state_path = _state_path(port)
    pid = json.loads(state_path.read_text(encoding="utf-8"))["pid"] if state_path.exists() else None
    if is_up(port):
        try:
            exec_code(_QUIT_CODE, port)
        except BridgeError:
            pass
    deadline = time.monotonic() + timeout
    while pid is not None and _pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.5)
    if pid is not None and _pid_alive(pid):
        os.kill(pid, 9)
    state_path.unlink(missing_ok=True)


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return (
                bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
            )
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    sub = parser.add_subparsers(dest="command", required=True)
    launch_parser = sub.add_parser("launch")
    launch_parser.add_argument("--blend", type=Path)
    exec_parser = sub.add_parser("exec")
    exec_parser.add_argument("file", type=Path)
    sub.add_parser("scene")
    shot = sub.add_parser("screenshot")
    shot.add_argument("out", type=Path)
    shot.add_argument("--max-size", type=int, default=1600)
    shot.add_argument("--camera", action="store_true", help="look through the scene camera")
    shot.add_argument("--shading", choices=("solid", "material", "rendered", "wireframe"))
    sub.add_parser("stop")
    options = parser.parse_args(argv)
    try:
        if options.command == "launch":
            print(
                f"[verse] blender pid {launch(options.port, options.blend)} on port {options.port}"
            )
        elif options.command == "exec":
            print(exec_code(options.file.read_text(encoding="utf-8"), options.port), end="")
        elif options.command == "scene":
            print(json.dumps(call("get_scene_info", port=options.port), indent=1))
        elif options.command == "screenshot":
            result = screenshot(
                options.out, options.port, options.max_size, options.camera, options.shading
            )
            print(f"[verse] {result['width']}x{result['height']} -> {result['filepath']}")
        elif options.command == "stop":
            stop(options.port)
            print(f"[verse] stopped Blender on port {options.port}")
    except BridgeError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main())
