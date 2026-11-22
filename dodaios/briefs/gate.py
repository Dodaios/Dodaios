"""One pass for every brief: look up, check, send back once, then let it go.

Every writer of a brief (the lead, the live voice model, the voice composer, a
society agent) hands its order here before anything is created or sent. The
pass gathers the kit for the order (``dodaios.briefs.kit``), checks the brief
(``dodaios.briefs.lint``) and decides:

* nothing to revise: the brief goes out;
* something to revise, and this is the writer's first attempt: the brief is
  sent back with the findings and the kit, and nothing has been started;
* the writer's second attempt: the brief goes out as it is, whatever the check
  still finds. A hand-off is delayed by one revision at most and never
  refused: the person's work must not hang on a check.

A second attempt is recognised without the writer's help: it is the next brief
from the same conversation, for the same kind of recipient in the same folder,
shortly after one was sent back. How much of its wording it shares with the
first attempt does not matter (a good revision shares little); with several
briefs waiting, the one it shares most with is taken. A brief that arrives
within seconds of one being sent back is another order of the same batch and
is checked on its own. That lets one unrelated
brief through unchecked when a writer gave up on a brief that was sent back,
which is the price of never sending the same order back twice. Remembered in
the process only; after a restart the next brief counts as a first attempt.

``mode`` is ``[briefs] check``: ``revise`` (the default) as above, ``note``
checks and records but never sends back, ``off`` skips the look-up and the
check.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Final

from dodaios.briefs import done, lint
from dodaios.briefs import kit as kit_module
from dodaios.briefs import log as log_module
from dodaios.briefs.model import SEVERITY_REVISE, Finding, Order
from dodaios.briefs.profiles import Profile, profile_for

__all__ = [
    "MODE_NOTE",
    "MODE_OFF",
    "MODE_REVISE",
    "MODES",
    "Decision",
    "Ticket",
    "forget_pending",
    "prepare",
    "review",
]

log = logging.getLogger(__name__)

MODE_REVISE: Final[str] = "revise"
MODE_NOTE: Final[str] = "note"
MODE_OFF: Final[str] = "off"
MODES: Final[tuple[str, ...]] = (MODE_REVISE, MODE_NOTE, MODE_OFF)

#: How long a brief that was sent back waits for its revision.
_PENDING_TTL_S: Final[float] = 10 * 60.0
#: A revision is written after the writer read why its brief came back, which
#: takes a model seconds. A brief that arrives sooner is another order of the
#: same batch (two agents briefed at once), not a revision.
_REVISION_MIN_AGE_S: float = 3.0
_WORD = re.compile(r"[^\W_]{3,}", re.UNICODE)

SENT_BACK_REASON: Final[str] = (
    "The brief was not sent: nothing was created and no agent was started. Fix the points "
    "under 'fix' with the facts under 'brief_kit', then make the same call again with the "
    "revised brief. A revised brief is sent as it is."
)


@dataclass(frozen=True, slots=True)
class Ticket:
    """What travels with a brief that was let through, to its delivery and its end."""

    brief_id: str
    kind: str = ""
    writer: str = ""
    criteria: tuple[done.Criterion, ...] = ()

    def meta(self) -> dict[str, Any]:
        """The part kept in the job's own record."""
        return {
            "brief_id": self.brief_id,
            "kind": self.kind,
            "criteria": [criterion.as_dict() for criterion in self.criteria],
        }

    @classmethod
    def from_meta(cls, meta: Any) -> Ticket | None:
        """A ticket read back from a job's record (after a restart); ``None`` without one."""
        if not isinstance(meta, dict) or not meta.get("brief_id"):
            return None
        criteria = tuple(
            done.Criterion(
                str(row.get("text") or ""), str(row.get("kind") or done.KIND_OTHER),
                str(row.get("target") or ""),
            )
            for row in meta.get("criteria") or []
            if isinstance(row, dict) and row.get("text")
        )
        return cls(brief_id=str(meta["brief_id"]), kind=str(meta.get("kind") or ""),
                   criteria=criteria)


