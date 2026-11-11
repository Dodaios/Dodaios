"""The ask-gate: a deterministic check before a question card is shown.

Asking costs the owner attention, so a card is shown only when the answer is
worth more than the question (value of information). The gate scores each
question, with no model call, in this order:

1. **Recoverable from memory.** The memory search runs first. When a current
   memory names exactly one of the question's options (or, for a question with
   no options, covers it), the answer comes from memory and nothing is asked.
2. **Reversible and confident.** The pending action is reversible and the
   asker states a confidence at or above ``ASSUME_CONFIDENCE``: the asker's
   recommendation is applied and the assumption is stated in the reply.
3. **Clarify questions are OFF by default** (``voice.clarify_incomplete_enabled``).
   While off, a card may only be asked for a recoverable or irreversible
   action (an action nobody classified counts as recoverable) or for a missing
   required parameter; anything else takes the recommendation.
4. **Otherwise ask**, one question at a time: the first remaining one, which
   the asker lists as the most decision-relevant. The others take their
   recommendations and are named as assumptions.

Every decision is logged (``dodaios.trust.ask_log``) so the agent score can
report needless questions and questions that should have been asked.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Final

from .questions import MEMORY, MULTI, UNATTENDED, QuestionAnswer, QuestionSpec, recommended_answer

log = logging.getLogger(__name__)

#: The decisions of the gate.
ASK: Final[str] = "ask"
FROM_MEMORY: Final[str] = "answer_from_memory"
ASSUME: Final[str] = "act_with_assumption"
#: A question of a multi-question call that lost to the one that matters most.
TRIMMED: Final[str] = "trimmed"

#: A stated confidence at or above this lets a reversible action go ahead.
ASSUME_CONFIDENCE: Final[float] = 0.7

_WORD: Final[re.Pattern[str]] = re.compile(r"\w+", re.UNICODE)
_STOP: Final[frozenset[str]] = frozenset(
    "the and for you your with that this what which when where who how should would could "
    "can will shall please from have has had are was were not any use want like prefer "
    "der die das und für mit ein eine einen soll sollen "  # i18n-allow: stopwords
    "welche welcher welches wie wann "
    "wo was ist sind bist ich du dir dich mir mich "  # i18n-allow: stopwords
    "dein deine mein meine auf von zu "  # i18n-allow: stopwords
    "el la los las una que cual para con por qual uma com".split()
)

#: What a memory search returns: ``(text, entities)`` of current memories, best first.
MemorySearch = Callable[[str], Sequence[tuple[str, Sequence[str]]]]


def _stems(text: str) -> set[str]:
    """Content words cut to four letters, so "prefers" matches "prefer"."""
    return {w[:4] for w in _WORD.findall((text or "").casefold()) if len(w) > 2 and w not in _STOP}


@dataclass(frozen=True, slots=True)
class AskContext:
    """What the asker says about the pending action, plus the owner's setting."""

    #: The asker's stated confidence in its recommendation, 0..1 (``None``: not stated).
    confidence: float | None = None
    #: ``reversible`` | ``recoverable`` | ``irreversible`` | ``""`` (not stated).
    reversibility: str = ""
    #: A required parameter of the pending action is missing and cannot be guessed.
    missing_required: bool = False
    #: ``voice.clarify_incomplete_enabled``: the owner's opt-in to clarifying questions.
    clarify_enabled: bool = False


@dataclass(frozen=True, slots=True)
class SpecDecision:
    decision: str
    reason: str
    #: Set unless the question is asked.
    answer: QuestionAnswer | None = None
    evidence: str = ""


@dataclass(frozen=True, slots=True)
class GateResult:
    decisions: tuple[SpecDecision, ...]
    #: Indices (into the specs) of the questions that need a card: at most one.
    ask_indices: tuple[int, ...] = field(default=())

    @property
    def needs_card(self) -> bool:
        return bool(self.ask_indices)


def pending_reversibility(tool: str, action: str, declared: str = "") -> str:
    """The reversibility class of the pending action; ``""`` when nothing is known.

    ``declared`` (a class the asker states) wins when valid; else the app's own
    table for known tools decides, and an unknown tool stays ``""``.
    """
    from dodaios.safety.reversibility import REVERSIBILITY, reversibility_of

    if declared in REVERSIBILITY:
        return declared
    if not tool:
        return ""
    try:
        return reversibility_of(SimpleNamespace(name=tool), {"action": action})
    except Exception:  # noqa: BLE001 - an unclassifiable call reads as "not stated"
        log.debug("ask gate: could not classify %r", tool, exc_info=True)
        return ""


