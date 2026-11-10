""""What's this?" in the lead conversation: "this" is what is on screen.

When the person types (or a call hands over) "summarize this", "turn this
mail into a calendar event" or "what is that?", the pronoun points at the
window in front of them, not at the conversation. With Screen Context switched
on, the lead's turn therefore carries one fresh, privacy-filtered capture of
the screen: the picture saved in the chat's own folder, the visible text, and
the model note that says what the picture is and what was withheld
(:func:`dodaios.screen_context.turn.model_note`).

Rules this module keeps:

* **One switch.** Nothing happens unless ``[screen_context].enabled`` is on —
  the same switch every other look obeys. There is no second setting.
* **Ask-shaped, never ambient.** Only a message that refers to something by a
  deictic ("this", "that mail", "das hier", "esto") gets a capture. Ordinary
  messages pass through untouched and never start the capture stack.
* **No question back.** An ambiguous "what is that?" is resolved by looking,
  not by a clarifying question (the person turned Screen Context on). The note
  tells the model to ignore the picture when the message plainly meant the
  conversation.
* **Looking is not operating.** A request to click or type on the screen is
  Computer-Use's, and is left alone here.
* **Fails quiet.** Any failure costs the picture, never the turn.

The vocabulary below is speech/typing *input matching data* (de/en/es/pt), the
closed-list exception of the language policy, like ``screen_context/intent.py``.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Final

log = logging.getLogger(__name__)

#: Set while a message from away from the desk (the owner's Telegram chat, a
#: Discord DM) is sent into the lead conversation: "this" there cannot mean
#: the screen of a computer nobody is sitting at.
_AWAY: ContextVar[bool] = ContextVar("dodaios.screen_reference.away", default=False)


def is_away() -> bool:
    """Whether the message being sent now was written away from the desk."""
    return _AWAY.get()


@contextmanager
def away_from_screen(away: bool = True) -> Iterator[None]:
    """Mark the messages sent inside this block as not written at the screen.

    ``away=False`` marks them as written at the desk (a queued desk message
    drained by a task that a phone message created).
    """
    token = _AWAY.set(away)
    try:
        yield
    finally:
        _AWAY.reset(token)

#: Longer messages are documents pasted in, not a pointer at the screen.
MAX_WORDS: Final[int] = 60

# Input folding: German letters are matched below as ae / oe / ue / ss.
_FOLD: Final = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})  # i18n-allow

# Things a person points at on a screen. A deictic determiner followed by one of
# these ("this mail" and its de/es/pt forms) names the screen.
_THINGS: Final[str] = (
    r"(?:e-?mails?|mails?|messages?|pages?|documents?|docs?|files?|texts?|articles?|"
    r"invoices?|errors?|tables?|lists?|forms?|events?|invitations?|invites?|pictures?|"
    r"images?|photos?|screenshots?|windows?|tabs?|sites?|websites?|posts?|tweets?|threads?|"
    r"chats?|offers?|orders?|receipts?|tickets?|charts?|graphs?|slides?|emails?|"
    # German / Spanish / Portuguese  i18n-allow: input vocabulary
    r"nachricht(?:en)?|seite|dokument|datei|artikel|rechnung|fehler(?:meldung)?|"  # i18n-allow
    r"tabelle|liste|formular|termin|einladung|bild|fenster|bestellung|angebot|"  # i18n-allow
    r"correo|mensaje|pagina|documento|archivo|texto|articulo|factura|tabla|"  # i18n-allow
    r"formulario|evento|invitacion|imagen|ventana|pestana|pedido|"  # i18n-allow
    r"mensagem|ficheiro|arquivo|artigo|fatura|erro|tabela|convite|janela|separador|"  # i18n-allow
    r"encomenda)"  # i18n-allow
)

_POINTED_THING_RE: Final = re.compile(
    r"\b(?:this|that|these|those)\s+(?:\w+\s+)?" + _THINGS + r"\b"
    r"|\b(?:diese[nrms]?|die\s+hier|das\s+hier|der\s+hier)\s+(?:\w+\s+)?"  # i18n-allow: DE
    + _THINGS
    + r"\b"
    r"|\b(?:die|das|den)\s+" + _THINGS + r"\s+(?:hier|da)\b"  # i18n-allow: DE
    r"|\b(?:este|esta|estos|estas|ese|esa|esos|esas)\s+(?:\w+\s+)?" + _THINGS + r"\b"
    r"|\b(?:esse|essa|esses|essas)\s+(?:\w+\s+)?" + _THINGS + r"\b",
    re.IGNORECASE,
)

# A verb that acts on "this" with the pronoun alone ("summarize this",
# "fass das zusammen", "traduce esto"). The pronoun must be an object, so it
# follows the verb directly or after a preposition.
_ACT_ON_IT_RE: Final = re.compile(
    r"\b(?:summari[sz]e|translate|explain|proofread|rewrite|reply\s+to|respond\s+to|"
    r"answer|read|save|remember|track|forward|turn|convert|copy|note|check)\s+"
    r"(?:this|that|these|those|it\s+here)\b(?!\s+(?:is|was|we|you|i|one|time|way|much|many)\b)"
    # Typed contractions the speech classifier does not see ("what's this?").
    r"|\bwhat['’]?s\s+(?:this|that)(?:\s+(?:here|there|now))?\s*[.?!]*\s*$"
    r"|\bwhat\s+does\s+(?:this|that)\s+(?:say|mean)\b"
    # German  i18n-allow: input vocabulary
    r"|\b(?:fass|uebersetz|uebersetze|erklaer|erklaere|beantworte|speicher|speichere|"  # i18n-allow
    r"merk|lies|pruef|pruefe|antworte\s+auf)\s+(?:mir\s+)?(?:mal\s+)?"  # i18n-allow
    r"(?:das|dies|diese[ns]?|das\s+hier)\b"  # i18n-allow
    r"|\bwas\s+steht\s+(?:da|hier)\b"  # i18n-allow
    # Spanish / Portuguese  i18n-allow: input vocabulary
    r"|\b(?:resume|resumeme|traduce|traduceme|explica|explicame|responde\s+a|"  # i18n-allow
    r"contesta|"  # i18n-allow
    r"guarda|lee)\s+(?:esto|eso)\b"  # i18n-allow
    r"|\b(?:resume|traduz|explica|responde\s+a|guarda|le)\s+(?:isto|isso)\b",  # i18n-allow
    re.IGNORECASE,
)


def _fold(text: str) -> str:
    folded = (text or "").casefold().translate(_FOLD)
    decomposed = unicodedata.normalize("NFKD", folded)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def refers_to_screen(text: str) -> bool:
    """Whether ``text`` points at something on the screen with a deictic.

    Deterministic regex, no model call (the turn must not wait for one). A
    Screen Context look request ("what's on my screen", "what is this?") counts
    through the shared classifier, so the two vocabularies cannot drift apart;
    an operation request ("click this button") never counts.
    """
    said = (text or "").strip()
    if not said or len(said.split()) > MAX_WORDS:
        return False
    from dodaios.screen_context import intent as intent_module

    try:
        verdict = intent_module.classify(said)
        if verdict.intent.value != "none":
            return True
        folded = _fold(said)
        if intent_module.requests_screen_operation(folded):
            return False
    except Exception:  # noqa: BLE001 — a classifier defect means "no look", never a broken turn
        log.warning("screen reference: classifier failed", exc_info=True)
        return False
    return bool(_POINTED_THING_RE.search(folded) or _ACT_ON_IT_RE.search(folded))


def _switch_on() -> bool:
    try:
        from dodaios.core.config import load_config

        block = getattr(load_config(), "screen_context", None)
        return bool(getattr(block, "enabled", True)) if block is not None else True
    except Exception:  # noqa: BLE001 — an unreadable config never turns the screen on
        log.warning("screen reference: config unreadable", exc_info=True)
        return False


_LEAD_IN: Final[str] = (
    "The user's message points at something with 'this' or 'that'. Screen Context is on, so "
    "a capture of their screen taken just now is attached below: resolve the reference "
    "against it. If the message plainly refers to our conversation instead, ignore the "
    "capture and do not mention it."
)


def _saved_picture(cwd: str, image: bytes, mime: str) -> str:
    """Store the capture in the chat's folder; returns its relative path or ""."""
    from dodaios.agentic_ide import drops

    suffix = ".png" if "png" in (mime or "") else ".jpg"
    try:
        stored = drops.store(cwd, [(f"screen{suffix}", image)])
    except (drops.DropError, OSError) as exc:
        log.info("screen reference: capture not saved in the chat folder (%s)", exc)
        return ""
    return stored[0].relative_path if stored else ""


