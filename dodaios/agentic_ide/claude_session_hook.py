"""Claude Code hooks of a pane: its conversation, and the prompts typed into it.

Why this exists: a pane is resumed after a reboot through the conversation id
it was launched with (``--session-id``). But that id is not stable for the
life of the pane — ``/clear`` starts a new conversation, ``/resume`` switches
to another, and compaction can roll over to a fresh one. Resuming the launch
id afterwards brings back an OLD conversation, which is exactly the failure
Herdr hit and fixed (herdrdev/herdr#4059) by recording the id from this hook
on EVERY session start, whatever its source.

Claude Code runs this script with the hook payload as JSON on stdin; the pane
it belongs to is named by ``JARVIS_PANE_ID`` in the environment Jarvis gave the
CLI, and ``JARVIS_PANE_SESSIONS_DIR`` says where to write. One small JSON file
per pane, written atomically; the registry reads it before saving and before
resuming (:mod:`dodaios.agentic_ide.session`).

The same script is the pane's ``UserPromptSubmit`` hook: every prompt the CLI
accepts is appended to ``<pane>.prompts.jsonl`` beside the session record.
The self-building loop reads those rows, and counts one only when the person
pressed Enter in the pane's own window right before it (``self_build/loop.py``):
a prompt Jarvis or an agent sent is not the person's. The hook prints nothing
on stdout, because Claude Code adds a ``UserPromptSubmit`` hook's stdout to the
prompt.

Deliberately stdlib-only and run as a plain script (not ``python -m``), so it
starts in tens of milliseconds and cannot slow the CLI's startup down, and it
never fails loudly: a hook that errors would print into the agent's pane.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

PANE_ENV = "JARVIS_PANE_ID"
DIR_ENV = "JARVIS_PANE_SESSIONS_DIR"
#: The file of typed prompts beside a pane's session record.
PROMPTS_SUFFIX = ".prompts.jsonl"
#: A prompts file is started over past this size; the reader notices the shrink.
PROMPTS_MAX_BYTES = 256 * 1024
#: Characters of one prompt kept.
PROMPT_MAX_CHARS = 4000


def _safe_name(pane_id: str) -> str:
    return "".join(ch for ch in pane_id if ch.isalnum() or ch in "-_")[:80]


def record(pane_id: str, directory: Path, payload: dict) -> Path | None:
    """Write the pane's current conversation id; None when there is nothing to write."""
    session_id = str(payload.get("session_id") or "").strip()
    name = _safe_name(pane_id)
    if not session_id or not name:
        return None
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{name}.json"
    tmp = directory / f"{name}.{os.getpid()}.tmp"
    tmp.write_text(
        json.dumps(
            {
                "session_id": session_id,
                "source": str(payload.get("source") or ""),
                "transcript_path": str(payload.get("transcript_path") or ""),
                "at": time.time(),
            }
        ),
        encoding="utf-8",
    )
    os.replace(tmp, target)
    return target


def prompts_file(pane_id: str, directory: Path) -> Path | None:
    name = _safe_name(pane_id)
    return directory / f"{name}{PROMPTS_SUFFIX}" if name else None


def record_prompt(pane_id: str, directory: Path, payload: dict) -> Path | None:
    """Append the prompt the CLI just accepted; None when there is none."""
    prompt = str(payload.get("prompt") or "").strip()
    target = prompts_file(pane_id, directory)
    if not prompt or target is None:
        return None
    directory.mkdir(parents=True, exist_ok=True)
    try:
        if target.stat().st_size > PROMPTS_MAX_BYTES:
            target.unlink()
    except FileNotFoundError:  # the pane's first prompt: there is no file to start over
        pass
    line = json.dumps(
        {
            "at": time.time(),
            "prompt": prompt[:PROMPT_MAX_CHARS],
            "session_id": str(payload.get("session_id") or ""),
        },
        ensure_ascii=False,
    )
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
    return target


def main() -> int:
    pane_id = os.environ.get(PANE_ENV, "")
    directory = os.environ.get(DIR_ENV, "")
    if not pane_id or not directory:
        return 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if isinstance(payload, dict):
            if payload.get("hook_event_name") == "UserPromptSubmit":
                record_prompt(pane_id, Path(directory), payload)
            else:
                record(pane_id, Path(directory), payload)
    except Exception as exc:  # noqa: BLE001 - a hook must never break the agent's start
        # Quiet on purpose, but not silent: stderr lands in Claude Code's own
        # hook log (``--debug``), never on the pane.
        print(f"jarvis session hook: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
