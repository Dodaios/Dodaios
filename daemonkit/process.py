"""Starting a process that outlives its parent, and checking or ending one by pid."""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import IO

from ._platform import (
    CREATE_BREAKAWAY_FROM_JOB,
    CREATE_NEW_PROCESS_GROUP,
    DETACHED_PROCESS,
    NO_WINDOW,
)

log = logging.getLogger(__name__)


def spawn_detached(
    argv: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    log_path: Path | None = None,
) -> int:
    """Start ``argv`` so that it keeps running after this process ends.

    * POSIX: a new session (``setsid``), so closing the terminal (SIGHUP to its
      process group) does not reach it.
    * Windows: detached from this console, in its own process group, with no
      window, and out of this process's Job Object when Windows allows it.

    stdin is closed; stdout and stderr go to ``log_path`` (appended) or are
    discarded. Never inherits this process's open files. Returns the pid.
    """
    handle: IO[bytes] | None = None
    if log_path is not None:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        handle = open(log_path, "ab")  # noqa: SIM115 - closed below, the child keeps its copy
    stdout: IO[bytes] | int = handle if handle is not None else subprocess.DEVNULL
    stderr = subprocess.STDOUT if handle is not None else subprocess.DEVNULL
    workdir = str(cwd) if cwd is not None else None
    environ = dict(env) if env is not None else None
    try:
        if sys.platform == "win32":
            flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | NO_WINDOW
            try:
                proc = subprocess.Popen(  # noqa: S603 - argv list from the caller
                    list(argv),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    close_fds=True,
                    cwd=workdir,
                    env=environ,
                    creationflags=flags | CREATE_BREAKAWAY_FROM_JOB,
                )
            except PermissionError:
                # The parent's job forbids breakaway. The child still starts;
                # it just stays in that job.
                log.warning("daemonkit: breakaway from the job refused; starting inside it")
                proc = subprocess.Popen(  # noqa: S603 - argv list from the caller
                    list(argv),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    close_fds=True,
                    cwd=workdir,
                    env=environ,
                    creationflags=flags,
                )
        else:
            proc = subprocess.Popen(  # noqa: S603 - argv list from the caller
                list(argv),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                close_fds=True,
                cwd=workdir,
                env=environ,
                start_new_session=True,
            )
    finally:
        if handle is not None:
            handle.close()
    return int(proc.pid)


def pid_alive(pid: int) -> bool:
    """Whether a process with this pid exists (it may not be ours: pids are reused)."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _win_pid_alive(pid)
    _reap(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by another user
    return True


def wait_for_exit(pid: int, timeout: float, *, poll: float = 0.1) -> bool:
    """Wait up to ``timeout`` seconds for ``pid`` to end. True when it has."""
    deadline = time.monotonic() + max(0.0, timeout)
    while pid_alive(pid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll)
    return True


def terminate(pid: int, *, grace: float = 10.0) -> bool:
    """Ask ``pid`` to end, then force it after ``grace`` seconds.

    POSIX sends SIGTERM, then SIGKILL. Windows has no polite signal for a
    windowless process, so it ends the process at once; a server that needs a
    clean shutdown on Windows should offer its own stop request (see
    ``Daemon.stop(graceful=...)``). Returns True when the process is gone.
    """
    if not pid_alive(pid):
        return True
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except OSError as exc:
        log.warning("daemonkit: could not signal pid %s: %s", pid, exc)
    if wait_for_exit(pid, grace):
        return True
    if sys.platform != "win32":
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
        return wait_for_exit(pid, 5.0)
    return not pid_alive(pid)


def _reap(pid: int) -> None:
    """Collect ``pid`` if it is a finished child of ours (else it stays a zombie)."""
    if sys.platform == "win32":
        return
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return  # not our child: nothing to collect
    except OSError as exc:
        log.debug("daemonkit: waitpid(%s) failed: %s", pid, exc)


def _win_pid_alive(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined,unused-ignore]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    process_query_limited_information = 0x1000
    still_active = 259
    error_access_denied = 5
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return bool(ctypes.get_last_error() == error_access_denied)  # type: ignore[attr-defined,unused-ignore]
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == still_active
    finally:
        kernel32.CloseHandle(handle)
