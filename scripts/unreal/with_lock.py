#!/usr/bin/env python3
"""Hold the machine-wide ``gpu-heavy`` lock around one heavy job.

One compile, cook, package, commandlet, Blender export or cook, rendered test
or balance run uses the box at a time (docs/verse/unreal/orchestration.md
section 4, architecture.md 8.2). Every Unreal wrapper script and the Blender
runner (``scripts/verse/blender.py``) take this same lock.

- The lock is an OS file lock on ``C:/demo/.locks/gpu-heavy.lock``
  (``DODAIOS_LOCK_DIR`` overrides the folder). The OS releases it when the
  holder dies, so a crashed job never blocks the box.
- Waiters queue in FIFO order with one ticket file each in
  ``gpu-heavy.queue/``; they wait, they never fail. Tickets of dead processes
  are dropped.
- The holder writes holder, command, start time and PID to
  ``gpu-heavy.holder.json`` for the queue view (``with_lock.py status``).
- A hold is timed out after 90 minutes with a loud log line: the wrapped job
  of this process is stopped and the lock released. Other processes are never
  killed; a waiter that sees an older hold only says so.
- Nested use is free: a job started under the lock inherits
  ``DODAIOS_GPU_LOCK_HELD`` and does not queue for the lock its parent holds.

    python scripts/unreal/with_lock.py --label cook -- python scripts/verse/cook.py hangar
    python scripts/unreal/with_lock.py status
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from filelock import FileLock, Timeout

from scripts.unreal import _common as common

LOCK_NAME = "gpu-heavy"
LOCK_DIR_ENV = "DODAIOS_LOCK_DIR"
HELD_ENV = "DODAIOS_GPU_LOCK_HELD"
DEFAULT_LOCK_DIR = Path("C:/demo/.locks")


class LockTimeout(common.UnrealScriptError):
    """The caller set a wait limit and the lock did not come free in time."""


def lock_dir(env: dict[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    override = env.get(LOCK_DIR_ENV, "").strip()
    if override:
        return Path(override)
    if os.name == "nt":
        return DEFAULT_LOCK_DIR
    return Path.home() / ".cache" / "dodaios" / "locks"


def pid_alive(pid: int) -> bool:
    """True while a process with this PID runs (never signals it)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class MachineLock:
    """Context manager for the ``gpu-heavy`` lock with a FIFO queue."""

    def __init__(
        self,
        label: str,
        command: Sequence[str] | str | None = None,
        *,
        directory: Path | None = None,
        wait_timeout: float | None = None,
        poll: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        alive: Callable[[int], bool] = pid_alive,
        pid: int | None = None,
        echo: Callable[[str], None] = common.log,
    ) -> None:
        self.label = label
        self.command = command if isinstance(command, str) else " ".join(command or ())
        self.directory = directory or lock_dir()
        self.wait_timeout = wait_timeout
        self.poll = poll
        self.clock = clock
        self.sleep = sleep
        self.alive = alive
        self.pid = os.getpid() if pid is None else pid
        self.echo = echo
        self.lock_path = self.directory / f"{LOCK_NAME}.lock"
        self.holder_path = self.directory / f"{LOCK_NAME}.holder.json"
        self.queue_dir = self.directory / f"{LOCK_NAME}.queue"
        self._lock = FileLock(str(self.lock_path))
        self._ticket: Path | None = None
        self._nested = False
        self._previous_env: str | None = None
        self.waited = 0.0

    # --- queue ---------------------------------------------------------------

    def tickets(self) -> list[Path]:
        """Live tickets in FIFO order; tickets of dead processes are removed."""
        live: list[Path] = []
        for ticket in sorted(self.queue_dir.glob("*.json")):
            data = _read_json(ticket)
            pid = int(data.get("pid", 0)) if data else 0
            if ticket == self._ticket or (pid and self.alive(pid)):
                live.append(ticket)
            else:
                ticket.unlink(missing_ok=True)
        return live

    def _enqueue(self) -> Path:
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        ticket = self.queue_dir / f"{time.time_ns():020d}-{self.pid}.json"
        payload = {"pid": self.pid, "label": self.label, "command": self.command,
                   "queued": time.strftime("%Y-%m-%dT%H:%M:%S")}
        ticket.write_text(json.dumps(payload), encoding="utf-8")
        self._ticket = ticket
        return ticket

    def _is_nested(self) -> bool:
        held = os.environ.get(HELD_ENV, "")
        path, _, pid = held.rpartition("|")
        if not path or Path(path) != self.lock_path or not pid.isdigit():
            return False
        return self.alive(int(pid))

    # --- acquire / release ---------------------------------------------------

    def acquire(self) -> None:
        if self._is_nested():
            self._nested = True
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        ticket = self._enqueue()
        started = self.clock()
        announced = False
        stale_warned = False
        try:
            while True:
                queue = self.tickets()
                if queue and queue[0] == ticket:
                    try:
                        self._lock.acquire(timeout=0)
                        break
                    except Timeout:
                        pass
                waited = self.clock() - started
                if self.wait_timeout is not None and waited > self.wait_timeout:
                    raise LockTimeout(
                        f"{LOCK_NAME} lock not acquired within {self.wait_timeout:.0f} s"
                    )
                holder = _read_json(self.holder_path) or {}
                if not announced:
                    position = queue.index(ticket) + 1 if ticket in queue else len(queue)
                    self.echo(
                        f"waiting for the {LOCK_NAME} lock (held by {holder.get('holder', '?')}, "
                        f"pid {holder.get('pid', '?')}); place {position} of {len(queue)}"
                    )
                    if len(queue) > common.QUEUE_DEPTH_WARN:
                        self.echo(
                            f"LOCK QUEUE DEEP: {len(queue)} waiters (limit "
                            f"{common.QUEUE_DEPTH_WARN}); stop starting build-heavy sub-tasks"
                        )
                    announced = True
                held_for = time.time() - float(holder.get("started_epoch", time.time()))
                if not stale_warned and held_for > common.MAX_HOLD_MINUTES * 60:
                    self.echo(
                        f"LOCK HELD TOO LONG: pid {holder.get('pid', '?')} has held the "
                        f"{LOCK_NAME} lock for {held_for / 60:.0f} min; still waiting, "
                        "nothing is killed"
                    )
                    stale_warned = True
                self.sleep(self.poll)
        finally:
            if not self._lock.is_locked:
                ticket.unlink(missing_ok=True)
                self._ticket = None
        self.waited = self.clock() - started
        ticket.unlink(missing_ok=True)
        self._ticket = None
        holder = {
            "holder": self.label,
            "command": self.command,
            "pid": self.pid,
            "host": socket.gethostname(),
            "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "started_epoch": time.time(),
        }
        self.holder_path.write_text(json.dumps(holder, indent=1), encoding="utf-8")
        self._previous_env = os.environ.get(HELD_ENV)
        os.environ[HELD_ENV] = f"{self.lock_path}|{self.pid}"

    def release(self) -> None:
        if self._nested:
            self._nested = False
            return
        if self._previous_env is None:
            os.environ.pop(HELD_ENV, None)
        else:
            os.environ[HELD_ENV] = self._previous_env
        self.holder_path.unlink(missing_ok=True)
        if self._lock.is_locked:
            self._lock.release()

    @property
    def nested(self) -> bool:
        return self._nested

    def __enter__(self) -> MachineLock:
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


