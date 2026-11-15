"""Rituals at run time: writing one, deciding whether a sentence starts it, starting it.

A ritual is started by its phrase (spoken after the wake word or typed), by the
person's click on "Run now", or by the assistant on request. Starting it does
two things at once:

* its ``now`` steps are done at that moment. They are sentences in the person's
  own words and may ask for anything the assistant can do, so they run as one
  turn of the lead's conversation, with the person's standing and nothing typed;
* a card in that conversation says the ritual started and carries what was
  gathered ahead for it (:mod:`dodaios.rituals.prepare`). If that is not ready
  yet, it is gathered now and follows in a second card (:func:`deliver_late`).

Whether a phrase starts a ritual right now is a matter of words and the clock
(:func:`find_match`, :func:`why_not`); no model is asked. A ritual whose
phrase may start it only once a day is claimed with one conditional update in
the store, so the phrase heard twice in one moment starts it once. A click or
a start on request always runs and does not use the phrase up.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Final

from . import matcher
from .models import (
    FIRED_VIA,
    MAX_NAME_CHARS,
    MAX_PHRASE_CHARS,
    MAX_PHRASE_WORDS,
    MAX_PHRASES,
    MAX_RITUALS,
    MAX_STEP_CHARS,
    MAX_STEPS,
    NOUN,
    ORIGINS,
    WHEN,
    Ritual,
    RitualDay,
    RitualError,
    RitualStep,
    clock,
    minutes_of,
    new_ritual_id,
    new_step_id,
    now_ms,
)
from .store import get_store

log = logging.getLogger(__name__)

#: How long the ``now`` steps wait for the lead conversation to be free.
SEAT_WAIT_S: Final[float] = 600.0
#: How much of a card's text a chat notice carries.
_MAX_CARD_CHARS: Final[int] = 4000
# A plain module value: tests shorten it.
_POLL_S: float = 0.5

_background: set[asyncio.Task[None]] = set()


@dataclass(frozen=True, slots=True)
class Match:
    """A ritual a sentence names, and whether the sentence starts it right now."""

    ritual: Ritual
    #: The phrase of the ritual that was said.
    phrase: str
    #: ``""`` when it starts now; else why not: ``off``, ``day``, ``time``, ``done_today``.
    blocked: str

    @property
    def fires(self) -> bool:
        return not self.blocked


# ----------------------------------------------------------------- plumbing


def _runtime() -> Any | None:
    from dodaios.society.runtime import current_runtime

    return current_runtime()


def _wake_phrase() -> str:
    """The configured wake phrase, ``""`` when there is none to read."""
    runtime = _runtime()
    try:
        cfg = runtime.config() if runtime is not None else None
        trigger = getattr(cfg, "trigger", None)
        wake = getattr(trigger, "wake_word", None)
        return str(getattr(wake, "phrase", "") or "")
    except Exception:  # noqa: BLE001 — without the name, only the fixed address words are peeled
        log.debug("rituals: wake phrase unreadable", exc_info=True)
        return ""


def _moment(now: datetime | None) -> datetime:
    """``now`` on the person's clock."""
    return now if now is not None else datetime.now().astimezone()


def day_of(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d")


def _require(ritual_id: str) -> Ritual:
    ritual = get_store().get(str(ritual_id or "").strip())
    if ritual is None:
        raise RitualError("not_found", f"There is no {NOUN} {ritual_id!r}.")
    return ritual


def _one_line(text: Any) -> str:
    return " ".join(str(text or "").split())


# --------------------------------------------------------------- validation


def _clean_phrases(raw: Any, *, wake_phrase: str) -> tuple[str, ...]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, Iterable):
        raise RitualError("invalid", "phrases must be a list of short sentences.")
    phrases: list[str] = []
    for item in raw:
        text = _one_line(item)
        if not text:
            continue
        problem = matcher.phrase_problem(text, wake_phrase=wake_phrase)
        if problem:
            raise RitualError("invalid", problem)
        if _is_brief_request(text):
            raise RitualError(
                "invalid",
                f'"{text}" already asks for the day\'s brief; pick another phrase.',
            )
        if not any(matcher.same_phrase(text, kept) for kept in phrases):
            phrases.append(text)
    if not phrases:
        raise RitualError("invalid", f"A {NOUN} needs a phrase that starts it.")
    if len(phrases) > MAX_PHRASES:
        raise RitualError("invalid", f"A {NOUN} takes at most {MAX_PHRASES} phrases.")
    return tuple(phrases)


