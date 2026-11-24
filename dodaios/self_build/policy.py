"""The hard limits of the self-building loop, decided in Python.

Nothing here asks a model, and nothing here asks the person. Every builder
calls :func:`admit` before it opens a build and :func:`settle` when a trial
ends, so the fixed autonomy per kind, the silent first days, the kill switch
and the caps hold no matter what a prompt says (docs/self-build.md, "Rules
enforced in code"). There is no approval step: a build goes live on trial when
it can be undone, and a finished trial is kept or archived from the person's
own use. What stays with the person is the kill switch and undo.
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
    #: Built, proven and live on trial with one-click undo; the trial ends by
    #: measure (:func:`settle`), never by a click.
    FULL = "full"
    #: Nothing new of this kind is opened: no intake, no build. What the loop
    #: already made (an open pull request) is still watched to its end.
    WATCH = "watch"


#: How far each kind goes. Fixed: there is no setting for it. Code changes
#: wait for a measured path of their own; until then the loop only watches
#: the pull requests it already opened (``code/loop.py``).
_AUTONOMY: Final[dict[Kind, Autonomy]] = {
    Kind.MEMORY: Autonomy.FULL,
    Kind.SKILL: Autonomy.FULL,
    Kind.ROUTINE: Autonomy.FULL,
    Kind.AGENT: Autonomy.FULL,
    Kind.CODE: Autonomy.WATCH,
}


def section(config: Any) -> Any:
    """The ``[self_build]`` section, or ``None`` on a bare config."""
    return getattr(config, "self_build", None)


def autonomy(kind: Kind) -> Autonomy:
    """How far a build of ``kind`` may go. ``[self_build]`` has no say in it."""
    return _AUTONOMY[Kind(kind)]


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
    #: ``BUILDING`` when the build may open now; ``None`` = not now (``reason``).
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
    """May a build of ``kind`` for ``signature`` be opened now?

    The answer is ``BUILDING`` or nothing: a build is never opened as a card
    that waits for the person. Every "not now" (paused, the silent first days,
    a cap, no undo for the kind) leaves the need for a later pass.
    ``undoable`` is whether an undoer is registered for the kind: a build that
    could not be undone is never made (rule 5).
    """
    kind = Kind(kind)
    stamp = now if now is not None else now_ms()
    cfg = section(config)
    level = autonomy(kind)
    if cfg is None:
        return Admission(None, "off")
    if level != Autonomy.FULL:
        return Admission(None, level.value)
    if paused(ledger):
        return Admission(None, "paused")
    if ledger.open_for(signature) is not None:
        return Admission(None, "already open")
    if ledger.rejections(signature) >= cfg.max_rejections:
        return Admission(None, "undone before")
    if silent(ledger, config, now=stamp):
        return Admission(None, "silent")
    if not undoable:
        return Admission(None, "no undo for this kind")
    if ledger.count_since(stamp - _DAY_MS, built_only=True) >= cfg.max_builds_per_day:
        return Admission(None, "daily build cap")
    if ledger.count_in([State.TRIAL]) >= cfg.max_open_trials:
        return Admission(None, "trial cap")
    if (
        kind == Kind.AGENT
        and ledger.count_since(stamp - 7 * _DAY_MS, kind=Kind.AGENT, built_only=True)
        >= cfg.max_agents_per_week
    ):
        return Admission(None, "weekly agent cap")
    if (
        kind == Kind.CODE
        and ledger.count_since(stamp - _DAY_MS, kind=Kind.CODE, built_only=True)
        >= cfg.max_code_runs_per_day
    ):
        return Admission(None, "daily code cap")
    return Admission(State.BUILDING, "on trial, kept or archived by use")


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
    as they were than corrected. Archived (never deleted) otherwise. No click
    decides it, for any kind.
    """
    corrected = record.outcomes.get(Outcome.CORRECTED.value, 0)
    accepted = record.outcomes.get(Outcome.ACCEPTED.value, 0) + record.outcomes.get(
        Outcome.USED.value, 0
    )
    if record.uses >= 2 and accepted > corrected:
        return State.KEPT
    return State.ARCHIVED
