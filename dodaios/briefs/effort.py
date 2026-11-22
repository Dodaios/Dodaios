"""How hard the receiving model should think, chosen from the job.

A new coding agent used to start on whatever the CLI's default effort was,
whether the job was a renamed label or a bug hunt across the app. The vendors'
guides tie effort to the job: a well-specified small change does well on a
lower level, hard debugging and long unattended work want a high one, and the
levels above that pay only where a gain was measured. So when the person named
no effort, the hand-off picks one of three sizes from what is known before the
agent starts, and the recipient's profile says which level that size means
there (``dodaios.briefs.profiles``).

The choice is deliberately coarse and never goes above ``high``: the top
levels are the person's to ask for. An effort the person or the writer named
always wins.

The German words below are speech input vocabulary, matching data and not
prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from dodaios.agentic_ide.task_kind import KIND_INVESTIGATE, KIND_QUESTION
from dodaios.briefs.profiles import Profile

__all__ = ["HARD", "LIGHT", "USUAL", "EffortChoice", "choose", "size_of"]

LIGHT: Final[str] = "light"
USUAL: Final[str] = "usual"
HARD: Final[str] = "hard"

#: A brief longer than this describes more than a small job.
_LONG_BRIEF_CHARS: Final[int] = 2_200
#: A brief this short, about at most one file, can be a light job.
_SHORT_BRIEF_CHARS: Final[int] = 700
_MANY_FILES: Final[int] = 6

_HARD_WORDS = re.compile(
    r"(?i)\b(?:root[- ]?cause|debug\w*|diagnos\w+|intermittent|flaky|race condition|deadlock"
    r"|memory leak|migrat\w+|architecture|redesign\w*|rebuild\w*|rewrite\w*|end[- ]to[- ]end"
    r"|across the (?:app|codebase|repo\w*)|whole (?:app|codebase|repo\w*)|entire (?:app|codebase)"
    r"|security|vulnerab\w+|performance|overnight|unattended|several (?:repos|services)"
    r"|ursache\w*|architektur\w*|komplett\w*|gesamte?\w*"  # i18n-allow: input vocab
    r"|[uü]berall|neu bauen|von grund auf)\b"  # i18n-allow: input vocab
)
_LIGHT_WORDS = re.compile(
    r"(?i)\b(?:typo|rename\w*|wording|label|copy change|colou?r|icon|logo|bump|one[- ]line\w*"
    r"|small (?:change|fix|tweak)|tiny|trivial"
    r"|tippfehler|umbenenn\w*|beschriftung|farbe\w*"  # i18n-allow: input vocab
    r"|kleine?\w* (?:[aä]nderung|fix))\b"  # i18n-allow: input vocab
)


@dataclass(frozen=True, slots=True)
class EffortChoice:
    """The effort a hand-off starts on, and why."""

    level: str
    size: str
    source: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {
            "level": self.level or "the CLI's default",
            "size": self.size,
            "chosen_by": self.source,
            "why": self.reason,
        }


def size_of(text: str, *, kind: str = "", files_named: int = 0) -> tuple[str, str]:
    """``(size, reason)`` of a job from its brief and the person's words."""
    body = " ".join((text or "").split())
    hard = _HARD_WORDS.search(body)
    if hard is not None:
        return HARD, f"the request speaks of '{hard.group(0).lower()}'"
    if kind == KIND_INVESTIGATE:
        return HARD, "finding a cause is open-ended work"
    if files_named >= _MANY_FILES:
        return HARD, f"it names {files_named} files"
    if len(body) > _LONG_BRIEF_CHARS:
        return HARD, "the brief is long"
    if kind == KIND_QUESTION and len(body) <= _SHORT_BRIEF_CHARS:
        return LIGHT, "a question answered from the code"
    light = _LIGHT_WORDS.search(body)
    if light is not None and len(body) <= _SHORT_BRIEF_CHARS and files_named <= 1:
        return LIGHT, f"a small, well-specified change ('{light.group(0).lower()}')"
    return USUAL, "an ordinary change"


def choose(
    profile: Profile,
    text: str,
    *,
    kind: str = "",
    files_named: int = 0,
    named: str = "",
    enabled: bool = True,
) -> EffortChoice:
    """The effort for one hand-off.

    ``named`` is the effort the person or the writer asked for; it is kept as
    it is. Otherwise the job's size picks the level from ``profile``; an empty
    level leaves the CLI's own default in place.
    """
    size, reason = size_of(text, kind=kind, files_named=files_named)
    if named.strip():
        return EffortChoice(named.strip(), size, "named", "asked for in the hand-off")
    if not enabled:
        return EffortChoice("", size, "default", "choosing by job size is switched off")
    level = {
        LIGHT: profile.effort_light,
        USUAL: profile.effort_usual,
        HARD: profile.effort_hard,
    }[size]
    if not level:
        return EffortChoice("", size, "default", "no guidance for this model family")
    return EffortChoice(level, size, "job_size", reason)
