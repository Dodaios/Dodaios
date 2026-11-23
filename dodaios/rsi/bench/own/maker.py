"""Makes the installation's own recall tasks, a few model calls per night.

Each night, on the night's copy of the memory:

1. **forgetting first.** Every own task that names a memory which is no longer
   current (forgotten, replaced, ended) is retired and its text erased.
2. **questions** for memories that have none yet (:mod:`questions`).
3. **messages**: real messages that were not looked at before, labelled twice
   (:mod:`messages`).

``ask`` is the only way out of the machine: ``(system, prompt) -> text`` on
the assistant's own provider, or ``None`` when no subscription or local model
can answer. Then nothing more is made that night, and the next one tries
again.

What a night may ask is counted: at most ``max_calls`` calls, however many
memories and messages wait. So the cost of a night is bounded by a number in
the kernel, not by how much there is to do.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from dodaios.memory.vault import runtime as vault_runtime
from dodaios.memory.vault.models import Memory
from dodaios.memory.vault.store import MemoryVault
from dodaios.rsi.bench.model import Domain, Source, Task
from dodaios.rsi.bench.store import BenchStore

from . import chat, messages, questions
from .world import LIVE_WORLD, LiveWorld

__all__ = ["Ask", "OwnRecallMaker"]

log = logging.getLogger(__name__)

#: ``(system, prompt) -> the model's text``, or ``None`` when nobody may be asked.
Ask = Callable[[str, str], str | None]

_STATE_KEY: Final = "own:recall"
#: Real messages used as examples of how the person writes.
_STYLE_EXAMPLES: Final[int] = 5
#: Message keys remembered as looked at (the newest are kept).
_SEEN_CAP: Final[int] = 5000
#: Kinds a question is written for. Ephemeral ones end by themselves.
_KINDS: Final[frozenset[str]] = frozenset(
    {"profile", "preference", "relationship", "project", "procedural", "episode", "reference"}
)


class _Budget:
    """Counts the night's model calls and notices when nobody answers."""

    def __init__(self, ask: Ask, limit: int) -> None:
        self._ask = ask
        self.limit = limit
        self.calls = 0
        #: True once a call came back empty-handed: no seat, or the model failed.
        self.deferred = False

    def can(self, calls: int = 1) -> bool:
        return not self.deferred and self.calls + calls <= self.limit

    def ask(self, system: str, prompt: str) -> str | None:
        self.calls += 1
        try:
            answer = self._ask(system, prompt)
        except Exception:  # noqa: BLE001 — a model that fails made nothing; the night goes on
            log.info("own tasks: the model call failed", exc_info=True)
            answer = None
        if answer is None:
            self.deferred = True
        return answer