def _is_brief_request(text: str) -> bool:
    """Whether the voice path answers ``text`` itself, before any ritual is looked at."""
    try:
        from dodaios.speech import spoken_brief

        return spoken_brief.is_brief_request(text)
    except Exception:  # noqa: BLE001 — without that module nothing takes the phrase away
        log.debug("rituals: brief phrases unreadable", exc_info=True)
        return False


def _clean_steps(raw: Any) -> tuple[RitualStep, ...]:
    if not isinstance(raw, Iterable) or isinstance(raw, str | bytes | dict):
        raise RitualError("invalid", "steps must be a list.")
    steps: list[RitualStep] = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, RitualStep):
            item = item.to_dict()
        if not isinstance(item, dict):
            raise RitualError("invalid", "Each step is an object with 'when' and 'text'.")
        when = str(item.get("when") or "").strip().lower()
        text = str(item.get("text") or "").strip()
        if when not in WHEN:
            raise RitualError(
                "invalid", "A step's 'when' is one of: " + ", ".join(WHEN) + "."
            )
        if not text:
            raise RitualError("invalid", "A step needs a sentence that says what should happen.")
        if len(text) > MAX_STEP_CHARS:
            raise RitualError(
                "invalid", f"A step is at most {MAX_STEP_CHARS} characters long."
            )
        step_id = str(item.get("id") or "").strip()
        if not step_id or step_id in seen:
            step_id = new_step_id()
        seen.add(step_id)
        steps.append(RitualStep(id=step_id, when=when, text=text))
    if not steps:
        raise RitualError("invalid", f"A {NOUN} needs at least one step.")
    if len(steps) > MAX_STEPS:
        raise RitualError("invalid", f"A {NOUN} takes at most {MAX_STEPS} steps.")
    return tuple(steps)


def _clean_weekdays(raw: Any) -> tuple[int, ...]:
    if raw is None or raw == "":
        return ()
    if not isinstance(raw, Iterable) or isinstance(raw, str | bytes | dict):
        raise RitualError("invalid", "weekdays is a list of numbers, Monday is 0.")
    days: set[int] = set()
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 6:
            raise RitualError("invalid", "weekdays is a list of numbers 0 to 6, Monday is 0.")
        days.add(item)
    # All seven days is the same as no limit.
    return () if len(days) == 7 else tuple(sorted(days))


def _clean_clock(value: Any, what: str) -> str:
    try:
        return clock(value)
    except ValueError as exc:
        raise RitualError("invalid", f"{what}: {exc}.") from exc


def _validated(fields: dict[str, Any], *, wake_phrase: str) -> dict[str, Any]:
    name = _one_line(fields.get("name"))
    if not name:
        raise RitualError("invalid", f"A {NOUN} needs a name.")
    if len(name) > MAX_NAME_CHARS:
        raise RitualError("invalid", f"The name is longer than {MAX_NAME_CHARS} characters.")
    window_from = _clean_clock(fields.get("window_from"), "window_from")
    window_to = _clean_clock(fields.get("window_to"), "window_to")
    if bool(window_from) != bool(window_to):
        raise RitualError("invalid", "A time window needs both its start and its end.")
    if window_from and window_from == window_to:
        raise RitualError("invalid", "The time window starts and ends at the same minute.")
    return {
        "name": name,
        "phrases": _clean_phrases(fields.get("phrases"), wake_phrase=wake_phrase),
        "enabled": bool(fields.get("enabled", True)),
        "window_from": window_from,
        "window_to": window_to,
        "weekdays": _clean_weekdays(fields.get("weekdays")),
        "once_per_day": bool(fields.get("once_per_day", True)),
        "prepare_from": _clean_clock(fields.get("prepare_from"), "prepare_from"),
        "steps": _clean_steps(fields.get("steps")),
    }


