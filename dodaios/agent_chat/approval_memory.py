"""The person's "Always allow" choices and narrow rules, kept across restarts.

The chat service remembers, per chat, which tools the person waved through
("Always allow"), the narrow rules from the card ("only this folder", "only
this command") and the rules a Claude Code session collected. They used to
live in plain dicts, so every restart asked the same questions again.

:class:`PersistedBags` is a drop-in for those dicts: it hands out a set or a
list per chat that writes itself to the chat database on every change, so the
code that grows, trims or empties the collection (the approval flow, the
approval bridge, a revoked rule on the Trust page) needs no second call. The
scope stays exactly what it was: one chat, one kind of rule. A chat that is
deleted takes its rules with it (``AgentChatStore.delete_session``).
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

__all__ = ["PersistedBags"]


class _Owner:
    """Writes one chat's bag back to the database."""

    def __init__(self, store: Any, bag: str) -> None:
        self.store = store
        self.bag = bag

    def flush(self, session_id: str, entries: list[str]) -> None:
        try:
            self.store.replace_approval_memory(session_id, self.bag, entries)
        except Exception:  # noqa: BLE001 - the rule holds for this run; only a restart forgets it
            log.warning("agent chat: %s of %s not saved", self.bag, session_id, exc_info=True)


class _PersistedSet(set[str]):
    def __init__(self, owner: _Owner, session_id: str, items: set[str] | None = None) -> None:
        super().__init__(items or ())
        self._owner = owner
        self._session_id = session_id

    def _save(self) -> None:
        self._owner.flush(self._session_id, sorted(self))

    def add(self, item: str) -> None:
        if item not in self:
            super().add(item)
            self._save()

    def discard(self, item: str) -> None:
        if item in self:
            super().discard(item)
            self._save()

    def remove(self, item: str) -> None:
        super().remove(item)
        self._save()

    def clear(self) -> None:
        super().clear()
        self._save()

    def update(self, *others: Any) -> None:
        super().update(*others)
        self._save()


class _PersistedList(list[dict[str, Any]]):
    def __init__(
        self, owner: _Owner, session_id: str, items: list[dict[str, Any]] | None = None
    ) -> None:
        super().__init__(items or ())
        self._owner = owner
        self._session_id = session_id

    def _save(self) -> None:
        entries = [
            json.dumps(item, ensure_ascii=False, sort_keys=True, default=str) for item in self
        ]
        self._owner.flush(self._session_id, entries)

    def append(self, item: dict[str, Any]) -> None:
        super().append(item)
        self._save()

    def extend(self, items: Any) -> None:
        super().extend(items)
        self._save()

    def remove(self, item: dict[str, Any]) -> None:
        super().remove(item)
        self._save()

    def clear(self) -> None:
        super().clear()
        self._save()

    def __setitem__(self, index: Any, value: Any) -> None:
        super().__setitem__(index, value)
        self._save()

    def __delitem__(self, index: Any) -> None:
        super().__delitem__(index)
        self._save()


class PersistedBags(dict[str, Any]):
    """``{session_id: set | list}`` whose values save themselves.

    ``kind`` is ``"set"`` (tool names) or ``"list"`` (JSON rules); ``bag`` names
    the table partition. ``setdefault`` ignores the default's value and returns
    the persisted collection, so ``bags.setdefault(sid, set()).add(x)`` and
    ``bags.get(sid)`` behave as before.
    """

    def __init__(self, store: Any, bag: str, kind: str) -> None:
        super().__init__()
        self._owner = _Owner(store, bag)
        self._kind = kind

    def load(self, rows: list[tuple[str, str]]) -> None:
        """Fill from ``(session_id, entry)`` rows read at start-up."""
        grouped: dict[str, list[str]] = {}
        for session_id, entry in rows:
            grouped.setdefault(session_id, []).append(entry)
        for session_id, entries in grouped.items():
            if self._kind == "set":
                dict.__setitem__(
                    self, session_id, _PersistedSet(self._owner, session_id, set(entries))
                )
                continue
            items: list[dict[str, Any]] = []
            for entry in entries:
                try:
                    value = json.loads(entry)
                except ValueError:
                    continue  # a damaged rule is dropped, never guessed
                if isinstance(value, dict):
                    items.append(value)
            dict.__setitem__(self, session_id, _PersistedList(self._owner, session_id, items))

    def setdefault(self, session_id: str, default: Any = None) -> Any:
        found = dict.get(self, session_id)
        if found is None:
            found = (
                _PersistedSet(self._owner, session_id)
                if self._kind == "set"
                else _PersistedList(self._owner, session_id)
            )
            dict.__setitem__(self, session_id, found)
        return found
