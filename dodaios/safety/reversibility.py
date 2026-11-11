"""How far an action can be taken back, and who started it.

Autonomy is chosen per action by two facts: how reversible the action is and
how much it can cost when it is wrong. The risk tier (safe / monitor / ask /
block) already carries the second. This module supplies the first and the
origin of the call, so the executor can apply one rule:

* an action the owner started directly keeps today's behaviour (the tier and
  the owner's rules decide; nothing new is asked);
* an action that runs without the owner (a routine, an event trigger, a
  watchdog repair, an agent's own initiative) may run when it is
  **reversible**; a **recoverable** or **irreversible** one needs an approval
  unless the owner's whitelist or a standing rule already covers it.

Classes:

``reversible``    nothing changes, or an undo exists (a draft, a label, a
                  calendar entry the app can delete again, a saved memory).
``recoverable``   it can be put right with effort (a file written, a message
                  moved to the trash, an event changed).
``irreversible``  it cannot be taken back: a send, a payment, a post, a share,
                  a delete without a trash, a credential change.

A tool may declare ``reversibility`` or ``reversibility_for_args(args)``. For
a tool that did not, a table maps the app's own tools; anything else is read
from the effect class the origin record already derives (ADR-0040).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Final

from .origin import canonical, tool_effect

log = logging.getLogger(__name__)

REVERSIBILITY: Final[tuple[str, ...]] = ("reversible", "recoverable", "irreversible")

#: ``tool -> action -> class``; ``"*"`` covers a tool without actions or any
#: action not listed. Canonical tool names. The table speaks only for tools
#: whose actions are known; the rest fall back to the effect class.
_DECLARED: Final[dict[str, dict[str, str]]] = {
    "gmail": {
        "send_message": "irreversible",
        "reply": "irreversible",
        "forward": "irreversible",
        "delete_message": "irreversible",
        "trash_message": "recoverable",
        "modify_message": "reversible",
        "create_draft": "reversible",
        "*": "reversible",
    },
    "google_calendar": {
        "create_event": "reversible",
        "update_event": "recoverable",
        "delete_event": "recoverable",
        "respond_to_event": "irreversible",
        "*": "reversible",
    },
    "google_drive": {
        "create_file": "reversible",
        "create_folder": "reversible",
        "update_file": "recoverable",
        "share_file": "irreversible",
        "delete_file": "irreversible",
        "*": "reversible",
    },
    "slack": {"post_message": "irreversible", "*": "reversible"},
    "remember": {"*": "reversible"},
    "search_web": {"*": "reversible"},
    "call_contact": {"*": "irreversible"},
    "society_browser": {"*": "recoverable"},
}

#: Effect class (``origin.EFFECTS``) to reversibility, for tools nobody listed.
_FROM_EFFECT: Final[dict[str, str]] = {
    "read": "reversible",
    "modify": "recoverable",
    "outbound": "irreversible",
    "destructive": "irreversible",
    "spend": "irreversible",
}

#: Hard limits of the trust layer: none of these can be taken back.
_IRREVERSIBLE_LIMITS: Final[frozenset[str]] = frozenset(
    {"money", "credentials", "permanent_delete", "new_recipient"}
)


def reversibility_of(
    tool: Any,
    args: dict[str, Any],
    *,
    tier: str = "",
    hard_limit: str = "",
) -> str:
    """The reversibility class of this call: one of :data:`REVERSIBILITY`.

    Never raises. A call nobody can classify is ``reversible`` when its tier is
    ``safe`` (a tool that already says it is harmless) and ``recoverable``
    otherwise: unknown never reads as the most permissive class for a tool that
    can change something.
    """
    args = args if isinstance(args, dict) else {}
    hook = getattr(tool, "reversibility_for_args", None)
    if callable(hook):
        try:
            answer = hook(args)
        except Exception as exc:  # noqa: BLE001 — a broken hook means "undeclared"
            log.warning("reversibility_for_args on %r raised %r", getattr(tool, "name", "?"), exc)
            answer = None
        if answer in REVERSIBILITY:
            return str(answer)
    declared = getattr(tool, "reversibility", None)
    if declared in REVERSIBILITY:
        return str(declared)
    if hard_limit in _IRREVERSIBLE_LIMITS:
        return "irreversible"
    table = _DECLARED.get(canonical(str(getattr(tool, "name", "") or "")))
    if table is not None:
        action = str(args.get("action") or "").strip()
        found = table.get(action) or table.get("*")
        if found:
            return found
    effect = tool_effect(tool, args)
    if effect in _FROM_EFFECT:
        return _FROM_EFFECT[effect]
    return "reversible" if tier == "safe" else "recoverable"


# ------------------------------------------------------------------- origin

#: Origins that run without the owner. Declared by the calling layer.
UNATTENDED_ORIGINS: Final[frozenset[str]] = frozenset({"routine", "trigger", "watchdog", "agent"})
#: ``config_snapshot`` key a layer uses to declare the origin of its calls.
AUTONOMY_ORIGIN_KEY: Final[str] = "autonomy_origin"

_origin_var: ContextVar[tuple[str, dict[str, str]]] = ContextVar(
    "dodaios.autonomy_origin", default=("", {})
)


@contextmanager
def autonomy_origin(kind: str, **refs: str):
    """Mark every tool call made inside this block (and the tasks it starts).

    For layers that start a whole agent turn, where the tool context is built
    further down: the routine runner wraps its ``send`` in this. ``refs`` are
    the stop-hold references of the work (``task_id``, ``agent_id``,
    ``trigger_id``, ``job_id``, ``session_id``).
    """
    if kind not in UNATTENDED_ORIGINS:
        raise ValueError(f"unknown autonomy origin: {kind!r}")
    token = _origin_var.set((kind, {k: str(v) for k, v in refs.items() if v}))
    try:
        yield
    finally:
        _origin_var.reset(token)


def origin_refs() -> dict[str, str]:
    """The stop-hold references of the enclosing :func:`autonomy_origin` block."""
    return dict(_origin_var.get()[1])


def unattended_origin(config_snapshot: Mapping[str, Any] | None) -> str:
    """``routine`` / ``trigger`` / ``watchdog`` / ``agent``, or ``""`` for a
    call the owner started directly.

    Read from the snapshot the calling layer built in code (never from tool
    arguments, which the model writes), then from the block marker.
    """
    declared = str((config_snapshot or {}).get(AUTONOMY_ORIGIN_KEY) or "").strip().lower()
    if declared in UNATTENDED_ORIGINS:
        return declared
    return _origin_var.get()[0]


__all__ = [
    "AUTONOMY_ORIGIN_KEY",
    "REVERSIBILITY",
    "UNATTENDED_ORIGINS",
    "autonomy_origin",
    "origin_refs",
    "reversibility_of",
    "unattended_origin",
]