def _check_unique(clean: dict[str, Any], *, ignore_id: str = "") -> None:
    """A name and a phrase each belong to one ritual."""
    for other in get_store().list():
        if other.id == ignore_id:
            continue
        if other.name.casefold() == clean["name"].casefold():
            raise RitualError("conflict", f'There is already a {NOUN} named "{other.name}".')
        for phrase in clean["phrases"]:
            if any(matcher.same_phrase(phrase, taken) for taken in other.phrases):
                raise RitualError(
                    "conflict", f'"{phrase}" already starts the {NOUN} "{other.name}".'
                )


# -------------------------------------------------------------------- writes


async def create(*, origin: str = "owner", **fields: Any) -> Ritual:
    """Write a new ritual. ``origin`` says who wrote it: the owner or the assistant."""
    if origin not in ORIGINS:
        raise RitualError("invalid", "origin must be one of " + ", ".join(ORIGINS) + ".")
    clean = _validated(fields, wake_phrase=_wake_phrase())
    if len(get_store().list()) >= MAX_RITUALS:
        raise RitualError(
            "limit", f"There are already {MAX_RITUALS} {NOUN}s. Remove one before adding another."
        )
    _check_unique(clean)
    stamp = now_ms()
    ritual = Ritual(
        id=new_ritual_id(), task_id="", origin=origin, created_ms=stamp, updated_ms=stamp, **clean
    )
    get_store().save(ritual)
    log.info("rituals: %s created (%d steps, origin %s)", ritual.id, len(ritual.steps), origin)
    return ritual


async def update(ritual_id: str, **changes: Any) -> Ritual:
    """Change only the fields that are given; the rest stays as written."""
    current = _require(ritual_id)
    known = {
        "name", "phrases", "enabled", "window_from", "window_to", "weekdays",
        "once_per_day", "prepare_from", "steps",
    }
    unknown = set(changes) - known
    if unknown:
        raise RitualError("invalid", "Unknown field: " + ", ".join(sorted(unknown)) + ".")
    merged = {
        "name": current.name,
        "phrases": list(current.phrases),
        "enabled": current.enabled,
        "window_from": current.window_from,
        "window_to": current.window_to,
        "weekdays": list(current.weekdays),
        "once_per_day": current.once_per_day,
        "prepare_from": current.prepare_from,
        "steps": [step.to_dict() for step in current.steps],
        **changes,
    }
    clean = _validated(merged, wake_phrase=_wake_phrase())
    _check_unique(clean, ignore_id=current.id)
    changed = replace(current, updated_ms=now_ms(), **clean)
    get_store().save(changed)
    return changed


async def remove(ritual_id: str) -> None:
    from . import prepare

    ritual = _require(ritual_id)
    # The run that gathers ahead for it goes with it.
    await prepare.drop_routine(ritual)
    get_store().delete(ritual.id)
    log.info("rituals: %s removed", ritual.id)


# --------------------------------------------------------------------- reads


def list_rituals() -> list[Ritual]:
    return get_store().list()


def get(ritual_id: str) -> Ritual | None:
    return get_store().get(str(ritual_id or "").strip())


def today_of(ritual_id: str, *, now: datetime | None = None) -> RitualDay | None:
    return get_store().day(ritual_id, day_of(_moment(now)))


def overview(*, now: datetime | None = None) -> dict[str, Any]:
    """Every ritual with where it stands today, and the limits a form needs."""
    today = {row.ritual_id: row for row in get_store().days(day_of(_moment(now)))}
    return {
        "available": True,
        "rituals": [
            {
                **ritual.to_dict(),
                "today": today[ritual.id].to_dict() if ritual.id in today else None,
            }
            for ritual in get_store().list()
        ],
        "limits": {
            "max_rituals": MAX_RITUALS,
            "max_name_chars": MAX_NAME_CHARS,
            "max_phrases": MAX_PHRASES,
            "max_phrase_words": MAX_PHRASE_WORDS,
            "max_phrase_chars": MAX_PHRASE_CHARS,
            "max_steps": MAX_STEPS,
            "max_step_chars": MAX_STEP_CHARS,
            "when": list(WHEN),
        },
    }


