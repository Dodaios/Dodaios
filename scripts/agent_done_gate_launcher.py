#!/usr/bin/env python3
"""User-level Stop hook launcher for the agent done gate.

Installed by ``scripts/install_agent_done_gate.py`` into the user's home and
registered as the Stop hook of CLIs whose hooks live in the user config
(Codex, Kimi CLI). A user-level hook fires in every folder a session runs in,
so this launcher runs the gate of a REGISTERED checkout only:

* the installer writes the primary checkout it was run from into
  ``~/.agent-done-gate/repos.json``;
* for a session, the launcher finds the primary checkout of the session's
  repository (the parent of its git common dir) and runs
  ``<primary checkout>/scripts/agent_done_gate.py`` with the session's folder
  as ``--cwd``. A linked worktree is therefore checked by the gate of the
  checkout it belongs to, never by its own copy of the script;
* a repository that is not registered is left alone, whatever files it has.
  Nothing inside the session's folder is ever executed.

Usage (from a hook config): ``python <home>/.agent-done-gate/hook.py codex``
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

MARKER = ".agent-done-gate"
REGISTRY_NAME = "repos.json"
GATE = ("scripts", "agent_done_gate.py")


def home() -> Path:
    return Path(os.environ.get("AGENT_DONE_GATE_HOME") or Path.home())


def log(line: str) -> None:
    path = home() / MARKER / "hook.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 1_000_000:
            path.write_text("", encoding="utf-8")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(time.strftime("%Y-%m-%dT%H:%M:%S ") + line + "\n")
    except OSError:
        pass


def same_path(path: str | Path) -> str:
    """A form of ``path`` two spellings of one folder share (case, links, 8.3 names)."""
    return os.path.normcase(os.path.realpath(str(path)))


def registered() -> set[str]:
    """The primary checkouts whose gate may run, as the installer recorded them."""
    try:
        data = json.loads((home() / MARKER / REGISTRY_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    repos = data.get("repos") if isinstance(data, dict) else None
    if not isinstance(repos, list):
        return set()
    return {same_path(item) for item in repos if isinstance(item, str) and item}


def _git(cwd: str, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", cwd, *args],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def primary_checkout(cwd: str) -> Path | None:
    """The checkout that owns the repository ``cwd`` is in: the parent of its
    git common dir. ``None`` outside a repository, and for a layout with no
    such checkout (a bare repository, a submodule, a separate git dir)."""
    common = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common or Path(common).name != ".git":
        return None
    return Path(common).parent


def main() -> int:
    dialect = sys.argv[1] if len(sys.argv) > 1 else "codex"
    raw = sys.stdin.read()
    try:
        cwd = str(json.loads(raw or "{}").get("cwd") or os.getcwd())
    except (ValueError, AttributeError):
        cwd = os.getcwd()
    cwd = cwd.removeprefix("file:///") if cwd.startswith("file:///") else cwd
    primary = primary_checkout(cwd)
    if primary is None:
        return 0
    if same_path(primary) not in registered():
        top = _git(cwd, "rev-parse", "--show-toplevel")
        if top and Path(top, *GATE).is_file():
            # A checkout that carries the gate but never registered: say so
            # once per stop in the log, and run nothing of it.
            log(f"{dialect} {cwd}: {primary} is not registered; its gate was not run")
        return 0
    gate = primary.joinpath(*GATE)
    if not gate.is_file():
        return 0
    try:
        proc = subprocess.run(  # noqa: S603
            [sys.executable, str(gate), "--hook", dialect, "--cwd", cwd],
            input=raw,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=590,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log(f"{dialect} {cwd}: gate did not answer ({exc})")
        return 0
    log(f"{dialect} {cwd}: exit {proc.returncode} {proc.stdout.strip()[:300]!r}")
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    return proc.returncode if proc.returncode in (0, 2) else 0


if __name__ == "__main__":
    sys.exit(main())
