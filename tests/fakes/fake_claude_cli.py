"""A stand-in for the ``claude`` CLI, for Claude subscription routing tests.

:func:`install` writes a ``claude`` launcher (``claude.cmd`` on Windows) into a
folder; the launcher runs this file. The fake reads the account it answers
for from ``$CLAUDE_CONFIG_DIR`` — the only thing a runtime's minimal child
environment tells the real CLI about the account — so a test can tell which
account was probed:

* ``auth status --json`` prints ``<CLAUDE_CONFIG_DIR>/fake-auth.json``
  (``{"loggedIn": false}`` when absent);
* anything else (a model call) exits 3: these tests never infer.

Every invocation appends its argv as one JSON line to
``<CLAUDE_CONFIG_DIR>/fake-calls.log``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SUBSCRIPTION = {"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "max"}
API_KEY = {"loggedIn": True, "authMethod": "api_key"}
LOGGED_OUT = {"loggedIn": False}


def install(directory: Path) -> Path:
    """Write a ``claude`` launcher for this fake into ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).resolve()
    if os.name == "nt":
        launcher = directory / "claude.cmd"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        launcher = directory / "claude"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
        launcher.chmod(0o755)
    return launcher


def sign_in(config_dir: Path, state: dict[str, object]) -> None:
    """What ``auth status --json`` answers for the account in ``config_dir``."""
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "fake-auth.json").write_text(json.dumps(state), encoding="utf-8")


def calls(config_dir: Path) -> list[list[str]]:
    """Every argv the fake was started with for ``config_dir``'s account."""
    try:
        lines = (config_dir / "fake-calls.log").read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    return [json.loads(line) for line in lines if line.strip()]


def main(argv: list[str]) -> int:
    import tempfile

    # Never the person's real ~/.claude: an unset account logs to a temp folder.
    config_dir = Path(
        os.environ.get("CLAUDE_CONFIG_DIR") or Path(tempfile.gettempdir()) / "fake-claude-unset"
    )
    config_dir.mkdir(parents=True, exist_ok=True)
    with (config_dir / "fake-calls.log").open("a", encoding="utf-8") as log:
        log.write(json.dumps(argv) + "\n")
    if argv[:3] == ["auth", "status", "--json"]:
        try:
            print((config_dir / "fake-auth.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            print(json.dumps(LOGGED_OUT))
        return 0
    print("fake claude: unexpected invocation", file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
