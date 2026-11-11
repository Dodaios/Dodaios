"""Deterministic extractors: what is in data the assistant already has.

Pure functions over plain data, no model, no network. Each returns
:class:`~dodaios.life_admin.model.Found` records; the ledger decides what is
new. Mail and calendar text is outside data: it is cleaned and shortened, and
it only ever becomes a title, never an instruction.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from typing import Any, Final

from .model import Found, clean

#: How far ahead a dated item is noticed at all.
HORIZON_DAYS: Final[int] = 60
#: How far back a dated item still counts (an unpaid bill, a missed deadline).
LOOKBACK_DAYS: Final[int] = 30

_MONTHS: Final[dict[str, int]] = {}
for _month, _names in enumerate(
    (
        "january jan januar januario janeiro enero ene",
        "february feb februar febrero fevereiro fev",
        "march mar märz maerz marzo março marco",
        "april apr abril",
        "may mai mayo maio",
        "june jun juni junio junho",
        "july jul juli julio julho",
        "august aug agosto ago",
        "september sep sept septiembre setembro set",
        "october oct oktober octubre outubro out",
        "november nov noviembre novembro",
        "december dec dezember diciembre dezembro dez dic",
    ),
    start=1,
):
    for _name in _names.split():
        _MONTHS[_name] = _month

_MONTH_WORDS = "|".join(sorted(_MONTHS, key=len, reverse=True))
_ISO = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)(?!\d)")
_NUMERIC = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4}|\d{2})\b")
_NUMERIC_SHORT = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(?!\d)")
_DAY_MONTH = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th|\.)?\s+(?:of\s+|de\s+)?({_MONTH_WORDS})\b\.?"
    r"(?:,?\s+(\d{4}))?",
    re.IGNORECASE,
)
_MONTH_DAY = re.compile(
    rf"\b({_MONTH_WORDS})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?",
    re.IGNORECASE,
)
#: Words that point at the due date of what follows.
_DUE_WORDS = re.compile(
    r"\b(?:due|by|before|until|expires?|expiring|expiry|renews?|deadline|on|"
    r"fällig|bis|spätestens|läuft ab|frist|am|vence|vencimiento|até|vencimento)\b",
    re.IGNORECASE,
)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:  # 31 February and the like are not dates
        return None


def _year(text: str) -> int:
    value = int(text)
    return 2000 + value if value < 100 else value


def _next_occurrence(month: int, day: int, today: date) -> date | None:
    """The next ``month``/``day`` on or after today (29 February falls on 1 March)."""
    for year in (today.year, today.year + 1, today.year + 2):
        found = _safe_date(year, month, day)
        if found is None and (month, day) == (2, 29):
            found = date(year, 3, 1)
        if found is not None and found >= today:
            return found
    return None


def find_dates(text: str, today: date) -> list[tuple[int, date]]:
    """Every date written in ``text`` as ``(position, date)``, in reading order.

    Understands ``2026-11-15``, ``15.11.2026``, ``15/11/26``, ``15 November 2026``,
    ``November 15`` and ``15. Nov`` (English, German, Spanish, Portuguese month
    names). A date without a year is the next one on or after today.
    """
    out: list[tuple[int, date]] = []
    for m in _ISO.finditer(text):
        d = _safe_date(int(m[1]), int(m[2]), int(m[3]))
        if d:
            out.append((m.start(), d))
    for m in _NUMERIC.finditer(text):
        first, second, year = int(m[1]), int(m[2]), _year(m[3])
        day, month = (first, second) if second <= 12 else (second, first)
        d = _safe_date(year, month, day)
        if d:
            out.append((m.start(), d))
    for m in _NUMERIC_SHORT.finditer(text):
        d = _next_occurrence(int(m[2]), int(m[1]), today)
        if d:
            out.append((m.start(), d))
    for pattern, order in ((_DAY_MONTH, "dm"), (_MONTH_DAY, "md")):
        for m in pattern.finditer(text):
            day, month = (int(m[1]), _MONTHS[m[2].lower()]) if order == "dm" else (
                int(m[2]), _MONTHS[m[1].lower()])
            if m[3]:
                d = _safe_date(int(m[3]), month, day)
            else:
                d = _next_occurrence(month, day, today)
            if d:
                out.append((m.start(), d))
    return sorted(out)


def due_date(text: str, today: date) -> date | None:
    """The date ``text`` says something is due: one right after a due word, else the first."""
    dates = find_dates(text, today)
    if not dates:
        return None
    for position, found in dates:
        window = text[max(0, position - 40):position]
        if _DUE_WORDS.search(window):
            return found
    return dates[0][1]


def in_range(due: date | None, today: date) -> bool:
    return due is None or today - timedelta(days=LOOKBACK_DAYS) <= due <= today + timedelta(
        days=HORIZON_DAYS
    )


# -- kinds from words ---------------------------------------------------------

_BIRTHDAY = re.compile(
    r"\b(?:birthday|b-day|anniversary|wedding day|geburtstag|hochzeitstag|jahrestag|jubiläum|"
    r"cumplea[ñn]os|aniversario|anivers[aá]rio)\b",
    re.IGNORECASE,
)
_BILL = re.compile(
    r"\b(?:invoice|bill|payment (?:is )?due|amount due|balance due|overdue|rechnung|"
    r"zahlungserinnerung|mahnung|zu zahlen|fällig|factura|fatura|pagamento|pago)\b",
    re.IGNORECASE,
)
_RENEWAL = re.compile(
    r"\b(?:renew(?:al|s|ed)?|will renew|auto-renew|expires?|expiring|expiry|subscription|"
    r"membership|verlängerung|verlängert sich|läuft ab|abo|kündigungsfrist|vencimiento|"
    r"renovaci[oó]n|renova[cç][aã]o|vence)\b",
    re.IGNORECASE,
)
_APPOINTMENT = re.compile(
    r"\b(?:book (?:an? )?appointment|schedule (?:an? )?appointment|make an appointment|"
    r"appointment to book|check-?up due|due for a check-?up|termin (?:vereinbaren|buchen)|"
    r"terminerinnerung|cita pendiente|agendar consulta)\b",
    re.IGNORECASE,
)
_SHOPPING = re.compile(
    r"\b(?:buy|groceries|grocery|restock|running (?:low|out)|need more|pick up|einkaufen|"
    r"besorgen|nachkaufen|ausgegangen|comprar|supermercado|compras)\b",
    re.IGNORECASE,
)
_DOCUMENT = re.compile(
    r"\b(?:passport|visa|tax return|tax declaration|steuererklärung|deadline|submit by|"
    r"hand in|abgabe|frist|id card|personalausweis|reisepass|licen[sc]e|documento|pasaporte|"
    r"declaraci[oó]n)\b",
    re.IGNORECASE,
)
_NOISE = re.compile(
    r"\b(?:sale|\d+\s?% off|discount|deals?|coupon|newsletter|webinar|unsubscribe|"
    r"rabatt|gutschein|angebot|oferta)\b",
    re.IGNORECASE,
)
_STRONG_BILL = re.compile(r"\b(?:invoice|rechnung|receipt|factura|fatura|payment due)\b", re.I)


def _kind_of_text(text: str) -> str | None:
    """The kind a piece of text is about; order matters (a bill beats a renewal)."""
    for kind, pattern in (
        ("birthday", _BIRTHDAY),
        ("appointment", _APPOINTMENT),
        ("bill", _BILL),
        ("renewal", _RENEWAL),
        ("document", _DOCUMENT),
        ("shopping", _SHOPPING),
    ):
        if pattern.search(text):
            return kind
    return None


# -- sources ------------------------------------------------------------------


def from_contacts(contacts: Iterable[Any], today: date) -> list[Found]:
    """A birthday per contact that has one, on its next date."""
    out: list[Found] = []
    for contact in contacts:
        raw = getattr(contact, "birthday", None)
        name = clean(getattr(contact, "name", "") or "")
        if not raw or not name:
            continue
        try:
            born = date.fromisoformat(str(raw))
        except ValueError:  # an unreadable birthday is skipped, not guessed
            continue
        due = _next_occurrence(born.month, born.day, today)
        if due is None or not in_range(due, today):
            continue
        out.append(
            Found(
                "birthday", f"{name}'s birthday", due,
                {"type": "contact", "ref": str(getattr(contact, "slug", "") or name)},
                subject=name,
            )
        )
    return out


_PERSON = re.compile(
    r"^(?P<name>[^\W\d_][\w .'-]{0,40}?)(?:'s|s'|’s)?\s+(?:birthday|anniversary|geburtstag)",
    re.IGNORECASE,
)
_PERSON_DE = re.compile(r"(?:geburtstag|birthday)\s+(?:of|von)\s+(?P<name>[^\W\d_][\w .'-]{0,40})",
                        re.IGNORECASE)
_PERSON_IS = re.compile(r"^(?P<name>[^\W\d_][\w'-]*(?: [^\W\d_][\w'-]*)?) (?:is|has|hat) ", re.I)


def _subject_of(text: str) -> str:
    for pattern in (_PERSON, _PERSON_DE):
        m = pattern.search(text.strip())
        if m:
            return clean(m["name"], 60)
    m = _PERSON_IS.match(text.strip())
    return clean(m["name"], 60) if m else ""


def from_memories(memories: Iterable[Any], today: date) -> list[Found]:
    """Vault facts with a date (due items and open loops) and birthdays named in text.

    A memory with ``due_at`` becomes an item of the kind its words say; an open
    loop is a follow-up; anything else dated is a deadline. A relationship or
    profile fact that names a birthday or anniversary and a day gets its next
    occurrence.
    """
    out: list[Found] = []
    for memory in memories:
        text = clean(getattr(memory, "text", ""), 300)
        if not text:
            continue
        source = getattr(memory, "source", None) or {}
        ref = str(getattr(memory, "id", "") or "")
        evidence = {"type": "vault", "ref": ref}
        due_at = getattr(memory, "due_at", None)
        if due_at:
            try:
                due = date.fromisoformat(str(due_at)[:10])
            except ValueError:  # an unreadable date leaves the memory out
                continue
            if not in_range(due, today):
                continue
            if source.get("via") == "open_loop":
                what = re.sub(r"^open loop:\s*", "", text, flags=re.IGNORECASE)
                out.append(Found("follow_up", clean(what), due, {**evidence, "type": "open_loop"}))
                continue
            kind = _kind_of_text(text) or "document"
            out.append(Found(kind, clean(text), due, evidence, subject=_subject_of(text)))
        elif _BIRTHDAY.search(text):
            dates = find_dates(text, today)
            if not dates:
                continue
            due = dates[0][1]
            if not in_range(due, today):
                continue
            subject = _subject_of(text) or clean(text, 60)
            out.append(Found("birthday", clean(text, 100), due, evidence, subject=subject))
    return out


def from_calendar(event: Mapping[str, Any], today: date) -> list[Found]:
    """A calendar entry that is a birthday, a deadline or an expiry.

    An ordinary appointment is already booked and stays in the calendar.
    """
    title = clean(str(event.get("title") or event.get("summary") or ""))
    if not title:
        return []
    kind = _kind_of_text(title)
    if kind not in ("birthday", "document", "renewal", "bill"):
        return []
    start = str(event.get("start") or event.get("date") or event.get("when") or "")
    due = due_date(start, today) or due_date(title, today)
    if due is None or not in_range(due, today):
        return []
    evidence = {"type": "calendar", "ref": str(event.get("id") or event.get("raw_ref") or "")}
    return [Found(kind, title, due, evidence, subject=_subject_of(title))]


def from_mail(mail: Mapping[str, Any], today: date) -> list[Found]:
    """An invoice, renewal, appointment prompt or deadline in a mail, by words.

    Marketing mail is left out unless it carries a strong bill word. A mail
    that says nothing this module recognises returns ``[]`` and may become a
    candidate for the model pass.
    """
    subject = clean(str(mail.get("subject") or mail.get("summary") or ""), 200)
    snippet = clean(str(mail.get("snippet") or mail.get("body") or mail.get("text") or ""), 600)
    text = f"{subject}. {snippet}"
    if not subject:
        return []
    if _NOISE.search(text) and not _STRONG_BILL.search(subject):
        return []
    kind = _kind_of_text(subject) or _kind_of_text(snippet)
    if kind not in ("bill", "renewal", "appointment", "document"):
        return []
    due = due_date(text, today)
    if not in_range(due, today):
        return []
    sender = clean(str(mail.get("sender") or mail.get("from") or ""), 80)
    evidence = {
        "type": "mail", "ref": str(mail.get("id") or mail.get("raw_ref") or ""), "sender": sender,
    }
    return [Found(kind, clean(subject), due, evidence)]


def is_candidate(mail: Mapping[str, Any]) -> bool:
    """A mail worth one cheap model look: a real subject, not obvious marketing."""
    subject = clean(str(mail.get("subject") or mail.get("summary") or ""))
    text = f"{subject} {mail.get('snippet') or ''}"
    return bool(subject) and not _NOISE.search(text)
