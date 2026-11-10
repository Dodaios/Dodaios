"""Reminders: memories with a due time, delivered on time.

A reminder is an ordinary memory in the personal vault (ADR-0044) of kind
``ephemeral`` with ``due_at`` set and ``source.reminder`` true. That gives it
everything for free: the sidebar's "Coming up" reads ``/upcoming``, the
morning brief grounds on ``dated_notes()``, export and import carry it, and
"forget" erases it. It leaves the current set :data:`GRACE_DAYS` after its
time (``valid_to``), so an overdue reminder stays visible for a week.

:class:`ReminderScheduler` wakes every :data:`TICK_S` seconds, takes every
current memory whose time has come and that was not delivered yet (a meta
flag per memory), and delivers it: a ``reminder_due`` notice in the lead
conversation (where Done / Snooze live) plus a desktop notification through
the :class:`~dodaios.notify.notifier.Notifier`. Nothing is spoken.

:func:`capture_dump` turns a brain dump ("tomorrow dentist, buy milk, mail
Anna about the offer") into separate items without a model call: split on
the usual separators, a time per piece where one is named.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

from dodaios.notify.when import clean_text, parse_when, strip_when

log = logging.getLogger(__name__)

REMINDER_KIND: Final[str] = "ephemeral"
TASK_KIND: Final[str] = "project"
#: How long an overdue reminder stays current (and in "Coming up").
GRACE_DAYS: Final[int] = 7
#: How often the scheduler looks for due reminders.
TICK_S: Final[float] = 30.0
#: A reminder found more than this late (the app was closed) is marked
#: delivered without a notice: a week-old "take the pizza out" helps nobody.
STALE_AFTER: Final[timedelta] = timedelta(days=3)
#: Notice kinds in the lead conversation.
NOTICE_DUE: Final[str] = "reminder_due"
NOTICE_CAPTURED: Final[str] = "tasks_captured"
#: Snooze presets the card offers, in minutes; ``tomorrow`` is resolved by the caller.
SNOOZE_MINUTES: Final[tuple[int, ...]] = (15, 60, 180)

_DELIVERED = "reminder.delivered:"


def _iso_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def utc_now() -> datetime:
    return datetime.now(UTC)


def zone_of(name: str | None) -> ZoneInfo | None:
    try:
        return ZoneInfo(name) if name else None
    except Exception:  # noqa: BLE001 — an unknown zone name is "no zone" to the caller
        return None


def person_zone(name: str | None = None) -> ZoneInfo:
    """The person's zone: the given name, else the one the UI last reported, else UTC."""
    zone = zone_of(name)
    if zone is not None:
        return zone
    try:
        from dodaios.tasks.context import turn_timezone

        zone = zone_of(turn_timezone())
    except Exception:  # noqa: BLE001 — without a reported zone the clock below is UTC
        zone = None
    return zone or ZoneInfo("UTC")


def resolve_due(when: str, *, now: datetime, text: str = "") -> tuple[datetime | None, str, bool]:
    """``(due, remaining_text, has_time)`` for a ``when`` value a tool or route passes.

    ``when`` may be an ISO date or time (as a model usually writes it) or a
    plain phrase ("Friday at 9"). When ``when`` is empty the phrase is looked
    for inside ``text`` itself and removed from it.
    """
    when = (when or "").strip()
    if when:
        iso = _from_iso(when, now)
        if iso is not None:
            return iso[0], clean_text(text), iso[1]
        parsed = parse_when(when, now=now)
        if parsed is not None:
            return parsed.at, clean_text(text), parsed.has_time
        # A phrase the parser does not know: look in the text as a last resort.
    parsed = parse_when(text, now=now)
    if parsed is None:
        return None, clean_text(text), False
    return parsed.at, strip_when(text, parsed), parsed.has_time


def _from_iso(value: str, now: datetime) -> tuple[datetime, bool] | None:
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            day = datetime.fromisoformat(value)
            return day.replace(hour=9, tzinfo=now.tzinfo), False
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:  # not ISO: the caller tries it as a phrase next
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=now.tzinfo)
    return moment, True


