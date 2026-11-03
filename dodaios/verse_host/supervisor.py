"""Supervisor (17.3, BW2, architecture 1.1): spawn, watch, restart, stop ``Verse.exe``.

* Lazy: launched on the first ``show``, never at app start.
* Containment: a Windows job object with ``KILL_ON_JOB_CLOSE`` (the app's
  handle closes when the app dies, and the job kills Verse); on Linux
  ``prctl(PR_SET_PDEATHSIG, SIGKILL)`` plus its own process group. Verse is
  only ever stopped by the PID this supervisor started.
* Token: 256 bits, minted per launch, passed in ``DODAIOS_VERSE_TOKEN`` with
  the bridge URL in ``DODAIOS_VERSE_BRIDGE``; never on the command line and
  never logged.
* Liveness: an unplanned exit or a hung bridge (5 s silent) is a crash. An
  exit Verse announced (``lifecycle.bye``, or ``gpu.yield`` while Dormant,
  contract 12) is a stop: status ``stopped``, no restart, no crash entry. Restarts after
  1 s, 4 s, 15 s; three crashes within 5 minutes stop it: status ``crashed``
  until a manual launch.
* Crash data: ``<DATA_DIR>/verse/crashes/<stamp>/`` gets the exit record, the
  last Verse log and any minidump. Never uploaded.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger(__name__)

BACKOFF_S = (1.0, 4.0, 15.0)
CRASH_WINDOW_S = 300.0
CRASH_LIMIT = 3
HEALTHY_AFTER_S = 300.0
QUIT_DEADLINE_MS = 3000


class Process(Protocol):
    pid: int

    async def wait(self) -> int: ...
    def kill(self) -> None: ...
    def alive(self) -> bool: ...


Spawner = Callable[[list[str], dict[str, str], Path], Awaitable[Process]]


# ---------------------------------------------------------------------- containment


class _WindowsJob:  # pragma: no cover - exercised by the Windows containment test
    """A job object that kills every process in it when its last handle closes."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._k32 = k32
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]

        class IO_COUNTERS(ctypes.Structure):  # noqa: N801
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class BASIC(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class EXTENDED(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        self.handle = k32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObject failed")
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(
            self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)
        ):  # JobObjectExtendedLimitInformation
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")

    def assign(self, pid: int) -> None:
        k32 = self._k32
        process = k32.OpenProcess(0x0001 | 0x0100, False, pid)  # TERMINATE | SET_QUOTA
        if not process:
            raise OSError(self._ctypes.get_last_error(), "OpenProcess failed")
        try:
            if not k32.AssignProcessToJobObject(self.handle, process):
                raise OSError(self._ctypes.get_last_error(), "AssignProcessToJobObject failed")
        finally:
            k32.CloseHandle(process)


_job: Any = None


def _shared_job() -> Any:  # pragma: no cover - Windows only
    """One job per app process; its handle lives as long as the app does."""
    global _job
    if _job is None:
        _job = _WindowsJob()
    return _job


def _linux_preexec() -> None:  # pragma: no cover - runs in the child on Linux
    import ctypes

    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    libc.prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG
    os.setpgid(0, 0)


@dataclass
class PopenProcess:
    popen: subprocess.Popen[bytes]

    @property
    def pid(self) -> int:
        return self.popen.pid

    async def wait(self) -> int:
        return await asyncio.to_thread(self.popen.wait)

    def kill(self) -> None:
        with contextlib.suppress(OSError):
            self.popen.kill()

    def alive(self) -> bool:
        return self.popen.poll() is None


async def spawn_contained(argv: list[str], env: dict[str, str], cwd: Path) -> Process:
    """Start ``argv`` so it dies with this process (job object / PDEATHSIG)."""
    return await asyncio.to_thread(_spawn_contained_sync, argv, env, cwd)


def _spawn_contained_sync(argv: list[str], env: dict[str, str], cwd: Path) -> Process:
    kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        popen = subprocess.Popen(argv, **kwargs)  # noqa: S603 - argv is our own exe, no shell
        try:
            _shared_job().assign(popen.pid)
        except OSError:
            log.warning("verse supervisor: job object unavailable; Verse may outlive the app")
    else:
        kwargs["preexec_fn"] = _linux_preexec  # noqa: PLW1509 - prctl must run in the child
        popen = subprocess.Popen(argv, **kwargs)  # noqa: S603
    return PopenProcess(popen)


# ---------------------------------------------------------------------- supervisor


@dataclass
class SupervisorState:
    status: str = "stopped"
    pid: int | None = None
    crash_report: str | None = None
    crashes: list[float] = field(default_factory=list)
    consecutive: int = 0
    launched_at: float | None = None
    last_exit: int | None = None


class Supervisor:
    def __init__(
        self,
        *,
        exe: Callable[[], Path | None],
        bridge_url: Callable[[], str],
        set_token: Callable[[str | None], None],
        mint: Callable[[], str],
        crash_dir: Path,
        spawn: Spawner = spawn_contained,
        on_change: Callable[[], Awaitable[None]] | None = None,
        request_quit: Callable[[str, int], Awaitable[bool]] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        extra_args: list[str] | None = None,
    ) -> None:
        self._exe = exe
        self._bridge_url = bridge_url
        self._set_token = set_token
        self._mint = mint
        self.crash_dir = crash_dir
        self._spawn = spawn
        self._on_change = on_change
        self._request_quit = request_quit
        self._clock = clock
        self._sleep = sleep
        self.extra_args = list(extra_args or [])
        self.state = SupervisorState()
        self.process: Process | None = None
        self._watch: asyncio.Task[None] | None = None
        self._restart: asyncio.Task[None] | None = None
        self._stopping = False
        self._planned_until: float | None = None
        self._lock = asyncio.Lock()
        self.token_in_env: str | None = None
        self.last_argv: list[str] = []
        self.healthy_since: float | None = None

    # ------------------------------------------------------------------ status
    @property
    def running(self) -> bool:
        return self.process is not None and self.process.alive()

    async def _changed(self) -> None:
        if self._on_change is not None:
            with contextlib.suppress(Exception):
                await self._on_change()

    # ------------------------------------------------------------------ launch
    async def ensure_running(self, *, manual: bool = False) -> bool:
        """Launch unless running. A crash loop stays stopped unless ``manual``."""
        async with self._lock:
            if self.running:
                return True
            if self.state.status == "crashed" and not manual:
                return False
            if manual:
                self.state.crashes.clear()
                self.state.consecutive = 0
            return await self._launch()

    async def _launch(self) -> bool:
        exe = self._exe()
        if exe is None:
            self.state.status = "stopped"
            return False
        token = self._mint()
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("DODAIOS_VERSE_TOKEN", "JARVIS_VERSE_TOKEN"))
        }
        env["DODAIOS_VERSE_BRIDGE"] = self._bridge_url()
        env["DODAIOS_VERSE_TOKEN"] = token
        env["DODAIOS_VERSE_APP_PID"] = str(os.getpid())
        argv = [str(exe), *self.extra_args]
        self.last_argv = argv
        self._set_token(token)
        self.token_in_env = token
        self._stopping = False
        self._planned_until = None
        try:
            process = await self._spawn(argv, env, exe.parent)
        except OSError as exc:
            log.warning("verse supervisor: launch failed: %s", exc)
            self._set_token(None)
            self.state.status = "stopped"
            await self._changed()
            return False
        self.process = process
        self.state.status = "running"
        self.state.pid = process.pid
        self.state.launched_at = self._clock()
        self.healthy_since = None
        log.info("verse supervisor: started Verse pid %s", process.pid)
        self._watch = asyncio.ensure_future(self._watch_exit(process))
        await self._changed()
        return True

    def mark_healthy(self) -> None:
        """``lifecycle.ready`` arrived: the launch counts as healthy."""
        self.healthy_since = self._clock()

    def expect_exit(self, within_s: float | None = None) -> None:
        """Verse is about to quit on its own (``lifecycle.bye``, or ``gpu.yield`` while
        Dormant): that exit is a stop, not a crash, and nothing restarts it.

        ``within_s`` bounds the expectation; ``None`` holds until the next launch.
        """
        if self.process is None:
            return
        self._planned_until = float("inf") if within_s is None else self._clock() + float(within_s)
        if self._restart is not None:
            self._restart.cancel()

    def _planned(self) -> bool:
        return self._planned_until is not None and self._clock() <= self._planned_until

    # ------------------------------------------------------------------ watch
    async def _watch_exit(self, process: Process) -> None:
        code = await process.wait()
        if self.process is not process:
            return
        self.process = None
        self.state.pid = None
        self.state.last_exit = code
        self._set_token(None)
        self.token_in_env = None
        if self._stopping or self._planned():
            self._planned_until = None
            self.state.status = "stopped"
            log.info("verse supervisor: Verse exited (%s) after a stop", code)
            await self._changed()
            return
        await self._crashed(code, "exited")

    async def _crashed(self, code: int | None, why: str) -> None:
        now = self._clock()
        if self.healthy_since is not None and now - self.healthy_since >= HEALTHY_AFTER_S:
            self.state.consecutive = 0
        self.state.crashes = [t for t in self.state.crashes if now - t < CRASH_WINDOW_S]
        self.state.crashes.append(now)
        self.state.consecutive += 1
        self.state.crash_report = self._save_crash(code, why)
        log.warning(
            "verse supervisor: Verse %s (code %s); crash %s", why, code, self.state.consecutive
        )
        if len(self.state.crashes) >= CRASH_LIMIT:
            self.state.status = "crashed"
            await self._changed()
            return
        delay = BACKOFF_S[min(self.state.consecutive, len(BACKOFF_S)) - 1]
        self.state.status = "stopped"
        await self._changed()
        self._restart = asyncio.ensure_future(self._restart_after(delay))

    async def _restart_after(self, delay: float) -> None:
        await self._sleep(delay)
        async with self._lock:
            if self.running or self._stopping or self.state.status == "crashed":
                return
            await self._launch()

    async def on_hung(self) -> None:
        """The bridge saw 5 s of silence: stop this Verse by its own PID; it restarts."""
        process = self.process
        if process is None:
            return
        log.warning("verse supervisor: bridge hung, stopping pid %s", process.pid)
        process.kill()

    # ------------------------------------------------------------------ stop
    async def stop(self, reason: str = "app_quit") -> None:
        """Ask Verse to quit (``lifecycle.quit``), then end it by PID after the deadline."""
        self._stopping = True
        if self._restart is not None:
            self._restart.cancel()
        process = self.process
        if process is None:
            self.state.status = "stopped" if self.state.status != "crashed" else "crashed"
            return
        asked = False
        if self._request_quit is not None:
            with contextlib.suppress(Exception):
                asked = await self._request_quit(reason, QUIT_DEADLINE_MS)
        if asked:
            deadline = self._clock() + QUIT_DEADLINE_MS / 1000.0 + 0.5
            while process.alive() and self._clock() < deadline:
                await self._sleep(0.05)
        if process.alive():
            process.kill()
        if self._watch is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(asyncio.shield(self._watch), 5.0)

    # ------------------------------------------------------------------ crash data
    def _save_crash(self, code: int | None, why: str) -> str | None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        folder = self.crash_dir / stamp
        try:
            folder.mkdir(parents=True, exist_ok=True)
            record = {"exit_code": code, "reason": why, "at": time.time()}
            (folder / "exit.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
            exe = self._exe()
            if exe is not None:
                saved = exe.parent / "Verse" / "Saved"
                log_file = saved / "Logs" / "Verse.log"
                if log_file.is_file():
                    shutil.copy2(log_file, folder / "Verse.log")
                crashes = saved / "Crashes"
                if crashes.is_dir():
                    newest = sorted(crashes.iterdir(), key=lambda p: p.stat().st_mtime)[-1:]
                    for entry in newest:
                        for dump in entry.glob("*.dmp"):
                            shutil.copy2(dump, folder / dump.name)
        except (OSError, IndexError):
            log.warning("verse supervisor: crash data not saved", exc_info=True)
            return None
        return str(folder)
