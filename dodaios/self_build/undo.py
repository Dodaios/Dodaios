"""One undo for any build: each artefact kind registers how it is removed.

A builder registers an undoer for its kind at startup. ``undo`` then works the
same for a memory entry, a skill, a routine, an agent or a pull request: the
undoer removes the artefact from the payload the builder stored with
:meth:`BuildLedger.attach_artefact`, and the build is marked ``undone``.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable

from .ledger import BuildLedger
from .records import LIVE_STATES, OPEN_STATES, BuildRecord, Kind, State

log = logging.getLogger(__name__)

#: Removes the artefact a build created. Raise to report that it could not.
Undoer = Callable[[BuildRecord], Awaitable[None] | None]


class UndoUnavailable(RuntimeError):
    """The build has an artefact, but nothing knows how to remove it."""


class UndoRegistry:
    def __init__(self) -> None:
        self._undoers: dict[Kind, Undoer] = {}

    def register(self, kind: Kind, undoer: Undoer) -> None:
        self._undoers[Kind(kind)] = undoer

    def has(self, kind: Kind) -> bool:
        return Kind(kind) in self._undoers

    async def undo(self, ledger: BuildLedger, build_id: str, note: str = "") -> BuildRecord:
        record = await asyncio.to_thread(ledger.get, build_id)
        if record is None:
            raise KeyError(build_id)
        if record.state == State.PROPOSED:
            return await asyncio.to_thread(
                ledger.set_state, build_id, State.REJECTED, note or "rejected"
            )
        if record.state not in LIVE_STATES | OPEN_STATES | {State.ARCHIVED}:
            return record  # already undone, rejected or failed: nothing exists
        if record.artefact:
            undoer = self._undoers.get(record.kind)
            if undoer is None:
                raise UndoUnavailable(record.kind.value)
            result = undoer(record)
            if inspect.isawaitable(result):
                await result
        return await asyncio.to_thread(ledger.set_state, build_id, State.UNDONE, note or "undone")
