"""The checks a coding agent ran itself during its turn, read from the thread's record.

Where a repository has no checks on GitHub, the weakest evidence that still
says something is what the agent's own test, lint and type runs printed. This
module reads those runs from the thread's events: the shell command of each
tool call and whether its result was an error (the CLIs mark a command that
exited with a non-zero code as one). It never runs anything, in the person's
checkout or anywhere else.

What counts:

* a command that runs a test, lint or type check (a fixed list below);
* only its newest run of each kind: an early red run that was fixed later
  does not count against the turn, a later red run does;
* only when a check of some kind ran after the last file the agent's own tools
  wrote: a check before the last edit says nothing about the end result.

The agent can still write a check that proves nothing, or run one on a subset.
That is why this is a verdict of its own (``self_checked``) below ``verified``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, Final

__all__ = ["SHELL_TOOLS", "kind_of", "read"]

#: Tool names under which the CLIs run a shell command.
SHELL_TOOLS: Final[frozenset[str]] = frozenset(
    {"bash", "shell", "command_execution", "run_shell_command", "exec_command", "terminal"}
)
#: Where a command starts, and where the program's name ends.
_AT: Final[str] = r"(?:^|[\s;&|(])"
_END: Final[str] = r"(?=$|[\s;&|)])"
_PY: Final[str] = r"(?:python\d?(?:\.\d+)?\s+-m\s+|uv\s+run\s+|poetry\s+run\s+)?"
_JS: Final[str] = r"(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?"
#: ``(kind, pattern)``: what a command checks, by the program it runs.
_KINDS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("tests", re.compile(
        rf"{_AT}{_PY}(?:pytest|py\.test|tox|nox|unittest){_END}"
        rf"|{_AT}{_JS}test{_END}"
        rf"|{_AT}(?:npx\s+)?(?:jest|vitest|mocha|playwright\s+test){_END}"
        rf"|{_AT}(?:go|cargo|dotnet|swift|mix)\s+test{_END}"
        rf"|{_AT}(?:\./)?gradlew?\s+test{_END}|{_AT}mvn\s+(?:-\S+\s+)*test{_END}"
        rf"|{_AT}make\s+(?:test|check){_END}",
    )),
    ("lint", re.compile(
        rf"{_AT}{_PY}(?:ruff|flake8|pylint){_END}"
        rf"|{_AT}(?:npx\s+)?(?:eslint|biome\s+(?:check|lint)){_END}"
        rf"|{_AT}{_JS}lint{_END}"
        rf"|{_AT}(?:cargo\s+clippy|golangci-lint|go\s+vet){_END}",
    )),
    ("types", re.compile(
        rf"{_AT}{_PY}(?:mypy|pyright){_END}"
        rf"|{_AT}(?:npx\s+)?(?:tsc|vue-tsc){_END}"
        rf"|{_AT}{_JS}(?:typecheck|type-check|tsc){_END}"
        rf"|{_AT}cargo\s+check{_END}",
    )),
)
_SHOWN_MAX: Final[int] = 160


def kind_of(command: str) -> str:
    """``tests``, ``lint``, ``types`` or ``""`` for a shell command."""
    for kind, pattern in _KINDS:
        if pattern.search(command or ""):
            return kind
    return ""


def _command(payload: dict[str, Any]) -> str:
    args = payload.get("input") if isinstance(payload.get("input"), dict) else {}
    for key in ("command", "cmd", "input"):
        value = args.get(key)
        if isinstance(value, list):
            value = " ".join(str(part) for part in value)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def read(events: Iterable[dict[str, Any]], since_ms: int = 0) -> dict[str, Any]:
    """What the agent's own checks in the run said, as a step detail.

    ``passed`` is true only when at least one check ran after the last file
    the agent's tools wrote, and the newest run of every kind of check passed.
    """
    from dodaios.society.coding_threads import _WRITING_TOOLS

    calls: dict[str, tuple[int, str, str]] = {}
    results: dict[str, bool] = {}
    last_write = -1
    order = 0
    for event in events:
        if int(event.get("ts_ms") or 0) < since_ms:
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        kind = event.get("kind")
        if kind == "tool_call":
            order += 1
            name = str(payload.get("name") or "").lower()
            if name in _WRITING_TOOLS:
                last_write = order
            elif name in SHELL_TOOLS:
                command = _command(payload)
                check = kind_of(command)
                if check and payload.get("call_id"):
                    calls[str(payload["call_id"])] = (order, check, command)
        elif kind == "tool_result" and str(payload.get("call_id") or "") in calls:
            results[str(payload["call_id"])] = not bool(payload.get("is_error"))
    newest: dict[str, tuple[int, str, bool]] = {}
    for call_id, (at, check, command) in calls.items():
        if call_id not in results:
            continue  # no result on record: it proves nothing either way
        if check not in newest or at > newest[check][0]:
            newest[check] = (at, command, results[call_id])
    after_edit = any(at > last_write for at, _c, _ok in newest.values())
    runs = [
        {"kind": check, "command": command[:_SHOWN_MAX], "ok": ok}
        for check, (_at, command, ok) in sorted(newest.items())
    ]
    passed = bool(runs) and after_edit and all(run["ok"] for run in runs)
    if not runs:
        reason = "the agent ran no test, lint or type check in its turn"
    elif not all(run["ok"] for run in runs):
        reason = "the agent's own newest " + ", ".join(
            run["kind"] for run in runs if not run["ok"]
        ) + " run failed"
    elif not after_edit:
        reason = "the agent's own checks ran before its last edit"
    else:
        reason = "the agent's own checks passed after its last edit: " + "; ".join(
            f"{run['kind']}: {run['command']}" for run in runs
        )
    return {"passed": passed, "runs": runs, "reason": reason}