# ---------------------------------------------------------- does it start now


def _inside_window(ritual: Ritual, moment: datetime) -> bool:
    if not ritual.window_from:
        return True
    minute = moment.hour * 60 + moment.minute
    start, end = minutes_of(ritual.window_from), minutes_of(ritual.window_to)
    if start <= end:
        return start <= minute <= end
    # A window over midnight (22:00 to 02:00).
    return minute >= start or minute <= end


def why_not(ritual: Ritual, moment: datetime, *, phrase_used: bool) -> str:
    """Why its phrase does not start ``ritual`` at ``moment``; ``""`` when it does.

    ``phrase_used`` is whether the phrase already started it on that day. A
    click on "Run now" or a start on request does not count: the phrase keeps
    its one start of the day.
    """
    if not ritual.enabled:
        return "off"
    if ritual.weekdays and moment.weekday() not in ritual.weekdays:
        return "day"
    if not _inside_window(ritual, moment):
        return "time"
    if ritual.once_per_day and phrase_used:
        return "done_today"
    return ""


def _phrase_used(ritual_id: str, day: str) -> bool:
    """Whether the ritual's phrase already started it on ``day``."""
    row = get_store().day(ritual_id, day)
    return row is not None and row.phrase_ms is not None


def find_match(
    text: str, *, wake_phrase: str | None = None, now: datetime | None = None
) -> Match | None:
    """The ritual ``text`` names with one of its phrases, or ``None`` when it names none.

    The answer also says whether the sentence starts the ritual right now. A
    caller that only wants to start one checks :attr:`Match.fires`; anything
    else is an ordinary sentence for the assistant to answer.
    """
    said = str(text or "")
    if not matcher.words(said):
        return None
    wake = _wake_phrase() if wake_phrase is None else wake_phrase
    moment = _moment(now)
    for ritual in get_store().list():
        for phrase in ritual.phrases:
            if matcher.says(said, phrase, wake_phrase=wake):
                blocked = why_not(
                    ritual, moment, phrase_used=_phrase_used(ritual.id, day_of(moment))
                )
                return Match(ritual=ritual, phrase=phrase, blocked=blocked)
    return None


# -------------------------------------------------------------------- start


def now_prompt(ritual: Ritual, steps: Sequence[RitualStep]) -> str:
    """What the lead is told to do for the ``now`` steps of a started ritual."""
    lines = "\n".join(f"{index}. {step.text}" for index, step in enumerate(steps, 1))
    return (
        f'[The person just started their {NOUN} "{ritual.name}". These are its steps for '
        "this moment, in their own words. They asked for each of them when they wrote the "
        f"{NOUN}: do every one now, in this order, without asking back. A step that cannot "
        "be done is skipped and named. Then say in one or two short sentences what you did."
        f"\n{lines}]"
    )


def card_text(ritual: Ritual, day: RitualDay | None) -> str:
    """The body of the card a started ritual puts into the conversation."""
    parts: list[str] = []
    written = (day.written if day is not None else "").strip()
    if written:
        parts.append(written)
    now_steps = ritual.steps_at("now")
    if now_steps:
        parts.append("\n".join(f"- {step.text}" for step in now_steps))
    return "\n\n".join(parts)[:_MAX_CARD_CHARS]


def card_text_late(day: RitualDay) -> str:
    """The body of the second card: what was gathered, once it is there."""
    return day.written.strip()[:_MAX_CARD_CHARS]


