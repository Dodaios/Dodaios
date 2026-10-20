"""Run Blender headless for the Verse content pipeline.

Library and CLI. Every Blender job of the pipeline goes through `run()`:

- Blender is located via the `DODAIOS_BLENDER` environment variable, the
  default Windows install path, or `blender` on PATH.
- Blender starts with `--factory-startup -b`, so user preferences and add-ons
  never change a cook.
- `_bootstrap.py` runs first inside Blender: it puts `art/verse` and
  `scripts/verse` on `sys.path` (so builders can `import lib.scene`), picks the
  Cycles device (OptiX, then CUDA, then CPU) and runs the target script as
  `__main__`. A Python exception inside Blender exits with code 1.
- Heavy jobs hold a cross-process GPU lock (`art/verse/.cache/gpu.lock`), so
  only one Cycles render runs at a time on the shared GPU; other callers wait.
- The Blender log streams to the console and to a log file.

CLI:
    python scripts/verse/blender.py info
    python scripts/verse/blender.py run [--blend F] [--timeout S] [--no-lock]
                                      [--device auto|optix|cuda|cpu]
                                      <script.py> [script args...]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from filelock import FileLock, Timeout

REPO_ROOT = Path(__file__).resolve().parents[2]
ART_ROOT = REPO_ROOT / "art" / "verse"
CACHE_ROOT = ART_ROOT / ".cache"
LOG_ROOT = CACHE_ROOT / "logs"
GPU_LOCK_PATH = CACHE_ROOT / "gpu.lock"
BOOTSTRAP = Path(__file__).with_name("_bootstrap.py")
DEFAULT_BLENDER = Path("C:/Program Files/Blender Foundation/Blender 5.0/blender.exe")
DONE_MARKER = "[verse] bootstrap: done"
DEVICES = ("auto", "optix", "cuda", "cpu")

# Log lines that are expected on this machine and only add noise to the console.
_QUIET_SUBSTRINGS = ("HIPEW initialization failed",)


class BlenderError(RuntimeError):
    """A Blender job failed, crashed or timed out."""


@dataclass(frozen=True)
class RunResult:
    returncode: int
    seconds: float
    log_path: Path


def find_blender() -> Path:
    """Return the Blender executable or raise BlenderError."""
    override = os.environ.get("DODAIOS_BLENDER")
    candidates = [Path(override)] if override else []
    candidates.append(DEFAULT_BLENDER)
    on_path = shutil.which("blender")
    if on_path:
        candidates.append(Path(on_path))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise BlenderError(
        "Blender not found. Set DODAIOS_BLENDER to blender.exe "
        f"(looked at: {', '.join(str(c) for c in candidates)})."
    )


@contextmanager
def gpu_lock(label: str, timeout: float | None = None) -> Iterator[None]:
    """Hold the machine-wide GPU lock; wait while another job renders."""
    GPU_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    owner_path = GPU_LOCK_PATH.with_suffix(".owner")
    lock = FileLock(str(GPU_LOCK_PATH))
    started = time.monotonic()
    announced = False
    while True:
        try:
            lock.acquire(timeout=5)
            break
        except Timeout:
            waited = time.monotonic() - started
            if timeout is not None and waited > timeout:
                raise BlenderError(f"GPU lock not acquired within {timeout:.0f} s") from None
            if not announced:
                holder = owner_path.read_text(encoding="utf-8") if owner_path.exists() else "?"
                print(f"[verse] waiting for the GPU lock (held by {holder.strip()})", flush=True)
                announced = True
    try:
        owner = {"pid": os.getpid(), "job": label, "since": time.strftime("%H:%M:%S")}
        owner_path.write_text(json.dumps(owner), encoding="utf-8")
        yield
    finally:
        owner_path.unlink(missing_ok=True)
        lock.release()


def _blender_command(
    blender: Path, script: Path | None, args: Sequence[str], blend: Path | None
) -> list[str]:
    command = [str(blender), "--factory-startup", "-b"]
    if blend is not None:
        command.append(str(blend))
    command += ["--python-exit-code", "1", "--python", str(BOOTSTRAP), "--"]
    command.append(str(script) if script is not None else "-")
    command += list(args)
    return command


def _pump(stream, log_file, echo: bool, tail: deque[str]) -> None:
    for line in stream:
        log_file.write(line)
        log_file.flush()
        tail.append(line.rstrip("\n"))
        if echo and not any(q in line for q in _QUIET_SUBSTRINGS):
            sys.stdout.write(line)
            sys.stdout.flush()


def _default_log_path(script: Path | None) -> Path:
    stem = script.stem if script is not None else "info"
    return LOG_ROOT / f"{time.strftime('%Y%m%d-%H%M%S')}-{stem}-{os.getpid()}.log"


def run(
    script: Path | None,
    args: Sequence[str] = (),
    *,
    timeout: float = 3600.0,
    blend: Path | None = None,
    lock: bool = True,
    device: str = "auto",
    echo: bool = True,
    log_path: Path | None = None,
) -> RunResult:
    """Run `script` inside headless Blender and return when it finished.

    Raises BlenderError on a non-zero exit, a missing completion marker
    (crash), or a timeout. `script=None` only configures the device (info).
    """
    if device not in DEVICES:
        raise ValueError(f"device must be one of {DEVICES}")
    blender = find_blender()
    log_path = log_path or _default_log_path(script)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = _blender_command(blender, script, args, blend)
    env = dict(os.environ, VERSE_CYCLES_DEVICE=device.upper(), PYTHONUNBUFFERED="1")
    label = script.name if script is not None else "info"
    context = gpu_lock(label) if lock else _no_lock()
    with context, open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write(" ".join(command) + "\n")
        started = time.monotonic()
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=str(REPO_ROOT),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        tail: deque[str] = deque(maxlen=60)
        pump = threading.Thread(
            target=_pump, args=(process.stdout, log_file, echo, tail), daemon=True
        )
        pump.start()
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise BlenderError(
                f"Blender timed out after {timeout:.0f} s (log: {log_path})"
            ) from None
        finally:
            pump.join(timeout=10)
        seconds = time.monotonic() - started
    finished = any(DONE_MARKER in line for line in tail)
    if returncode != 0 or not finished:
        excerpt = "\n".join(tail)
        raise BlenderError(
            f"Blender job {label} failed (exit {returncode}, log: {log_path})\n{excerpt}"
        )
    return RunResult(returncode=returncode, seconds=seconds, log_path=log_path)


@contextmanager
def _no_lock() -> Iterator[None]:
    yield


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("info", help="print the Blender path, version and Cycles device")
    run_parser = sub.add_parser("run", help="run a script inside headless Blender")
    run_parser.add_argument("--blend", type=Path, help="open this .blend first")
    run_parser.add_argument("--timeout", type=float, default=3600.0)
    run_parser.add_argument(
        "--no-lock", action="store_true", help="skip the GPU lock (no heavy rendering)"
    )
    run_parser.add_argument("--device", choices=DEVICES, default="auto")
    run_parser.add_argument("script", type=Path)
    run_parser.add_argument("args", nargs=argparse.REMAINDER)
    options = parser.parse_args(argv)
    try:
        if options.command == "info":
            print(f"blender: {find_blender()}")
            run(None, lock=False)
            return 0
        result = run(
            options.script.resolve(),
            options.args,
            timeout=options.timeout,
            blend=options.blend,
            lock=not options.no_lock,
            device=options.device,
        )
    except BlenderError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"[verse] finished in {result.seconds:.1f} s (log: {result.log_path})")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
