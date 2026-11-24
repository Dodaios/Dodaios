"""Platform facts and the one way this package runs a short helper command."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

#: Windows: a child of a windowless process must not flash a console window.
NO_WINDOW: int = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if IS_WINDOWS else 0
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
#: Lets a child outlive a parent that sits in a Job Object which kills its
#: members when it closes (a terminal, an IDE, a scheduled task).
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def run_quiet(
    argv: Sequence[str],
    *,
    timeout: float = 30.0,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a short helper (systemctl, launchctl, schtasks) and capture its text.

    No console window on Windows. Output is decoded as UTF-8 with replacement,
    because Windows tools answer in the console code page and a decode error
    must never hide the exit code.
    """
    return subprocess.run(  # noqa: S603 - argv is built by this package, never a shell string
        list(argv),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=NO_WINDOW,
        env=dict(env) if env is not None else None,
        check=False,
    )


def windowless_python(executable: str | None = None) -> str:
    """The interpreter to use for a process nobody looks at.

    On Windows that is ``pythonw.exe`` next to ``python.exe`` when it exists, so
    a service started at login opens no console. Elsewhere it is the
    interpreter itself.
    """
    exe = executable or sys.executable
    if IS_WINDOWS:
        path = Path(exe)
        if path.name.lower() == "python.exe":
            candidate = path.with_name("pythonw.exe")
            if candidate.is_file():
                return str(candidate)
    return exe


def default_state_dir(name: str) -> Path:
    """Where a daemon called ``name`` keeps its lock, record and log.

    Per user, never shared between accounts:

    * Windows: ``%LOCALAPPDATA%\\<name>\\daemon``
    * macOS: ``~/Library/Application Support/<name>/daemon``
    * Linux and others: ``$XDG_STATE_HOME/<name>`` (``~/.local/state/<name>``)
    """
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / name / "daemon"
    if IS_MACOS:
        return Path.home() / "Library" / "Application Support" / name / "daemon"
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / name
