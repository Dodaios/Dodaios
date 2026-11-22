"""Did a run's work land, and what do the repository's checks say about it.

The agent's own report never counts. What counts is what GitHub answers for the
commit the run left behind: is the commit there, is it in a pull request, was
that merged, and how did the checks on it end. The answer is read with the
person's own GitHub connection (the app's, else the GitHub CLI's), one GraphQL
call per read, and only for a repository on github.com.

Two facts, kept apart because they answer different questions:

``landing``
    ``none`` (the work is not on GitHub: nothing changed, left uncommitted, or
    not pushed), ``pushed`` (the commit is there, in no pull request),
    ``pr_open``, ``pr_closed`` (closed without a merge), ``merged``, or
    ``unknown`` (GitHub could not be asked).

``checks``
    ``passing``, ``failing``, ``running``, ``none`` (the commit has no checks,
    or they were cancelled), or ``unknown``. A cancelled check is not a failed
    one. For merged work these are the checks of the merge commit; when that
    commit has none that completed (a merge queue tests several pull requests
    as one and cancels the runs of all but the last), the next commit on the
    default branch with checks speaks for it when they passed, since it holds
    the work; else the checks of the pull request's head.

Reading happens after the run's turn ended and again while checks still run
(:data:`RECHECK_AFTER_S`), from the recorder's own thread. Nothing here looks at
an agent while it works, and nothing is sent to it.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Final

log = logging.getLogger(__name__)

__all__ = [
    "CHECKS",
    "LANDINGS",
    "NO_CHECKS_GIVE_UP_S",
    "RECHECK_AFTER_S",
    "Evidence",
    "from_payload",
    "github_repo",
    "is_step",
    "read",
]

NONE: Final[str] = "none"
UNKNOWN: Final[str] = "unknown"
PUSHED: Final[str] = "pushed"
PR_OPEN: Final[str] = "pr_open"
PR_CLOSED: Final[str] = "pr_closed"
MERGED: Final[str] = "merged"
LANDINGS: Final[tuple[str, ...]] = (NONE, PUSHED, PR_OPEN, PR_CLOSED, MERGED, UNKNOWN)

PASSING: Final[str] = "passing"
FAILING: Final[str] = "failing"
RUNNING: Final[str] = "running"
CHECKS: Final[tuple[str, ...]] = (PASSING, FAILING, RUNNING, NONE, UNKNOWN)

#: Seconds after the run's end at which unsettled evidence is read again. After
#: the last one the record keeps what was read: a check that runs for more than
#: six hours is not waited for.
RECHECK_AFTER_S: Final[tuple[int, ...]] = (
    120, 300, 600, 1200, 2400, 3600, 5400, 7200, 10800, 14400, 21600,
)

#: A commit that shows no check this long after the run's end is taken to have
#: none: a push starts its checks within seconds, and the push came before the end.
NO_CHECKS_GIVE_UP_S: Final[int] = 300

_FAILING_KEPT: Final[int] = 8
#: ``GitHubError.code`` values that a later call may not meet again.
_TRANSIENT: Final[frozenset[str]] = frozenset({"unreachable", "rate_limited", "error"})
_TOKEN_TTL_S: Final[float] = 300.0
_ROLLUP = {
    "SUCCESS": PASSING,
    "FAILURE": FAILING,
    "ERROR": FAILING,
    "PENDING": RUNNING,
    "EXPECTED": RUNNING,
}
_RED = {"FAILURE", "ERROR", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
#: How far back on the default branch a merge commit is looked for.
_HISTORY: Final[int] = 50
_GITHUB_ID = re.compile(r"^github\.com/(?P<owner>[A-Za-z0-9-]+)/(?P<name>[A-Za-z0-9._-]+)$")

_QUERY: Final[str] = """
query($owner: String!, $name: String!, $oid: GitObjectID!, $history: Int!) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: $history) { nodes { oid statusCheckRollup { state } } }
        }
      }
    }
    object(oid: $oid) {
      ... on Commit {
        oid
        statusCheckRollup { ...rollup }
        associatedPullRequests(first: 10) {
          nodes {
            number state isDraft merged headRefOid
            mergeCommit { oid statusCheckRollup { ...rollup } }
            commits(last: 1) { nodes { commit { oid statusCheckRollup { ...rollup } } } }
          }
        }
      }
    }
  }
}
fragment rollup on StatusCheckRollup {
  state
  contexts(first: 100) {
    nodes {
      __typename
      ... on CheckRun { name conclusion }
      ... on StatusContext { context state }
    }
  }
}
"""


@dataclass(frozen=True, slots=True)
class Evidence:
    """What GitHub says about the commit a run left behind."""

    landing: str = UNKNOWN
    checks: str = UNKNOWN
    head_sha: str = ""
    pr: int = 0
    draft: bool = False
    #: The commit whose checks were read (the merge commit of merged work).
    checked_sha: str = ""
    #: Names of the checks that failed, capped.
    failing: tuple[str, ...] = ()
    reason: str = ""
    #: GitHub could not be reached this time; asking again may tell more.
    transient: bool = False

    @property
    def settled(self) -> bool:
        """True when reading again later would not tell more.

        Waited for: checks that still run, an open pull request (it may merge),
        a commit on GitHub without any check yet (CI may not have started; see
        :data:`NO_CHECKS_GIVE_UP_S`), and GitHub being out of reach.
        """
        if self.landing == UNKNOWN:
            return not self.transient
        if self.landing in (NONE, PR_CLOSED):
            return True
        if self.landing == PR_OPEN and not self.draft:
            return False
        return self.checks in (PASSING, FAILING)

    def to_detail(self) -> dict[str, Any]:
        detail = asdict(self)
        detail["failing"] = list(self.failing)
        return detail


def is_step(step: dict[str, Any]) -> bool:
    """True for a step of a run's record that holds a reading of landing and checks.

    The first reading of an output is the step ``evidence``; each later one
    that told something new is ``evidence:1``, ``evidence:2`` and so on.
    """
    name = str(step.get("step") or "")
    return name == "evidence" or name.startswith("evidence:")


def github_repo(repo_id: str) -> tuple[str, str] | None:
    """``(owner, name)`` for a run's repository id on github.com, else ``None``."""
    match = _GITHUB_ID.match((repo_id or "").strip())
    return (match["owner"], match["name"]) if match else None


