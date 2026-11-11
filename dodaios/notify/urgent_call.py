"""Call me for urgent decisions: the one place the assistant may ring the owner.

Dodaios never speaks uncalled. This module is the single, narrow, opt-in
exception, off until the owner switches it on (``NotifySettings.urgent_call``):

* Only an approval or a question that is urgent may ring: the owner's explicit
  mark on it, one of the owner's keywords, or a deadline within the owner's
  window; or a critical watchdog finding. Each kind has its own switch.
* The text channels come first (the desktop notification and the phone chat
  buttons already carry every decision). The call is the escalation, placed
  only when the decision is still open after ``escalate_after_min``.
* Quiet hours and a daily cap hold the call back. Nothing else can ring.
* The desktop route rings the call window (a silent card the owner answers).
  The phone route dials the owner's number through telephony; while the install
  runs on a subscription it only goes ahead when the voice seat is one the
  background policy allows, otherwise the text escalation stands alone.
* The call opens with one short statement of the decision and the exact action
  (the approval card's own preview), takes yes / no / later by voice and settles
  the same card. Hanging up is the owner's kill switch.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from dodaios.core.events import Event
from dodaios.notify.reminders import notification_language, phrase
from dodaios.notify.settings import NotifySettings, UrgentCallSettings, load_settings

log = logging.getLogger(__name__)

#: ``handle()`` outcomes.
OFF: Final[str] = "off"
NOT_URGENT: Final[str] = "not_urgent"
QUIET: Final[str] = "quiet_hours"
CAPPED: Final[str] = "daily_cap"
RESOLVED: Final[str] = "resolved"
TEXT_ONLY: Final[str] = "text_only"
NO_NUMBER: Final[str] = "no_number"
RANG: Final[str] = "rang"
FAILED: Final[str] = "failed"
DUPLICATE: Final[str] = "duplicate"

_SUMMARY_CHARS: Final[int] = 300


@dataclass(frozen=True, slots=True)
class UrgentCallRinging(Event):
    """The desktop call window rings: a decision the owner marked urgent is open."""

    kind: str = ""
    ref_id: str = ""
    session_id: str = ""
    agent: str = ""
    summary: str = ""


@dataclass(frozen=True, slots=True)
class UrgentEvent:
    """One open decision, as the caller sees it."""

    kind: str  # "approval" | "question" | "watchdog"
    ref_id: str
    session_id: str = ""
    summary: str = ""
    agent: str = ""
    tool: str = ""
    #: The owner (or the agent on the owner's rule) marked this one urgent.
    urgent: bool = False
    #: When the decision expires by itself (epoch ms), 0 = no deadline.
    deadline_ms: int = 0
    #: What "yes" means for a question: the recommended answer's label.
    recommended: str = ""
    #: A watchdog finding's severity.
    severity: str = ""

    @property
    def accepts_yes(self) -> bool:
        return self.kind == "approval" or (self.kind == "question" and bool(self.recommended))


def _line(value: Any, limit: int = _SUMMARY_CHARS) -> str:
    return " ".join(str(value or "").split())[:limit]


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):  # an unreadable deadline means none
        return 0


def event_from_chat(session_id: str, event: dict[str, Any]) -> UrgentEvent | None:
    """An open approval or question from a chat event, ``None`` for anything else."""
    kind = event.get("kind")
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    if kind == "approval_required":
        ref = str(payload.get("approval_id") or "")
        if not ref:
            return None
        preview = payload.get("preview") if isinstance(payload.get("preview"), dict) else {}
        said = _line(preview.get("compact") or payload.get("summary") or payload.get("name"))
        return UrgentEvent(
            kind="approval",
            ref_id=ref,
            session_id=session_id,
            summary=said,
            agent=_line(payload.get("agent_name"), 80),
            tool=_line(payload.get("name"), 120),
            urgent=payload.get("urgent") is True,
            deadline_ms=_int(payload.get("deadline_ms") or payload.get("expires_ms")),
        )
    if kind == "question_required":
        ref = str(payload.get("question_id") or "")
        questions = payload.get("questions") if isinstance(payload.get("questions"), list) else []
        if not ref or not questions or not isinstance(questions[0], dict):
            return None
        first = questions[0]
        options = first.get("options") if isinstance(first.get("options"), list) else []
        label = ""
        plain = len(questions) == 1 and not first.get("kind")
        if plain and options and isinstance(options[0], dict):
            label = _line(options[0].get("label"), 120)
        return UrgentEvent(
            kind="question",
            ref_id=ref,
            session_id=session_id,
            summary=_line(first.get("question")),
            agent=_line(payload.get("asker"), 80),
            urgent=payload.get("urgent") is True,
            deadline_ms=_int(payload.get("expires_ms")),
            recommended=label,
        )
    return None


def qualifies(event: UrgentEvent, urgent: UrgentCallSettings, now_ms: int) -> bool:
    """Whether the owner's rules make this event worth a call. Pure."""
    if not urgent.allows_event(event.kind):
        return False
    if event.kind == "watchdog":
        return event.severity == "critical"
    if event.urgent:
        return True
    haystack = f"{event.summary} {event.tool}".lower()
    if any(word in haystack for word in urgent.keywords):
        return True
    if urgent.deadline_min > 0 and event.deadline_ms > 0:
        return 0 < event.deadline_ms - now_ms <= urgent.deadline_min * 60_000
    return False