class OwnRecallMaker:
    def __init__(self, bench: BenchStore, world: LiveWorld, chat_db: Path, ask: Ask) -> None:
        self._bench = bench
        self._world = world
        self._chat_db = Path(chat_db)
        self._ask = ask

    # ---------------------------------------------------------------- state

    def _state(self) -> dict[str, Any]:
        found = self._bench.get_meta(_STATE_KEY)
        return {
            "asked_memories": list(found.get("asked_memories") or []),
            "seen_messages": list(found.get("seen_messages") or []),
        }

    def _save(self, state: dict[str, Any]) -> None:
        state["seen_messages"] = state["seen_messages"][-_SEEN_CAP:]
        self._bench.set_meta(_STATE_KEY, state)

    def _own_tasks(self) -> list[Task]:
        return [
            task
            for task in self._bench.tasks(Domain.RECALL, source=Source.MADE)
            if task.payload.get("world") == LIVE_WORLD
        ]

    # ---------------------------------------------------------------- steps

    def _forget(self, current: set[str]) -> int:
        """Retire and erase the tasks whose memories are gone."""
        gone = [
            task.id
            for task in self._own_tasks()
            if any(str(memory_id) not in current for memory_id in task.check.get("gold") or ())
        ]
        if gone:
            self._bench.scrub(gone)
        return len(gone)

    def _questions(
        self, memories: list[Memory], texts: list[str], state: dict[str, Any], budget: _Budget
    ) -> int | None:
        """Ask for one batch. ``None``: every memory was asked about already."""
        asked = set(state["asked_memories"])
        waiting = [
            m
            for m in memories
            if m.id not in asked and m.kind in _KINDS and m.sensitivity != "sensitive"
        ]
        if not waiting:
            return None
        batch = waiting[: questions.BATCH]
        style = [t for t in texts if len(t.split()) <= 25][-_STYLE_EXAMPLES:]
        answer = budget.ask(questions.SYSTEM, questions.build_prompt(batch, style))
        if answer is None:
            return 0  # not asked: these memories wait for the next night
        made = questions.tasks_from(questions.parse(answer), batch)
        self._bench.put_tasks(made)
        state["asked_memories"] += [m.id for m in batch]
        return len(made)

    def _messages(
        self,
        vault: MemoryVault,
        texts: list[str],
        in_mind: frozenset[str],
        state: dict[str, Any],
        budget: _Budget,
    ) -> int | None:
        """Label one batch of real messages. ``None``: every message was looked at already."""
        seen = set(state["seen_messages"])
        batch: list[messages.Candidate] = []
        for text in reversed(texts):  # the newest first: how the person writes now
            key = messages.key_of(text)
            if key in seen or not messages.usable(text):
                continue
            seen.add(key)
            found = messages.candidates_for(vault, text, in_mind)
            batch.append(messages.Candidate(key, text, found))
            if len(batch) >= messages.BATCH:
                break
        if not batch:
            return None
        # A message nothing was found for needs no asking: no stored memory could be needed.
        open_ones = [c for c in batch if c.memories]
        labels: dict[str, frozenset[str]] = {c.key: frozenset() for c in batch if not c.memories}
        if open_ones:
            if not budget.can(2):
                return 0
            first = budget.ask(messages.SYSTEM, messages.build_prompt(open_ones))
            second = None
            if first is not None:
                second = budget.ask(messages.SYSTEM, messages.build_prompt(open_ones, flip=True))
            if first is None or second is None:
                return 0  # not labelled: these messages wait for the next night
            labels.update(
                messages.agreed(
                    messages.parse(first, open_ones),
                    messages.parse(second, open_ones, flip=True),
                )
            )
        made = [messages.task_from(c, labels[c.key]) for c in batch if c.key in labels]
        self._bench.put_tasks(made)
        state["seen_messages"] += [c.key for c in batch]
        return len(made)

    # ------------------------------------------------------------------ run

    def run(self, max_calls: int) -> dict[str, Any]:
        """One night's making. Never raises for a model that does not answer."""
        report: dict[str, Any] = {
            "forgotten": 0,
            "questions": 0,
            "messages": 0,
            "calls": 0,
            "deferred": False,
        }
        vault = self._world.vault
        if vault is None or self._bench.readonly:
            return report
        memories = vault.list()
        report["forgotten"] = self._forget({m.id for m in memories})
        texts = chat.person_messages(self._chat_db)
        in_mind = vault_runtime.in_mind_ids(vault)
        state = self._state()
        budget = _Budget(self._ask, max_calls)
        more_questions = more_messages = True
        # One call of every night goes to questions while memories wait for one, so both
        # kinds grow from the first night on.
        if budget.can(1):
            first = self._questions(memories, texts, state, budget)
            more_questions = first is not None
            report["questions"] += first or 0
        try:
            # Real messages first: they are the kind of task that tells changes apart.
            while more_messages and budget.can(2):
                made = self._messages(vault, texts, in_mind, state, budget)
                more_messages = made is not None
                report["messages"] += made or 0
            while more_questions and budget.can(1):
                made = self._questions(memories, texts, state, budget)
                more_questions = made is not None
                report["questions"] += made or 0
        finally:
            self._save(state)
        report["calls"] = budget.calls
        report["deferred"] = budget.deferred
        return report
