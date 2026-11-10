"""Open loops: what the person said they would do, asked back once when it is due.

"I'll call Max tomorrow" is a commitment with a date. :func:`detect` finds
such sentences in what the person typed (English and German), and
:func:`note_user_text` stores each as a dated memory in the personal vault
(ADR-0044) through the vault's public write, ``due_at`` set to the evening
of that day. The "needs you" check (``proactive_checks.run_context``) reads
the loops that fell due with :func:`due_loops`, asks back once, and
:func:`mark_asked` closes them so no loop is ever asked twice. The person's
answer reaches memory the usual way, through the learning loop.

Only the person's own words count (direct turns in the lead conversation),
never a routine's or an agent's. Nothing here calls a model.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

#: ``source.via`` of every memory this module writes.
VIA: Final[str] = "open_loop"
#: Local hour of the due day from which a loop counts as due.
DUE_HOUR: Final[int] = 18
_MAX_LOOPS_PER_TURN: Final[int] = 3
_MAX_WHAT_CHARS: Final[int] = 120

#: Sentences with their closing marks kept, so a question stays recognisable.
_SENTENCE_SPLIT = re.compile(r"([.!?\n]+)")

#: "I'll call Max", "I need to send the report", "ich werde Max anrufen".
#: Wishes and obligations to someone else are no promise: "I want to / should"
#: and "ich möchte / sollte / wollte" are left out on purpose.  # i18n-allow
_COMMITMENTS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"\bI(?:'ll| will|'m going to| am going to| need to| have to| must"
        r"| plan to| promised to|'ve got to| have got to)\s+(?P<what>.{3,160})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bich\s+(?:werde|muss|will|plane)\s+(?P<what>.{3,160})",  # i18n-allow
        re.IGNORECASE,
    ),
    re.compile(  # Spanish: "voy a llamar a Max", "tengo que enviar el informe"
        r"\b(?:voy a|tengo que|tengo previsto|debo|necesito|planeo|prometí)\s+"  # i18n-allow
        r"(?P<what>.{3,160})",
        re.IGNORECASE,
    ),
    re.compile(  # Portuguese: "vou ligar ao Max", "tenho de enviar o relatório"
        r"\b(?:vou|tenho que|tenho de|preciso de|preciso|devo|planeio|prometi)\s+"  # i18n-allow
        r"(?P<what>.{3,160})",
        re.IGNORECASE,
    ),
)

#: A greeting is not a day: "Guten Morgen, ich muss noch X" has no due day.  # i18n-allow
_GREETINGS: Final = re.compile(
    r"\b(?:guten\s+morgen|good\s+morning|buenos\s+d[ií]as|bom\s+dia)\b",  # i18n-allow
    re.IGNORECASE,
)

_WEEKDAYS: Final[dict[str, int]] = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4,
    "saturday": 5, "sunday": 6,
    "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3, "freitag": 4,  # i18n-allow
    "samstag": 5, "sonntag": 6,  # i18n-allow
    "lunes": 0, "martes": 1, "miércoles": 2, "miercoles": 2, "jueves": 3,  # i18n-allow
    "viernes": 4, "sábado": 5, "sabado": 5, "domingo": 6,  # i18n-allow
    "segunda": 0, "terça": 1, "terca": 1, "quarta": 2, "quinta": 3,  # i18n-allow
    "sexta": 4,  # i18n-allow
}

#: Relative day words and their offset from today. "This morning" comes before
#: "morning"-style words that also contain a day word ("heute Morgen" is today,
#: not tomorrow), and "day after tomorrow" before "tomorrow".
_RELATIVE_DAYS: Final[tuple[tuple[re.Pattern[str], int], ...]] = (
    (re.compile(r"\bday after tomorrow\b", re.IGNORECASE), 2),
    (re.compile(r"\bthis morning\b", re.IGNORECASE), 0),
    (re.compile(r"\btomorrow\b", re.IGNORECASE), 1),
    (
        re.compile(r"\b(?:today|tonight|this evening|this afternoon|later today)\b", re.IGNORECASE),
        0,
    ),
    (re.compile(r"\bnext week\b", re.IGNORECASE), 7),
    (re.compile(r"\bübermorgen\b", re.IGNORECASE), 2),  # i18n-allow
    (re.compile(r"\bheute\s+(?:morgen|früh)\b", re.IGNORECASE), 0),  # i18n-allow
    (re.compile(r"\bmorgen\b", re.IGNORECASE), 1),  # i18n-allow
    (re.compile(r"\bheute\b", re.IGNORECASE), 0),  # i18n-allow
    (re.compile(r"\bnächste woche\b", re.IGNORECASE), 7),  # i18n-allow
    # Spanish
    (re.compile(r"\bpasado ma[ñn]ana\b", re.IGNORECASE), 2),  # i18n-allow
    (re.compile(r"\besta ma[ñn]ana\b", re.IGNORECASE), 0),  # i18n-allow
    (re.compile(r"\bma[ñn]ana\b", re.IGNORECASE), 1),  # i18n-allow
    (re.compile(r"\b(?:hoy|esta tarde|esta noche)\b", re.IGNORECASE), 0),  # i18n-allow
    (re.compile(r"\b(?:la )?pr[oó]xima semana\b|\bla semana que viene\b", re.I), 7),  # i18n-allow
    # Portuguese
    (re.compile(r"\bdepois de amanh[ãa]\b", re.IGNORECASE), 2),  # i18n-allow
    (re.compile(r"\bamanh[ãa]\b", re.IGNORECASE), 1),  # i18n-allow
    (re.compile(r"\b(?:hoje|esta manh[ãa]|esta tarde|esta noite)\b", re.I), 0),  # i18n-allow
    (re.compile(r"\b(?:na )?pr[oó]xima semana\b|\bsemana que vem\b", re.I), 7),  # i18n-allow
)
_IN_DAYS = re.compile(
    r"\b(?:in|en|em|daqui a) (\d{1,2}) (?:days?|tagen?|d[ií]as?)\b",  # i18n-allow
    re.IGNORECASE,
)
_ON_WEEKDAY = re.compile(
    r"\b(?:on|by|this|next|am|bis|el|este|pr[oó]ximo|na|no|at[eé])\s+("  # i18n-allow
    + "|".join(_WEEKDAYS)
    + r")\b",
    re.IGNORECASE,
)
@dataclass(frozen=True)
class OpenLoop:
    """One detected commitment: what, and the day it is due."""

    what: str
    due: date
    said: str

    @property
    def text(self) -> str:
        return f"Open loop: {self.what}"


def _due_day(sentence: str, today: date) -> tuple[date, str] | None:
    """The day a sentence points at and the phrase that said so, else ``None``."""
    for pattern, offset in _RELATIVE_DAYS:
        match = pattern.search(sentence)
        if match:
            return today + timedelta(days=offset), match.group(0)
    match = _IN_DAYS.search(sentence)
    if match:
        return today + timedelta(days=min(60, int(match.group(1)))), match.group(0)
    match = _ON_WEEKDAY.search(sentence)
    if match:
        weekday = _WEEKDAYS[match.group(1).lower()]
        ahead = (weekday - today.weekday()) % 7 or 7
        return today + timedelta(days=ahead), match.group(0)
    return None


def _clean_what(what: str) -> str:
    """The plan without the day phrase and without a short trailing aside
    ("send the report, promise" -> "send the report"; names after a comma stay)."""
    what = " ".join(what.split()).strip(" ,;:-")
    head, sep, tail = what.rpartition(",")
    if sep and len(tail.split()) <= 2:
        what = head.strip(" ,;:-")
    return what[:_MAX_WHAT_CHARS].rstrip(" ,;:-")


def _today_in(timezone: str) -> date:
    """Today's date where the person is: just after midnight Berlin time it is
    still yesterday in UTC, and "tomorrow" must not land a day early."""
    try:
        zone: Any = ZoneInfo(timezone) if timezone else UTC
    except Exception:  # noqa: BLE001 — an unknown zone falls back to UTC
        zone = UTC
    return datetime.now(zone).date()


def detect(text: str, *, today: date | None = None, timezone: str = "") -> list[OpenLoop]:
    """The commitments with a date in ``text``, at most a few per message.

    A sentence counts when it has a first-person commitment and a day word.
    Questions are left alone: "should I call Max tomorrow?" is not a plan.
    ``today`` defaults to the date in ``timezone`` (the person's own zone).
    """
    today = today or _today_in(timezone)
    loops: list[OpenLoop] = []
    seen: set[str] = set()
    pieces = _SENTENCE_SPLIT.split(text or "")
    for index in range(0, len(pieces), 2):
        sentence = " ".join(_GREETINGS.sub(" ", pieces[index]).split())
        closing = pieces[index + 1] if index + 1 < len(pieces) else ""
        if not sentence or "?" in closing:
            continue
        for pattern in _COMMITMENTS:
            match = pattern.search(sentence)
            if match is None:
                continue
            when = _due_day(sentence, today)
            if when is None:
                break
            due, phrase = when
            what = _clean_what(match.group("what").replace(phrase, ""))
            key = what.casefold()
            if len(what) < 3 or key in seen:
                break
            seen.add(key)
            loops.append(OpenLoop(what=what, due=due, said=sentence[:300]))
            break
        if len(loops) >= _MAX_LOOPS_PER_TURN:
            break
    return loops


def _due_at(due: date, timezone: str) -> str:
    """``DUE_HOUR`` local on the due day, as the vault writes times (UTC, seconds)."""
    try:
        zone: Any = ZoneInfo(timezone) if timezone else UTC
    except Exception:  # noqa: BLE001 — an unknown zone falls back to UTC
        zone = UTC
    local = datetime.combine(due, time(hour=DUE_HOUR), tzinfo=zone)
    return local.astimezone(UTC).isoformat(timespec="seconds")


def _vault() -> Any | None:
    try:
        from dodaios.memory.vault.runtime import active
    except Exception:  # noqa: BLE001 — no vault package: no open loops
        return None
    return active()


def note_user_text(text: str, *, session_id: str = "", timezone: str = "") -> int:
    """Remember every dated commitment in ``text``; returns how many were added.

    Blocking (SQLite); a missing vault or a refused write is not an error.
    """
    vault = _vault()
    if vault is None:
        return 0
    added = 0
    for loop in detect(text, timezone=timezone):
        try:
            result = vault.remember(
                loop.text,
                "project",
                origin="inferred",
                confidence=0.7,
                due_at=_due_at(loop.due, timezone),
                source={"via": VIA, "session": session_id, "said": loop.said},
            )
        except Exception:  # noqa: BLE001 — a loop that cannot be saved is simply not asked back
            log.warning("open loops: memory write failed", exc_info=True)
            continue
        if result.action == "added":
            added += 1
    if added:
        try:
            from dodaios.memory.vault.runtime import changed

            changed()
        except Exception:  # noqa: BLE001 — the memory is saved; the cache catches up later
            log.debug("open loops: vault change signal failed", exc_info=True)
    return added


def due_loops() -> list[Any]:
    """Current open-loop memories whose due time has passed, oldest first."""
    vault = _vault()
    if vault is None:
        return []
    try:
        memories = vault.upcoming(days=0)
    except Exception:  # noqa: BLE001 — no loops is the honest answer
        log.warning("open loops: vault read failed", exc_info=True)
        return []
    return [m for m in memories if (m.source or {}).get("via") == VIA]


def mark_asked(memory_ids: list[str]) -> int:
    """Close the loops that were asked back; returns how many were closed."""
    vault = _vault()
    if vault is None:
        return 0
    closed = 0
    for memory_id in memory_ids:
        try:
            closed += int(vault.invalidate(memory_id, reason="asked back once"))
        except Exception:  # noqa: BLE001 — an unclosable loop is logged, not fatal
            log.warning("open loops: could not close %s", memory_id, exc_info=True)
    return closed


__all__ = ["DUE_HOUR", "VIA", "OpenLoop", "detect", "due_loops", "mark_asked", "note_user_text"]