@dataclass(slots=True)
class Decision:
    """The outcome of one pass."""

    send: bool
    brief_id: str
    order: Order
    kit: kit_module.Kit
    findings: list[Finding] = field(default_factory=list)
    #: This brief is the writer's revision of one that was sent back.
    revised: bool = False
    mode: str = MODE_REVISE

    @property
    def kind(self) -> str:
        return self.kit.kind

    def to_fix(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == SEVERITY_REVISE]

    def ticket(self) -> Ticket:
        draft = self.order.draft
        return Ticket(
            brief_id=self.brief_id,
            kind=self.kind,
            writer=self.order.writer,
            criteria=tuple(done.criteria_of(f"{draft.task}\n\n{draft.context}", draft.criteria)),
        )

    def reply(self) -> dict[str, Any]:
        """The tool result for a brief that is sent back."""
        fix = [f.as_dict() for f in self.to_fix()]
        noted = [f.as_dict() for f in self.findings if f.severity != SEVERITY_REVISE]
        return {
            "status": "needs_revision",
            "success": False,
            "input_written": False,
            "reason": SENT_BACK_REASON,
            "fix": fix,
            **({"also_noted": noted} if noted else {}),
            "brief_kit": self.kit.as_dict(),
        }

    def remarks(self) -> list[dict[str, str]]:
        """What the check still found in a brief that was sent, for its receipt."""
        return [f.as_dict() for f in self.findings]


@dataclass(slots=True)
class _Pending:
    brief_id: str
    words: frozenset[str]
    at: float


_LOCK = threading.Lock()
_PENDING: dict[tuple[str, str, str], list[_Pending]] = {}
_PREPARED: dict[tuple[str, str, str], float] = {}
#: Briefs that were let through, by writer, conversation, folder and text: a
#: repeated call with the same brief is the same order, not a new one to check.
_PASSED: dict[tuple[str, str, str, str], tuple[Decision, float]] = {}


def _key(order: Order) -> tuple[str, str, str]:
    recipient = order.recipient
    return (order.writer, order.writer_session, f"{recipient.kind}:{recipient.folder}")


def _words(text: str) -> frozenset[str]:
    return frozenset(word.casefold() for word in _WORD.findall(text or ""))