# ------------------------------------------------------------------ writing


def is_reminder(memory: Any) -> bool:
    return bool((getattr(memory, "source", None) or {}).get("reminder"))


def row_of(memory: Any, now: str) -> dict[str, Any]:
    """The reminder as the API and the notices carry it."""
    return {
        "id": memory.id,
        "text": memory.text,
        "due_at": memory.due_at,
        "kind": memory.kind,
        "reminder": is_reminder(memory),
        "overdue": bool(memory.due_at) and memory.due_at <= now,
        "delivered": False,
    }


def create_reminder(
    vault: Any,
    text: str,
    due: datetime,
    *,
    via: str = "reminders tool",
    evidence: str = "",
    zone: str = "",
) -> Any:
    """Store ``text`` as a reminder due at ``due`` (aware); returns the ``WriteResult``."""
    text = " ".join((text or "").split())
    if not text:
        raise ValueError("a reminder needs a text")
    if due.tzinfo is None:
        raise ValueError("due must be timezone-aware")
    due_utc = _iso_utc(due)
    result = vault.remember(
        text,
        REMINDER_KIND,
        origin="user",
        source={
            "via": via,
            "reminder": True,
            "local": due.isoformat(timespec="minutes"),
            "zone": zone or str(due.tzinfo),
            "evidence": (evidence or "")[:300],
        },
        valid_to=_iso_utc(due + timedelta(days=GRACE_DAYS)),
        due_at=due_utc,
    )
    _changed()
    return result


def create_task(vault: Any, text: str, *, via: str = "reminders tool", evidence: str = "") -> Any:
    """An item without a time: a plan the person can see in memory and tick off."""
    text = " ".join((text or "").split())
    if not text:
        raise ValueError("a task needs a text")
    result = vault.remember(
        text,
        TASK_KIND,
        origin="user",
        source={"via": via, "task": True, "evidence": (evidence or "")[:300]},
    )
    _changed()
    return result


def mark_done(vault: Any, memory_id: str) -> bool:
    """Tick a reminder or task off: it is no longer current, its history stays."""
    ok = bool(vault.invalidate(memory_id, reason="done"))
    if ok:
        _changed()
    return ok


def snooze(vault: Any, memory_id: str, until: datetime) -> Any | None:
    """Move a reminder to ``until``: the old one ends, a new one takes its text."""
    old = vault.get(memory_id)
    if old is None:
        return None
    source = dict(old.source or {})
    vault.invalidate(memory_id, reason="snoozed")
    result = vault.remember(
        old.text,
        REMINDER_KIND,
        origin="user",
        source={
            **source,
            "via": "snooze",
            "reminder": True,
            "local": until.isoformat(timespec="minutes"),
            "snoozed_from": memory_id,
        },
        valid_to=_iso_utc(until + timedelta(days=GRACE_DAYS)),
        due_at=_iso_utc(until),
    )
    _changed()
    return result.memory


def list_due(vault: Any, *, days: int = 14) -> list[dict[str, Any]]:
    """Everything with a due time within ``days`` (overdue first), delivered flag set."""
    now = vault.now()
    rows = []
    for memory in vault.upcoming(days=days):
        row = row_of(memory, now)
        row["delivered"] = vault.get_meta(_DELIVERED + memory.id) is not None
        rows.append(row)
    return rows


def _changed() -> None:
    from dodaios.memory.vault.runtime import changed

    changed()


# ---------------------------------------------------------------- brain dump

# No unbounded whitespace runs on both sides of a separator: the pieces are
# stripped afterwards, and adjacent `\s*`/`\s+` made the split polynomial on
# long runs of spaces (a ReDoS shape). Connector words need a space on each side.
_SPLIT = re.compile(
    r"[\n;,]|\.(?=\s)|(?<=\s)(?:and then|and|then|also|plus|"
    r"und dann|und|dann|außerdem|"  # i18n-allow
    r"y luego|y|luego|además|"  # i18n-allow
    r"e depois|e|depois|também)(?=\s)",  # i18n-allow
    re.I,
)
_MIN_ITEM_CHARS = 3


