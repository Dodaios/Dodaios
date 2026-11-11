"""Safe self-improvement: one versioned, gated, reversible record of every self-change.

See :mod:`dodaios.self_change.registry` for the flow and docs/self-change.md for
the rules (what is core, what the gate checks, how rollback works).
"""

from __future__ import annotations

from .gate import Draft, Gate
from .registry import OWNER, SelfChangeError, SelfChangeRegistry
from .surfaces import State, Surface

_current: SelfChangeRegistry | None = None


def current() -> SelfChangeRegistry | None:
    """The running app's registry, or ``None`` before boot (tests, headless tools)."""
    return _current


def set_current(registry: SelfChangeRegistry | None) -> None:
    global _current
    _current = registry


__all__ = [
    "OWNER",
    "Draft",
    "Gate",
    "SelfChangeError",
    "SelfChangeRegistry",
    "State",
    "Surface",
    "current",
    "set_current",
]
