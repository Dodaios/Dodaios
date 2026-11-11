"""What the owner's phone chat gets: short, conclusions first, one question.

The lead takes as little of the owner's attention as it can. In an instant
message chat (Telegram, a Discord DM, WhatsApp) it behaves like a good
colleague: one confirmation, silence while it works, then a short message
only when a decision is needed, a result is ready or it cannot finish.

Two halves keep that promise:

* :data:`STYLE_BLOCK` goes into the turn prompt of a message that came from
  such a chat (the model is asked to write short and plain);
* :func:`enforce` is deterministic and runs on what is *sent*: a reply over the
  word cap becomes a short summary plus a pointer to the app, a reply with
  several questions keeps the first. The full answer stays in the lead
  conversation; only the phone copy is shortened.

Voice and desk chat never pass through here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

#: Words a phone message may have. A hard cap, not a target.
WORD_CAP: Final[int] = 100

#: The channels this contract covers (instant-message chats).
IM_CHANNELS: Final[frozenset[str]] = frozenset({"telegram", "discord", "whatsapp"})

#: Added to the turn prompt of a message written away from the desk.
STYLE_BLOCK: Final[str] = (
    "[Channel style: this message came from the owner's phone chat. Write the "
    f"reply for a small screen: at most {WORD_CAP} words, the conclusion first, "
    "plain sentences, no headings, no tables, no tool or step traces and no "
    "reasoning. Ask at most one question, and only when you cannot go on "
    "without the answer. For detail, say it is in the app instead of pasting it. "
    "Do not send progress chatter: work silently and answer once the result is "
    "ready, a decision is needed or you cannot finish.]"
)

_POINTERS: Final[dict[str, str]] = {
    "en": "Full answer in the app.",
    "de": "Die ganze Antwort steht in der App.",  # i18n-allow: phone line
    "es": "La respuesta completa está en la app.",  # i18n-allow: phone line
    "pt": "A resposta completa está na app.",  # i18n-allow: phone line
}

_FENCE = re.compile(r"```.*?```", re.DOTALL)
_URL = re.compile(r"https?://\S+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=\S)")
_CLAUSE_END = re.compile(r"(?<=[;:,])\s+(?=\S)")
_HOLD = "\u0001{}\u0001"
_HELD = re.compile("\u0001(\\d+)\u0001")


@dataclass(frozen=True, slots=True)
class ChannelText:
    """The text to send and whether it is a shortened copy of the full answer."""

    text: str
    shortened: bool = False


def words(text: str) -> int:
    return len(text.split())


def _protect(text: str) -> tuple[str, list[str]]:
    """Swap code blocks and links for one-word markers so they never split."""
    held: list[str] = []

    def hold(match: re.Match[str]) -> str:
        held.append(match.group(0))
        return _HOLD.format(len(held) - 1)

    return _URL.sub(hold, _FENCE.sub(hold, text)), held


def _restore(text: str, held: list[str]) -> str:
    return _HELD.sub(lambda m: held[int(m.group(1))], text)


def _units(text: str) -> list[str]:
    """Sentences, with a long one split further at its clause breaks."""
    units: list[str] = []
    for paragraph in re.split(r"\n\s*\n|\n(?=[-*\u2022] |\d+[.)] )", text):
        paragraph = " ".join(paragraph.split())
        if not paragraph:
            continue
        units.extend(s for s in _SENTENCE_END.split(paragraph) if s)
    return units


def _held_words(unit: str, held: list[str]) -> int:
    return words(_restore(unit, held))


def one_question(text: str) -> str:
    """Keep the statements and only the first question, which comes last."""
    protected, held = _protect(text)
    units = _units(protected)
    questions = [u for u in units if u.rstrip().endswith("?")]
    if len(questions) <= 1:
        return text
    kept = [u for u in units if u not in questions]
    kept.append(questions[0])
    return _restore("\n".join(kept), held)


def shorten(text: str, *, cap: int, pointer: str) -> str:
    """A summary of at most ``cap`` words made of whole sentences (or clauses).

    Code blocks and links stay intact. A first sentence that alone is over the
    budget is cut at a clause break, then at a word boundary with an ellipsis.
    """
    budget = max(cap - words(pointer), 10)
    protected, held = _protect(text)
    chosen: list[str] = []
    used = 0
    for unit in _units(protected):
        size = _held_words(unit, held)
        if used + size > budget:
            if not chosen:
                chosen.append(_cut(unit, held, budget))
            break
        chosen.append(unit)
        used += size
    summary = _restore(" ".join(chosen), held).strip()
    return f"{summary}\n{pointer}" if summary else pointer


def _cut(unit: str, held: list[str], budget: int) -> str:
    """The longest clause-bounded prefix of an over-long sentence, else a word cut."""
    pieces = _CLAUSE_END.split(unit)
    out = ""
    for piece in pieces:
        candidate = f"{out} {piece}".strip()
        if _held_words(candidate, held) > budget:
            break
        out = candidate
    if out:
        return out.rstrip(",;:") + "."
    # No clause fits: cut at a word, never inside a held code block or link.
    tokens = unit.split()
    take: list[str] = []
    total = 0
    for token in tokens:
        size = _held_words(token, held)
        if total + size > budget:
            break
        take.append(token)
        total += size
    return (" ".join(take).rstrip(",;:") + "\u2026") if take else ""


def enforce(answer: str, *, language: str = "en", cap: int = WORD_CAP) -> ChannelText:
    """The phone copy of ``answer``: one question, at most ``cap`` words."""
    text = one_question((answer or "").strip())
    if words(text) <= cap:
        return ChannelText(text, shortened=text != (answer or "").strip())
    pointer = _POINTERS.get(language) or _POINTERS["en"]
    return ChannelText(shorten(text, cap=cap, pointer=pointer), shortened=True)


__all__ = ["IM_CHANNELS", "STYLE_BLOCK", "WORD_CAP", "ChannelText", "enforce", "one_question",
           "shorten", "words"]
