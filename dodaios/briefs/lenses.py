"""What makes a brief precise in each field of work.

"Make it nicer" needs different facts than "it crashes" or "it is slow". A
lens names the few facts that turn a request of one kind into a brief an agent
can act on, and what a checkable "done" looks like there. The writer of a
brief gets the lenses that fit the request and fills them from the repository,
the conversation and memory; the agent never sees a lens.

Two lenses at most are picked for a request: one for the nature of the work
(a defect, a speed problem, a restructuring, a question) and one for the area
it touches (the interface, data, the build, text, behaviour behind an
interface, tests). The area comes from the files in play
(``dodaios.rsi.domains``) and, when no file is known yet, from the person's
wording.

The German words below are speech input vocabulary: what a person says when
they describe a problem. They are matching data, not prose.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from dodaios.agentic_ide.task_kind import (
    KIND_INVESTIGATE,
    KIND_QUESTION,
    KIND_REVIEW,
)
from dodaios.rsi import domains

__all__ = ["AREA_LENSES", "LENSES", "NATURE_LENSES", "Lens", "pick"]


@dataclass(frozen=True, slots=True)
class Lens:
    """The facts a brief of one kind needs, and its checkable end."""

    key: str
    title: str
    precise: tuple[str, ...]
    done: str

    def as_dict(self) -> dict[str, object]:
        return {"field": self.title, "name_in_the_brief": list(self.precise), "done": self.done}


_DEFECT: Final[Lens] = Lens(
    key="defect",
    title="a defect",
    precise=(
        "what was observed, verbatim (error text, log line, what the screen showed)",
        "what was expected instead",
        "how to trigger it, or that the trigger is not known",
        "where it happens and since when (version, platform, account)",
    ),
    done="a check that fails before the fix and passes after it",
)
_SPEED: Final[Lens] = Lens(
    key="speed",
    title="a speed or resource problem",
    precise=(
        "the measure (time to first response, frames per second, memory, request count)",
        "its value now and how it was measured",
        "the value it should reach",
    ),
    done="the same measurement, taken the same way, at or under the target",
)
_RESTRUCTURE: Final[Lens] = Lens(
    key="restructure",
    title="a change of shape, not of behaviour",
    precise=(
        "the behaviour that must stay exactly as it is",
        "the shape wanted (what moves, merges or goes)",
        "the public names and interfaces that must not change",
    ),
    done="the existing tests pass unchanged and the named duplication or structure is gone",
)
_QUESTION: Final[Lens] = Lens(
    key="question",
    title="a question or an investigation",
    precise=(
        "the question to answer, in one sentence",
        "the evidence wanted (code references, a measurement, a source)",
        "that nothing is to be changed, when the person asked only for an answer",
    ),
    done="an answer with its evidence, and what could not be established",
)
_INTERFACE: Final[Lens] = Lens(
    key="interface",
    title="the user interface",
    precise=(
        "the component or screen by the name it has in the code",
        "the state it is in (empty, loading, hover, error, long text)",
        "theme and window size when the look depends on them",
        "each visible fault as its own fact: what is shown, what should be shown",
    ),
    done="what the person sees in the running app, shown as a screenshot or a described state",
)
_DATA: Final[Lens] = Lens(
    key="data",
    title="stored data",
    precise=(
        "the table, file or store and the fields in play",
        "what happens to the rows that already exist (migration, backfill, nothing)",
        "whether the step has to be reversible",
    ),
    done="the change applied to a copy with existing data, and a read that shows the new shape",
)
_BUILD: Final[Lens] = Lens(
    key="build",
    title="build, release or automation",
    precise=(
        "the workflow, job or script by its name",
        "the failing run or the log line, verbatim",
        "the platforms or environments it has to work on",
    ),
    done="a named run of that job that passes",
)
_TEXT: Final[Lens] = Lens(
    key="text",
    title="text for people",
    precise=(
        "the reader and what they should do or know after reading",
        "tone and length",
        "the facts that must appear and the claims that must not",
    ),
    done="the text in place, each stated fact checked against its source",
)
_BEHAVIOUR: Final[Lens] = Lens(
    key="behaviour",
    title="behaviour behind an interface",
    precise=(
        "the function, route or command by its name",
        "the input and the expected result for each case that matters",
        "the errors and edge cases that must be handled",
    ),
    done="one test per stated case",
)
_TESTS: Final[Lens] = Lens(
    key="tests",
    title="tests",
    precise=(
        "the behaviour the tests must pin down",
        "the cases, with the one that fails today",
    ),
    done="the new tests fail without the change they guard and pass with it",
)

NATURE_LENSES: Final[tuple[Lens, ...]] = (_DEFECT, _SPEED, _RESTRUCTURE, _QUESTION)
AREA_LENSES: Final[tuple[Lens, ...]] = (_INTERFACE, _DATA, _BUILD, _TEXT, _BEHAVIOUR, _TESTS)
LENSES: Final[dict[str, Lens]] = {lens.key: lens for lens in (*NATURE_LENSES, *AREA_LENSES)}

#: A path domain (``dodaios.rsi.domains``) and the area lens it stands for.
_AREA_OF_DOMAIN: Final[dict[str, str]] = {
    "frontend": "interface",
    "database": "data",
    "infra_ci": "build",
    "docs": "text",
    "backend": "behaviour",
    "testing": "tests",
}

_SPEED_WORDS = re.compile(
    r"(?i)\b(?:slow\w*|lag\w*|sluggish|latency|delay\w*|performance|takes? (?:too )?long|freez\w+"
    r"|memory|cpu"
    r"|langsam\w*|ruckel\w*|tr[aä]ge\w*|verz[oö]ger\w*"  # i18n-allow: input vocab
    r"|dauert\w*|h[aä]ngt|laggy)\b"  # i18n-allow: input vocab
)
_DEFECT_WORDS = re.compile(
    r"(?i)\b(?:bug\w*|error\w*|crash\w*|broken|fail\w*|exception|traceback|wrong|garbled"
    r"|does ?n[o']t work|not working|stopped working|regression|aborts?|hangs?|is lost"
    r"|abbrich\w*|abbruch|bricht (?:\w+ ){0,3}ab|h[aä]ngt sich auf"  # i18n-allow: input vocab
    r"|sind (?:\w+ ){0,2}weg|ist (?:\w+ ){0,2}weg"  # i18n-allow: input vocab
    r"|kaputt\w*|fehler\w*|absturz|abgest[uü]rzt"  # i18n-allow: input vocab
    r"|st[uü]rzt|spinnt|funktioniert nicht|funktioniert nicht mehr"  # i18n-allow: input vocab
    r"|geht nicht|klappt nicht|falsch\w*)\b"  # i18n-allow: input vocab
)
_INTERFACE_WORDS = re.compile(
    r"(?i)\b(?:ui|ux|layout|button\w*|dialog\w*|popup|popover|modal|sidebar|icon\w*|logo\w*"
    r"|colou?r\w*|font\w*|theme|dark mode|screen|page|tooltip|menu"
    r"|oberfl[aä]che|seitenleiste|schaltfl[aä]che|knopf|farbe\w*"  # i18n-allow: input vocab
    r"|schrift\w*|anzeige\w*|ansicht|fenster|aussehen|sieht)\b"  # i18n-allow: input vocab
)
_TEXT_WORDS = re.compile(
    r"(?i)\b(?:readme|wording|copy|headline|tagline|blog post|announcement|documentation|docs"
    r"|formulierung\w*|text|texte|doku\w*"  # i18n-allow: input vocab
    r"|anleitung\w*|beschreibung\w*)\b"  # i18n-allow: input vocab
)
_BUILD_WORDS = re.compile(
    r"(?i)\b(?:ci|workflow\w*|pipeline\w*|release\w*|installer\w*|deploy\w*|docker\w*|build fails?"
    r"|ver[oö]ffentlich\w*)\b"  # i18n-allow: input vocab
)
_DATA_WORDS = re.compile(
    r"(?i)\b(?:database|migration\w*|schema|table|sql|backfill"
    r"|datenbank\w*|tabelle\w*)\b"  # i18n-allow: input vocab
)
_AREA_WORDS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("data", _DATA_WORDS),
    ("build", _BUILD_WORDS),
    ("interface", _INTERFACE_WORDS),
    ("text", _TEXT_WORDS),
)


def _nature(words: str, kind: str) -> Lens | None:
    # A defect first: "it breaks on a slow connection" is about the break.
    if _DEFECT_WORDS.search(words):
        return _DEFECT
    if _SPEED_WORDS.search(words):
        return _SPEED
    if domains.is_refactoring(words):
        return _RESTRUCTURE
    if kind in (KIND_INVESTIGATE, KIND_QUESTION, KIND_REVIEW):
        return _QUESTION
    return None


def _area(words: str, paths: Sequence[str], frontend_roots: Sequence[str]) -> Lens | None:
    if paths:
        main = domains.primary(paths, frontend_roots=frontend_roots)
        key = _AREA_OF_DOMAIN.get(main)
        if key:
            return LENSES[key]
    for key, pattern in _AREA_WORDS:
        if pattern.search(words):
            return LENSES[key]
    return None


def pick(
    words: str,
    *,
    kind: str = "",
    paths: Iterable[str] = (),
    frontend_roots: Sequence[str] = (),
) -> list[Lens]:
    """The lenses that fit a request: its nature first, then its area.

    ``words`` is what the person said (and, when a draft exists, the draft),
    ``kind`` the task kind (``dodaios.agentic_ide.task_kind``) and ``paths``
    the files in play. Nothing recognised gives an empty list: a request that
    fits no lens gets no made-up checklist.
    """
    text = " ".join((words or "").split())
    found: list[Lens] = []
    nature = _nature(text, kind)
    if nature is not None:
        found.append(nature)
    area = _area(text, [p for p in paths if str(p).strip()], frontend_roots)
    if area is not None and area not in found:
        found.append(area)
    return found
