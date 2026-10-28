"""Search mandate for public-fact questions answered by an on-device model.

A small local model (Qwen3 1.7B on the BC-250) is not a trustworthy source of
public facts, and it does not reliably decide on its own to call ``search_web``.
Live 2026-10-28: asked about a train accident in Spain, it called no tool, wrote
"[used tool search_web]" as plain text and invented a story about luxury
wagons, while Claude, given the same question, searched and found the real
collision. The realtime voice path already grounds such turns through the
planner's ``requires_public_fact_grounding`` capability; the brain path used by
the chat and the Pipeline voice never asked the planner.

This module decides, from text alone (no model call, no I/O), whether the turn
must call ``search_web``. The brain reuses its evidence-mandate machinery: the
directive goes into the prompt, and an answer that claims facts while no search
ran is replaced by an honest phrase from this module. A short clarifying
question claims nothing, so it is kept: a vague question ("did you not see an
accident?") with no subject or place in the conversation should be answered
with a question, not with an invented event.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from dodaios.brain.turn_planner import plan_turn

SEARCH_TOOL = "search_web"
#: Evidence domain the brain records for this mandate; it picks the phrase below.
PUBLIC_FACT_DOMAIN = "public_fact_search"

PUBLIC_FACT_DIRECTIVE = (
    "MANDATORY THIS TURN: the person asks about public, real-world facts and "
    "you run on a small local model whose memory of such facts is not "
    "reliable. Call search_web before answering, and answer only from what "
    "the results say, naming the source. If the results do not answer the "
    "question, say so plainly; never fill the gap from memory. Never write "
    "'[used tool ...]' yourself: only a real tool call counts. If the question "
    "is too vague to search (no subject, place or time, and the conversation "
    "gives none), do not guess: ask one short clarifying question instead."
)

# Questions about the assistant itself and plain arithmetic have public-fact
# shapes ("who are you?", "how much is 12 times 7?") but no web answer.
_SELF_OR_MATH_RE = re.compile(
    r"\b(?:who are you|what(?:'s| is) your name|what can you do|"
    r"qui es[\s-]tu|tu es qui|t['’]?\s?es qui|ton nom|"  # i18n-allow: French
    r"tu t['’]?\s?appelles|(?:que|qu['’]?\s?est[\s-]ce que tu) sais"  # i18n-allow: French
    r"(?:[\s-]tu)? faire|tu sais faire quoi)\b|"  # i18n-allow: French speech input
    r"\d+\s*(?:[-+*/x×]|plus|minus|times|divided by|moins|fois|divise par)\s*\d+"  # i18n-allow
)

_UNFULFILLED: dict[str, str] = {
    "en": (
        "I could not run a web search for that just now, so I would rather not "
        "guess. Ask me again in a moment, or tell me more precisely what you "
        "are looking for."
    ),
    "fr": (  # i18n-allow: French spoken phrase
        "Je n'ai pas pu lancer de recherche sur le Web pour ça, alors je "  # i18n-allow: French
        "préfère ne pas inventer. Redemande-moi dans un instant, ou "  # i18n-allow: French
        "précise ce que tu cherches."  # i18n-allow: French spoken phrase
    ),
    "de": (  # i18n-allow: German spoken phrase
        "Ich konnte dafür gerade keine Websuche ausführen und rate lieber "  # i18n-allow: German
        "nicht. Frag mich gleich noch einmal oder sag mir genauer, was du "  # i18n-allow: German
        "suchst."  # i18n-allow: German spoken phrase
    ),
    "es": (  # i18n-allow: Spanish spoken phrase
        "No he podido hacer una búsqueda web para eso, así que prefiero no "  # i18n-allow
        "adivinar. Pregúntame de nuevo en un momento o dime con más "  # i18n-allow: Spanish
        "precisión qué buscas."  # i18n-allow: Spanish spoken phrase
    ),
    "pt": (  # i18n-allow: Portuguese spoken phrase
        "Não consegui fazer uma pesquisa na web para isso, então prefiro não "  # i18n-allow
        "adivinhar. Pergunte de novo daqui a pouco ou diga com mais precisão "  # i18n-allow
        "o que procura."  # i18n-allow: Portuguese spoken phrase
    ),
}


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", str(text or "").casefold())
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def public_fact_search_directive(
    user_text: str,
    *,
    provider: str | None,
    tool_names: Iterable[str],
    previous_user_text: str = "",
    local_providers: Iterable[str] = (),
) -> str | None:
    """The mandate directive when this turn must search, else ``None``.

    Only for on-device providers (``local_providers``) and only when the
    ``search_web`` tool is live. The planner decides the shape: a fresh public
    fact, or any concrete public-fact question because the model requires
    grounding. A referential follow-up inherits freshness from the previous
    user request through the planner's own context rule.
    """
    name = (provider or "").strip().lower()
    if not name or name not in {p.strip().lower() for p in local_providers}:
        return None
    tools = set(tool_names)
    if SEARCH_TOOL not in tools:
        return None
    text = (user_text or "").strip()
    if not text or _SELF_OR_MATH_RE.search(_normalize(text)):
        return None
    try:
        plan = plan_turn(
            text,
            tool_names=tuple(tools),
            context=(previous_user_text,) if previous_user_text else (),
            requires_public_fact_grounding=True,
        )
    except Exception:  # noqa: BLE001 — a routing guard must never break a turn
        return None
    if not plan.requires_public_fact_grounding:
        return None
    return PUBLIC_FACT_DIRECTIVE


#: A clarifying question longer than this is an answer wearing a question mark.
_MAX_CLARIFYING_CHARS = 280


def public_fact_answer_unverified(
    response_text: str, *, executed: Iterable[str], suppressed: bool = False
) -> bool:
    """True when the answer must be replaced: facts stated with no search run.

    Stricter than the generic evidence backstop, which needs a figure or a date
    to see a claim: the invented French story of 2026-10-28 carried neither in
    some turns. Without a search every statement here is a guess, so only a
    short clarifying question survives.
    """
    if suppressed or SEARCH_TOOL in set(executed or ()):
        return False
    text = (response_text or "").strip()
    if not text:
        return False
    return not (text.endswith("?") and len(text) <= _MAX_CLARIFYING_CHARS)


def public_fact_unfulfilled_answer(language: str) -> str:
    """Honest phrase when the mandated search never ran; English if unknown."""
    code = (language or "").split("-", 1)[0].strip().lower()
    return _UNFULFILLED.get(code, _UNFULFILLED["en"])


__all__ = [
    "PUBLIC_FACT_DIRECTIVE",
    "PUBLIC_FACT_DOMAIN",
    "SEARCH_TOOL",
    "public_fact_answer_unverified",
    "public_fact_search_directive",
    "public_fact_unfulfilled_answer",
]
