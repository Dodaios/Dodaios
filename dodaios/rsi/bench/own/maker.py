"""Makes the installation's own recall tasks, as many model calls as the gate needs.

Each learning round, on the round's copy of the memory:

1. **forgetting first.** Every own task that names a memory which is no longer
   current (forgotten, replaced, ended) is retired and its text erased.
2. **questions** for memories that have none yet (:mod:`questions`).
3. **messages**: real messages that were not looked at before, labelled twice
   (:mod:`messages`).

``ask`` is the only way out of the machine: ``(system, prompt) -> text`` on
the assistant's own provider, or ``None`` when no subscription or local model
can answer. Then nothing more is made that round, and the next one tries
again.

How much is made is the work's to decide: batches go on while ``wants``
names a reason the gate still lacks tasks (``night.tasks_wanted``) and there
is material left, and stop when the gate has enough, when the material is
used up, or when :data:`DRY_BATCHES` batches in a row added no task. What a
round may ask is the kernel's: every batch asks the round's
:class:`~dodaios.rsi.budget.Budget` first (the plan's usage windows, the
person being away, the round's ceiling, or the fixed caps when the windows
cannot be read).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final, NamedTuple

from dodaios.memory.vault import runtime as vault_runtime
from dodaios.memory.vault.models import Memory
from dodaios.memory.vault.store import MemoryVault
from dodaios.rsi.bench.model import Domain, Source, Task
from dodaios.rsi.bench.store import BenchStore
from dodaios.rsi.budget import Budget

from . import chat, messages, questions
from .world import LIVE_WORLD, LiveWorld

__all__ = ["DRY_BATCHES", "Ask", "OwnRecallMaker", "Wants"]

log = logging.getLogger(__name__)

#: ``(system, prompt) -> the model's text``, or ``None`` when nobody may be asked.
Ask = Callable[[str, str], str | None]
#: Why the gate still lacks tasks (``""``: it has enough).
Wants = Callable[[], str]

#: Batches in a row that added no task, after which a round stops building:
#: the model's answers no longer turn the material into tasks.
DRY_BATCHES: Final[int] = 3

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
    """Asks the round's allowance before a batch, counts the calls, notices silence."""

    def __init__(self, ask: Ask, allowance: Budget) -> None:
        self._ask = ask
        self.allowance = allowance
        self.calls = 0
        #: True once a call came back empty-handed: no seat, or the model failed.
        self.deferred = False
        #: The last batch did not fit what is left (a smaller one may).
        self.short = False

    @property
    def open(self) -> bool:
        return not self.deferred and not self.allowance.stopped

    def take(self, calls: int) -> bool:
        """The allowance grants the batch's ``calls`` (they are counted against it)."""
        granted = not self.deferred and self.allowance.take(calls) == ""
        self.short = not granted and self.open
        return granted

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
        if not budget.take(1):
            return 0  # not granted: these memories wait for the next round
        style = [t for t in texts if len(t.split()) <= 25][-_STYLE_EXAMPLES:]
        answer = budget.ask(questions.SYSTEM, questions.build_prompt(batch, style))
        if answer is None:
            return 0  # not asked: these memories wait for the next round
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
            if not budget.take(2):
                return 0
            first = budget.ask(messages.SYSTEM, messages.build_prompt(open_ones))
            second = None
            if first is not None:
                second = budget.ask(messages.SYSTEM, messages.build_prompt(open_ones, flip=True))
            if first is None or second is None:
                return 0  # not labelled: these messages wait for the next round
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

    def run(self, allowance: Budget | int, wants: Wants | None = None) -> dict[str, Any]:
        """One round's making. Never raises for a model that does not answer.

        ``allowance`` is the round's budget (a plain number: that many calls,
        no other rule). ``wants`` says why the gate still lacks tasks; without
        it the round builds until the allowance or the material ends.

        The report says what was made, the calls, and ``until``: why building
        stopped (``enough``, ``material``, ``budget``, ``no_model``, ``dry``).
        """
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
        material = _Material(
            vault,
            memories,
            chat.person_messages(self._chat_db),
            vault_runtime.in_mind_ids(vault),
            self._state(),
        )
        allowance = allowance if isinstance(allowance, Budget) else Budget(allowance)
        want = wants or (lambda: "build until the allowance ends")
        budget = _Budget(self._ask, allowance)
        try:
            more, dry = self._build(material, budget, want, report)
        finally:
            self._save(material.state)
        report["calls"] = budget.calls
        report["deferred"] = budget.deferred
        report["until"] = _until(budget, want, more, dry)
        report["share"] = round(allowance.share, 2)
        report["usage_read"] = allowance.read
        return report

    def _build(
        self, m: _Material, budget: _Budget, want: Wants, report: dict[str, Any]
    ) -> tuple[bool, int]:
        """Batches while the gate wants tasks. Returns (material left, dry batches in a row)."""
        more = {"messages": True, "questions": True}
        dry = 0
        # One batch of every round goes to questions while memories wait for one,
        # so both kinds grow from the first round on.
        if want():
            dry = self._batch("questions", m, budget, report, more, dry)
        # Real messages first: they are the kind of task that tells changes apart.
        while budget.open and any(more.values()) and dry < DRY_BATCHES and want():
            kind = "messages" if more["messages"] else "questions"
            dry = self._batch(kind, m, budget, report, more, dry)
        return any(more.values()), dry

    def _batch(
        self,
        kind: str,
        m: _Material,
        budget: _Budget,
        report: dict[str, Any],
        more: dict[str, bool],
        dry: int,
    ) -> int:
        """One batch of ``kind``. Returns the batches in a row that added no task after it."""
        if kind == "messages":
            made = self._messages(m.vault, m.texts, m.in_mind, m.state, budget)
        else:
            made = self._questions(m.memories, m.texts, m.state, budget)
        # ``None``: nothing of this kind is left. Short: two calls do not fit what is
        # left, so the messages give way to the questions, which take one each.
        more[kind] = made is not None and not budget.short
        report[kind] += made or 0
        if made is None or budget.short:
            return dry
        return dry + 1 if made == 0 and budget.open else 0


class _Material(NamedTuple):
    """What one round builds from: the memory copy, the person's messages, the state."""

    vault: MemoryVault
    memories: list[Memory]
    texts: list[str]
    in_mind: frozenset[str]
    state: dict[str, Any]


def _until(budget: _Budget, want: Wants, more: bool, dry: int) -> str:
    """Why building stopped, as a word the page translates."""
    if budget.deferred:
        return "no_model"
    if budget.allowance.stopped:
        return "budget"
    if dry >= DRY_BATCHES:
        return "dry"
    if not more:
        return "material"
    return "enough" if not want() else "budget"