@contextlib.contextmanager
def held(label: str, command: Sequence[str] | str | None = None, **kwargs) -> Iterator[MachineLock]:
    with MachineLock(label, command, **kwargs) as lock:
        yield lock


def run_locked(
    command: Sequence[str],
    *,
    label: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    max_hold_minutes: float = common.MAX_HOLD_MINUTES,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
    lock_factory: Callable[..., MachineLock] = MachineLock,
) -> int:
    """Run ``command`` under the lock; stop it after ``max_hold_minutes``."""
    with lock_factory(label, command):
        child_env = dict(os.environ if env is None else env)
        child_env[HELD_ENV] = os.environ.get(HELD_ENV, "")
        process = popen(list(command), cwd=str(cwd) if cwd else None, env=child_env)
        try:
            return process.wait(timeout=max_hold_minutes * 60)
        except subprocess.TimeoutExpired:
            common.log(
                f"LOCK HOLD TIMEOUT: '{label}' ran past {max_hold_minutes:.0f} min; "
                "stopping this job and releasing the lock"
            )
            process.kill()
            process.wait()
            return 124
        except KeyboardInterrupt:
            process.kill()
            process.wait()
            raise


def status(directory: Path | None = None, alive: Callable[[int], bool] = pid_alive) -> dict:
    lock = MachineLock("status", directory=directory, alive=alive)
    holder = _read_json(lock.holder_path)
    if holder and not alive(int(holder.get("pid", 0))):
        holder = None
    queue = [_read_json(t) or {} for t in lock.tickets()] if lock.queue_dir.exists() else []
    return {"lock": str(lock.lock_path), "holder": holder, "queue": queue}


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["status"]:
        print(json.dumps(status(), indent=1))
        return 0
    command: list[str] = []
    if "--" in argv:
        split = argv.index("--")
        argv, command = argv[:split], argv[split + 1 :]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", default="", help="who holds the lock (default: the command)")
    parser.add_argument("--max-hold-minutes", type=float, default=common.MAX_HOLD_MINUTES)
    options = parser.parse_args(argv)
    if not command:
        parser.error("give the command after --")
    label = options.label or Path(command[0]).name
    return run_locked(command, label=label, max_hold_minutes=options.max_hold_minutes)


if __name__ == "__main__":
    sys.exit(main())
