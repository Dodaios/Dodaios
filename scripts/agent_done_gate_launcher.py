#!/usr/bin/env python3
"""User-level Stop hook launcher for the agent done gate.

Installed by ``scripts/install_agent_done_gate.py`` into the user's home and
registered as the Stop hook of CLIs whose hooks live in the user config
(Codex, Kimi CLI). It finds the git repository of the session's working
directory and runs that repository's own ``scripts/agent_done_gate.py``.
A repository without the gate is left alone, so the hook is harmless
everywhere else.

Usage (from a hook config): ``python <home>/.agent-done-gate/hook.py codex``
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

LOG = Path.home() / ".agent-done-gate" / "hook.log"


def log(line: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > 1_000_000:
            LOG.write_text("", encoding="utf-8")
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(time.strftime("%Y-%m-%dT%H:%M:%S ") + line + "\n")
    except OSError:
        pass


def main() -> int:
    dialect = sys.argv[1] if len(sys.argv) > 1 else "codex"
    raw = sys.stdin.read()
    try:
        cwd = str(json.loads(raw or "{}").get("cwd") or os.getcwd())
    except ValueError:
        cwd = os.getcwd()
    cwd = cwd.removeprefix("file:///") if cwd.startswith("file:///") else cwd
    try:
        top = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0
    if top.returncode != 0:
        return 0
    gate = Path(top.stdout.strip()) / "scripts" / "agent_done_gate.py"
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
