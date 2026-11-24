"""daemonkit: keep one server process running per user, and let clients find it.

A small, dependency-free toolkit for the client-server shape that tmux and
long-running agent gateways use: one long-lived server owns the work, and any
number of clients (a desktop window, a terminal UI, a CLI, a script) attach to
it and may come and go without stopping anything.

Pieces, each usable alone:

* :class:`Daemon` - the shared object: ``claim()`` in the server,
  ``ensure_running()`` / ``stop()`` / ``status()`` in clients.
* :mod:`daemonkit.lock` - an instance lock the OS releases when its owner dies.
* :mod:`daemonkit.record` - the atomically written file clients read.
* :mod:`daemonkit.process` - start a process that outlives its parent.
* :mod:`daemonkit.supervise` - restart after a crash, stand by while another
  instance runs, stop on request.
* :mod:`daemonkit.service` - register with systemd, launchd or the Windows
  Task Scheduler so it starts at login and comes back after a crash.

Only the Python standard library is used, and nothing outside this folder is
imported, so the folder can be copied into another project as it is.
"""

from __future__ import annotations

from .daemon import AlreadyRunning, Claim, Daemon, DaemonStatus, StartTimeout
from .lock import InstanceLock, is_locked
from .paths import DaemonPaths
from .process import pid_alive, spawn_detached, terminate
from .record import ServerRecord, new_token, read_record, token_matches, write_record
from .supervise import EXIT_ALREADY_RUNNING, EXIT_CONFIG, Supervisor, SupervisorPolicy

__version__ = "0.1.0"

__all__ = [
    "EXIT_ALREADY_RUNNING",
    "EXIT_CONFIG",
    "AlreadyRunning",
    "Claim",
    "Daemon",
    "DaemonPaths",
    "DaemonStatus",
    "InstanceLock",
    "ServerRecord",
    "StartTimeout",
    "Supervisor",
    "SupervisorPolicy",
    "is_locked",
    "new_token",
    "pid_alive",
    "read_record",
    "spawn_detached",
    "terminate",
    "token_matches",
    "write_record",
]