@dataclass(frozen=True)
class CapturedItem:
    text: str
    due: datetime | None
    has_time: bool = False


def split_dump(text: str, *, now: datetime) -> list[CapturedItem]:
    """Separate items of a brain dump, each with the time it names (if any)."""
    items: list[CapturedItem] = []
    pieces = [
        piece
        for line in (text or "").splitlines()
        for piece in _SPLIT.split(" ".join(line.split()))
    ]
    for raw in pieces:
        piece = (raw or "").strip(" .,;:-")
        if len(piece) < _MIN_ITEM_CHARS:
            continue
        parsed = parse_when(piece, now=now)
        if parsed is None:
            cleaned = clean_text(piece)
            if cleaned:
                items.append(CapturedItem(cleaned, None))
            continue
        rest = strip_when(piece, parsed)
        if not rest and items:
            # "tomorrow" on its own dates the item before it ("dentist tomorrow").
            previous = items.pop()
            items.append(CapturedItem(previous.text, parsed.at, parsed.has_time))
            continue
        if rest:
            items.append(CapturedItem(rest, parsed.at, parsed.has_time))
    return items


def capture_dump(
    vault: Any, text: str, *, now: datetime, evidence: str = ""
) -> list[dict[str, Any]]:
    """Store every item of a brain dump; returns the rows for the card."""
    rows: list[dict[str, Any]] = []
    for item in split_dump(text, now=now):
        if item.due is not None:
            result = create_reminder(
                vault, item.text, item.due, via="brain dump", evidence=evidence
            )
        else:
            result = create_task(vault, item.text, via="brain dump", evidence=evidence)
        memory = result.memory
        if memory is None:
            log.info("reminders: brain dump item not stored (%s): %s", result.action, item.text)
            continue
        row = row_of(memory, vault.now())
        row["op"] = result.action
        rows.append(row)
    return rows


# -------------------------------------------------------------- the lead chat


def lead_target() -> tuple[Any, str] | None:
    """``(service, session_id)`` of the lead conversation, ``None`` without one."""
    try:
        from dodaios.agent_chat.lead import lead_session
        from dodaios.society.runtime import current_runtime

        runtime = current_runtime()
        svc = runtime.chat_service() if runtime is not None else None
        if svc is None:
            return None
        session = lead_session(svc, create=False)
        if session is None:
            return None
        return svc, session.session_id
    except Exception:  # noqa: BLE001 — no conversation is a plain "nowhere to post"
        log.debug("reminders: lead conversation unavailable", exc_info=True)
        return None


async def post_notice(svc: Any, session_id: str, payload: dict[str, Any]) -> str:
    """Post a notice and return its timeline id (``n-<seq>``), or ``""``."""
    await svc.post_notice(session_id, payload)
    try:
        tail = svc.store.list_events(session_id, tail=1)
    except Exception:  # noqa: BLE001 — the id only sharpens the click target
        return ""
    if tail and tail[-1].get("kind") == "notice":
        seq = tail[-1].get("seq")
        return f"n-{seq}" if seq else ""
    return ""


# ------------------------------------------------------------------ scheduler


def _ui_language() -> str:
    try:
        from dodaios.core.config import load_config

        cfg = load_config()
        lang = str(getattr(getattr(cfg, "ui", None), "language", "") or "en").lower()
        return lang.split("-", 1)[0]
    except Exception:  # noqa: BLE001 — English is the catalog's safety net anyway
        return "en"


