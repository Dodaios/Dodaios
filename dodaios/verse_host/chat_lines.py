"""Desk-monitor chat lines: a Python port of ``crewFeeds/deskChat.ts`` (contract 6).

The tail of an agent's chat reduced to a few short lines: who said what and
which tool runs. Limits of the contract: at most 12 lines; each cut on a word
boundary at 160 characters (tool 80, notice and error 100).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any, Final

MAX_LINES: Final = 12
TEXT_MAX: Final = 160
TOOL_MAX: Final = 80
NOTICE_MAX: Final = 100
_SPACE = re.compile(r"\s+")


def clean(text: Any, limit: int = TEXT_MAX) -> str:
    """Whitespace flattened; longer than ``limit``: cut on a word boundary plus an ellipsis."""
    if not isinstance(text, str):
        return ""
    flat = _SPACE.sub(" ", text).strip()
    if len(flat) <= limit:
        return flat
    cut = flat[: limit - 1]
    space = cut.rfind(" ")
    # Only back off to a word boundary when it keeps most of the line.
    if space >= limit // 2:
        cut = cut[:space]
    return f"{cut.rstrip()}…"


def tool_label(name: Any) -> str:
    """Short tool names: ``mcp__dodaios__society_shell`` -> ``society_shell``."""
    if not isinstance(name, str) or not name:
        return "tool"
    return name.split("__")[-1] or name


def _line(event: Mapping[str, Any]) -> dict[str, str] | None:
    p = event.get("payload") or {}
    if not isinstance(p, Mapping):
        p = {}
    kind = event.get("kind")
    if kind == "user_message":
        return {"kind": "user", "text": clean(p.get("text"))}
    if kind == "agent_message":
        who = "user" if p.get("sender_kind") == "user" else "agent"
        return {"kind": who, "text": clean(p.get("text"))}
    if kind == "assistant_text":
        return {"kind": "agent", "text": clean(p.get("text"))}
    if kind == "tool_call":
        summary = p.get("summary")
        label = summary if isinstance(summary, str) and summary else tool_label(p.get("name"))
        return {"kind": "tool", "text": clean(label, TOOL_MAX)}
    if kind == "notice":
        text = p.get("text") if p.get("text") is not None else p.get("summary")
        return {"kind": "notice", "text": clean(text, NOTICE_MAX)}
    if kind == "error":
        return {"kind": "error", "text": clean(p.get("message"), NOTICE_MAX)}
    return None


def chat_lines(
    events: Iterable[Mapping[str, Any]], max_lines: int = MAX_LINES
) -> list[dict[str, str]]:
    lines = [line for e in events if (line := _line(e)) is not None and line["text"]]
    return lines[-max_lines:]


def chat_version(events: list[Mapping[str, Any]]) -> str:
    """A cheap identity for "did anything change": last event id or seq, and count."""
    if not events:
        return ""
    last = events[-1]
    ident = last.get("event_id") or last.get("id") or last.get("seq") or ""
    return f"{ident}:{len(events)}"
