#!/usr/bin/env python3
"""Can a Linux session bring the Verse window to the front? (architecture.md 1.3, RK7)

The backend hands focus to ``Verse`` and back. On X11 that needs a window
manager that supports ``_NET_ACTIVE_WINDOW``; on Wayland it needs the
compositor's ``xdg_activation_v1`` global, whose token travels over the
bridge. This check asks the running display servers and prints JSON:

    python3 activation_check.py --x11 :98 --wayland wl-verse-smoke
    {"x11": "ok", "wayland": "ok", "detail": {...}}

Each entry is ``ok``, ``fail`` (the server answered without the feature) or
``skip`` (no such server was given or it did not answer). Exit code 1 when
any entry is ``fail``. Standard library only: it runs in the smoke container.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence

Runner = Callable[[Sequence[str], dict], "tuple[int, str]"]


def _run(command: Sequence[str], env: dict) -> tuple[int, str]:
    try:
        done = subprocess.run(list(command), env=env, capture_output=True, text=True,
                              timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return done.returncode, done.stdout


def x11_supports_activation(xprop_output: str) -> bool:
    """``xprop -root _NET_SUPPORTED`` lists ``_NET_ACTIVE_WINDOW``."""
    for line in xprop_output.splitlines():
        if line.startswith("_NET_SUPPORTED"):
            atoms = {atom.strip() for atom in line.split("=", 1)[-1].split(",")}
            return "_NET_ACTIVE_WINDOW" in atoms
    return False


def wayland_supports_activation(info_output: str) -> bool:
    """``wayland-info`` lists the ``xdg_activation_v1`` global."""
    return any("xdg_activation_v1" in line for line in info_output.splitlines())


def check_x11(display: str | None, run: Runner = _run) -> tuple[str, str]:
    if not display:
        return "skip", "no X11 display given"
    env = dict(os.environ, DISPLAY=display)
    code, output = run(["xprop", "-root", "_NET_SUPPORTED"], env)
    if code != 0:
        return "skip", f"xprop on {display} exited {code}"
    if x11_supports_activation(output):
        return "ok", "_NET_ACTIVE_WINDOW supported"
    return "fail", "the window manager does not list _NET_ACTIVE_WINDOW"


def check_wayland(socket: str | None, run: Runner = _run) -> tuple[str, str]:
    if not socket:
        return "skip", "no Wayland socket given"
    env = dict(os.environ, WAYLAND_DISPLAY=socket)
    code, output = run(["wayland-info"], env)
    if code != 0:
        return "skip", f"wayland-info on {socket} exited {code}"
    if wayland_supports_activation(output):
        return "ok", "xdg_activation_v1 available"
    return "fail", "the compositor has no xdg_activation_v1 global"


def main(argv: Sequence[str] | None = None, run: Runner = _run) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--x11", help="X11 display, for example :98")
    parser.add_argument("--wayland", help="Wayland socket name")
    options = parser.parse_args(argv)
    x11, x11_detail = check_x11(options.x11, run)
    wayland, wayland_detail = check_wayland(options.wayland, run)
    result = {"x11": x11, "wayland": wayland,
              "detail": {"x11": x11_detail, "wayland": wayland_detail}}
    print(json.dumps(result, indent=2))
    return 1 if "fail" in (x11, wayland) else 0


if __name__ == "__main__":
    sys.exit(main())
