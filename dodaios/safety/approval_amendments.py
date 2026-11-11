"""The person's inline edit of a call, carried from the approval card to the executor.

A card may let the person change the text of what they are approving (a mail's
subject and body, a message, an event's title and time). The chat bridge
:func:`put` the amended arguments under the ticket's trace id *before* it
publishes the approval; :class:`~dodaios.safety.tool_executor.ToolExecutor`
:func:`take` them once the approval arrives and re-validates them through
its own gateway (blacklist, outbound checks) before anything runs. The map is
tiny and short-lived: an entry is consumed by the very call it belongs to, and
the oldest ones are dropped if a call never comes back for its own.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Final
from uuid import UUID

_MAX: Final[int] = 64
_lock = threading.Lock()
_pending: OrderedDict[UUID, tuple[dict[str, Any], dict[str, dict[str, str]]]] = OrderedDict()


def put(trace_id: UUID, args: dict[str, Any], changed: dict[str, dict[str, str]]) -> None:
    """Remember the amended ``args`` (and what changed) for the call ``trace_id``."""
    with _lock:
        _pending[trace_id] = (dict(args), dict(changed))
        while len(_pending) > _MAX:
            _pending.popitem(last=False)


def take(trace_id: UUID) -> tuple[dict[str, Any], dict[str, dict[str, str]]] | None:
    """The amendment of ``trace_id`` once, else ``None``."""
    with _lock:
        return _pending.pop(trace_id, None)


def discard(trace_id: UUID) -> None:
    with _lock:
        _pending.pop(trace_id, None)


__all__ = ["discard", "put", "take"]
