"""Registering a command with the operating system's own service manager.

The OS then starts it at login (on Linux also at boot, without a login) and
starts it again if it dies. Per user, no administrator rights:

============  ==========================================  ======================
Platform      Mechanism                                   Starts
============  ==========================================  ======================
Linux         systemd user unit (``systemctl --user``)    login; boot with linger
macOS         launchd agent (``~/Library/LaunchAgents``)  login
Windows       Task Scheduler logon task; if Windows       login
              refuses it, the per-user ``Run`` key
============  ==========================================  ======================

A Windows service and a macOS LaunchDaemon are deliberately not offered: both
need administrator rights, and both run outside the user's session, where the
user's keychain or credential store and their microphone are out of reach.

Every backend renders its file from a :class:`ServiceSpec` with a pure
function, and runs its tool through an injectable ``runner``, so all of them
are testable on any OS.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from .._platform import run_quiet
from ..paths import check_name

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]

LOGIN = "login"
BOOT = "boot"
_STARTS = (LOGIN, BOOT)


@dataclass(frozen=True)
class ServiceSpec:
    """What the OS should run, and how to name it."""

    name: str
    argv: tuple[str, ...]
    description: str = ""
    working_dir: str | None = None
    #: Applied natively by systemd and launchd. Windows tasks carry no
    #: environment: pass it in ``argv`` instead (the supervisor takes ``--env``).
    env: Mapping[str, str] = field(default_factory=dict)
    log_path: str | None = None
    #: launchd label / Windows task name. Defaults derive from ``name``.
    label: str | None = None

    def __post_init__(self) -> None:
        check_name(self.name)
        if not self.argv:
            raise ValueError("a service needs a command")
        for arg in self.argv:
            if "\n" in arg or "\r" in arg or "\0" in arg:
                raise ValueError(f"argument {arg!r} contains a line break or NUL")


@dataclass(frozen=True)
class ServiceStatus:
    """What the OS knows about the service."""

    mechanism: str
    supported: bool
    installed: bool
    active: bool | None = None
    starts_at: str | None = None
    location: str | None = None
    detail: str = ""


class ServiceManager(Protocol):
    mechanism: str

    def available(self) -> tuple[bool, str]: ...

    def install(
        self, spec: ServiceSpec, *, start_at: str = LOGIN, start_now: bool = True
    ) -> ServiceStatus: ...

    def uninstall(self, spec: ServiceSpec) -> ServiceStatus: ...

    def status(self, spec: ServiceSpec) -> ServiceStatus: ...

    def start(self, spec: ServiceSpec) -> bool: ...

    def stop(self, spec: ServiceSpec) -> bool: ...


def check_start_at(start_at: str) -> str:
    if start_at not in _STARTS:
        raise ValueError(f"start_at must be one of {_STARTS}, got {start_at!r}")
    return start_at


class NullServiceManager:
    """For a platform without a supported service manager."""

    mechanism = "none"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def available(self) -> tuple[bool, str]:
        return False, self.reason

    def _status(self) -> ServiceStatus:
        return ServiceStatus(self.mechanism, supported=False, installed=False, detail=self.reason)

    def install(
        self, spec: ServiceSpec, *, start_at: str = LOGIN, start_now: bool = True
    ) -> ServiceStatus:
        return self._status()

    def uninstall(self, spec: ServiceSpec) -> ServiceStatus:
        return self._status()

    def status(self, spec: ServiceSpec) -> ServiceStatus:
        return self._status()

    def start(self, spec: ServiceSpec) -> bool:
        return False

    def stop(self, spec: ServiceSpec) -> bool:
        return False


def service_manager(platform: str | None = None, runner: Runner = run_quiet) -> ServiceManager:
    """The service manager for this OS (or ``platform``, for tests)."""
    plat = platform or sys.platform
    if plat == "win32":
        from .windows import WindowsTaskManager

        return WindowsTaskManager(runner=runner)
    if plat == "darwin":
        from .launchd import LaunchdAgentManager

        return LaunchdAgentManager(runner=runner)
    if plat.startswith("linux"):
        from .systemd import SystemdUserManager

        return SystemdUserManager(runner=runner)
    return NullServiceManager(f"no supported service manager on {plat}")


__all__ = [
    "BOOT",
    "LOGIN",
    "NullServiceManager",
    "Runner",
    "ServiceManager",
    "ServiceSpec",
    "ServiceStatus",
    "check_start_at",
    "service_manager",
]
