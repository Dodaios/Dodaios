"""Keep an assistant's own commands away from where the vault keeps its values.

On macOS every Dodaios secret lives in one Keychain item that any process of
the person can read through ``/usr/bin/security`` without a dialog
(``dodaios/core/keychain_bundle.py`` says why). An assistant runs its shell
commands as that person, so a command that names that item, dumps a keychain,
asks a keyring for a value or opens the file store would hand the owner's
secrets to the model. Such a command is refused:

- in the lead's ``run_shell`` and a society seat's ``society_shell``
  (``refusal``), before anything runs;
- in a Claude Code seat's own tools, through a ``PreToolUse`` hook that runs
  this file as a script (``hook_settings``). Exit code 2 blocks the call and
  the reason goes back to the model. Hooks run in every permission mode,
  "bypass" included: bypass skips asking, never this block.

Lexical, like the command blacklist: it stops the obvious and the accidental
read. It is no wall against code written to get round it, which is why the
values also never enter a prompt, a tool result or a chat event.

This file imports nothing from ``dodaios``: the hook runs it with the app's
Python as a plain script, from whatever folder the chat works in.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Final

__all__ = ["REFUSAL", "hook_settings", "refusal", "touches_vault"]

REFUSAL: Final[str] = (
    "Refused: this command would read the owner's secret store (the Keychain, a keyring or "
    "Dodaios' credential file). Secrets are never shown to you. Use a stored secret by its "
    "environment variable name inside run_shell or society_shell, or ask for one with "
    "society_request_credential."
)

_COMMAND_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        # The one Keychain item every Dodaios secret lives in, and its slots.
        r"__jarvis_vault__",
        r"\bsociety_(?:credential|login)\.",
        # macOS: reading a password item or a whole keychain.
        r"\b(?:find-generic-password|find-internet-password|dump-keychain)\b",
        r"\bsecurity\s+(?:-\S+\s+)*export\b",
        # Python keyring and Dodaios' own secret reader.
        r"\bkeyring\s+get\b",
        r"\bget_password\s*\(",
        r"\bget_credential\s*\(",
        r"\bget_secret(?:_any)?\s*\(",
        # Linux Secret Service, Windows Credential Manager.
        r"\bsecret-tool\s+(?:lookup|search)\b",
        r"\bGet-StoredCredential\b",
        r"\bCredRead\w*",
        r"Windows\.Security\.Credentials",
        # The 0600 file store the app falls back to without a working keyring.
        r"(?:^|[\s'\"/=:])data(?:-dev)?[/\\]credentials\.json\b",
    )
)

#: Fields of a file tool (Read, Grep, Glob …) that name what it opens.
_PATH_KEYS: Final[tuple[str, ...]] = ("file_path", "path", "notebook_path", "pattern")
_FILE_STORE: Final[re.Pattern[str]] = re.compile(
    r"(?:^|[/\\])data(?:-dev)?[/\\]credentials\.json$", re.IGNORECASE
)


def touches_vault(command: str) -> bool:
    """``command`` would read where the vault keeps its values."""
    text = str(command or "")
    return any(pattern.search(text) for pattern in _COMMAND_PATTERNS)


def refusal(command: str) -> str | None:
    """The reason to refuse ``command``, or ``None`` when it may run."""
    return REFUSAL if touches_vault(command) else None


def _blocked_call(call: dict[str, Any]) -> bool:
    tool = str(call.get("tool_name") or "")
    args = call.get("tool_input")
    if not isinstance(args, dict):
        return False
    if tool in {"Bash", "BashOutput", "PowerShell"} or "command" in args:
        if touches_vault(str(args.get("command") or "")):
            return True
    for key in _PATH_KEYS:
        value = args.get(key)
        if isinstance(value, str) and _FILE_STORE.search(value.strip()):
            return True
    return False


def hook_settings(python: str | None = None) -> dict[str, Any]:
    """Claude Code ``--settings`` that run this guard before every shell or file call."""
    interpreter = python or sys.executable or "python3"
    script = str(Path(__file__).resolve())
    # Double quotes read the same in sh, bash and cmd (Claude Code on Windows);
    # neither path can hold a double quote.
    command = f'"{interpreter}" "{script}"'
    return {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash|Read|Grep|Glob|NotebookRead",
                    "hooks": [{"type": "command", "command": command, "timeout": 10}],
                }
            ]
        }
    }


def _main() -> int:
    try:
        call = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0  # Not a hook payload: nothing to judge.
    if isinstance(call, dict) and _blocked_call(call):
        sys.stderr.write(REFUSAL + "\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(_main())
