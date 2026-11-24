"""The recall domain: for this message, did the model get the memory it needed.

A task is a message the person sends and the memories that message needs
(``check["gold"]``, possibly none). The run asks the same code a live turn
uses (:func:`dodaios.memory.vault.runtime.recall_for`) which memories the
message brings up, and scores:

* a message with gold: the share of its gold memories the model has in front
  of it (looked up for the message, or always in mind). Where the task names
  ``stale`` memories (an older fact about the same thing), a gold memory that
  is shown BEHIND a stale one counts half: the model would read the outdated
  fact first;
* a message that needs no memory: 1.0 when nothing is looked up, else 0.0.
  A recall that shows something to every message would otherwise score best.

The cost of a task is the prompt it adds, in tokens (characters / 4): a recall
that shows more costs more on every message, and the gate holds that against
a gain.

No model is asked and nothing is written: the domain runs in milliseconds.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from dodaios.memory.vault import runtime as vault_runtime
from dodaios.memory.vault.store import MemoryVault

from .model import Task

__all__ = ["RecallWorld", "Scored", "score"]

_CHARS_PER_TOKEN = 4


@dataclass(frozen=True, slots=True)
class RecallWorld:
    """A memory a recall task runs against."""

    vault: MemoryVault
    #: How a task names a memory -> its id in :attr:`vault`. Empty: tasks name ids.
    ids: Mapping[str, str]
    #: The always-on ids, read once: the vault does not change while tasks run against it.
    _in_mind: list[frozenset[str]] = field(default_factory=list, compare=False, repr=False)

    def id_of(self, name: str) -> str:
        return self.ids.get(name, name) if self.ids else name

    def in_mind(self) -> frozenset[str]:
        if not self._in_mind:
            self._in_mind.append(vault_runtime.in_mind_ids(self.vault))
        return self._in_mind[0]


@dataclass(frozen=True, slots=True)
class Scored:
    score: float
    tokens: int
    detail: str = ""


#: The parts of the domain a result is shown in: tasks where a memory belongs in
#: front of the model, and tasks where none does.
NEEDS_MEMORY: Final = "needs_memory"
NEEDS_NONE: Final = "needs_none"


def part_of(task: Task) -> str:
    """``NEEDS_MEMORY`` when the task names a gold memory, ``NEEDS_NONE`` otherwise."""
    return NEEDS_MEMORY if task.check.get("gold") else NEEDS_NONE


def score(task: Task, world: RecallWorld) -> Scored:
    """Run one recall task in ``world`` under the overlay that is active."""
    query = str(task.payload.get("query") or "")
    gold: list[Any] = list(task.check.get("gold") or ())
    found = vault_runtime.recall_for(world.vault, query, in_mind=world.in_mind())
    tokens = round(found.chars / _CHARS_PER_TOKEN)
    if not gold:
        if found.chosen:
            return Scored(0.0, tokens, f"showed {len(found.chosen)} memories to a message without")
        return Scored(1.0, tokens)
    order = {memory.id: place for place, memory in enumerate(found.chosen)}

    def place(name: Any) -> int | None:
        """Where the model meets a memory: -1 always in mind, else its line, ``None`` not at all."""
        memory_id = world.id_of(str(name))
        return -1 if memory_id in found.in_mind else order.get(memory_id)

    stale = [p for p in (place(name) for name in task.check.get("stale") or ()) if p is not None]
    total = 0.0
    notes: list[str] = []
    for name in gold:
        at = place(name)
        if at is None:
            notes.append(f"missing: {name}")
        elif any(other < at for other in stale):
            total += 0.5
            notes.append(f"behind an outdated memory: {name}")
        else:
            total += 1.0
    return Scored(total / len(gold), tokens, "; ".join(notes))
