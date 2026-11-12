"""The memory vault as the two pages the assistant's profile shows (ADR-0044).

Since the vault runs, a reviewed conversation is written into
``data/memory/vault.db`` and no longer into the lead's notebooks
(``society/jarvis/MEMORY.md`` and ``USER.md``). The assistant's profile page
(``/api/soul``) still has a "MEMORY.md" and a "USER.md" page: here they are
views of the vault, so the page shows what the assistant really knows.

* ``user``    what it knows about the person: who they are, what they like,
              the people around them, what they are working toward;
* ``memory``  what it was asked to remember, and its own working notes:
              standing rules, lessons, where things are, notable events.

Reads only, except :func:`forget`. Nothing here calls a model.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Final

from dodaios.memory.vault.models import Memory
from dodaios.memory.vault.store import MemoryVault

log = logging.getLogger(__name__)

#: Kinds that say something about the person; every other kind is a working note.
USER_KINDS: Final[frozenset[str]] = frozenset({"profile", "preference", "relationship", "project"})
PAGES: Final[tuple[str, ...]] = ("memory", "user")

#: Audit actions the "Recently learned" list shows, as the ledger's operations.
_OPERATIONS: Final[dict[str, str]] = {
    "add": "add",
    "supersede": "replace",
    "invalidate": "remove",
}
#: Audit rows read for one activity list (pins, scope changes and forgets are skipped).
_AUDIT_WINDOW: Final[int] = 80
_SEAT_FIELDS: Final[tuple[str, ...]] = ("seat", "seat_label", "billing")


def page_of(memory: Memory) -> str:
    """The page a memory belongs on.

    What the person asked to remember stays under "remembered" whatever it is
    about, as it did in MEMORY.md; everything else goes by its kind.
    """
    if memory.origin == "user":
        return "memory"
    return "user" if memory.kind in USER_KINDS else "memory"


def time_ms(stamp: str | None) -> int | None:
    """An ISO time as Unix milliseconds; ``None`` when it does not parse."""
    if not stamp:
        return None
    try:
        return int(datetime.fromisoformat(stamp).timestamp() * 1000)
    except ValueError:  # an unreadable stamp shows no date
        return None


def _entry(memory: Memory) -> dict[str, Any]:
    return {
        "id": memory.id,
        "text": memory.text,
        "importance": 10 if memory.pinned else 5,
        "origin": memory.origin,
        "explicit": memory.origin == "user",
        "store": "vault",
        "at_ms": time_ms(memory.recorded_at),
    }


def entries(vault: MemoryVault) -> dict[str, list[dict[str, Any]]]:
    """The current memories per page, newest first."""
    pages: dict[str, list[dict[str, Any]]] = {page: [] for page in PAGES}
    for memory in vault.list():
        pages[page_of(memory)].append({**_entry(memory), "source": dict(memory.source)})
    return pages


def activity(vault: MemoryVault, *, limit: int) -> list[dict[str, Any]]:
    """The newest changes to the vault, in the shape of the learning ledger's lines."""
    out: list[dict[str, Any]] = []
    for row in vault.audit_log(limit=max(limit, _AUDIT_WINDOW)):
        operation = _OPERATIONS.get(str(row.get("action") or ""))
        memory = vault.get(str(row.get("memory_id") or "")) if operation else None
        if operation is None or memory is None:
            continue  # a pin, a scope change, or a memory that was forgotten since
        if memory.origin == "imported":
            continue  # copied in from another store, not learned in a conversation
        source = memory.source
        via = str(source.get("via") or "")
        reason = str(source.get("reason") or "")
        out.append(
            {
                "ts": str(row.get("at") or ""),
                "source": f"{via}: {reason}" if via and reason else via,
                "target": page_of(memory),
                "operation": operation,
                "text": memory.text,
                # An ended memory was closed by a later line; its own quote is
                # why it was once written, not why it ended.
                "evidence": "" if operation == "remove" else str(source.get("evidence") or ""),
                **{name: str(source.get(name) or "") for name in _SEAT_FIELDS},
            }
        )
        if len(out) >= limit:
            break
    return out


def forget(vault: MemoryVault, memory_id: str) -> bool:
    """Forget one memory with every version of it; False when the vault has no such id."""
    if vault.get(memory_id) is None:
        return False
    erased = vault.forget(memory_id, reason="forgotten on the assistant's profile page")
    if erased:
        from dodaios.memory.vault import runtime

        runtime.changed()
    return bool(erased)