async def _lead_chat() -> tuple[Any, Any, Any]:
    """``(runtime, lead, chat service)``, or ``RitualError("unavailable")``."""
    from dodaios.society.roster import LEAD_AGENT_ID

    runtime = _runtime()
    if runtime is None:
        raise RitualError("unavailable", "The assistant is not running yet.")
    lead = await runtime.roster.get(LEAD_AGENT_ID)
    if lead is None:
        raise RitualError("unavailable", "The assistant's agent record is missing.")
    return runtime, lead, runtime.chat_service()


async def _post(ritual: Ritual, fields: dict[str, Any]) -> None:
    """One notice about ``ritual`` in the lead's conversation. Never raises."""
    try:
        runtime, lead, _svc = await _lead_chat()
        namer = getattr(runtime, "display_name", None)
        await runtime.post_chat_notice(
            lead,
            {
                "kind": "society_result",
                "status": "done",
                "source": "ritual",
                "agent_id": lead.agent_id,
                "agent_name": namer(lead) if callable(namer) else str(lead.name),
                "ritual_id": ritual.id,
                "ritual_title": ritual.name,
                **fields,
            },
        )
    except Exception:  # noqa: BLE001 — the card is a projection; the ritual itself started
        log.warning("rituals: card of %s not posted", ritual.id, exc_info=True)


async def _post_card(
    ritual: Ritual, day: RitualDay | None, *, via: str, pending: bool = False
) -> None:
    """The card of a start. ``pending``: what is gathered ahead follows in a second card."""
    await _post(
        ritual,
        {
            "via": via,
            "text": card_text(ritual, day),
            "pending": pending,
            # The person started it where they are; their phone stays quiet.
            "push": False,
        },
    )


async def deliver_late(ritual: Ritual, day: str) -> None:
    """Hand over what was gathered after the ritual had already started.

    The start found nothing ready and said so; this is the second card. It may
    reach the phone: the person may have walked away while it was gathered.
    When the gathering failed for good, the card says that instead.
    """
    from . import prepare

    store = get_store()
    row = store.day(ritual.id, day)
    if row is None or row.fired_ms is None or row.delivered_ms is not None:
        return
    if prepare.usable(ritual, row):
        await _post(ritual, {"via": row.fired_via, "late": True, "text": card_text_late(row)})
        from . import said

        # Started by voice: it is also said, when the call is still open.
        await said.announce_late(ritual, row)
    else:
        reason = row.prep_error or "Nothing could be gathered."
        await _post(
            ritual, {"via": row.fired_via, "late": True, "status": "failed", "text": reason}
        )
    store.patch_day(ritual.id, day, delivered_ms=now_ms())


async def _run_now_steps(ritual: Ritual, steps: Sequence[RitualStep]) -> None:
    """One turn of the lead's conversation that does the ``now`` steps.

    The person asked for it by starting the ritual, so the turn runs with
    their standing; nothing was typed, so the timeline shows only the answer.
    A conversation that is busy is waited for, for a while.
    """
    from dodaios.agent_chat.lead import lead_session
    from dodaios.agent_chat.send_queue import has_waiting
    from dodaios.agent_chat.service import NoSuchSession, SessionBusy

    try:
        _runtime_, _lead, svc = await _lead_chat()
        session = lead_session(svc) if svc is not None else None
    except Exception:  # noqa: BLE001 — without a conversation the steps cannot run; say so in the log
        log.warning("rituals: no conversation for the steps of %s", ritual.id, exc_info=True)
        return
    if session is None:
        log.warning("rituals: no conversation for the steps of %s", ritual.id)
        return
    session_id = str(session.session_id)
    prompt = now_prompt(ritual, steps)
    deadline = time.monotonic() + SEAT_WAIT_S
    while True:
        if not svc.is_running(session_id) and not has_waiting(svc, session_id):
            try:
                await svc.send(
                    session_id, prompt, display_text=ritual.name, background_result=True
                )
            except SessionBusy:
                log.debug("rituals: the conversation was taken first; trying again")
            except NoSuchSession:
                log.warning("rituals: the conversation is gone; steps of %s not run", ritual.id)
                return
            else:
                return
        if time.monotonic() >= deadline:
            log.warning(
                "rituals: the conversation stayed busy; steps of %s not run", ritual.id
            )
            return
        await asyncio.sleep(_POLL_S)


