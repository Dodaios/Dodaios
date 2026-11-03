"""Duty status of crew members, computed by the backend (contract 4.1).

A Python port of ``frontend/src/components/society/verse/ranks/dutyStatus.ts``
(``dutyOf``, ``dutyOfPane``) and of the pane dot reading in
``frontend/src/components/agentic/sidePanel/agentStatus.ts`` (``dotKindFor``,
``stateKeyFor``), so Unreal never re-implements the precedence rules.

Precedence: paused > waiting > working > error > idle. The parity table
``tests/unit/verse_host/parity/duty_cases.json`` is checked against both the
TS code (vitest) and this module (pytest).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

DUTY_STATUSES: Final = ("working", "waiting", "idle", "paused", "error")
RUN_STATES: Final = ("paused", "waiting", "working", "idle")
PANE_STATUSES: Final = ("pending", "live", "exited", "error")
PANE_ACTIVITIES: Final = (
    "starting",
    "working",
    "waiting",
    "asking",
    "failed",
    "exited",
    "stopped",
    "unknown",
    "",
)


def duty_of(
    state: str, lifecycle: str | None = None, *, asking: bool = False, error: bool = False
) -> str:
    """A society agent's duty status (``dutyOf``)."""
    if state == "paused" or lifecycle == "paused":
        return "paused"
    if asking or state == "waiting":
        return "waiting"
    if state == "working":
        return "working"
    if error:
        return "error"
    return "idle"


def dot_kind_for(pane: Mapping[str, Any]) -> str:
    """The IDE's dot colour of a pane (``dotKindFor``)."""
    status, activity = pane.get("status"), pane.get("activity")
    if status == "error" or activity == "failed":
        return "error"
    if activity == "asking":
        return "waiting"
    if activity in ("working", "starting") or status == "pending":
        return "working"
    return "idle"


def state_key_for(pane: Mapping[str, Any], kind: str | None = None) -> str:
    """The finer reading behind a pane's dot (``stateKeyFor``)."""
    kind = kind or dot_kind_for(pane)
    activity, status = pane.get("activity"), pane.get("status")
    if activity in ("stopped", "unknown"):
        return str(activity)
    if kind == "working":
        return "starting" if activity == "starting" or status == "pending" else "working"
    if kind == "waiting":
        return "needs_input"
    if kind == "error":
        return "failed" if activity == "failed" else "error"
    if status == "exited":
        return "exited"
    return "done" if pane.get("worked") else "idle"


def duty_of_pane(dot: str, state_key: str | None = None) -> str:
    """A coding pane's duty status from its dot and state key (``dutyOfPane``)."""
    if state_key == "stopped":
        return "paused"
    if dot in ("working", "waiting", "error"):
        return dot
    return "idle"


def pane_duty(pane: Mapping[str, Any]) -> str:
    """Shortcut: the duty of a ``WorkspacePaneRow``-shaped pane row."""
    kind = dot_kind_for(pane)
    return duty_of_pane(kind, state_key_for(pane, kind))


def or_fallback(value: Any, allowed: tuple[str, ...], fallback: str) -> str:
    """An enum value as sent, or the documented fallback for anything else."""
    return value if isinstance(value, str) and value in allowed else fallback
