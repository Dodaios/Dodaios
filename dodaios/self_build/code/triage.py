"""Which issues the loop may pick: deterministic, in Python, before any model.

An issue is a candidate only when all of these hold:

* it is open and nobody is assigned;
* the person stands behind it: they wrote it, or it carries a label that marks
  it for agents (labels need triage rights in the repository, so only the
  person or their collaborators set them). A stranger's issue text alone never
  starts a build (docs/self-build.md, rule 2);
* it is fit for an agent: labelled for agents, or like issues whose loop pull
  requests the person merged before;
* its scope is clear: a real title and description, not an epic, no long
  discussion, no pull request already open for it;
* it does not touch secrets, credentials, deployment, releases or CI config;
* the repository has a test command, so the result can be judged;
* the repository's record is not against it: once the person closed loop pull
  requests there without merging any, the loop stays out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

from .github import Issue, PullRef

#: Labels that mark an issue for an agent (lower case).
FIT_LABELS: Final[frozenset[str]] = frozenset(
    {
        "dodaios",
        "agent",
        "agents",
        "ai",
        "ai-agent",
        "agent-ready",
        "good first issue",
        "good-first-issue",
        "easy",
        "small",
        "trivial",
    }
)
#: Labels that keep an issue away from the loop.
BLOCK_LABELS: Final[frozenset[str]] = frozenset(
    {
        "wontfix",
        "won't fix",
        "question",
        "discussion",
        "blocked",
        "duplicate",
        "invalid",
        "epic",
        "needs design",
        "needs-design",
        "needs discussion",
        "needs-discussion",
        "security",
        "do not merge",
        "manual",
        "no-agent",
        "no agent",
    }
)
#: Labels too common to make two issues alike.
_GENERIC: Final[frozenset[str]] = frozenset(
    {"bug", "enhancement", "feature", "documentation", "docs", "improvement"}
)
#: Words that mean secrets, deployment, releases or CI: never for the loop.
RISKY: Final[re.Pattern[str]] = re.compile(
    r"(?i)(?<![\w-])("
    r"secrets?|tokens?|passwords?|credentials?|api[ _-]?keys?|private[ _-]keys?|\.env|"
    r"oauth|auth(?:entication)?|deploy(?:s|ment|ments|ing)?|releases?|publish(?:ing)?|"
    r"production|prod|infra(?:structure)?|terraform|kubernetes|k8s|helm|dockerfile|"
    r"ci|ci/cd|workflows?|github actions|\.github|pipelines?|billing|payments?|"
    r"migrations?|dns|ssl|tls|certificates?|signing|licen[cs]e"
    r")(?![\w-])"
)
_CHECKBOX: Final[re.Pattern[str]] = re.compile(r"^\s*[-*]\s*\[[ xX]\]", re.MULTILINE)
_WORD: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]{3,}")
_STOP: Final[frozenset[str]] = frozenset(
    "the and for with that this from when should not are add fix use into have has can "
    "but all any its was were will make".split()
)
MAX_BODY: Final[int] = 6_000
MIN_BODY: Final[int] = 30
MAX_COMMENTS: Final[int] = 8
MAX_CHECKBOXES: Final[int] = 6
SIMILAR: Final[float] = 0.34


@dataclass(frozen=True, slots=True)
class Verdict:
    fit: bool
    reason: str
    #: Why the issue is fit, in one phrase (``labelled agent``, ``like #12``).
    signal: str = ""


def _no(reason: str) -> Verdict:
    return Verdict(False, reason)


def words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


def _similar(issue: Issue, merged: list[dict[str, Any]]) -> str:
    """``like #n`` when the issue resembles one whose loop PR was merged unchanged."""
    mine = words(issue.title)
    labels = {label.lower() for label in issue.labels} - _GENERIC
    for entry in reversed(merged):
        if entry.get("changed"):
            continue
        other = words(str(entry.get("title") or ""))
        union = mine | other
        if union and len(mine & other) / len(union) >= SIMILAR:
            return f"like #{entry.get('number')}"
        if labels & ({str(x).lower() for x in entry.get("labels") or []} - _GENERIC):
            return f"like #{entry.get('number')}"
    return ""


def has_open_pull(issue: Issue, pulls: tuple[PullRef, ...] | list[PullRef]) -> bool:
    mention = re.compile(rf"(?<![\w/])#{issue.number}(?!\d)")
    branch = re.compile(rf"(?<!\d){issue.number}(?!\d)")
    for pull in pulls:
        if mention.search(pull.title) or mention.search(pull.body):
            return True
        if "issue" in pull.head.lower() and branch.search(pull.head):
            return True
    return False


def triage(
    issue: Issue,
    *,
    login: str,
    profile: dict[str, Any],
    pulls: tuple[PullRef, ...] | list[PullRef] = (),
    has_tests: bool,
) -> Verdict:
    if issue.state.upper() != "OPEN":
        return _no("closed")
    if issue.assignees:
        return _no("assigned")
    labels = {label.strip().lower() for label in issue.labels}
    blocked = sorted(labels & BLOCK_LABELS)
    if blocked:
        return _no(f"labelled {blocked[0]}")
    fit_labels = sorted(labels & FIT_LABELS)
    if not (issue.author and issue.author.lower() == login.lower()) and not fit_labels:
        return _no("neither written nor labelled by the person")
    if not has_tests:
        return _no("no test command in this repository")
    text = f"{issue.title}\n{issue.body}"
    risky = RISKY.search(text)
    if risky:
        return _no(f"touches {risky.group(1).lower()}")
    if len(issue.title.strip()) < 8:
        return _no("title too short to know the scope")
    if not MIN_BODY <= len(issue.body.strip()) <= MAX_BODY:
        return _no("description too short or too long to know the scope")
    if len(_CHECKBOX.findall(issue.body)) > MAX_CHECKBOXES:
        return _no("a list of tasks, not one task")
    if issue.comments > MAX_COMMENTS:
        return _no("long discussion, scope unclear")
    if has_open_pull(issue, pulls):
        return _no("a pull request is already open for it")
    merged = [e for e in profile.get("merged", []) if isinstance(e, dict)]
    closed = [e for e in profile.get("closed", []) if isinstance(e, dict)]
    if len(closed) >= 2 and not merged:
        return _no("the person closed earlier loop pull requests here")
    if fit_labels:
        return Verdict(True, "fit", f"labelled {fit_labels[0]}")
    like = _similar(issue, merged)
    if like:
        return Verdict(True, "fit", like)
    return _no("no sign it suits an agent")
