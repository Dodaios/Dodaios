"""Windows: a Task Scheduler logon task, with the per-user ``Run`` key as fallback.

Why a scheduled task: Explorer runs the Startup folder and the ``Run`` key
through a throttled queue after login, so on a busy machine they can start
minutes late. The Task Scheduler starts a logon task within seconds, and it
can restart a task that failed.

Registering a task with a logon trigger is refused to a non-elevated process
on many Windows installations. When that happens this module writes the
``HKCU\\...\\Run`` value instead: no elevation, no PowerShell, starts at the
next login. Both run as the user, in the user's session, without elevation.

Starting before anyone logs in is not offered: it needs administrator rights
and a task that runs outside the user's session, where secrets stored in the
user's credential store are generally not readable.
"""

from __future__ import annotations

import dataclasses
import getpass
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from xml.sax.saxutils import escape

from .._platform import run_quiet
from ..process import spawn_detached
from . import BOOT, LOGIN, Runner, ServiceSpec, ServiceStatus, check_start_at

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


class Registry(Protocol):
    """The three operations on ``HKCU\\...\\Run`` this module needs."""

    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


if sys.platform == "win32":
    import winreg

    class WinRunKey:
        """``HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run``."""

        def get(self, name: str) -> str | None:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                    value, _kind = winreg.QueryValueEx(key, name)
            except FileNotFoundError:
                return None
            return str(value)

        def set(self, name: str, value: str) -> None:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

        def delete(self, name: str) -> None:
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
                ) as key:
                    winreg.DeleteValue(key, name)
            except FileNotFoundError:
                return  # nothing to delete

else:

    class WinRunKey:
        """Stand-in off Windows: there is no Run key to read or write."""

        def get(self, name: str) -> str | None:
            return None

        def set(self, name: str, value: str) -> None:
            raise OSError("the Run key exists only on Windows")

        def delete(self, name: str) -> None:
            return  # nothing exists to delete


def task_name(spec: ServiceSpec) -> str:
    return spec.label or spec.name


def current_user_id() -> str:
    """``DOMAIN\\user`` as Task Scheduler names the logged-in user."""
    user = os.environ.get("USERNAME") or getpass.getuser()
    domain = os.environ.get("USERDOMAIN")
    return f"{domain}\\{user}" if domain else user


def render_task_xml(spec: ServiceSpec, *, user_id: str) -> str:
    """The task definition for ``spec``. Pure: no files, no commands."""
    if spec.env:
        raise ValueError(
            "a Windows task carries no environment; put it in argv "
            "(daemonkit's supervisor takes --env KEY=VALUE)"
        )
    command = escape(spec.argv[0])
    arguments = escape(subprocess.list2cmdline(list(spec.argv[1:])))
    workdir = (
        f"\n      <WorkingDirectory>{escape(spec.working_dir)}</WorkingDirectory>"
        if spec.working_dir
        else ""
    )
    user = escape(user_id)
    description = escape(spec.description or spec.name)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{description}</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{user}</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{command}</Command>
      <Arguments>{arguments}</Arguments>{workdir}
    </Exec>
  </Actions>
</Task>
"""


class WindowsTaskManager:
    mechanism = "windows-task"
    fallback_mechanism = "windows-run-key"

    def __init__(
        self,
        *,
        runner: Runner = run_quiet,
        registry: Registry | None = None,
        user_id: str | None = None,
        spawn: Callable[..., int] = spawn_detached,
    ) -> None:
        self._run = runner
        self._registry = registry or WinRunKey()
        self._user_id = user_id
        self._spawn = spawn

    def available(self) -> tuple[bool, str]:
        return True, ""

    def _schtasks(self, *args: str) -> tuple[bool, str]:
        result = self._run(["schtasks", *args])
        return result.returncode == 0, (result.stdout + result.stderr).strip()

    def _task_exists(self, spec: ServiceSpec) -> bool:
        return self._schtasks("/Query", "/TN", task_name(spec))[0]

    def install(
        self, spec: ServiceSpec, *, start_at: str = LOGIN, start_now: bool = True
    ) -> ServiceStatus:
        check_start_at(start_at)
        notes: list[str] = []
        if start_at == BOOT:
            notes.append(
                "Windows starts it at login; starting before login needs administrator "
                "rights and runs outside the user's credential store"
            )
        xml = render_task_xml(spec, user_id=self._user_id or current_user_id())
        with tempfile.TemporaryDirectory(prefix="daemonkit-") as tmp:
            path = Path(tmp) / "task.xml"
            # schtasks reads a task definition as UTF-16 with a byte-order mark.
            path.write_text(xml, encoding="utf-16")
            created, out = self._schtasks(
                "/Create", "/TN", task_name(spec), "/XML", str(path), "/F"
            )
        if created:
            self._registry.delete(spec.name)
        else:
            # Commonly "access denied" for a logon trigger without elevation.
            self._registry.set(spec.name, subprocess.list2cmdline(list(spec.argv)))
            notes.append(f"Task Scheduler refused the logon task ({out}); using the Run key")
        if start_now:
            self.start(spec)
        status = self.status(spec)
        if notes:
            return dataclasses.replace(status, detail="; ".join(notes))
        return status

    def uninstall(self, spec: ServiceSpec) -> ServiceStatus:
        if self._task_exists(spec):
            self._schtasks("/Delete", "/TN", task_name(spec), "/F")
        self._registry.delete(spec.name)
        return self.status(spec)

    def status(self, spec: ServiceSpec) -> ServiceStatus:
        if self._task_exists(spec):
            return ServiceStatus(
                self.mechanism,
                supported=True,
                installed=True,
                starts_at=LOGIN,
                location=task_name(spec),
            )
        value = self._registry.get(spec.name)
        if value is not None:
            return ServiceStatus(
                self.fallback_mechanism,
                supported=True,
                installed=True,
                starts_at=LOGIN,
                location=f"HKCU\\{RUN_KEY}\\{spec.name}",
            )
        return ServiceStatus(self.mechanism, supported=True, installed=False)

    def start(self, spec: ServiceSpec) -> bool:
        if self._task_exists(spec):
            return self._schtasks("/Run", "/TN", task_name(spec))[0]
        if self._registry.get(spec.name) is not None:
            self._spawn(list(spec.argv), cwd=spec.working_dir)
            return True
        return False

    def stop(self, spec: ServiceSpec) -> bool:
        """End the task's process. Stop the server itself with ``Daemon.stop``."""
        if self._task_exists(spec):
            return self._schtasks("/End", "/TN", task_name(spec))[0]
        return False
