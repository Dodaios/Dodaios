"""The few git and shell calls the code builder makes, bounded and windowless."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS

GIT_TIMEOUT_S = 60.0
NETWORK_TIMEOUT_S = 180.0


@dataclass(frozen=True, slots=True)
class Result:
    code: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.code == 0

    def tail(self, limit: int = 1500) -> str:
        text = (self.out + ("\n" + self.err if self.err else "")).strip()
        return text[-limit:]


def run(
    argv: Sequence[str],
    cwd: str | Path,
    *,
    timeout: float = GIT_TIMEOUT_S,
    env: Mapping[str, str] | None = None,
) -> Result:
    """Run ``argv`` in ``cwd``. Never raises: a missing program or a timeout is a
    non-zero :class:`Result` whose ``err`` says which."""
    child = dict(os.environ if env is None else env)
    # Never wait on a credential or editor prompt nobody can see.
    child["GIT_TERMINAL_PROMPT"] = "0"
    child.setdefault("GIT_EDITOR", "true")
    child["GH_PROMPT_DISABLED"] = "1"
    try:
        done = subprocess.run(
            list(argv),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=child,
            creationflags=NO_WINDOW_CREATIONFLAGS,
        )
    except FileNotFoundError:  # reported in the Result, which every caller checks
        return Result(127, "", f"{argv[0]} is not installed")
    except subprocess.TimeoutExpired:  # reported in the Result, which every caller checks
        return Result(124, "", f"{argv[0]} did not finish within {int(timeout)} s")
    except OSError as exc:  # reported in the Result, which every caller checks
        return Result(126, "", f"{argv[0]} could not start: {exc}")
    return Result(done.returncode, done.stdout or "", done.stderr or "")


def git(args: Sequence[str], cwd: str | Path, *, timeout: float = GIT_TIMEOUT_S) -> Result:
    return run(["git", "-c", "core.quotepath=off", *args], cwd, timeout=timeout)


def out(args: Sequence[str], cwd: str | Path) -> str:
    """Trimmed stdout of a git call, ``""`` when it failed."""
    result = git(args, cwd)
    return result.out.strip() if result.ok else ""