def recall_answer(spec: QuestionSpec, search: MemorySearch | None) -> SpecDecision | None:
    """An answer the memory already holds for this question, or ``None``."""
    if search is None or spec.kind == MULTI:
        return None
    try:
        hits = list(search(spec.question))[:5]
    except Exception:  # noqa: BLE001 - a broken memory search means "no memory", never a failed ask
        log.warning("ask gate: memory search failed", exc_info=True)
        return None
    q_stems = _stems(spec.question)
    labels = [(i, o.label.casefold().strip()) for i, o in enumerate(spec.options)]
    labels = [(i, label) for i, label in labels if label]
    label_stems: set[str] = set()
    for _, label in labels:
        label_stems |= _stems(label)
    context = q_stems - label_stems
    for text, entities in hits:
        haystack = f"{text} {' '.join(entities)}".casefold()
        overlap = len(context & _stems(haystack))
        if labels:
            named = [i for i, label in labels if label in haystack]
            if len(named) != 1 or overlap < min(2, max(1, len(context))):
                continue
            idx = named[0]
            answer = QuestionAnswer(spec.options[idx].label, idx, MEMORY)
            return SpecDecision(FROM_MEMORY, "a current memory names the answer", answer, text)
        if len(q_stems) >= 3 and overlap / len(q_stems) >= 0.75:
            answer = QuestionAnswer(text, None, MEMORY)
            return SpecDecision(FROM_MEMORY, "a current memory covers the question", answer, text)
    return None


def _assume_reason(ctx: AskContext) -> str:
    """Why the pending action does not need a card, or ``""`` when it may."""
    confident = ctx.confidence is not None and ctx.confidence >= ASSUME_CONFIDENCE
    if ctx.reversibility == "reversible" and confident:
        return (
            f"the action is reversible and confidence {ctx.confidence:.2f} is at or above "
            f"{ASSUME_CONFIDENCE:.2f}"
        )
    if not ctx.clarify_enabled and ctx.reversibility == "reversible" and not ctx.missing_required:
        return "clarify questions are off and the action is reversible"
    return ""


def decide(
    specs: Sequence[QuestionSpec], ctx: AskContext, search: MemorySearch | None = None
) -> GateResult:
    """Score every question, then ask at most one. Pure: same inputs, same decision."""
    reason = _assume_reason(ctx)
    decisions: list[SpecDecision] = []
    ask_indices: list[int] = []
    for i, spec in enumerate(specs):
        recalled = recall_answer(spec, search)
        if recalled is not None:
            decisions.append(recalled)
        elif reason:
            decisions.append(SpecDecision(ASSUME, reason, recommended_answer(spec, UNATTENDED)))
        elif not ask_indices:
            ask_indices.append(i)
            decisions.append(
                SpecDecision(ASK, "the answer is not in memory and the action is costly or unclear")
            )
        else:
            why = "one question at a time: the more decision-relevant one was asked"
            decisions.append(SpecDecision(TRIMMED, why, recommended_answer(spec, UNATTENDED)))
    return GateResult(tuple(decisions), tuple(ask_indices))


def vault_search(limit: int = 5) -> MemorySearch | None:
    """The active memory vault as a :data:`MemorySearch`, or ``None`` while none runs."""
    from dodaios.memory.vault import runtime as vault_runtime

    vault = vault_runtime.active()
    if vault is None:
        return None

    def search(query: str) -> list[tuple[str, tuple[str, ...]]]:
        out: list[tuple[str, tuple[str, ...]]] = []
        for hit in vault.search(query, limit=limit):
            memory = hit.memory
            if memory.sensitivity != "normal":
                continue
            out.append((memory.text, tuple(memory.entities)))
        return out

    return search


__all__ = [
    "ASK",
    "ASSUME",
    "ASSUME_CONFIDENCE",
    "FROM_MEMORY",
    "TRIMMED",
    "AskContext",
    "GateResult",
    "SpecDecision",
    "decide",
    "pending_reversibility",
    "recall_answer",
    "vault_search",
]