def _rollup(node: Any) -> tuple[str, tuple[str, ...]]:
    """``(checks, failing names)`` of a ``statusCheckRollup`` node.

    GitHub rolls a cancelled run up as a failure. Here it is none: a rollup
    that is red with no check that failed and at least one that was cancelled
    reads as "no checks completed".
    """
    if not isinstance(node, dict):
        return NONE, ()
    state = _ROLLUP.get(str(node.get("state") or ""), NONE)
    failing: list[str] = []
    cancelled = False
    for context in ((node.get("contexts") or {}).get("nodes")) or []:
        if not isinstance(context, dict):
            continue
        if context.get("__typename") == "CheckRun":
            name, verdict = context.get("name"), context.get("conclusion")
        else:
            name, verdict = context.get("context"), context.get("state")
        cancelled = cancelled or str(verdict or "") == "CANCELLED"
        if name and str(verdict or "") in _RED and str(name) not in failing:
            failing.append(str(name))
    if state == FAILING and not failing and cancelled:
        return NONE, ()
    return state, tuple(failing[:_FAILING_KEPT])


def _next_on_default_branch(repository: dict[str, Any], merge_oid: str) -> tuple[str, str]:
    """``(commit, checks)`` of the nearest later commit on the default branch with checks.

    That commit holds the merged work, so checks that passed on it passed with
    the work. Only the nearest one counts: a red commit is never skipped for a
    green one after it, because the red may be this work's doing. ``("", "none")``
    when there is none, when it is red, or when the merge commit is out of sight.
    """
    target = (repository.get("defaultBranchRef") or {}).get("target") or {}
    nodes = [
        node for node in ((target.get("history") or {}).get("nodes")) or []
        if isinstance(node, dict)
    ]
    # Newest first: everything before the merge commit came after it.
    at = next((i for i, node in enumerate(nodes) if node.get("oid") == merge_oid), -1)
    for node in reversed(nodes[:at] if at > 0 else []):
        state = _ROLLUP.get(str((node.get("statusCheckRollup") or {}).get("state") or ""), NONE)
        if state == PASSING:
            return str(node.get("oid") or ""), PASSING
        if state == RUNNING:
            return "", RUNNING
        if state == FAILING:
            break
    return "", NONE


