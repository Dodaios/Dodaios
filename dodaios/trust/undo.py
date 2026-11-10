"""Undo for a reversible action the assistant just took.

A tool registers how to undo one of its actions::

    register_inverse("gmail", lambda args, output: {...} or None)

The function reads the call's arguments and the tool's output and returns an
*inverse*: ``{"tool": name, "args": {...}, "label": "Archived a mail"}``, or
``None`` when this particular call cannot be undone. The ``ToolExecutor``
hands every successful call to :meth:`UndoLedger.record`, which keeps the
inverse for a few minutes and tells its listeners (the chat posts an
``undo_available`` notice; the front end shows an undo toast for six seconds).
``POST /api/trust/undo/{id}`` runs the inverse through the same executor, so
an undo is audited and gated like any other call.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any, Final

from .hard_limits import bare_tool

log = logging.getLogger(__name__)

Inverse = dict[str, Any]
InverseFn = Callable[[dict[str, Any], Any], Inverse | None]
Listener = Callable[[dict[str, Any]], None]
#: ``run(tool_name, args, entry) -> ToolResult``: how the ledger runs an inverse.
#: ``entry`` is the ledger row, so the runner can stamp ``undo_of`` on the call.
Runner = Callable[[str, dict[str, Any], dict[str, Any]], Awaitable[Any]]

#: How long an inverse stays runnable after the action. The toast shows for six
#: seconds; the window is longer so a click just before it fades still lands.
UNDO_WINDOW_MS: Final[int] = 5 * 60 * 1000
_KEEP: Final[int] = 50

_INVERSES: dict[str, InverseFn] = {}


def register_inverse(tool_name: str, fn: InverseFn) -> None:
    """Register how calls of ``tool_name`` are undone (the last registration wins)."""
    _INVERSES[bare_tool(tool_name).lower()] = fn


def inverse_for(tool_name: str, args: dict[str, Any], output: Any) -> Inverse | None:
    fn = _INVERSES.get(bare_tool(tool_name).lower())
    if fn is None:
        return None
    try:
        inverse = fn(dict(args or {}), output)
    except Exception:  # noqa: BLE001 — a broken inverse means "no undo", never a failed call
        log.warning("undo: inverse for %s failed", tool_name, exc_info=True)
        return None
    if not isinstance(inverse, dict) or not inverse.get("tool"):
        return None
    return {
        "tool": str(inverse["tool"]),
        "args": dict(inverse.get("args") or {}),
        "label": str(inverse.get("label") or "")[:160],
    }


def session_of(config_snapshot: dict[str, Any] | None) -> str:
    ref = str((config_snapshot or {}).get("approval_ref") or "")
    return ref.removeprefix("agent-chat:") if ref.startswith("agent-chat:") else ""


class UndoLedger:
    def __init__(self, *, window_ms: int = UNDO_WINDOW_MS) -> None:
        self._window_ms = window_ms
        self._entries: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._listeners: list[Listener] = []
        self._runner: Runner | None = None

    def set_runner(self, runner: Runner | None) -> None:
        """How inverses run: the live tool executor, installed at bootstrap."""
        self._runner = runner

    def on_recorded(self, listener: Listener) -> Callable[[], None]:
        """Hear about every recorded inverse; returns how to stop listening."""
        self._listeners.append(listener)

        def off() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return off

    def record(
        self,
        tool_name: str,
        args: dict[str, Any],
        output: Any,
        config_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Keep the inverse of a successful call, if its tool has one."""
        if (config_snapshot or {}).get("undo_of"):
            return None  # an undo is not itself undoable
        inverse = inverse_for(tool_name, args, output)
        if inverse is None:
            return None
        now = int(time.time() * 1000)
        entry = {
            "id": uuid.uuid4().hex[:12],
            "tool": bare_tool(tool_name),
            "label": inverse["label"],
            "inverse": inverse,
            "session_id": session_of(config_snapshot),
            "created_ms": now,
            "expires_ms": now + self._window_ms,
            "state": "ready",
        }
        self._entries[entry["id"]] = entry
        while len(self._entries) > _KEEP:
            self._entries.popitem(last=False)
        for listener in list(self._listeners):
            try:
                listener(dict(entry))
            except Exception:  # noqa: BLE001 — a listener never costs the call
                log.warning("undo: listener failed", exc_info=True)
        return dict(entry)

    def get(self, undo_id: str) -> dict[str, Any] | None:
        entry = self._entries.get(undo_id)
        return dict(entry) if entry else None

    def items(self) -> list[dict[str, Any]]:
        return [dict(e) for e in self._entries.values()]

    async def undo(self, undo_id: str) -> dict[str, Any]:
        """Run the inverse. Returns the entry with its new ``state`` and ``error``."""
        entry = self._entries.get(undo_id)
        if entry is None:
            raise KeyError(undo_id)
        if entry["state"] != "ready":
            return dict(entry)
        if int(time.time() * 1000) > int(entry["expires_ms"]):
            entry["state"] = "expired"
            return dict(entry)
        if self._runner is None:
            entry["state"] = "failed"
            entry["error"] = "undo is not wired on this surface"
            return dict(entry)
        entry["state"] = "running"
        inverse = entry["inverse"]
        try:
            result = await self._runner(inverse["tool"], dict(inverse["args"]), dict(entry))
        except asyncio.CancelledError:
            entry["state"] = "ready"
            raise
        except Exception as exc:  # noqa: BLE001 — reported on the entry, never raised to the route
            entry["state"] = "failed"
            entry["error"] = str(exc)[:300]
            return dict(entry)
        ok = bool(getattr(result, "success", False))
        entry["state"] = "undone" if ok else "failed"
        if not ok:
            entry["error"] = str(getattr(result, "error", "") or "the inverse did not run")[:300]
        return dict(entry)

    def _reset_for_tests(self) -> None:
        self._entries.clear()
        self._listeners.clear()
        self._runner = None


_LEDGER = UndoLedger()


def undo_ledger() -> UndoLedger:
    return _LEDGER


__all__ = [
    "UNDO_WINDOW_MS",
    "Inverse",
    "InverseFn",
    "UndoLedger",
    "inverse_for",
    "register_inverse",
    "session_of",
    "undo_ledger",
]
