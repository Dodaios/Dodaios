"""Linux: a systemd user unit, optionally kept alive without a login (linger)."""

from __future__ import annotations

import dataclasses
import getpass
import os
import re
import shutil
from collections.abc import Callable
from pathlib import Path

from .._platform import run_quiet
from . import BOOT, LOGIN, Runner, ServiceSpec, ServiceStatus, check_start_at

_PLAIN = re.compile(r"^[A-Za-z0-9_@%+=:,./-]+$")


def quote_exec_arg(arg: str) -> str:
    """One ``ExecStart=`` word, quoted the way systemd parses it.

    ``%`` starts a specifier and ``$`` an environment variable in systemd's
    command lines; both are doubled so they reach the program literally.
    """
    escaped = arg.replace("%", "%%").replace("$", "$$")
    if escaped and _PLAIN.match(escaped):
        return escaped
    return '"' + escaped.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _quote_value(text: str) -> str:
    return text.replace("%", "%%")


def render_unit(spec: ServiceSpec) -> str:
    """The unit file text for ``spec``. Pure: no files, no commands."""
    lines = [
        "# Written by daemonkit. Remove it with the program that installed it.",
        "[Unit]",
        f"Description={_quote_value(spec.description or spec.name)}",
        "",
        "[Service]",
        "Type=simple",
        "ExecStart=" + " ".join(quote_exec_arg(a) for a in spec.argv),
    ]
    if spec.working_dir:
        lines.append(f"WorkingDirectory={_quote_value(spec.working_dir)}")
    for key, value in sorted(spec.env.items()):
        pair = f"{key}={value}".replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'Environment="{_quote_value(pair)}"')
    lines += [
        # The supervisor exits 0 when it is done on purpose; any other end
        # means it died, and systemd starts it again.
        "Restart=on-failure",
        "RestartSec=5",
        # SIGTERM to the supervisor (which ends its server), SIGKILL to
        # whatever is left after the timeout.
        "KillMode=mixed",
        "TimeoutStopSec=45",
        "",
        "[Install]",
        "WantedBy=default.target",
        "",
    ]
    return "\n".join(lines)


class SystemdUserManager:
    mechanism = "systemd-user"

    def __init__(
        self,
        *,
        runner: Runner = run_quiet,
        unit_dir: Path | None = None,
        linger_dir: Path = Path("/var/lib/systemd/linger"),
        user: str | None = None,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self._run = runner
        self._unit_dir = unit_dir
        self._linger_dir = linger_dir
        self._user = user
        self._which = which

    # -- naming --------------------------------------------------------------

    @property
    def user(self) -> str:
        return self._user or getpass.getuser()

    def unit_name(self, spec: ServiceSpec) -> str:
        return f"{spec.name}.service"

    def unit_dir(self) -> Path:
        if self._unit_dir is not None:
            return self._unit_dir
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        return Path(base) / "systemd" / "user"

    def unit_path(self, spec: ServiceSpec) -> Path:
        return self.unit_dir() / self.unit_name(spec)

    # -- probes --------------------------------------------------------------

    def available(self) -> tuple[bool, str]:
        if not self._which("systemctl"):
            return False, "systemctl not found: this Linux does not run systemd"
        probe = self._run(["systemctl", "--user", "show-environment"])
        if probe.returncode != 0:
            reason = (probe.stderr or probe.stdout).strip() or "no user service manager"
            return False, f"the systemd user manager is not reachable: {reason}"
        return True, ""

    def lingering(self) -> bool:
        """Whether this user's services run without a login (``loginctl enable-linger``)."""
        return (self._linger_dir / self.user).exists()

    def _systemctl(self, *args: str) -> tuple[bool, str]:
        result = self._run(["systemctl", "--user", *args])
        return result.returncode == 0, (result.stdout + result.stderr).strip()

    # -- operations ----------------------------------------------------------

    def install(
        self, spec: ServiceSpec, *, start_at: str = LOGIN, start_now: bool = True
    ) -> ServiceStatus:
        check_start_at(start_at)
        ok, reason = self.available()
        if not ok:
            return ServiceStatus(self.mechanism, supported=False, installed=False, detail=reason)
        path = self.unit_path(spec)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(render_unit(spec), encoding="utf-8")
        os.replace(tmp, path)
        notes: list[str] = []
        done, out = self._systemctl("daemon-reload")
        if not done:
            notes.append(f"daemon-reload failed: {out}")
        enable = ["enable", "--now"] if start_now else ["enable"]
        done, out = self._systemctl(*enable, self.unit_name(spec))
        if not done:
            notes.append(f"enable failed: {out}")
        if start_at == BOOT and not self.lingering():
            result = self._run(["loginctl", "enable-linger", self.user])
            if result.returncode != 0:
                notes.append(
                    "could not keep services running without a login "
                    f"(loginctl enable-linger {self.user}): "
                    + (result.stderr or result.stdout).strip()
                )
        status = self.status(spec)
        if notes:
            return dataclasses.replace(status, detail="; ".join(notes))
        return status

    def uninstall(self, spec: ServiceSpec) -> ServiceStatus:
        path = self.unit_path(spec)
        if path.exists():
            self._systemctl("disable", "--now", self.unit_name(spec))
            path.unlink()
            self._systemctl("daemon-reload")
        # Linger is left as it is: other services of this user may rely on it.
        return self.status(spec)

    def status(self, spec: ServiceSpec) -> ServiceStatus:
        path = self.unit_path(spec)
        installed = path.exists()
        if not installed:
            ok, reason = self.available()
            return ServiceStatus(
                self.mechanism, supported=ok, installed=False, location=str(path), detail=reason
            )
        _, enabled = self._systemctl("is-enabled", self.unit_name(spec))
        _, active = self._systemctl("is-active", self.unit_name(spec))
        is_enabled = enabled.splitlines()[0] == "enabled" if enabled else False
        starts_at = (BOOT if self.lingering() else LOGIN) if is_enabled else None
        return ServiceStatus(
            self.mechanism,
            supported=True,
            installed=True,
            active=(active.splitlines()[0] == "active") if active else False,
            starts_at=starts_at,
            location=str(path),
            detail="" if is_enabled else f"unit is {enabled or 'not enabled'}",
        )

    def start(self, spec: ServiceSpec) -> bool:
        return self._systemctl("start", self.unit_name(spec))[0]

    def stop(self, spec: ServiceSpec) -> bool:
        return self._systemctl("stop", self.unit_name(spec))[0]