async def screen_context_block(
    text: str,
    *,
    session_id: str,
    cwd: str,
    locale: str = "",
    bus: Any | None = None,
) -> str:
    """The block a lead turn carries when ``text`` points at the screen, or "".

    Captured: the lead-in, where the picture was saved, its reference id, and
    the model note (with the visible text). Refused by a privacy rule: one line
    saying the screen could not be used, so the model does not guess.
    Anything else (switch off, no deictic, capture failure): "".
    """
    if _AWAY.get() or not refers_to_screen(text) or not _switch_on():
        return ""
    from dodaios.screen_context.turn import screen_context_for_turn

    try:
        outcome = await screen_context_for_turn(
            text, locale=locale or "en", bus=bus, force=True, allow_pending_appshot=False
        )
    except Exception:  # noqa: BLE001 — a failed look costs the picture, never the turn
        log.warning("screen reference: capture failed", exc_info=True)
        return ""
    if outcome.status == "refused" and outcome.message:
        return (
            "The user's message points at something on screen, but the screen could not be "
            f"used: {outcome.message} Say so in one short sentence if it matters."
        )
    if not outcome.has_image or outcome.image is None:
        return ""
    parts = [_LEAD_IN]
    saved = await asyncio.to_thread(_saved_picture, cwd, outcome.image, outcome.mime)
    if saved:
        parts.append(f"The capture is saved in this chat's folder as {saved}; open it to look.")
    try:
        from dodaios.core.image_references import get_store, instruction

        ref = get_store().add(
            "chat:" + session_id, outcome.image, outcome.mime, source="screen"
        )
        parts.append(instruction([ref]))
    except Exception:  # noqa: BLE001 — the reference id is a convenience for hand-offs
        log.info("screen reference: image reference not registered", exc_info=True)
    if outcome.note:
        parts.append(outcome.note)
    log.info("screen reference: attached a screen capture to the lead turn")
    return "\n\n".join(parts)


__all__ = ["MAX_WORDS", "away_from_screen", "refers_to_screen", "screen_context_block"]