def from_payload(payload: dict[str, Any], head_sha: str) -> Evidence:
    """The evidence in one GraphQL answer for the commit ``head_sha``."""
    repository = ((payload.get("data") or {}).get("repository")) or {}
    commit = repository.get("object")
    if not isinstance(commit, dict) or not commit.get("oid"):
        return Evidence(NONE, NONE, head_sha, reason="the commit is not on GitHub")
    pulls = [
        node
        for node in ((commit.get("associatedPullRequests") or {}).get("nodes")) or []
        if isinstance(node, dict) and node.get("number")
    ]
    if not pulls:
        checks, failing = _rollup(commit.get("statusCheckRollup"))
        return Evidence(
            PUSHED, checks, head_sha, checked_sha=head_sha, failing=failing,
            reason="the commit is on GitHub, in no pull request",
        )
    # The pull request this commit heads; else a merged one; else the first.
    pull = next(
        (p for p in pulls if str(p.get("headRefOid") or "") == head_sha),
        next((p for p in pulls if p.get("merged")), pulls[0]),
    )
    number = int(pull["number"])
    heads = ((pull.get("commits") or {}).get("nodes")) or []
    head = (heads[-1].get("commit") if heads and isinstance(heads[-1], dict) else None) or {}
    if pull.get("merged"):
        merge = pull.get("mergeCommit") if isinstance(pull.get("mergeCommit"), dict) else {}
        checks, failing = _rollup(merge.get("statusCheckRollup"))
        checked = str(merge.get("oid") or "")
        where = "the merge commit"
        later, later_checks = (
            _next_on_default_branch(repository, checked) if checks == NONE and checked
            else ("", NONE)
        )
        if later_checks == PASSING:
            checks, checked = PASSING, later
            where = "the next commit on the default branch that completed them"
        elif later_checks == RUNNING:
            checks = RUNNING
            where = "the next commit on the default branch, where they still run"
        elif checks == NONE:
            # A repository without checks on its default branch: the pull
            # request's own checks are what was run on this work.
            checks, failing = _rollup(head.get("statusCheckRollup"))
            checked = str(head.get("oid") or "")
            where = "the pull request's head"
        return Evidence(
            MERGED, checks, head_sha, pr=number, checked_sha=checked, failing=failing,
            reason=f"pull request #{number} is merged; checks read on {where}",
        )
    if str(pull.get("headRefOid") or "") == head_sha:
        checks, failing = _rollup(head.get("statusCheckRollup"))
    else:
        # The pull request moved on after this run: judge the run's own commit.
        checks, failing = _rollup(commit.get("statusCheckRollup"))
    closed = str(pull.get("state") or "") == "CLOSED"
    return Evidence(
        PR_CLOSED if closed else PR_OPEN, checks, head_sha, pr=number,
        draft=bool(pull.get("isDraft")), checked_sha=head_sha, failing=failing,
        reason=f"pull request #{number} is {'closed without a merge' if closed else 'open'}",
    )


# ----------------------------------------------------------------- asking

_token: tuple[float, str] | None = None
_token_lock = threading.Lock()


def _github_token() -> str:
    """The person's GitHub token, remembered for a few minutes; ``""`` without one."""
    global _token
    with _token_lock:
        if _token is not None and time.monotonic() - _token[0] < _TOKEN_TTL_S:
            return _token[1]
    from dodaios.agentic_ide import github_link

    found = github_link.credential()
    value = found.token if found is not None else ""
    with _token_lock:
        _token = (time.monotonic(), value)
    return value


def _ask_github(owner: str, name: str, oid: str) -> dict[str, Any]:
    from dodaios.agentic_ide import github_link

    token = _github_token()
    if not token:
        raise github_link.GitHubError("GitHub is not connected.", code="not_connected")
    return github_link.graphql(
        token, _QUERY, {"owner": owner, "name": name, "oid": oid, "history": _HISTORY}
    )


def read(
    repo_id: str,
    head_sha: str,
    *,
    ask: Callable[[str, str, str], dict[str, Any]] | None = None,
) -> Evidence:
    """What GitHub says about ``head_sha`` in the repository ``repo_id``. Never raises."""
    if not head_sha:
        return Evidence(NONE, NONE, "", reason="the run left no commit")
    target = github_repo(repo_id)
    if target is None:
        return Evidence(
            UNKNOWN, UNKNOWN, head_sha, reason="the repository is not on github.com"
        )
    try:
        payload = (ask or _ask_github)(target[0], target[1], head_sha)
    except Exception as exc:  # noqa: BLE001 - no answer is an answer: "unknown"
        log.info("evidence: GitHub not asked for %s (%s)", head_sha[:12], exc)
        code = str(getattr(exc, "code", "") or "error")
        return Evidence(
            UNKNOWN, UNKNOWN, head_sha, reason=str(exc) or type(exc).__name__,
            transient=code in _TRANSIENT,
        )
    if not isinstance(payload, dict):
        return Evidence(
            UNKNOWN, UNKNOWN, head_sha, reason="GitHub sent an answer that could not be read",
            transient=True,
        )
    return from_payload(payload, head_sha)
