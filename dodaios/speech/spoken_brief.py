"""The day's brief, spoken in a call, with follow-ups kept in the same call.

"What's on today?" used to be an ordinary brain turn: a model call with
tools, ten seconds of thinking, and an answer that knew nothing of the
morning brief the lead routine had already written. This module answers it
without a model turn:

1. the brief the lead routine posted into the conversation TODAY
   (``agent_chat/proactive.py``; a ``society_result`` notice of the routine
   tagged ``lead-brief:morning``), read back in a form made for the ear —
   headings and bullets gone, links reduced to their words;
2. otherwise the memory vault's dated memories that fall due today (calendar
   appointments mirrored by ``memory/vault/calendar_sync.py``, deadlines the
   person asked to be reminded of), composed into a few spoken sentences;
3. nothing known: one honest sentence.

Both voice paths use it. The classic pipeline speaks the result itself and
seeds the brain's history with the exchange, so "move that to 3 pm" is a
normal brain turn that resolves "that" against the brief and changes the
calendar through the calendar tool. The live session exposes it as the
``today_brief`` tool (``dodaios/live/tools.py``), so the provider's model
reads the same text and the follow-up stays in the same call.

Reads are SQLite and run off the event loop. Nothing here bills a key.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Final

from dodaios.i18n import catalog as i18n_catalog

log = logging.getLogger(__name__)

#: How much of a written brief is read aloud before it stops at a sentence.
SPOKEN_MAX_CHARS: Final[int] = 1400

_INTENT_RE: Final[re.Pattern[str]] = re.compile(
    r"""
    (?:
      \bwhat(?:'s|\s+is|\s+do\s+i\s+have|\s+have\s+i\s+got)\s+(?:on|up|planned|happening|going\s+on)?\s*(?:for\s+)?(?:today|my\s+day|the\s+day)\b
    | \b(?:my|the)\s+day\s+today\b
    | \btoday'?s\s+(?:brief(?:ing)?|agenda|schedule|plan)\b
    | \b(?:morning|daily)\s+brief(?:ing)?\b
    | \bbrief\s+me\b
    | \banything\s+(?:on|planned|up)\s+(?:for\s+)?today\b
    | \bwas\s+(?:steht|liegt)\s+heute\s+an\b
    | \bwas\s+(?:habe|hab)\s+ich\s+heute\b
    | \bmein\s+tag\s+heute\b
    | \bwie\s+sieht\s+mein\s+tag\s+aus\b
    | \btages(?:briefing|übersicht|plan)\b  # i18n-allow: spoken German request forms
    | \bbriefing\b
    | \bqu[ée]\s+(?:tengo|hay)\s+(?:para\s+)?hoy\b
    | \bmi\s+d[ií]a\s+(?:de\s+)?hoy\b
    | \bresumen\s+del\s+d[ií]a\b
    | \bo\s+que\s+(?:tenho|h[áa])\s+(?:para\s+)?hoje\b
    | \b(?:meu|o\s+meu)\s+dia\s+hoje\b
    | \bresumo\s+do\s+dia\b
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MD_MARK_RE = re.compile(r"[*_`~]+")
_MD_LEAD_RE = re.compile(r"^\s*(?:#{1,6}\s*|[-*•]\s+|\d+[.)]\s+|>\s*)")
_WS_RE = re.compile(r"\s+")
_DUE_TAIL_RE = re.compile(r"\s+on\s+\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?(?=\s*[(.]|\s*$)")
_TIME_RE = re.compile(r"T?(\d{2}):(\d{2})")


def is_brief_request(text: str) -> bool:
    """Whether ``text`` asks for the day's brief (en / de / es / pt)."""
    return bool(text) and _INTENT_RE.search(text) is not None


def spoken_form(markdown: str, *, max_chars: int = SPOKEN_MAX_CHARS) -> str:
    """A written brief as something to say: no markup, sentences, a ceiling."""
    sentences: list[str] = []
    for raw in str(markdown or "").splitlines():
        line = _MD_LINK_RE.sub(r"\1", raw)
        line = _MD_LEAD_RE.sub("", line)
        line = _MD_MARK_RE.sub("", line)
        line = _WS_RE.sub(" ", line).strip()
        if not line:
            continue
        if line[-1] not in ".!?:":
            line += "."
        sentences.append(line)
    text = " ".join(sentences)
    if len(text) <= max_chars:
        return text
    cut = text.rfind(". ", 0, max_chars)
    return text[: cut + 1] if cut > 0 else text[:max_chars].rstrip() + "."


def _local_date(value: str) -> str:
    return str(value or "")[:10]


def _time_of(value: str) -> str:
    match = _TIME_RE.search(str(value or "")[10:])
    if not match:
        return ""
    return f"{match.group(1)}:{match.group(2)}"


def _item_text(memory: Any) -> str:
    text = str(getattr(memory, "text", "") or "").strip()
    text = re.sub(r"^(?:Appointment|Termin|Cita|Compromisso):\s*", "", text)
    text = _DUE_TAIL_RE.sub("", text)
    return text.rstrip(".")


def compose_from_memories(
    memories: list[Any], *, now: datetime, language: str | None
) -> str:
    """Today's dated memories (and anything overdue) as a few sentences."""
    today = now.strftime("%Y-%m-%d")
    due_today: list[Any] = []
    overdue: list[Any] = []
    for memory in memories:
        due = _local_date(getattr(memory, "due_at", "") or "")
        if not due:
            continue
        if due == today:
            due_today.append(memory)
        elif due < today:
            overdue.append(memory)
    if not due_today and not overdue:
        return i18n_catalog.t("speech.brief.nothing", language)
    parts: list[str] = []
    if due_today:
        items = []
        for memory in due_today[:8]:
            when = _time_of(str(getattr(memory, "due_at", "") or ""))
            text = _item_text(memory)
            items.append(
                i18n_catalog.t("speech.brief.item_at", language, time=when, text=text)
                if when
                else text
            )
        more = len(due_today) - len(items)
        listed = "; ".join(items)
        if more > 0:
            listed += " " + i18n_catalog.t("speech.brief.more", language, count=more)
        parts.append(i18n_catalog.t("speech.brief.today", language, items=listed))
    if overdue:
        items = [_item_text(memory) for memory in overdue[:4]]
        parts.append(i18n_catalog.t("speech.brief.open", language, items="; ".join(items)))
    return " ".join(part if part.endswith((".", "!", "?")) else part + "." for part in parts)


def written_brief_today(events: list[dict[str, Any]], *, task_id: str, now: datetime) -> str | None:
    """The brief routine's result posted today, newest first; ``None`` if none."""
    if not task_id:
        return None
    today = now.strftime("%Y-%m-%d")
    for event in reversed(events):
        if str(event.get("kind") or "") != "notice":
            continue
        payload = event.get("payload") or {}
        if not isinstance(payload, dict) or payload.get("kind") != "society_result":
            continue
        if str(payload.get("task_id") or "") != task_id:
            continue
        try:
            posted = datetime.fromtimestamp(int(event.get("ts_ms") or 0) / 1000)
        except (TypeError, ValueError, OSError, OverflowError):
            # A notice without a readable timestamp cannot be "today's".
            continue
        if posted.strftime("%Y-%m-%d") != today:
            return None
        text = str(payload.get("text") or "").strip()
        return text or None
    return None


def _read_written_brief(task_id: str, now: datetime) -> str | None:
    """Blocking: the lead conversation's brief of today (SQLite)."""
    from dodaios.agent_chat.lead import lead_session
    from dodaios.society.runtime import current_runtime

    runtime = current_runtime()
    svc = runtime.chat_service() if runtime is not None else None
    if svc is None:
        return None
    session = lead_session(svc, create=False)
    if session is None:
        return None
    events = svc.store.list_events(session.session_id, tail=400)
    return written_brief_today(events, task_id=task_id, now=now)


def _read_upcoming() -> list[Any]:
    """Blocking: the vault's dated memories inside the next day (SQLite)."""
    from dodaios.memory.vault import runtime as vault_runtime

    vault = vault_runtime.active()
    if vault is None:
        return []
    return list(vault.upcoming(days=1))


async def _brief_task_id() -> str:
    try:
        from dodaios.agent_chat.proactive import brief_state

        state = await brief_state()
        return str(state.get("task_id") or "")
    except Exception:  # noqa: BLE001 — no routine means no written brief, nothing more
        log.debug("spoken brief: brief routine state unavailable", exc_info=True)
        return ""


async def build(*, language: str | None, now: datetime | None = None) -> str:
    """The brief to say now, in ``language``; never raises, never empty."""
    moment = now or datetime.now()
    try:
        task_id = await _brief_task_id()
        if task_id:
            written = await asyncio.to_thread(_read_written_brief, task_id, moment)
            if written:
                spoken = spoken_form(written)
                if spoken:
                    return spoken
    except Exception:  # noqa: BLE001 — the written brief is the first choice, not the only one
        log.debug("spoken brief: written brief unavailable", exc_info=True)
    try:
        memories = await asyncio.to_thread(_read_upcoming)
    except Exception:  # noqa: BLE001 — a vault that cannot be read means nothing is known
        log.debug("spoken brief: vault unavailable", exc_info=True)
        memories = []
    return compose_from_memories(memories, now=moment, language=language)


__all__ = [
    "SPOKEN_MAX_CHARS",
    "build",
    "compose_from_memories",
    "is_brief_request",
    "spoken_form",
    "written_brief_today",
]
