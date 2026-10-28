"""Questions an agent asks the person, answered from a card of choices.

The open standard of chat agents: when a decision genuinely belongs to the
person, the agent asks with a few prepared answers per question, marks the
one it recommends, and the person taps an answer (or types their own). One
call may carry a short series of related questions; the card walks through
them as "question 1 of 3". The card lives in the chat timeline as events —
``question_required``, one ``question_progress`` per answered step and
``question_resolved`` — so a reopened chat replays it like any other row.

Never a stall: when nobody answers for ``QUESTION_TIMEOUT_S`` the remaining
questions resolve to their recommendations. Every answer restarts that
window, so a person working through the series is never cut off. Closing the
card does the same at once ("let the agent decide"). The agent is told which
answers were picked for it, so it can say so in its reply.

Asking is rationed: at most ``MAX_QUESTIONS`` per call and ``MAX_ASKS_PER_TURN``
calls per turn. An agent that keeps asking gets its own recommendations back
instead of another card.

Three kinds of question share the card. ``single`` (the default) takes one
option or the person's own words; ``multi`` takes any number of options, and
its answer reaches the agent as one label per line; ``text`` takes the
person's own words only, with the options (if any) offered as suggestions.
Every kind keeps a default answer for the timeout, so nothing ever stalls:
the recommended option(s), or an empty answer for a ``text`` question with no
options. The person may also skip one question (``declined``), answer from
the chat composer (``message``), or move on so that older open questions
fall back to their recommendations (``moved_on``).

A question is never put to the person twice. When the agent asks again what
the person already answered (the same question with the same options) in this
turn or within ``RECALL_WINDOW_S``, that answer comes back without a new card
(``recalled``), and a fallback (timeout, skip) never replaces it. A fallback
answer always tells the agent that the person did not choose it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

#: How long the card waits for the NEXT answer before the recommendations win.
QUESTION_TIMEOUT_S: Final[float] = 300.0

#: Choices on one question: fewer is no choice, more is a form.
MIN_OPTIONS: Final[int] = 2
MAX_OPTIONS: Final[int] = 4

#: Questions in one call — a short series, never a questionnaire.
MAX_QUESTIONS: Final[int] = 4

#: Cards per agent turn. A third ask in one turn gets the recommendations.
MAX_ASKS_PER_TURN: Final[int] = 2

#: Answer sources.
PERSON: Final[str] = "person"
TIMEOUT: Final[str] = "timeout"
SKIPPED: Final[str] = "skipped"
CANCELLED: Final[str] = "cancelled"
#: Applied without a card (a routine, a background run, the per-turn limit).
UNATTENDED: Final[str] = "unattended"
#: The person skipped this one question: an empty answer, the agent decides.
DECLINED: Final[str] = "declined"
#: The person answered by sending a chat message while the card was open.
MESSAGE: Final[str] = "message"
#: The person sent a message instead of answering: the recommendation applies.
MOVED_ON: Final[str] = "moved_on"
#: The person answered this same question earlier; no new card was shown.
RECALLED: Final[str] = "recalled"
#: Sources where nobody picked the answer: the agent's own recommendation applies.
DEFAULTED: Final[frozenset[str]] = frozenset({TIMEOUT, SKIPPED, MOVED_ON, UNATTENDED})

#: How long an answer from an earlier turn still answers the same question.
RECALL_WINDOW_S: Final[float] = 3600.0

#: Question kinds.
SINGLE: Final[str] = "single"
MULTI: Final[str] = "multi"
TEXT: Final[str] = "text"
KINDS: Final[tuple[str, ...]] = (SINGLE, MULTI, TEXT)

_MAX_QUESTION: Final[int] = 600
_MAX_LABEL: Final[int] = 80
_MAX_DESCRIPTION: Final[int] = 300
_MAX_ANSWER: Final[int] = 2000


@dataclass(frozen=True, slots=True)
class QuestionOption:
    label: str
    description: str = ""


@dataclass(frozen=True, slots=True)
class QuestionSpec:
    """One validated question: the recommended option is always index 0.

    A ``multi`` question may recommend several options; they lead the list
    and ``recommended_count`` says how many. A ``text`` question may have no
    options at all.
    """

    question: str
    options: tuple[QuestionOption, ...]
    recommendation_reason: str = ""
    kind: str = SINGLE
    #: The person may type their own answer instead of (or, for ``multi``,
    #: next to) the options.
    allow_custom: bool = True
    #: A chat message sent instead of an answer settles this question with
    #: its recommendation ("moved on"); ``False`` keeps it open.
    dismiss_on_move_on: bool = True
    recommended_count: int = 1

    @property
    def recommended(self) -> QuestionOption | None:
        return self.options[0] if self.options else None

    @property
    def recommended_indices(self) -> tuple[int, ...]:
        if not self.options:
            return ()
        count = self.recommended_count if self.kind == MULTI else 1
        return tuple(range(max(1, min(count, len(self.options)))))

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "question": self.question,
            "options": [{"label": o.label, "description": o.description} for o in self.options],
            "recommended": 0,
            "recommendation_reason": self.recommendation_reason,
        }
        # Only what differs from the classic card, so older readers and
        # stored events stay identical for single questions.
        if self.kind != SINGLE:
            payload["kind"] = self.kind
        if self.kind == MULTI and self.recommended_count > 1:
            payload["recommended_count"] = self.recommended_count
        if not self.allow_custom:
            payload["allow_custom"] = False
        if not self.dismiss_on_move_on:
            payload["dismiss_on_move_on"] = False
        return payload


@dataclass(frozen=True, slots=True)
class QuestionAnswer:
    """What the person (or the timeout, a skip, a cancel) chose for one question."""

    #: What the agent reads. A ``multi`` answer holds one label per line,
    #: the person's own words (if any) as the last line.
    answer: str
    #: The picked option's index, or ``None`` for a typed answer, a ``multi``
    #: answer or a cancel.
    option_index: int | None
    #: ``person`` | ``timeout`` | ``skipped`` | ``cancelled`` | ``unattended``
    #: | ``declined`` | ``message`` | ``moved_on``.
    source: str
    #: The picked options of a ``multi`` answer, in option order.
    option_indices: tuple[int, ...] = ()

    @property
    def by_person(self) -> bool:
        return self.source in (PERSON, MESSAGE, RECALLED)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "answer": self.answer,
            "option_index": self.option_index,
            "source": self.source,
        }
        if self.option_indices:
            payload["option_indices"] = list(self.option_indices)
        return payload


class TooManyQuestions(RuntimeError):
    """This turn already showed ``MAX_ASKS_PER_TURN`` question cards."""


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _flag(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return default


def _kind(raw: dict[str, Any]) -> str:
    """``kind``, else the multi-select flags the runtimes use (``multi``,
    ``multi_select``, Claude's ``multiSelect``); an unknown kind is single."""
    kind = str(raw.get("kind") or "").strip().lower()
    if kind in KINDS:
        return kind
    for key in ("multi", "multi_select", "multiSelect"):
        if _flag(raw.get(key), False):
            return MULTI
    return SINGLE


def _recommended(raw: Any, count: int, kind: str) -> list[int]:
    """The recommended option indices, in the agent's order; raises on a bad index."""
    if not count:  # a text question without suggestions recommends nothing
        return []
    values = raw if isinstance(raw, list) and kind == MULTI else [raw]
    picked: list[int] = []
    for value in values:
        if value is None:
            continue
        try:
            index = int(value)
        except (TypeError, ValueError):  # a malformed pick means the first option leads
            continue
        if not 0 <= index < count:
            raise ValueError("recommended must be the index of one of the options")
        if index not in picked:
            picked.append(index)
    return picked or ([0] if count else [])


def _parse_one(raw: dict[str, Any]) -> QuestionSpec:
    question = _text(raw.get("question"), _MAX_QUESTION)
    if not question:
        raise ValueError("every question needs its question text")
    kind = _kind(raw)
    entries = raw.get("options")
    if entries is None and kind == TEXT:
        entries = []
    if not isinstance(entries, list):
        raise ValueError("options must be a list of {label, description}")
    options: list[QuestionOption] = []
    seen: set[str] = set()
    for entry in entries:
        if isinstance(entry, str):
            label, description = _text(entry, _MAX_LABEL), ""
        elif isinstance(entry, dict):
            label = _text(entry.get("label"), _MAX_LABEL)
            description = _text(entry.get("description"), _MAX_DESCRIPTION)
        else:
            continue
        if not label or label.casefold() in seen:
            continue
        seen.add(label.casefold())
        options.append(QuestionOption(label, description))
    if kind == TEXT:
        if len(options) > MAX_OPTIONS:
            raise ValueError(f"give a text question at most {MAX_OPTIONS} suggested answers")
    elif not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
        raise ValueError(f"give each question {MIN_OPTIONS} to {MAX_OPTIONS} distinct options")
    picked = _recommended(raw.get("recommended", 0), len(options), kind)
    stored_count = raw.get("recommended_count")
    if (
        kind == MULTI
        and picked == [0]
        and isinstance(stored_count, int)
        and not isinstance(stored_count, bool)
        and stored_count > 1
    ):
        # A stored card (an end-of-turn card read back from its event) keeps
        # its recommendations in front and says how many lead.
        picked = list(range(min(stored_count, len(options) - 1)))
    if picked:
        # The recommendations lead, in the agent's order; the rest keep theirs.
        lead = [options[i] for i in picked]
        options = lead + [o for i, o in enumerate(options) if i not in picked]
    if kind == MULTI and len(picked) >= len(options):
        raise ValueError("leave at least one option of a multi-select question unrecommended")
    return QuestionSpec(
        question=question,
        options=tuple(options),
        recommendation_reason=_text(raw.get("recommendation_reason"), _MAX_DESCRIPTION),
        kind=kind,
        # A text question is nothing but the person's own words.
        allow_custom=True if kind == TEXT else _flag(raw.get("allow_custom"), True),
        dismiss_on_move_on=_flag(raw.get("dismiss_on_move_on"), True),
        recommended_count=len(picked) if kind == MULTI else 1,
    )


def parse_questions(args: dict[str, Any]) -> tuple[QuestionSpec, ...]:
    """Validate a tool call's arguments; raises ``ValueError`` with a fixable reason.

    Takes ``questions: [...]`` (the series) or a single question's fields at
    the top level. ``recommended`` moves that option to the front, so every
    consumer can rely on index 0 being the recommendation.
    """
    raw = args.get("questions")
    items: list[Any] = raw if isinstance(raw, list) else [args]
    if not items:
        raise ValueError("ask at least one question")
    if len(items) > MAX_QUESTIONS:
        raise ValueError(
            f"ask at most {MAX_QUESTIONS} questions at once; keep only the ones whose "
            "answer changes what you do and decide the rest yourself"
        )
    specs = tuple(_parse_one(item) for item in items if isinstance(item, dict))
    if len(specs) != len(items):
        raise ValueError("every question must be an object")
    if len({s.question.casefold() for s in specs}) != len(specs):
        raise ValueError("do not ask the same question twice")
    return specs


def answer_from(
    spec: QuestionSpec,
    *,
    option_index: int | None,
    text: str | None,
    option_indices: list[int] | tuple[int, ...] | None = None,
    source: str = PERSON,
) -> QuestionAnswer:
    """The person's pick as an answer; raises ``ValueError`` for an answer that
    does not fit the question (nothing picked, both for a single question, an
    option out of range, own words where the question takes none)."""
    typed = (text or "").strip()[:_MAX_ANSWER]
    if typed and not spec.allow_custom and source != MESSAGE:
        raise ValueError("this question takes one of its options only")
    if option_indices is not None and spec.kind == MULTI:
        picks = sorted({int(i) for i in option_indices})
        if any(not 0 <= i < len(spec.options) for i in picks):
            raise ValueError("no such option")
        if not picks and not typed:
            raise ValueError("pick at least one option or type an answer")
        lines = [spec.options[i].label for i in picks] + ([typed] if typed else [])
        return QuestionAnswer("\n".join(lines), None, source, tuple(picks))
    if option_indices is not None:
        # A single pick sent as a list (one shared client for every kind).
        if len(option_indices) > 1:
            raise ValueError("this question takes one option")
        option_index = option_indices[0] if option_indices else option_index
    if option_index is not None and typed:
        raise ValueError("send either an option or a typed answer, not both")
    if option_index is not None:
        if not 0 <= option_index < len(spec.options):
            raise ValueError("no such option")
        if spec.kind == MULTI:
            return QuestionAnswer(
                spec.options[option_index].label, None, source, (option_index,)
            )
        return QuestionAnswer(spec.options[option_index].label, option_index, source)
    if typed:
        return QuestionAnswer(typed, None, source)
    raise ValueError("send an option or a typed answer")


def recommended_answer(spec: QuestionSpec, source: str) -> QuestionAnswer:
    """The default the agent proposed: its recommended option(s), or an empty
    answer for a ``text`` question that offered none."""
    if not spec.options:
        return QuestionAnswer("", None, source)
    if spec.kind == MULTI:
        picks = spec.recommended_indices
        return QuestionAnswer(
            "\n".join(spec.options[i].label for i in picks), None, source, picks
        )
    return QuestionAnswer(spec.options[0].label, 0, source)


def declined_answer() -> QuestionAnswer:
    """The person skipped this one question: an empty answer, the agent decides."""
    return QuestionAnswer("", None, DECLINED)


def answer_json(spec: QuestionSpec, raw: Any) -> QuestionAnswer:
    """One answer of a submitted series: ``{option_index | option_indices | text | skip}``."""
    if not isinstance(raw, dict):
        raise ValueError("every answer must be an object")
    if _flag(raw.get("skip"), False):
        return declined_answer()
    indices = raw.get("option_indices")
    if indices is not None and not isinstance(indices, list):
        raise ValueError("option_indices must be a list")
    option = raw.get("option_index")
    if option is not None and (isinstance(option, bool) or not isinstance(option, int)):
        raise ValueError("option_index must be a number")
    try:
        picks = [int(i) for i in indices] if indices is not None else None
    except (TypeError, ValueError) as exc:
        raise ValueError("option_indices must be numbers") from exc
    text = raw.get("text")
    return answer_from(
        spec,
        option_index=option,
        option_indices=picks,
        text=str(text) if text is not None else None,
    )


def same_question(spec: QuestionSpec) -> tuple[str, str, frozenset[str]]:
    """What makes two questions the same: their wording, kind and options."""
    wording = " ".join(spec.question.casefold().split()).rstrip(" ?!.:")
    return wording, spec.kind, frozenset(o.label.casefold() for o in spec.options)


def recalled(
    spec: QuestionSpec, earlier: QuestionSpec, answer: QuestionAnswer
) -> QuestionAnswer:
    """The person's earlier ``answer`` to ``earlier``, as an answer to ``spec``.

    The options may stand in another order (the recommendation leads), so a
    picked option is found again by its label.
    """
    index = {o.label.casefold(): i for i, o in enumerate(spec.options)}

    def moved(old: int) -> int | None:
        if not 0 <= old < len(earlier.options):
            return None
        return index.get(earlier.options[old].label.casefold())

    picks = tuple(sorted(p for p in (moved(i) for i in answer.option_indices) if p is not None))
    option = moved(answer.option_index) if answer.option_index is not None else None
    return QuestionAnswer(answer.answer, option, RECALLED, picks)


def answer_from_payload(row: Any) -> QuestionAnswer | None:
    """One stored answer (``QuestionAnswer.to_payload``) read back, or ``None``."""
    if not isinstance(row, dict):
        return None
    option = row.get("option_index")
    picks = row.get("option_indices")
    return QuestionAnswer(
        str(row.get("answer") or ""),
        option if isinstance(option, int) and not isinstance(option, bool) else None,
        str(row.get("source") or PERSON),
        tuple(i for i in picks if isinstance(i, int)) if isinstance(picks, list) else (),
    )


Answered = dict[tuple[str, str, frozenset[str]], tuple[QuestionSpec, QuestionAnswer]]


def note_answers(
    found: Answered,
    specs: tuple[QuestionSpec, ...] | list[QuestionSpec],
    answers: list[QuestionAnswer | None] | tuple[QuestionAnswer | None, ...],
) -> None:
    """Add the person's own answers among ``answers`` to ``found`` (newest wins)."""
    for spec, answer in zip(specs, answers, strict=False):
        if answer is not None and answer.by_person and (answer.answer or answer.option_indices):
            found[same_question(spec)] = (spec, answer)


def person_answers(events: list[dict[str, Any]], *, turn_id: str, since_ms: int) -> Answered:
    """The person's answers on the cards in ``events``: every card of ``turn_id``
    and every other card opened at or after ``since_ms``."""
    cards: dict[str, tuple[QuestionSpec, ...]] = {}
    found: Answered = {}
    for event in events:
        kind = event.get("kind")
        payload = event.get("payload") or {}
        question_id = str(payload.get("question_id") or "")
        if kind == "question_required":
            if payload.get("turn_id") != turn_id and int(event.get("ts_ms") or 0) < since_ms:
                continue
            try:
                cards[question_id] = parse_questions({"questions": payload.get("questions") or []})
            except ValueError:  # a corrupt stored card answers nothing
                continue
        elif kind in ("question_progress", "question_resolved") and question_id in cards:
            rows = payload.get("answers")
            if isinstance(rows, list):
                note_answers(found, cards[question_id], [answer_from_payload(r) for r in rows])
    return found


def recall(
    specs: tuple[QuestionSpec, ...], found: Answered
) -> list[QuestionAnswer | None]:
    """Per question, the person's earlier answer to the same question, else ``None``."""
    out: list[QuestionAnswer | None] = []
    for spec in specs:
        hit = found.get(same_question(spec))
        out.append(recalled(spec, hit[0], hit[1]) if hit else None)
    return out


def for_agent(answer: QuestionAnswer) -> dict[str, Any]:
    """What the agent must know about who chose ``answer``."""
    if answer.source in DEFAULTED:
        return {
            "person_answered": False,
            "note": "The person did not answer; this is your default. Never say they chose it.",
        }
    if answer.source == RECALLED:
        return {"person_answered": True, "note": "The person already answered this earlier."}
    return {}


def as_line(answer: str) -> str:
    """A ``multi`` answer on one line, for a sentence that lists several answers."""
    return ", ".join(line.strip() for line in answer.splitlines() if line.strip())


__all__ = [
    "CANCELLED",
    "DECLINED",
    "DEFAULTED",
    "KINDS",
    "MESSAGE",
    "MOVED_ON",
    "MULTI",
    "SINGLE",
    "TEXT",
    "MAX_ASKS_PER_TURN",
    "MAX_OPTIONS",
    "MAX_QUESTIONS",
    "MIN_OPTIONS",
    "PERSON",
    "QUESTION_TIMEOUT_S",
    "RECALLED",
    "RECALL_WINDOW_S",
    "SKIPPED",
    "TIMEOUT",
    "UNATTENDED",
    "QuestionAnswer",
    "QuestionOption",
    "QuestionSpec",
    "TooManyQuestions",
    "answer_from",
    "answer_from_payload",
    "answer_json",
    "as_line",
    "declined_answer",
    "for_agent",
    "note_answers",
    "parse_questions",
    "person_answers",
    "recall",
    "recalled",
    "recommended_answer",
    "same_question",
]
