"""What one self-built thing is, and the states it may move through.

A *build* is anything Dodaios made on its own initiative: a memory entry, a
skill, a routine, a specialised agent or a code change in one of the person's
projects. Every build has one :class:`BuildRecord` in the ledger, so the
person can always see why it exists, how it was checked, what it cost and how
to undo it (docs/self-build.md).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final


class Kind(StrEnum):
    """The artefact ladder, cheapest first."""

    MEMORY = "memory"
    SKILL = "skill"
    ROUTINE = "routine"
    AGENT = "agent"
    CODE = "code"


class State(StrEnum):
    #: A build case was written; nothing exists yet. With autonomy ``suggest``
    #: this is the card the person accepts or rejects.
    PROPOSED = "proposed"
    BUILDING = "building"
    PROVING = "proving"
    #: Live, labelled, undoable; value is being measured.
    TRIAL = "trial"
    KEPT = "kept"
    ARCHIVED = "archived"
    UNDONE = "undone"
    REJECTED = "rejected"
    FAILED = "failed"


class Outcome(StrEnum):
    """What happened when a build was used."""

    USED = "used"
    ACCEPTED = "accepted"
    CORRECTED = "corrected"
    IGNORED = "ignored"


#: States a build can still leave.
OPEN_STATES: Final[frozenset[State]] = frozenset(
    {State.PROPOSED, State.BUILDING, State.PROVING, State.TRIAL}
)
#: States in which an artefact exists and an undo has something to remove.
LIVE_STATES: Final[frozenset[State]] = frozenset({State.TRIAL, State.KEPT})

_ALLOWED: Final[dict[State, frozenset[State]]] = {
    State.PROPOSED: frozenset({State.BUILDING, State.REJECTED, State.FAILED}),
    State.BUILDING: frozenset({State.PROVING, State.TRIAL, State.FAILED, State.UNDONE}),
    State.PROVING: frozenset({State.TRIAL, State.FAILED, State.UNDONE}),
    State.TRIAL: frozenset({State.KEPT, State.ARCHIVED, State.UNDONE, State.FAILED}),
    State.KEPT: frozenset({State.ARCHIVED, State.UNDONE}),
    State.ARCHIVED: frozenset({State.KEPT, State.UNDONE}),
    State.UNDONE: frozenset(),
    State.REJECTED: frozenset(),
    State.FAILED: frozenset(),
}


def can_move(src: State, dst: State) -> bool:
    return dst in _ALLOWED[src]


class TransitionError(ValueError):
    """A state change the lifecycle does not allow."""


@dataclass(frozen=True, slots=True)
class BuildRecord:
    id: str
    kind: Kind
    state: State
    #: Stable key of the need this build answers; one open build per signature.
    signature: str
    #: One sentence the person reads: why this build exists.
    title: str
    #: The build case: need, expected value, expected cost, how it is checked.
    case: str = ""
    #: References to the person's own turns or actions that justify the build.
    evidence: tuple[str, ...] = ()
    #: Verdict of the judge (``{"passed": bool, "judge": str, "detail": str}``).
    proof: dict[str, Any] = field(default_factory=dict)
    #: What was created (``{"type": "skill", "id": "..."}``), empty before that.
    artefact: dict[str, Any] = field(default_factory=dict)
    #: Kind-specific data the registered undoer needs.
    undo: dict[str, Any] = field(default_factory=dict)
    uses: int = 0
    outcomes: dict[str, int] = field(default_factory=dict)
    note: str = ""
    created_ms: int = 0
    updated_ms: int = 0
    trial_started_ms: int = 0
    last_used_ms: int = 0

    @property
    def open(self) -> bool:
        return self.state in OPEN_STATES

    @property
    def caller(self) -> str:
        """The cost-ledger caller tag every model call for this build carries."""
        return caller_for(self.id)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "state": self.state.value,
            "signature": self.signature,
            "title": self.title,
            "case": self.case,
            "evidence": list(self.evidence),
            "proof": dict(self.proof),
            "artefact": dict(self.artefact),
            "uses": self.uses,
            "outcomes": dict(self.outcomes),
            "note": self.note,
            "created_ms": self.created_ms,
            "updated_ms": self.updated_ms,
            "trial_started_ms": self.trial_started_ms,
            "last_used_ms": self.last_used_ms,
            "undoable": self.state in LIVE_STATES or self.state in OPEN_STATES,
        }


CALLER_PREFIX: Final[str] = "self_build:"


def caller_for(build_id: str) -> str:
    return f"{CALLER_PREFIX}{build_id}"


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
