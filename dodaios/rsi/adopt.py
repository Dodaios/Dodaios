"""Notes the assistant wrote for itself are self-changes too: bring them into the registry.

The memory learner keeps two kinds of rule for the assistant. A *lesson* is the
person's correction in the person's words: that is an instruction, it applies
at once and nothing measures whether to obey it. A *how-to* is different: the
assistant watched a tool fail and a later call work, and wrote itself a note.
Nobody asked for it, and it rides in later prompts. That is the assistant
changing its own behaviour, and until now it left no trace in the registry.

Each night this module makes sure every current how-to note has an entry of
the surface ``lesson`` (:func:`how_tos`). From then on it shows in the list of
what the assistant changed in itself, the person can take it back with one
click (the note is ended in the memory, see :func:`revert`), and a benchmark
run of the assistant "as it ships" does not see it (:func:`memory_ids`).

The entry holds no text of the note, only the memory's id. So when the person
forgets a memory, nothing of it stays behind here; the entry is closed.

A how-to is not measured yet (nothing can tell so far whether one helps). It
is listed as what it is: learned, in effect, not measured.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from dodaios.memory.vault import lessons
from dodaios.memory.vault.store import MemoryVault
from dodaios.self_change import SelfChangeRegistry, State, Surface
from dodaios.self_change.store import Change

__all__ = ["AUTHOR", "PREFIX", "how_tos", "memory_id", "memory_ids", "revert"]

log = logging.getLogger(__name__)

#: ``ref`` prefix of a registry entry that stands for a note in the memory.
PREFIX: Final = "lesson:"
#: Who wrote these notes.
AUTHOR: Final = "memory-learner"
_TITLE: Final = "a how-to note the assistant wrote for itself"


def memory_id(change: Change) -> str:
    """The memory an entry stands for; "" when it is no such entry."""
    return change.ref[len(PREFIX) :] if change.ref.startswith(PREFIX) else ""


def memory_ids(registry: SelfChangeRegistry) -> frozenset[str]:
    """Ids of the notes in effect that the assistant wrote for itself."""
    return frozenset(
        found
        for change in registry.learned()
        if change.surface is Surface.LESSON and (found := memory_id(change))
    )


def how_tos(registry: SelfChangeRegistry, vault: MemoryVault) -> dict[str, int]:
    """Bring the registry in step with the how-to notes of ``vault``. Returns what it did."""
    current = {
        m.id for m in lessons.current_notes(vault, lessons.HOW_TO) if m.origin != "user"
    }
    known = {
        memory_id(change): change
        for change in registry.store.list(limit=5000)
        if change.surface is Surface.LESSON and memory_id(change)
    }
    adopted = closed = 0
    for found in sorted(current - set(known)):
        registry.note_external(
            surface=Surface.LESSON,
            ref=f"{PREFIX}{found}",
            title=_TITLE,
            state=State.LIVE,
            author=AUTHOR,
        )
        adopted += 1
    for found, change in known.items():
        if found not in current and change.state in (State.TRIAL, State.LIVE):
            # The note ended in the memory (forgotten, replaced, taken back there).
            registry.store.move(
                change.id, State.REVERTED, actor=AUTHOR, note="the note is gone from the memory"
            )
            closed += 1
    return {"adopted": adopted, "closed": closed}


def revert(change: Change, vault: Any) -> None:
    """Take a how-to note back: end it in the memory. The registry calls this on undo."""
    found = memory_id(change)
    if not found:
        raise RuntimeError(f"{change.ref!r} is not a note of the memory")
    if vault is None:
        raise RuntimeError("the memory is not running, so the note cannot be ended")
    if not vault.invalidate(found, reason="taken back in Self-improvement"):
        log.info("adopt: the note %s was already gone", found)
