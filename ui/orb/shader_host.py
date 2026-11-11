"""Parent side of the desktop shader figure.

The figure is a child process (:mod:`ui.orb.shader_desktop`) so its
``QApplication`` never shares the Tk orb process. macOS requires that split:
Qt and Tk cannot both own the Cocoa application.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from typing import Any, Callable

log = logging.getLogger("jarvis.orb")

_Pos = tuple[int, int, int, int]


def _unit(value: float) -> float:
    try:
        level = float(value)
    except (TypeError, ValueError):
        return 0.0
    if level != level or level < 0.0:
        return 0.0
    return 1.0 if level > 1.0 else level


class ShaderFigureHost:
    """Show, move and hide the shader figure. Events arrive on a background thread."""

    def __init__(self, on_event: Callable[[dict[str, Any]], None]) -> None:
        self._on_event = on_event
        self._proc: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._source: str | None = None
        self._pos: _Pos | None = None
        self._state: int | None = None
        self._level = 0.0
        self._backdrop = 0.0
        self._visible = False
        self._failed = False
        self._failed_source: str | None = None
        self._png: bytes | None = None
        self._strip_png: bytes | None = None
        self._strip_pos: _Pos | None = None
        self._strip_on = False

    def sync(
        self,
        *,
        source: str | None,
        x: int,
        y: int,
        w: int,
        h: int,
        state: int,
        shown: bool,
        dragging: bool,
        level: float = 0.0,
        backdrop: float = 0.0,
    ) -> None:
        """Send whatever changed since the last call. ``dragging`` skips a move."""
        if not shown or not source:
            if self._visible:
                self._send({"op": "hide"})
                self._visible = False
                self._png = None
            return
        if self._failed and source == self._failed_source:
            return
        if self._proc is None and not self._start():
            self._failed = True
            self._failed_source = source
            return
        pos = (int(x), int(y), max(1, int(w)), max(1, int(h)))
        loud = _unit(level)
        shade = _unit(backdrop)
        if source != self._source or not self._visible:
            self._send(
                {
                    "op": "show",
                    "source": source,
                    "x": pos[0],
                    "y": pos[1],
                    "w": pos[2],
                    "h": pos[3],
                    "state": int(state),
                    "level": loud,
                    "backdrop": shade,
                }
            )
            self._source = source
            self._png = None
            self._pos = pos
            self._state = int(state)
            self._level = loud
            self._backdrop = shade
            self._visible = True
            self._failed = False
            return
        if not dragging and pos != self._pos:
            self._send({"op": "place", "x": pos[0], "y": pos[1], "w": pos[2], "h": pos[3]})
            self._pos = pos
        if int(state) != self._state:
            self._send({"op": "state", "state": int(state)})
            self._state = int(state)
        # A hundredth is enough for a glow. Smaller steps would flood stdin.
        if abs(loud - self._level) >= 0.01:
            self._send({"op": "level", "level": loud})
            self._level = loud
        if abs(shade - self._backdrop) >= 0.01:
            self._send({"op": "backdrop", "backdrop": shade})
            self._backdrop = shade

    def show_sprite(self, png: bytes, x: int, y: int, w: int, h: int) -> bool:
        """Show one pixel-pet frame. The same bytes are not sent twice."""
        import base64

        if self._proc is None and not self._start():
            return False
        pos = (int(x), int(y), max(1, int(w)), max(1, int(h)))
        if png != self._png or not self._visible or self._source is not None:
            encoded = base64.b64encode(png).decode("ascii")
            if not self._send(
                {"op": "sprite", "png": encoded, "x": pos[0], "y": pos[1], "w": pos[2], "h": pos[3]}
            ):
                return False
            self._png = png
            self._source = None
            self._pos = pos
            self._visible = True
            self._failed = False
            return True
        if pos != self._pos:
            if not self._send({"op": "place", "x": pos[0], "y": pos[1], "w": pos[2], "h": pos[3]}):
                return False
            self._pos = pos
        return True

    def show_strip(
        self, png: bytes, x: int, y: int, w: int, h: int, *, premul: bool = False
    ) -> bool:
        """Show the control strip. The same bytes are not sent twice.

        ``premul`` marks a frame whose RGB is already multiplied by its alpha
        (a fade step). The Qt window must not multiply again.
        """
        import base64

        if self._proc is None and not self._start():
            return False
        pos = (int(x), int(y), max(1, int(w)), max(1, int(h)))
        if png != self._strip_png or not self._strip_on:
            encoded = base64.b64encode(png).decode("ascii")
            if not self._send(
                {
                    "op": "strip",
                    "png": encoded,
                    "x": pos[0],
                    "y": pos[1],
                    "w": pos[2],
                    "h": pos[3],
                    "premul": bool(premul),
                }
            ):
                return False
            self._strip_png = png
            self._strip_pos = pos
            self._strip_on = True
            return True
        if pos != self._strip_pos:
            if not self._send(
                {"op": "strip", "png": "", "x": pos[0], "y": pos[1], "w": pos[2], "h": pos[3]}
            ):
                return False
            self._strip_pos = pos
        return True

    def hide_strip(self) -> None:
        if not self._strip_on:
            return
        self._send({"op": "strip-hide"})
        self._strip_on = False
        self._strip_png = None

    def close(self) -> None:
        """Ask the figure to quit, then kill it if it stays."""
        with self._lock:
            proc = self._proc
            self._proc = None
            self._visible = False
            self._strip_on = False
            self._strip_png = None
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.write(b'{"op":"quit"}\n')
                proc.stdin.flush()
        except OSError:
            pass
        try:
            proc.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            proc.kill()

    def _start(self) -> bool:
        from dodaios.platform.qt_sidecar import stderr_sink

        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(sys.path)
        kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "ui.orb.shader_desktop"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr_sink("shader-pet"),
                env=env,
                **kwargs,
            )
        except OSError:
            log.warning("shader figure could not start", exc_info=True)
            return False
        with self._lock:
            self._proc = proc
            self._failed = False
        threading.Thread(target=self._read, args=(proc,), name="shader-pet", daemon=True).start()
        return True

    def _send(self, payload: dict[str, Any]) -> bool:
        proc = self._proc
        if proc is None or proc.stdin is None:
            return False
        try:
            proc.stdin.write(json.dumps(payload, ensure_ascii=True).encode("utf-8") + b"\n")
            proc.stdin.flush()
        except (OSError, ValueError):
            log.warning("shader figure stopped accepting commands", exc_info=True)
            self._failed = True
            self._failed_source = self._source
            self._visible = False
            return False
        return True

    def _read(self, proc: subprocess.Popen[bytes]) -> None:
        stdout = proc.stdout
        if stdout is None:
            return
        for raw in stdout:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            try:
                self._on_event(event)
            except Exception:
                log.debug("shader figure event failed", exc_info=True)
        code = proc.poll()
        with self._lock:
            if self._proc is proc:
                self._proc = None
                self._visible = False
                self._strip_on = False
                self._strip_png = None
                self._failed = True
                self._failed_source = self._source
        if code not in (0, None):
            from dodaios.platform.qt_sidecar import crash_hint

            log.warning("shader figure exited (%s).%s", code, crash_hint(code, "shader-pet"))
