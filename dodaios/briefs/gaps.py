"""What a request leaves open, found before the agent starts.

Coding agents almost never ask on their own, and a task that lacks the wanted
behaviour costs them more than any other missing part. One round of questions
before the start wins most of that back. This module names the open points of
a request; it does not ask. The writer of the brief settles each point from
memory, the conversation or the repository, asks the person once (all open
points on one question card) when none of those answers it and the answer
would change the work, and otherwise states the assumption in the brief.

The German words below are speech input vocabulary, matching data and not
prose.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from dodaios.agentic_ide.task_kind import KIND_IMPLEMENT, KIND_NEUTRAL
from dodaios.briefs.lenses import Lens
from dodaios.briefs.repo_facts import RepoFacts
from dodaios.briefs.terms import OpenPhrase

__all__ = ["HOW_TO_SETTLE", "Gap", "find", "has_expectation"]

#: What a writer does with an open point, said once for all of them.
HOW_TO_SETTLE: Final[str] = (
    "Settle each open point from memory, the conversation or the repository. Ask the person "
    "only when none of those answers it and the answer changes the work: all open points in "
    "one question card. Otherwise write your reading into the brief as 'Assumption: ...'."
)

# What says how the thing should behave. A bare "should" does not, in English
# or in German: it is as often about the agent ("he should look into it") as
# about the result.
_EXPECTATION = re.compile(
    r"(?i)\b(?:supposed to|expect\w*|instead|rather than|so that|in order to"
    r"|should(?:\s+\w+){0,3}?\s+(?:not|still|always|never|again|be|show|work|keep|stay|open)"
    r"|must(?:\s+\w+){0,3}?\s+(?:not|still|always|never|be|show|work|keep|stay)"
    r"|want\w* (?:it|them|this|that|the \w+) to"
    r"|statt(?:dessen)?|anstatt|damit|sodass|so dass"  # i18n-allow: input vocab
    r"|erwart\w+|m[oö]chte,? dass|will,? dass"  # i18n-allow: input vocab
    r"|(?:soll(?:te|en|ten)?|muss|m[uü]ssen)(?:\s+\w+){0,4}?\s+"  # i18n-allow: input vocab
    r"(?:nicht|wieder|immer|weiterhin|bleiben"  # i18n-allow: input vocab
    r"|funktionieren|gehen|anzeigen|zeigen))\b"  # i18n-allow: input vocab
)
_SHOULD_IN_A_BRIEF = re.compile(r"(?i)\b(?:should|must|has to|have to|needs? to|done when)\b")
# "He should fix it" says what the agent is to do, not how the thing should behave.
_TASK_FOR_THE_AGENT = re.compile(
    r"(?i)\b(?:should|must|needs? to|has to"
    r"|soll(?:te|en|ten)?|muss|m[uü]ssen)\b(?:\s+\w+){0,5}?\s+"  # i18n-allow: input vocab
    r"(?:fix\w*|repair\w*|look\w*|check\w*|build\w*|change\w*|improve\w*|investigat\w+"
    r"|beheb\w*|reparier\w*|mach\w*|anschau\w*|bau\w*"  # i18n-allow: input vocab
    r"|[aä]nder\w*|verbesser\w*|untersuch\w*|pr[uü]f\w*)\b"  # i18n-allow: input vocab
)
_ASSUMPTION = re.compile(r"(?im)^\W*assumptions?\b\s*[:.-]")


@dataclass(frozen=True, slots=True)
class Gap:
    """One open point of a request."""

    key: str
    open_point: str
    question: str

    def as_dict(self) -> dict[str, str]:
        return {"open_point": self.open_point, "question_for_the_person": self.question}


def has_expectation(text: str, *, in_brief: bool = False) -> bool:
    """Whether a text says what should be the case, not only what is wrong.

    ``in_brief`` reads a written brief, where a plain "should" or "must" is
    about the result; in a person's own sentence it may as well be about the
    agent.
    """
    cleaned = _TASK_FOR_THE_AGENT.sub(" ", text or "")
    if _EXPECTATION.search(cleaned):
        return True
    return in_brief and bool(_SHOULD_IN_A_BRIEF.search(text or ""))


def find(
    words: str,
    *,
    kind: str = "",
    lenses: Sequence[Lens] = (),
    open_phrases: Sequence[OpenPhrase] = (),
    facts: RepoFacts | None = None,
    brief: str = "",
) -> list[Gap]:
    """The open points of a request.

    ``words`` is what the person said; ``brief`` is the draft when one exists.
    A point the draft already settles (it states the wanted behaviour, or an
    assumption) is not reported.
    """
    said = " ".join((words or "").split())
    draft = brief or ""
    settled_by_draft = bool(draft) and (
        has_expectation(draft, in_brief=True) or bool(_ASSUMPTION.search(draft))
    )
    found: list[Gap] = []
    lens_keys = {lens.key for lens in lenses}
    phrase_kinds = {phrase.kind for phrase in open_phrases}

    if (
        ("defect" in lens_keys or "broken" in phrase_kinds)
        and not has_expectation(said)
        and not settled_by_draft
    ):
        found.append(Gap(
            key="expected_behaviour",
            open_point="what should happen instead of what was observed",
            question="What should happen instead?",
        ))
    if phrase_kinds & {"look", "better"} and not settled_by_draft:
        found.append(Gap(
            key="which_faults",
            open_point="which faults exactly, or which property should change",
            question="What exactly bothers you about it?",
        ))
    if "speed" in lens_keys and not re.search(r"\d", said) and not settled_by_draft:
        found.append(Gap(
            key="measure",
            open_point="the measure and the value that would be good enough",
            question="How fast would be fast enough, and where do you notice it?",
        ))
    if facts is not None and not facts.folder:
        found.append(Gap(
            key="where",
            open_point="the project or folder the work belongs to",
            question="Which project is this for?",
        ))
    elif (
        facts is not None
        and facts.known
        and facts.files
        and not facts.starting_points
        and kind in (KIND_IMPLEMENT, KIND_NEUTRAL)
        and said
    ):
        found.append(Gap(
            key="starting_point",
            open_point="the part of the project this is about (no file matched the request)",
            question="Which part of the app do you mean?",
        ))
    return found