def _overlap(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _take_pending(order: Order, words: frozenset[str]) -> _Pending | None:
    """The brief this one revises, removed from the waiting list; ``None`` for a new order."""
    now = time.monotonic()
    with _LOCK:
        waiting = [p for p in _PENDING.get(_key(order), []) if now - p.at < _PENDING_TTL_S]
        ripe = [p for p in waiting if now - p.at >= _REVISION_MIN_AGE_S]
        match = max(ripe, key=lambda p: _overlap(p.words, words), default=None)
        if match is not None:
            waiting.remove(match)
        if waiting:
            _PENDING[_key(order)] = waiting
        else:
            _PENDING.pop(_key(order), None)
    return match


def _was_prepared(order: Order) -> bool:
    with _LOCK:
        at = _PREPARED.pop(_key(order), None)
    return at is not None and time.monotonic() - at < _PENDING_TTL_S


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _passed_before(order: Order, text: str) -> Decision | None:
    """The decision this very brief already got from this writer for this folder."""
    now = time.monotonic()
    with _LOCK:
        found = _PASSED.get((*_key(order), _digest(text)))
        for key in [k for k, (_, at) in _PASSED.items() if now - at >= _PENDING_TTL_S]:
            del _PASSED[key]
    if found is None or now - found[1] >= _PENDING_TTL_S:
        return None
    return found[0]


def _remember_passed(order: Order, text: str, decision: Decision) -> None:
    with _LOCK:
        _PASSED[(*_key(order), _digest(text))] = (decision, time.monotonic())


def forget_pending() -> None:
    """Drop every brief that waits for its revision or was let through (tests)."""
    with _LOCK:
        _PENDING.clear()
        _PREPARED.clear()
        _PASSED.clear()


def _record(decision: Decision, *, sent_back: bool, prepared: bool) -> None:
    store = log_module.get_log()
    if store is None:
        return
    order, kit = decision.order, decision.kit
    try:
        repo = ""
        if order.recipient.folder:
            from dodaios.rsi.repo_identity import repo_id

            repo = repo_id(order.recipient.folder)
        store.note_attempt(
            decision.brief_id,
            writer=order.writer,
            writer_session=order.writer_session,
            target_kind=order.recipient.kind,
            folder=order.recipient.folder,
            repo_id=repo,
            kind=kit.kind,
            lenses=[lens.key for lens in kit.lenses],
            person_words=order.person_words,
            draft=order.draft.text(),
            findings=[f.as_dict() for f in decision.findings],
            criteria=[c.as_dict() for c in decision.ticket().criteria],
            gaps=[gap.key for gap in kit.gaps],
            sent_back=sent_back,
            prepared=prepared,
        )
    except Exception:  # noqa: BLE001 - the record never holds a hand-off back
        log.warning("brief gate: the order could not be recorded", exc_info=True)


def review(
    order: Order,
    *,
    profiles: Sequence[Profile] = (),
    mode: str = MODE_REVISE,
    auto_effort: bool = True,
    standing: bool = True,
    record: bool = True,
    read_repository: bool = True,
    abandoned: threading.Event | None = None,
) -> Decision:
    """Look up, check and decide for one order. Blocking: run it off the event loop.

    ``profiles`` are the model families that will receive the brief (the
    order's own recipient when empty) and ``standing`` says the recipient has
    the standing rules. ``read_repository=False`` is for a writer on a spoken
    turn's clock: the brief is checked on its wording alone, without the file
    look-up. ``abandoned`` is set by a caller that stopped waiting for this
    pass: its result is then nobody's, so it leaves no record and no brief
    waiting for a revision. Never raises: a fault in the look-up or the check
    lets the brief through.
    """
    mode = mode if mode in MODES else MODE_REVISE
    families = list(profiles) or [profile_for(order.recipient.cli, order.recipient.model)]
    text = order.draft.text()
    passed = _passed_before(order, text)
    if passed is not None:
        # The same brief again (a retry after a timeout): the answer it got stands.
        return passed
    words = _words(text)
    try:
        # Without a folder the kit reads nothing from disk: only the recipient's
        # profile and the effort are worked out.
        lean = replace(order, recipient=replace(order.recipient, folder=""))
        source = order if read_repository and mode != MODE_OFF else lean
        gathered = kit_module.build(source, profiles=families, auto_effort=auto_effort)
        findings: list[Finding] = []
        if mode != MODE_OFF:
            findings = lint.check(
                order,
                facts=gathered.facts if read_repository else None,
                profiles=families,
                standing=standing,
            )
    except Exception:  # noqa: BLE001 - a broken check must not cost the person their hand-off
        log.warning("brief gate: check failed, the brief goes out unchecked", exc_info=True)
        gathered = kit_module.Kit(kind=lint.kind_of(order), profiles=families)
        findings = []
    if abandoned is not None and abandoned.is_set():
        # Nobody waits for this pass any more: it takes no revision off the
        # waiting list and leaves no record.
        return Decision(
            send=True, brief_id=log_module.new_brief_id(), order=order, kit=gathered,
            findings=findings, mode=mode,
        )
    # Only now, with the answer in hand, is this brief matched to one that waits.
    pending = _take_pending(order, words) if mode == MODE_REVISE else None
    brief_id = pending.brief_id if pending is not None else log_module.new_brief_id()
    decision = Decision(
        send=True,
        brief_id=brief_id,
        order=order,
        kit=gathered,
        findings=findings,
        revised=pending is not None,
        mode=mode,
    )
    prepared = _was_prepared(order)
    if mode == MODE_REVISE and pending is None and decision.to_fix():
        decision.send = False
        with _LOCK:
            _PENDING.setdefault(_key(order), []).append(
                _Pending(brief_id=brief_id, words=words, at=time.monotonic())
            )
    if record:
        _record(decision, sent_back=not decision.send, prepared=prepared)
    if decision.send:
        _remember_passed(order, text, decision)
    return decision


def prepare(
    order: Order, *, profiles: Sequence[Profile] = (), auto_effort: bool = True
) -> dict[str, Any]:
    """The kit for a request, before its brief is written. Blocking.

    ``order.draft.task`` holds what the person wants in the writer's words;
    nothing is checked and nothing is sent.
    """
    families = list(profiles) or [profile_for(order.recipient.cli, order.recipient.model)]
    try:
        gathered = kit_module.build(
            order, profiles=families, auto_effort=auto_effort, with_draft=False
        )
    except Exception:  # noqa: BLE001 - without a kit the writer briefs as before
        log.warning("brief gate: the kit could not be gathered", exc_info=True)
        gathered = kit_module.Kit(kind=lint.kind_of(order), profiles=families)
    with _LOCK:
        _PREPARED[_key(order)] = time.monotonic()
    return {
        "status": "prepared",
        "nothing_sent": True,
        "brief_kit": gathered.as_dict(),
        "next": "Write the brief from these facts and make the call again without "
                "options.prepare.",
    }