def notification_language(text: str) -> str:
    """The language a reminder's notification is worded in (one resolver, ADR doctrine)."""
    try:
        from dodaios.core.config import load_config
        from dodaios.core.turn_language import resolve_output_language

        cfg = load_config()
        pin = getattr(getattr(cfg, "brain", None), "reply_language", "auto")
        return resolve_output_language(pin, None, text, default=_ui_language())
    except Exception:  # noqa: BLE001 — English is the catalog's safety net anyway
        return "en"


def phrase(key: str, lang: str, **fields: object) -> str:
    from dodaios.i18n import catalog

    return catalog.t(f"notify.{key}", lang, **fields)


class ReminderScheduler:
    """Delivers due reminders; one instance per app."""

    def __init__(
        self,
        *,
        vault: Callable[[], Any | None],
        target: Callable[[], tuple[Any, str] | None] = lead_target,
        notifier: Callable[[], Any | None],
        clock: Callable[[], datetime] = utc_now,
        tick_s: float = TICK_S,
    ) -> None:
        self._vault = vault
        self._target = target
        self._notifier = notifier
        self._clock = clock
        self._tick_s = tick_s
        self._task: asyncio.Task[None] | None = None

    def start(self) -> asyncio.Task[None]:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run(), name="reminders")
        return self._task

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — one bad tick must not stop every later reminder
                log.warning("reminders: tick failed", exc_info=True)
            await asyncio.sleep(self._tick_s)

    async def tick(self) -> list[str]:
        """Deliver what is due; returns the ids delivered this round."""
        vault = self._vault()
        if vault is None:
            return []
        now = self._clock()
        try:
            due = await asyncio.to_thread(vault.upcoming, days=0)
        except Exception:  # noqa: BLE001 — a locked vault is retried on the next tick
            log.warning("reminders: could not read due memories", exc_info=True)
            return []
        delivered: list[str] = []
        for memory in due:
            key = _DELIVERED + memory.id
            if vault.get_meta(key) is not None:
                continue
            # Claim first: a second tick (or a restart mid-delivery) must not
            # tell the same reminder twice.
            vault.set_meta(key, _iso_utc(now))
            due_at = _due_moment(memory.due_at)
            if due_at is not None and now - due_at > STALE_AFTER:
                log.info("reminders: %s was due %s; too old to tell", memory.id, memory.due_at)
                continue
            await self.deliver(memory)
            delivered.append(memory.id)
        return delivered

    async def deliver(self, memory: Any) -> None:
        lang = notification_language(memory.text)
        session_id = ""
        message_id = ""
        target = self._target()
        if target is not None:
            svc, session_id = target
            try:
                message_id = await post_notice(
                    svc,
                    session_id,
                    {
                        "kind": NOTICE_DUE,
                        "status": "",
                        "text": memory.text,
                        "memory_id": memory.id,
                        "due_at": memory.due_at,
                        "reminder": is_reminder(memory),
                    },
                )
            except Exception:  # noqa: BLE001 — the desktop notification below still goes out
                log.warning("reminders: notice not posted for %s", memory.id, exc_info=True)
        notifier = self._notifier()
        if notifier is None:
            return
        title = phrase("reminder_title", lang)
        await notifier.notify(
            "reminder",
            title,
            memory.text,
            session_id=session_id,
            message_id=message_id,
            # The person asked for this at this time: tell them even while the
            # window is in front (the notice is a line among many).
            ignore_focus=True,
        )


def _due_moment(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:  # an unreadable due time is treated as "not yet known"
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


__all__ = [
    "GRACE_DAYS",
    "NOTICE_CAPTURED",
    "NOTICE_DUE",
    "REMINDER_KIND",
    "SNOOZE_MINUTES",
    "STALE_AFTER",
    "TASK_KIND",
    "TICK_S",
    "CapturedItem",
    "ReminderScheduler",
    "capture_dump",
    "create_reminder",
    "create_task",
    "is_reminder",
    "lead_target",
    "list_due",
    "mark_done",
    "notification_language",
    "person_zone",
    "phrase",
    "post_notice",
    "resolve_due",
    "row_of",
    "snooze",
    "split_dump",
    "utc_now",
]
