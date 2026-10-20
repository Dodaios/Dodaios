"""Entry point that scripts/verse/blender.py runs inside Blender first.

argv after `--`: <script.py | -> [script args...]. Puts the pipeline on
sys.path, selects the Cycles device and runs the script as `__main__`.
Exceptions propagate, so `--python-exit-code 1` makes Blender exit with 1.
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for _path in (REPO_ROOT / "scripts" / "verse", REPO_ROOT / "art" / "verse"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import bpy  # noqa: E402

DONE_MARKER = "[verse] bootstrap: done"


def _user_argv() -> list[str]:
    argv = sys.argv
    return argv[argv.index("--") + 1 :] if "--" in argv else []


def configure_cycles(preferred: str) -> str:
    """Enable the best GPU backend and return its name (OPTIX, CUDA or CPU)."""
    prefs = bpy.context.preferences.addons["cycles"].preferences
    order = {"AUTO": ("OPTIX", "CUDA"), "OPTIX": ("OPTIX",), "CUDA": ("CUDA",)}.get(preferred, ())
    for backend in order:
        try:
            prefs.compute_device_type = backend
        except TypeError:
            continue
        prefs.get_devices()
        if not any(device.type == backend for device in prefs.devices):
            continue
        for device in prefs.devices:
            device.use = device.type == backend
        return backend
    prefs.compute_device_type = "NONE"
    return "CPU"


def main() -> None:
    argv = _user_argv()
    backend = configure_cycles(os.environ.get("VERSE_CYCLES_DEVICE", "AUTO").upper())
    os.environ["VERSE_CYCLES_BACKEND"] = backend
    print(f"[verse] blender {bpy.app.version_string}, cycles backend {backend}", flush=True)
    if argv and argv[0] != "-":
        script = Path(argv[0]).resolve()
        sys.argv = [str(script), *argv[1:]]
        try:
            runpy.run_path(str(script), run_name="__main__")
        except SystemExit as stop:
            if stop.code not in (None, 0):
                print(f"[verse] script exited with {stop.code}", flush=True)
                raise RuntimeError(f"script exited with {stop.code}") from None
        except BaseException as error:
            print(f"[verse] FAILED: {type(error).__name__}: {error}", flush=True)
            raise
    print(DONE_MARKER, flush=True)


main()
