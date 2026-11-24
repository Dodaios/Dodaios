"""The files one daemon keeps in its state directory."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def check_name(name: str) -> str:
    """A daemon name is a file name and a service name: letters, digits, ``._-``."""
    if not _NAME.match(name):
        raise ValueError(
            f"invalid daemon name {name!r}: use 1-64 letters, digits, '.', '_' or '-', "
            "starting with a letter or digit"
        )
    return name


@dataclass(frozen=True)
class DaemonPaths:
    """``<state_dir>/<name>.{lock,json,launch.lock,stop,log}``."""

    state_dir: Path
    name: str

    def __post_init__(self) -> None:
        check_name(self.name)

    @property
    def lock(self) -> Path:
        """Held by the running server for its whole life."""
        return self.state_dir / f"{self.name}.lock"

    @property
    def record(self) -> Path:
        """Where the server says how to reach it."""
        return self.state_dir / f"{self.name}.json"

    @property
    def launch_lock(self) -> Path:
        """Serializes clients that would otherwise start two servers at once."""
        return self.state_dir / f"{self.name}.launch.lock"

    @property
    def stop(self) -> Path:
        """Present while a stop was requested (the supervisor must not restart)."""
        return self.state_dir / f"{self.name}.stop"

    @property
    def log(self) -> Path:
        """Output of the supervisor and the server it runs."""
        return self.state_dir / f"{self.name}.log"
