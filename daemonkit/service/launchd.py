"""macOS: a launchd agent in ``~/Library/LaunchAgents``, started at login."""

from __future__ import annotations

import dataclasses
import os
import plistlib
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .._platform import run_quiet
from . import BOOT, LOGIN, Runner, ServiceSpec, ServiceStatus, check_start_at


def default_label(spec: ServiceSpec) -> str:
    return spec.label or f"local.daemonkit.{spec.name}"


def render_plist(spec: ServiceSpec) -> bytes:
    """The agent's property list for ``spec``. Pure: no files, no commands."""
    plist: dict[str, Any] = {
        "Label": default_label(spec),
        "ProgramArguments": list(spec.argv),
        "RunAtLoad": True,
        # Start it again only when it died; a supervisor that ended on
        # purpose exits 0 and stays down.
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 10,
    }
    if spec.working_dir:
        plist["WorkingDirectory"] = spec.working_dir
    if spec.env:
        plist["EnvironmentVariables"] = dict(sorted(spec.env.items()))
    if spec.log_path:
        plist["StandardOutPath"] = spec.log_path
        plist["StandardErrorPath"] = spec.log_path
    return plistlib.dumps(plist, sort_keys=False)


class LaunchdAgentManager:
    mechanism = "launchd-agent"

    def __init__(
        self,
        *,
        runner: Runner = run_quiet,
        agents_dir: Path | None = None,
        uid: int | None = None,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self._run = runner
        self._agents_dir = agents_dir
        self._uid = uid
        self._which = which

    def plist_path(self, spec: ServiceSpec) -> Path:
        base = self._agents_dir or Path.home() / "Library" / "LaunchAgents"
        return base / f"{default_label(spec)}.plist"

    def domain(self) -> str:
        uid = self._uid if self._uid is not None else os.getuid()  # type: ignore[attr-defined,unused-ignore]
        return f"gui/{uid}"

    def target(self, spec: ServiceSpec) -> str:
        return f"{self.domain()}/{default_label(spec)}"

    def available(self) -> tuple[bool, str]:
        if not self._which("launchctl"):
            return False, "launchctl not found"
        return True, ""

    def _launchctl(self, *args: str) -> tuple[bool, str]:
        result = self._run(["launchctl", *args])
        return result.returncode == 0, (result.stdout + result.stderr).strip()

    def install(
        self, spec: ServiceSpec, *, start_at: str = LOGIN, start_now: bool = True
    ) -> ServiceStatus:
        check_start_at(start_at)
        ok, reason = self.available()
        if not ok:
            return ServiceStatus(self.mechanism, supported=False, installed=False, detail=reason)
        path = self.plist_path(spec)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_bytes(render_plist(spec))
        os.replace(tmp, path)
        notes: list[str] = []
        if start_at == BOOT:
            notes.append(
                "macOS starts user agents at login only; starting before login would "
                "need a LaunchDaemon, which runs outside the user's keychain"
            )
        # Reload so a changed command takes effect; an agent that was not
        # loaded makes bootout fail, which is fine.
        self._launchctl("bootout", self.target(spec))
        if start_now:
            done, out = self._launchctl("bootstrap", self.domain(), str(path))
            if not done:
                notes.append(f"bootstrap failed: {out}")
        status = self.status(spec)
        if notes:
            return dataclasses.replace(status, detail="; ".join(notes))
        return status

    def uninstall(self, spec: ServiceSpec, *, stop: bool = True) -> ServiceStatus:
        """Remove the agent; with ``stop=False`` a loaded one runs until logout."""
        if stop:
            self._launchctl("bootout", self.target(spec))
        path = self.plist_path(spec)
        if path.exists():
            path.unlink()
        return self.status(spec)

    def status(self, spec: ServiceSpec) -> ServiceStatus:
        path = self.plist_path(spec)
        if not path.exists():
            ok, reason = self.available()
            return ServiceStatus(
                self.mechanism, supported=ok, installed=False, location=str(path), detail=reason
            )
        loaded, out = self._launchctl("print", self.target(spec))
        active = loaded and "state = running" in out
        return ServiceStatus(
            self.mechanism,
            supported=True,
            installed=True,
            active=active,
            starts_at=LOGIN,
            location=str(path),
            detail="" if loaded else "installed; loads at the next login",
        )

    def start(self, spec: ServiceSpec) -> bool:
        loaded, _ = self._launchctl("print", self.target(spec))
        if not loaded:
            return self._launchctl("bootstrap", self.domain(), str(self.plist_path(spec)))[0]
        return self._launchctl("kickstart", self.target(spec))[0]

    def stop(self, spec: ServiceSpec) -> bool:
        # bootout unloads it until the next login; ``launchctl stop`` would
        # only have KeepAlive start it again.
        return self._launchctl("bootout", self.target(spec))[0]
