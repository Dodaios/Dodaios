"""What "done" means in a brief: finding it, judging it, taking it apart.

A reproduction test in the task description is the strongest single hint a
coding agent can get, and every vendor's guide asks for a checkable end. Two
thirds of the lead's real briefs ended on "tests and typecheck" instead, which
names no failing case and no command of the project. This module

* finds the done part of a brief (the ``completion_criteria`` field, or a
  ``Done when`` passage in the text),
* tells a criterion that could be true of any change ("tests pass", "merged")
  from one that belongs to this task, and
* splits the criteria into single points and says what kind each one is, so
  the acceptance check (``dodaios.briefs.acceptance``) knows where to look.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

__all__ = [
    "KIND_COMMAND",
    "KIND_FILE",
    "KIND_LANDED",
    "KIND_OTHER",
    "KIND_REPORT",
    "KIND_TEST",
    "KIND_VISIBLE",
    "Criterion",
    "criteria_of",
    "done_part",
    "is_generic",
    "split",
]

KIND_COMMAND: Final[str] = "command"
KIND_TEST: Final[str] = "test"
KIND_LANDED: Final[str] = "landed"
KIND_FILE: Final[str] = "file"
KIND_VISIBLE: Final[str] = "visible"
KIND_REPORT: Final[str] = "report"
KIND_OTHER: Final[str] = "other"

_DONE_HEAD = re.compile(
    r"(?im)^[ \t>*#-]*(?:done (?:when|means|is when|if)|definition of done|completion criteria"
    r"|acceptance(?: criteria)?|done)[ \t]*[:.-][ \t]*"
)
_NEXT_HEAD = re.compile(
    r"(?im)^[ \t>*#-]*(?:boundar(?:y|ies)|limits?|report(?: back)?|context|why|autonomy|scope"
    r"|constraints?|requirements?|visual references?|the person'?s (?:own )?words)[ \t]*[:.-]"
)


def done_part(brief: str, criteria: str = "") -> str:
    """The done passage of a brief: the explicit field, else a ``Done when`` passage."""
    if criteria.strip():
        return criteria.strip()
    text = brief or ""
    match = _DONE_HEAD.search(text)
    if match is None:
        inline = re.search(r"(?i)\bdone (?:when|means)\b[: ]", text)
        if inline is None:
            return ""
        rest = text[inline.end():]
        stop = re.search(r"\n[ \t]*\n", rest)
        return rest[: stop.start() if stop else len(rest)].strip()
    rest = text[match.end():]
    stop = _NEXT_HEAD.search(rest)
    blank = re.search(r"\n[ \t]*\n(?![ \t]*[-*\d])", rest)
    ends = [m.start() for m in (stop, blank) if m is not None]
    return rest[: min(ends) if ends else len(rest)].strip()


_BULLET = re.compile(r"(?m)^[ \t]*(?:[-*•]|\d+[.)])[ \t]+")
_SPLIT_SENTENCE = re.compile(r"(?<=[.;])\s+(?=[A-Z`])")
# "... passes, and `make test` is green": two points, one of them a command.
_SPLIT_COMMAND = re.compile(
    r",?\s+and\s+(?=`[^`\n]+`\s+(?:is|says|shows|passes|prints|returns|exits|comes)\b)"
)


def split(done: str) -> list[str]:
    """The single points of a done passage, in order."""
    text = (done or "").strip()
    if not text:
        return []
    if _BULLET.search(text):
        parts = [p.strip() for p in _BULLET.split(text)]
    else:
        parts = [p.strip() for p in _SPLIT_SENTENCE.split(" ".join(text.split()))]
    parts = [piece for part in parts for piece in _SPLIT_COMMAND.split(part)]
    points: list[str] = []
    for part in parts:
        cleaned = " ".join(part.split()).rstrip(";").strip()
        if len(cleaned) >= 4 and cleaned not in points:
            points.append(cleaned)
    return points


# What is true of every shipped change. A done passage made only of these names
# nothing this task has to achieve.
_GENERIC = re.compile(
    r"(?i)\b(?:(?:all |the |existing )?(?:unit )?tests?(?: and (?:the )?(?:type ?check|lint\w*))?"
    r" (?:pass(?:es|ing)?|(?:are |is |stay )?green|succeed)"
    r"|tests? and type ?check(?:s)?(?: pass(?:es)?)?"
    r"|type ?check(?:s)?(?: pass(?:es)?| (?:is |are )?green)?"
    r"|lint(?:ing)?(?: pass(?:es)?| (?:is )?clean)?|ci (?:is |stays )?green|with ci green"
    r"|checks? (?:are |is )?green|no regressions?|everything works|it works|works as expected"
    r"|review(?:ed)? (?:your|its) own work|commit(?:ted)?,? (?:and )?push(?:ed)?(?:,? and merged?)?"
    r"|(?:is |are |gets? )?(?:merged|landed|shipped)(?: (?:in|on|to) main)?"
    r"|(?:open|create) (?:a |the )?(?:pull request|pr)|report back\b[^.;]*)\b"
)
_FILLER = re.compile(
    r"(?i)\b(?:and|the|a|an|is|are|it|with|when|then|after|your|its|own|also|all|that|this|"
    r"change|changes|work|fix|done|means|to|on|in|of|for|be|been|has|have)\b"
)


def is_generic(done: str) -> bool:
    """Whether a done passage holds nothing that belongs to this task."""
    text = " ".join((done or "").split())
    if not text:
        return False
    left = _FILLER.sub(" ", _GENERIC.sub(" ", text))
    return len(re.sub(r"[\W_]+", "", left)) < 12


@dataclass(frozen=True, slots=True)
class Criterion:
    """One done point and where its proof can be found."""

    text: str
    kind: str
    #: The command a ``command`` point names, or the path of a ``file`` point.
    target: str = ""

    def as_dict(self) -> dict[str, str]:
        out = {"text": self.text, "kind": self.kind}
        if self.target:
            out["target"] = self.target
        return out


_BACKTICK = re.compile(r"`([^`\n]{2,200})`")
_COMMAND_START = re.compile(
    r"^(?:\./|(?:[~\w./-]*/)?python3?\b|(?:[~\w./-]*/)?pytest\b|npm\b|pnpm\b|yarn\b|npx\b"
    r"|node\b|make\b|cargo\b|go\b|uv\b|tox\b"
    r"|git\b|gh\b|bash\b|sh\b|curl\b|docker\b|ruff\b|mypy\b|tsc\b|vitest\b|jest\b)"
)
_PATH_LIKE = re.compile(r"^(?:[\w.\-]+/)*[\w.\-]+\.\w{1,8}$")
_TEST_WORDS = re.compile(r"(?i)\b(?:tests?|spec|pytest|vitest|jest|regression test|test case)\b")
_LANDED_WORDS = re.compile(
    r"(?i)\b(?:merged|landed|shipped|on main|in main|pull request|\bpr\b|ci (?:is )?green"
    r"|checks? (?:are )?green|released|published|deployed)\b"
)
_VISIBLE_WORDS = re.compile(
    r"(?i)\b(?:screenshot|visible|shows?|displayed|appears?|renders?|in the running app|on screen"
    r"|looks|the page|the dialog|the button|plays?)\b"
)
# A point is about the report when the report is what it asks for ("report the
# cause", "the answer names the commit"), not whenever one of these words
# appears in it ("asked first and used the answer" is about what the agent did).
_REPORT_WORDS = re.compile(
    r"(?i)^(?:(?:the|a|an|its|your)\s+)?(?:(?:final|written|short|clear)\s+)?"
    r"(?:report|answer|verdict|findings?|summary|assessment|explanation|list)\b"
    r"|^(?:report|explain|list|name|state|describe|say|answer|summari[sz]e)s?\b"
    r"|\b(?:the|your|its) (?:report|answer) (?:names|lists|says|states|explains|gives"
    r"|contains|covers)\b"
    r"|\breport (?:only|back)\b"
)
_EXISTS_WORDS = re.compile(r"(?i)\b(?:exists?|is (?:saved|written|created|in place)|contains?)\b")


def _kind_of(point: str) -> tuple[str, str]:
    for snippet in _BACKTICK.findall(point):
        if _COMMAND_START.match(snippet.strip()):
            return KIND_COMMAND, snippet.strip()
    for snippet in _BACKTICK.findall(point):
        if _PATH_LIKE.match(snippet.strip()) and _EXISTS_WORDS.search(point):
            return KIND_FILE, snippet.strip()
    if _REPORT_WORDS.search(point.strip(" -*\t")):
        return KIND_REPORT, ""
    if _TEST_WORDS.search(point):
        return KIND_TEST, ""
    if _LANDED_WORDS.search(point):
        return KIND_LANDED, ""
    if _VISIBLE_WORDS.search(point):
        return KIND_VISIBLE, ""
    return KIND_OTHER, ""


def criteria_of(brief: str, criteria: str = "") -> list[Criterion]:
    """The done points of a brief, each with its kind."""
    out: list[Criterion] = []
    for point in split(done_part(brief, criteria)):
        kind, target = _kind_of(point)
        out.append(Criterion(text=point, kind=kind, target=target))
    return out