class CallLedger:
    """How many calls rang today (local date); survives a restart when given a path."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._memory: dict[str, int] = {}

    def count(self, day: str) -> int:
        if self._path is None:
            return self._memory.get(day, 0)
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:  # nothing rang yet
            return 0
        except (OSError, ValueError):
            log.warning("urgent call: ledger unreadable, counting from zero", exc_info=True)
            return 0
        return int(data.get(day, 0)) if isinstance(data, dict) else 0

    def add(self, day: str) -> None:
        total = self.count(day) + 1
        if self._path is None:
            self._memory = {day: total}
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps({day: total}), encoding="utf-8")
        except OSError:
            log.warning("urgent call: ledger not saved", exc_info=True)


RingFn = Callable[[UrgentEvent, str], Awaitable[bool]]


class UrgentCaller:
    """Decides whether an open decision rings, and rings it through the route's callable."""

    def __init__(
        self,
        *,
        ring_desktop: RingFn,
        ring_phone: RingFn,
        is_open: Callable[[UrgentEvent], bool],
        phone_allowed: Callable[[], bool],
        settings: Callable[[], NotifySettings] = load_settings,
        clock: Callable[[], datetime] = datetime.now,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        ledger: CallLedger | None = None,
    ) -> None:
        self._ring_desktop = ring_desktop
        self._ring_phone = ring_phone
        self._is_open = is_open
        self._phone_allowed = phone_allowed
        self._settings = settings
        self._clock = clock
        self._sleep = sleep
        self._ledger = ledger or CallLedger()
        self._seen: set[str] = set()
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self.last: dict[str, str] = {}

    # ------------------------------------------------------------ the gates

    def _held(self, event: UrgentEvent, *, settle: bool) -> str | None:
        """Why this event does not ring right now, ``None`` when it may."""
        settings = self._settings()
        urgent = settings.urgent_call
        if not urgent.enabled:
            return OFF
        now = self._clock()
        if not qualifies(event, urgent, int(now.timestamp() * 1000)):
            return NOT_URGENT
        if settle:
            if not self._is_open(event):
                return RESOLVED
            if settings.quiet_hours.covers(now):
                return QUIET
            if self._ledger.count(now.date().isoformat()) >= urgent.max_per_day:
                return CAPPED
        return None

    async def handle(self, event: UrgentEvent) -> str:
        """Run one event through the gates, wait out the text grace, ring. Returns the outcome."""
        outcome = await self._handle(event)
        self.last[event.ref_id] = outcome
        log.debug("urgent call: %s %s -> %s", event.kind, event.ref_id, outcome)
        return outcome

    async def _handle(self, event: UrgentEvent) -> str:
        held = self._held(event, settle=False)
        if held is not None:
            return held
        if event.ref_id in self._seen:
            return DUPLICATE
        self._seen.add(event.ref_id)
        grace = self._settings().urgent_call.escalate_after_min
        if grace > 0:
            await self._sleep(grace * 60.0)
        # Everything is read again: the owner may have answered, switched it off or gone quiet.
        held = self._held(event, settle=True)
        if held is not None:
            return held
        urgent = self._settings().urgent_call
        if urgent.route == "phone":
            if not urgent.phone_number:
                return NO_NUMBER
            if not self._phone_allowed():
                return TEXT_ONLY
            ok = await self._ring_phone(event, urgent.phone_number)
        else:
            ok = await self._ring_desktop(event, "")
        if not ok:
            return FAILED
        self._ledger.add(self._clock().date().isoformat())
        return RANG

    # --------------------------------------------------------- chat events

    def on_chat_event(self, session_id: str, event: dict[str, Any]) -> None:
        """Listener for the chat service: records and schedules, never awaits."""
        kind = event.get("kind")
        opened = ("approval_required", "question_required")
        if kind not in (*opened, "approval_resolved", "question_resolved"):
            return
        if not self._settings().urgent_call.enabled:
            return
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if kind in ("approval_resolved", "question_resolved"):
            ref = str(payload.get("approval_id") or payload.get("question_id") or "")
            task = self._tasks.pop(ref, None)
            if task is not None:
                task.cancel()
            return
        found = event_from_chat(session_id, event)
        if found is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # emitted off the loop: nothing to schedule from here
            return
        task = loop.create_task(self.handle(found), name="urgent-call")
        self._tasks[found.ref_id] = task
        task.add_done_callback(lambda t, ref=found.ref_id: self._finished(ref, t))

    def _finished(self, ref: str, task: asyncio.Task[Any]) -> None:
        if self._tasks.get(ref) is task:
            self._tasks.pop(ref, None)
        if not task.cancelled() and task.exception() is not None:
            log.warning("urgent call failed: %s", task.exception())

    async def report_finding(self, ref_id: str, summary: str, severity: str) -> str:
        """A watchdog finding; only ``critical`` can ring, and only when its switch is on."""
        return await self.handle(
            UrgentEvent(kind="watchdog", ref_id=ref_id, summary=_line(summary), severity=severity)
        )


# ------------------------------------------------------------- the words


def opening_for(event: UrgentEvent, agent: str) -> str:
    """The one short statement a call opens with: who, what, the exact action, how to answer."""
    lang = notification_language(event.summary)
    who = agent or event.agent or phrase("an_agent", lang)
    summary = event.summary or "..."
    if event.kind == "approval":
        return phrase("call_opening_approval", lang, agent=who, summary=summary)
    if event.kind == "question" and event.accepts_yes:
        return phrase(
            "call_opening_question", lang, agent=who, summary=summary, answer=event.recommended
        )
    return phrase("call_opening_notice", lang, agent=who, summary=summary)


__all__ = [
    "CAPPED",
    "DUPLICATE",
    "FAILED",
    "NOT_URGENT",
    "NO_NUMBER",
    "OFF",
    "QUIET",
    "RANG",
    "RESOLVED",
    "TEXT_ONLY",
    "CallLedger",
    "UrgentCallRinging",
    "UrgentCaller",
    "UrgentEvent",
    "event_from_chat",
    "opening_for",
    "qualifies",
]
