"""The built-in inverses: actions the app's own tools already know how to reverse.

Each function reads a successful call's arguments and output and returns the
call that undoes it, or ``None``. Registered on import of :mod:`dodaios.trust`
through :func:`install_builtin_inverses`; a plugin adds its own with
:func:`dodaios.trust.undo.register_inverse`.
"""

from __future__ import annotations

import re
from typing import Any

from .undo import Inverse, register_inverse


def _summary_of(args: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())[:80]
    return ""


def gmail_inverse(args: dict[str, Any], output: Any) -> Inverse | None:
    """Archiving or relabelling a mail is undone by swapping the labels back."""
    if str(args.get("action") or "") != "modify_message":
        return None
    message_id = str(args.get("message_id") or "").strip()
    added = [str(x) for x in (args.get("add_labels") or []) if x]
    removed = [str(x) for x in (args.get("remove_labels") or []) if x]
    if not message_id or (not added and not removed):
        return None
    if "INBOX" in removed:
        label = "Archived a mail"
    elif "UNREAD" in removed and not added:
        label = "Marked a mail as read"
    else:
        label = "Changed a mail's labels"
    return {
        "tool": "gmail",
        "args": {
            "action": "modify_message",
            "message_id": message_id,
            "add_labels": removed,
            "remove_labels": added,
        },
        "label": label,
    }


def calendar_inverse(args: dict[str, Any], output: Any) -> Inverse | None:
    """A created event is undone by deleting it (the calendar keeps it in its bin)."""
    if str(args.get("action") or "") != "create_event":
        return None
    event_id = output.get("id") if isinstance(output, dict) else None
    if not isinstance(event_id, str) or not event_id.strip():
        return None
    title = _summary_of(args, "summary", "title")
    inverse_args: dict[str, Any] = {"action": "delete_event", "event_id": event_id.strip()}
    calendar_id = args.get("calendar_id")
    if isinstance(calendar_id, str) and calendar_id.strip():
        inverse_args["calendar_id"] = calendar_id.strip()
    return {
        "tool": "google_calendar",
        "args": inverse_args,
        "label": f"Created an event: {title}" if title else "Created an event",
    }


_SAVED = re.compile(
    r"^(Saved to memory|Saved to MEMORY\.md|Remembered: \[[^\]]*\]):?\s*(.+)$", re.S
)


def remember_inverse(args: dict[str, Any], output: Any) -> Inverse | None:
    """A fact just saved is undone by forgetting that exact fact."""
    if not isinstance(output, str):
        return None
    match = _SAVED.match(output.strip())
    if match is None:
        return None  # "Already in memory": nothing new to take back
    fact = " ".join(match.group(2).split())
    if not fact:
        return None
    return {
        "tool": "memory-forget",
        "args": {"about": fact},
        "label": f"Saved a memory: {fact[:60]}",
    }


def install_builtin_inverses() -> None:
    register_inverse("gmail", gmail_inverse)
    register_inverse("google_calendar", calendar_inverse)
    register_inverse("remember", remember_inverse)


install_builtin_inverses()

__all__ = [
    "calendar_inverse",
    "gmail_inverse",
    "install_builtin_inverses",
    "remember_inverse",
]
