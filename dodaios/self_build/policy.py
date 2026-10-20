"""The hard limits of the self-building loop, decided in Python.

Nothing here asks a model. Every builder calls :func:`admit` before it opens a
build and :func:`settle` when a trial ends, so the autonomy level per kind, the
silent first days, the kill switch and the caps hold no matter what a prompt
says (docs/self-build.md, "Rules enforced in code").
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from .ledger import BuildLedger, now_ms
from .records import BuildRecord, Kind, Outcome, State

_DAY_MS: Final[int] = 86_400_000

#: Meta keys in ``self_build.db``.
META_PAUSED: Final[str] = "paused"
META_FIRST_SEEN: Final[str] = "first_seen_ms"


class Autonomy(StrEnum):
    #: Nothing of this kind is built or proposed.
    OFF = "off"
    #: A card the person accepts or rejects; nothing exists before that.
    SUGGEST = "suggest"
    #: Built, proven and live on trial with one-click undo.
    TRIAL = "trial"
    #: As trial, and the trial ends by measure without a card.
    FULL = "full"


def section(config: Any) -> Any:
    """The ``[self_build]`` section, or ``None`` on a bare config."""
    return getattr(config, "self_build", None)


def autonomy(config: Any, kind: Kind) -> Autonomy:
    cfg = section(config)
    if cfg is None or not cfg.enabled:
        return Autonomy.OFF
    value = {
        Kind.MEMORY: cfg.memory,
        Kind.SKILL: cfg.skill,
        Kind.ROUTINE: cfg.routine,
        Kind.AGENT: cfg.agent,
        Kind.CODE: cfg.code,
    }[Kind(kind)]
    try:
        return Autonomy(str(value))
    except ValueError:  # an unknown level falls back to the safe one: suggest
        return Autonomy.SUGGEST


def paused(ledger: BuildLedger) -> bool:
    """The kill switch: on, nothing is observed, built or settled."""
    return ledger.get_meta(META_PAUSED) == "1"


def set_paused(ledger: BuildLedger, value: bool) -> None:
    ledger.set_meta(META_PAUSED, "1" if value else "0")


def first_seen_ms(ledger: BuildLedger, *, now: int | None = None) -> int:
    raw = ledger.get_meta(META_FIRST_SEEN)
    if raw.isdigit():
        return int(raw)
    stamp = now if now is not None else now_ms()
    ledger.set_meta(META_FIRST_SEEN, str(stamp))
    return stamp


def silent(ledger: BuildLedger, config: Any, *, now: int | None = None) -> bool:
    """The first days after the loop first ran: cases are recorded, nothing is built."""
    cfg = section(config)
    days = int(getattr(cfg, "silent_days", 0) or 0) if cfg is not None else 0
    if days <= 0:
        return False
    stamp = now if now is not None else now_ms()
    return stamp - first_seen_ms(ledger, now=stamp) < days * _DAY_MS


@dataclass(frozen=True, slots=True)
class Admission:
    #: The state the build may open in; ``None`` = do not open it at all.
    start: State | None
    reason: str

    @property
    def build(self) -> bool:
        return self.start == State.BUILDING


def admit(
    ledger: BuildLedger,
    config: Any,
    kind: Kind,
    signature: str,
    *,
    undoable: bool,
    now: int | None = None,
) -> Admission:
    """May a build of ``kind`` for ``signature`` be opened, and how far may it go?

    ``undoable`` is whether an undoer is registered for the kind: a build that
    could not be undone is never made (rule 5).
    """
    kind = Kind(kind)
    stamp = now if now is not None else now_ms()
    cfg = section(config)
    level = autonomy(config, kind)
    if cfg is None or level == Autonomy.OFF:
        return Admission(None, "off")
    if paused(ledger):
        return Admission(None, "paused")
    if ledger.open_for(signature) is not None:
        return Admission(None, "already open")
    if ledger.rejections(signature) >= cfg.max_rejections:
        return Admission(None, "rejected before")
    if level == Autonomy.SUGGEST or silent(ledger, config, now=stamp):
        reason = "suggest" if level == Autonomy.SUGGEST else "silent"
        if ledger.count_in([State.PROPOSED]) >= cfg.max_open_trials * 2:
            return Admission(None, "too many open proposals")
        return Admission(State.PROPOSED, reason)
    if not undoable:
        return Admission(State.PROPOSED, "no undo for this kind")
    if ledger.count_since(stamp - _DAY_MS, built_only=True) >= cfg.max_builds_per_day:
        return Admission(State.PROPOSED, "daily build cap")
    if ledger.count_in([State.TRIAL]) >= cfg.max_open_trials:
        return Admission(State.PROPOSED, "trial cap")
    if (
        kind == Kind.AGENT
        and ledger.count_since(stamp - 7 * _DAY_MS, kind=Kind.AGENT, built_only=True)
        >= cfg.max_agents_per_week
    ):
        return Admission(State.PROPOSED, "weekly agent cap")
    if (
        kind == Kind.CODE
        and ledger.count_since(stamp - _DAY_MS, kind=Kind.CODE, built_only=True)
        >= cfg.max_code_runs_per_day
    ):
        return Admission(State.PROPOSED, "daily code cap")
    return Admission(State.BUILDING, level.value)


def trial_over(record: BuildRecord, config: Any, *, now: int | None = None) -> bool:
    """Has a build on trial run long enough, or been used enough, to be judged?"""
    if record.state != State.TRIAL or not record.trial_started_ms:
        return False
    cfg = section(config)
    if cfg is None:
        return False
    stamp = now if now is not None else now_ms()
    return (
        stamp - record.trial_started_ms >= cfg.trial_days * _DAY_MS
        or record.uses >= cfg.trial_uses
    )


def settle(record: BuildRecord) -> State:
    """Keep or archive a build whose trial is over, from what it did.

    Kept when it was used at least twice and more of its uses were accepted
    as they were than corrected. Archived (never deleted) otherwise.
    """
    corrected = record.outcomes.get(Outcome.CORRECTED.value, 0)
    accepted = record.outcomes.get(Outcome.ACCEPTED.value, 0) + record.outcomes.get(
        Outcome.USED.value, 0
    )
    if record.uses >= 2 and accepted > corrected:
        return State.KEPT
    return State.ARCHIVED