def _does_not_start(ritual: Ritual, why: str) -> RitualError:
    return RitualError("state", f'The {NOUN} "{ritual.name}" does not start now ({why}).')


def _spawn(coro: Any, name: str) -> None:
    task = asyncio.get_running_loop().create_task(coro, name=name)
    _background.add(task)
    task.add_done_callback(_background.discard)


async def drain() -> None:
    """Wait for what a start left running (tests, shutdown)."""
    while _background:
        await asyncio.gather(*list(_background), return_exceptions=True)


async def _file_said(said: str) -> None:
    """Put what the person said or typed into the conversation, without a turn for it."""
    text = str(said or "").strip()
    if not text:
        return
    try:
        from dodaios.agent_chat.lead import lead_session

        _runtime_, _lead, svc = await _lead_chat()
        session = lead_session(svc) if svc is not None else None
        if session is not None:
            await svc.import_voice_turn(str(session.session_id), text, "")
    except Exception:  # noqa: BLE001 — the ritual starts without the line that shows what was said
        log.warning("rituals: the phrase was not filed into the conversation", exc_info=True)


async def fire(
    ritual_id: str,
    *,
    via: str,
    force: bool = False,
    said: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Start a ritual: the card, and its ``now`` steps as a turn.

    ``force`` is the person's own click or the assistant on request: it starts
    the ritual whatever the clock says and however often it ran today, and it
    leaves the phrase its one start of the day. Without it the ritual's
    conditions hold, and a ritual that may start once a day is claimed first,
    so the same phrase heard twice in one moment starts it once.

    ``said`` is the sentence that started it (spoken or typed). It is filed
    into the conversation above the card, because no turn answers it.
    """
    if via not in FIRED_VIA:
        raise RitualError("invalid", "via must be one of " + ", ".join(FIRED_VIA) + ".")
    ritual = _require(ritual_id)
    # A start nobody would see or hear of is refused before the day is claimed.
    await _lead_chat()
    moment = _moment(now)
    day = day_of(moment)
    store = get_store()
    stamp = now_ms()
    if force:
        store.record_fire(ritual.id, day, stamp, via)
    else:
        blocked = why_not(ritual, moment, phrase_used=_phrase_used(ritual.id, day))
        if blocked:
            raise _does_not_start(ritual, blocked)
        if ritual.once_per_day:
            if not store.claim_fire(ritual.id, day, stamp, via):
                raise _does_not_start(ritual, "done_today")
        else:
            store.record_fire(ritual.id, day, stamp, via)
    log.info("rituals: %s started via %s", ritual.id, via)
    from . import prepare

    today = store.day(ritual.id, day)
    ahead = ritual.steps_at("ahead")
    ready = prepare.usable(ritual, today)
    await _file_said(said)
    await _post_card(ritual, today if ready else None, via=via, pending=bool(ahead) and not ready)
    if ready or not ahead:
        today = store.patch_day(ritual.id, day, delivered_ms=now_ms())
    else:
        # Nothing ready (the machine slept, the phrase came early): gather now,
        # the result follows in a second card.
        prepare.request(ritual.id, day)
    now_steps = ritual.steps_at("now")
    if now_steps:
        _spawn(_run_now_steps(ritual, now_steps), f"ritual-now-{ritual.id}")
    return {
        "ritual": ritual.to_dict(),
        "today": today.to_dict() if today is not None else None,
        "pending": bool(ahead) and not ready,
        # What was gathered, in the form made for the ear; "" when nothing is ready.
        "spoken": today.spoken if ready and today is not None else "",
    }


__all__ = [
    "Match",
    "SEAT_WAIT_S",
    "card_text",
    "card_text_late",
    "create",
    "day_of",
    "deliver_late",
    "drain",
    "find_match",
    "fire",
    "get",
    "list_rituals",
    "now_prompt",
    "overview",
    "remove",
    "today_of",
    "update",
    "why_not",
]
