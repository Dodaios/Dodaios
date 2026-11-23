"""The shapes of the benchmark: a task, its split, and the result of one run.

**Task.** One thing to do, with the check that says whether it was done. A
task has a *group*: tasks that came from the same piece of the person's work
(a request and its repeat, a memory and the questions about it) share one, and
a group is the unit that is put into a split. So nothing learned from one task
can leak into the check of its sibling.

**Split.** Every group falls into exactly one of four, by a hash of its key.
The draw is fixed in this file: no update and no learner ever re-draws it. The
domain is not part of the draw, so the tasks of one piece of work stay together
even when they measure different things (the brief and the coding task of one
pull request).

==========  =====================================================  ==========
split       used for                                               who reads
==========  =====================================================  ==========
practice    learners look at these and try candidates on them      learners
select      the gate decides on these whether a candidate goes in  the gate
guard       decides whether a change that is live stays            the gate
sealed      only reported: the number the person sees              the report
==========  =====================================================  ==========

**Result.** The score of one task under one state of the assistant (the
*arm*, a fingerprint id). ``void`` names why a result does not count (the seat
changed in the middle, the run timed out); a void result is kept and ignored.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

__all__ = [
    "LEARNER_SPLITS",
    "SPLIT_SHARES",
    "Domain",
    "Result",
    "Source",
    "Split",
    "Task",
    "split_of",
    "task_id",
]


class Domain(StrEnum):
    """What a task measures."""

    RECALL = "recall"  # the right memory is among the first hits
    SKILL = "skill"  # the right skill is picked, or none
    FIRST_MOVE = "first_move"  # the lead's first tool call for a request
    ACTION = "action"  # a whole assistant turn, up to the committing call
    ANSWER = "answer"  # an open answer, judged by a jury
    BRIEF = "brief"  # the brief a coding agent would get
    CODING = "coding"  # a coding run, checked by the tests that were merged


class Split(StrEnum):
    PRACTICE = "practice"
    SELECT = "select"
    GUARD = "guard"
    SEALED = "sealed"


class Source(StrEnum):
    SEED = "seed"  # shipped with the app
    MINED = "mined"  # built from the person's own past work
    MADE = "made"  # written by a task maker and validated


#: The only split a learner may read.
LEARNER_SPLITS: Final[frozenset[Split]] = frozenset({Split.PRACTICE})

#: Share of the groups in each split, in percent. Fixed: changing it would move
#: tasks between splits and show sealed tasks to the learners.
SPLIT_SHARES: Final[tuple[tuple[Split, int], ...]] = (
    (Split.PRACTICE, 40),
    (Split.SELECT, 25),
    (Split.GUARD, 15),
    (Split.SEALED, 20),
)
_SPLIT_SALT: Final = "dodaios-bench-split-v1"


def split_of(domain: Domain, group: str) -> Split:
    """The split of a group. Stable for ever: the same group always lands in the same one.

    ``domain`` says whose task is asked about and does not change the answer. Were it
    part of the draw, a learner could practise on one task of a piece of work and be
    graded on its sibling in another domain.
    """
    digest = hashlib.sha256(f"{_SPLIT_SALT}|{group}".encode()).digest()
    bucket = int.from_bytes(digest[:8], "big") % 100
    upper = 0
    for split, share in SPLIT_SHARES:
        upper += share
        if bucket < upper:
            return split
    return Split.SEALED  # unreachable while the shares sum to 100


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def task_id(domain: Domain, source: Source, key: str) -> str:
    """A stable id from where a task came from (not from its content, which may be corrected)."""
    digest = hashlib.sha256(f"{domain.value}|{source.value}|{key}".encode()).hexdigest()[:14]
    return f"{domain.value}-{digest}"


def _frozen(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


@dataclass(frozen=True, slots=True)
class Task:
    """One thing to do and how its result is checked."""

    id: str
    domain: Domain
    source: Source
    #: Key of the piece of work this task came from; the unit of the split.
    group: str
    #: What the assistant is given (a request, a query, a repository state).
    payload: Mapping[str, Any] = field(default_factory=dict)
    #: What a right result looks like. Never shown to what is being measured.
    check: Mapping[str, Any] = field(default_factory=dict)
    created_ms: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", _frozen(self.payload))
        object.__setattr__(self, "check", _frozen(self.check))

    @property
    def split(self) -> Split:
        return split_of(self.domain, self.group)

    @property
    def digest(self) -> str:
        """A hash of the content. A result belongs to the content it was measured on."""
        text = _canonical({"d": self.domain.value, "p": dict(self.payload), "c": dict(self.check)})
        return hashlib.sha256(text.encode()).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class Result:
    """The outcome of one task under one arm."""

    task_id: str
    task_digest: str
    #: Fingerprint id of the state the assistant ran in (:mod:`dodaios.rsi.fingerprint`).
    arm: str
    #: 0.0 to 1.0. Checks that only pass or fail give 0.0 or 1.0.
    score: float
    cost_usd: float = 0.0
    tokens: int = 0
    wall_ms: int = 0
    #: The model seat that ran it ("" for checks that need no model).
    seat: str = ""
    #: Why the result does not count; "" when it does.
    void: str = ""
    detail: str = ""
    ts_ms: int = 0

    def __post_init__(self) -> None:
        if not 0.0 <= float(self.score) <= 1.0:
            raise ValueError(f"a score is between 0 and 1, not {self.score!r}")

    @property
    def counts(self) -> bool:
        return not self.void
