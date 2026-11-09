"""Thread features a grid pane already has: fork a conversation, adopt a CLI session.

* **Fork** — a new thread that starts from a copy of an existing one. The
  transcript is copied so the person sees what was said; the CLI's own
  conversation is forked where the vendor has a fork flag (Claude Code:
  ``--resume <id> --fork-session``). Codex' ``fork`` is interactive-only (there
  is no ``exec`` form), so a Codex fork starts a fresh CLI conversation under
  the copied transcript.
* **Adopt** — a thread created on a CLI session that already exists (a grid
  pane's), so the next turn resumes it.

A fork that has not run yet is stored as ``vendor_session = "fork:<source id>"``.
The Claude planner turns it into the fork argv and reports the new id, which
replaces the marker after the first turn.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dodaios.agent_chat.store import AgentChatSession

FORK_PREFIX = "fork:"

#: Runners whose CLI can fork a conversation in a headless turn.
FORKING_RUNNERS = frozenset({"claude-cli"})
#: Runners that resume a conversation by a plain UUID.
_UUID_RUNNERS = frozenset({"claude-cli", "codex-cli"})
_UUID = re.compile(r"^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
#: Event kinds a fork copies: what was said, not what was running.
_COPIED_KINDS = frozenset(
    {
        "user_message",
        "turn_started",
        "turn_finished",
        "assistant_text",
        "reasoning",
        "tool_call",
        "tool_result",
        "subagent_started",
        "subagent_finished",
    }
)


def split_fork(resume: str | None) -> tuple[str | None, str | None]:
    """``(resume id, fork source)`` for a stored vendor session value."""
    if resume and resume.startswith(FORK_PREFIX):
        return None, resume[len(FORK_PREFIX) :] or None
    return resume, None


def clean_vendor_session(runner: str, raw: str) -> str:
    """A session id the runner can resume, or ``ValueError``."""
    value = (raw or "").strip()
    if not value:
        return ""
    if runner not in _UUID_RUNNERS:
        raise ValueError("Continuing an existing session is supported for Claude Code and Codex.")
    if not _UUID.match(value):
        raise ValueError("That is not a valid session id.")
    return value


def fork_session(
    svc: Any,
    source: AgentChatSession,
    *,
    runner: str,
    cwd: str | None = None,
    title: str = "",
) -> AgentChatSession:
    """A new thread that carries ``source``'s picks, transcript and (where possible) conversation."""
    copy = svc.store.create_session(
        provider=source.provider,
        model=source.model,
        effort=source.effort,
        cwd=cwd or source.cwd,
        permission_mode=source.permission_mode,
        title=title or source.title,
        surface=source.surface,
        account_id=source.account_id,
        runtime=source.runtime,
    )
    events = svc.store.list_events(source.session_id)
    # Only whole turns: a turn still running (or cut off) in the source would
    # open a phantom turn in the copy.
    done = [i for i, e in enumerate(events) if e.get("kind") == "turn_finished"]
    for event in events[: done[-1] + 1] if done else []:
        if event.get("kind") in _COPIED_KINDS:
            svc.store.append_event(
                copy.session_id,
                {
                    "kind": event["kind"],
                    "payload": event.get("payload") or {},
                    "ts_ms": event.get("ts_ms"),
                },
            )
    vendor = source.vendor_session or ""
    if vendor and runner in FORKING_RUNNERS:
        # An unforked source that is itself a pending fork forks its own source.
        _, pending = split_fork(vendor)
        marker = FORK_PREFIX + (pending or vendor)
        updated = svc.store.update_session(copy.session_id, vendor_session=marker)
        return updated or copy
    return svc.store.get_session(copy.session_id) or copy
