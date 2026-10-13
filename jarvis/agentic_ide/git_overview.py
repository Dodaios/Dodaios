"""Branches, pull requests and CI of a workspace's repository, in one answer.

The IDE's Git tab lists a project's branches and, for each one, three
separate facts that are easy to mix up:

* **Merged** — local git knows a branch is contained in a target branch
  (``git for-each-ref --merged``), and GitHub knows a pull request was merged
  (which also covers squash merges, where git ancestry says nothing).
* **Pull request** — the state of the branch's pull request on GitHub: draft,
  open, in the merge queue, merged, or closed without a merge.
* **CI** — the checks on the branch's newest pushed commit: pending, running,
  passed or failed. Green checks never mean "merged"; the two are reported
  apart on purpose.

Local git comes from :mod:`jarvis.agentic_ide.git_local`: the branch list is
reused until a ref moves, so a poll of an unchanged repository costs one
``git status``. GitHub
is read for the repository the person picked for this folder ONCE
(:mod:`jarvis.agentic_ide.github_link`), with their existing GitHub
connection, in a few GraphQL queries asked side by side, cached per repository: N open
panes polling one project cost one GitHub read per minute — shorter while a
check is still running, because that is exactly when the user is waiting.

Degrades, never raises: no git, not a repository, GitHub not connected, no
repository picked yet — each comes back as ``available=False`` or
``github.available=False`` with a ``code`` the tab turns into the one next
step (connect GitHub, pick the repository) and one plain sentence.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from jarvis.agentic_ide import git_local, github_link
from jarvis.core.process_utils import NO_WINDOW_CREATIONFLAGS

_GIT_TIMEOUT_S = 8.0
#: Most local branches listed; the newest by commit date win. High enough that
#: a busy repository shows every branch; the cap only guards a pathological one.
MAX_BRANCHES = 1000
#: Most GitHub-only branches listed beside the local ones.
MAX_REMOTE_ONLY = 1000
#: GitHub branch pages (100 names each) read beyond the first CI-bearing page.
MAX_REF_PAGES = 10
#: Most target branches a "merged into" check runs against (one git call each).
MAX_MERGE_TARGETS = 4
#: Pull requests kept per branch (the most relevant first).
MAX_PRS_PER_BRANCH = 3
#: Failed or running check names kept for a tooltip.
MAX_CHECK_NAMES = 6

#: How long one GitHub answer is reused while nothing is in flight ...
GITHUB_TTL_S = 60.0
#: ... and while a check runs or a pull request waits in the merge queue.
GITHUB_BUSY_TTL_S = 20.0
#: A forced refresh still reuses an answer this young.
GITHUB_MIN_REFRESH_S = 5.0

# GitHub is asked three things side by side instead of in one query. One
# query for all of it takes about ten seconds on a repository with many checks
# per commit — the edge of GitHub's own time limit, where it answers 504. Each
# part alone is well inside it, and the slowest one sets the wait.

#: Every open pull request with the CI of its newest commit.
_OPEN_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    url
    pullRequests(first: 50, states: OPEN, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes {
        ...PullRequestRow
        commits(last: 1) { nodes { commit { oid statusCheckRollup { ...Rollup } } } }
      }
    }
  }
}
"""

#: What recently landed or was dropped — the state alone, no CI.
_RECENT_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    pullRequests(first: 60, states: [MERGED, CLOSED],
                 orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes { ...PullRequestRow }
    }
  }
}
"""

#: CI of the most recently changed branches (the ones without a pull request need it).
_REFS_CI_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    url
    refs(refPrefix: "refs/heads/", first: 30,
         orderBy: {field: TAG_COMMIT_DATE, direction: DESC}) {
      nodes {
        name
        target { ... on Commit { oid committedDate statusCheckRollup { ...Rollup } } }
      }
    }
  }
}
"""

_PR_FRAGMENT = """
fragment PullRequestRow on PullRequest {
  number title url state isDraft isCrossRepository
  headRefName headRefOid baseRefName mergedAt updatedAt
  isInMergeQueue mergeable reviewDecision
  author { login }
  mergeQueueEntry { position }
}
"""

_ROLLUP_FRAGMENT = """
fragment Rollup on StatusCheckRollup {
  state
  contexts(first: 40) {
    totalCount
    nodes {
      __typename
      ... on CheckRun {
        name status conclusion detailsUrl
        checkSuite { workflowRun { url } }
      }
      ... on StatusContext { context state targetUrl }
    }
  }
}
"""

# Every branch name on GitHub, without CI: the main query carries CI for the
# newest branches only, so older ones would otherwise never show up.
_REFS_QUERY = """
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    refs(refPrefix: "refs/heads/", first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes { name target { ... on Commit { oid committedDate } } }
    }
  }
}
"""

# CheckRun.status values that have not started yet.
_QUEUED = {"QUEUED", "PENDING", "WAITING", "REQUESTED", "EXPECTED"}
# CheckRun.conclusion values that count as a pass.
_PASSED = {"SUCCESS", "NEUTRAL", "SKIPPED"}


# ------------------------------------------------------------------ model


@dataclass(slots=True)
class CiStatus:
    #: ``none`` | ``pending`` | ``running`` | ``success`` | ``failure``
    state: str = "none"
    #: Where a click goes: the failing / running workflow run, or the checks page.
    url: str = ""
    total: int = 0
    passed: int = 0
    failed: int = 0
    running: int = 0
    pending: int = 0
    #: The commit the checks ran on (12 chars).
    commit: str = ""
    #: Names of the failed checks (or the running ones while nothing failed).
    names: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PullRequest:
    number: int
    title: str
    url: str
    #: ``draft`` | ``open`` | ``queued`` | ``merged`` | ``closed``
    state: str
    base: str
    head: str
    head_oid: str = ""
    merged_at: str = ""
    updated_at: str = ""
    #: 1-based place in the merge queue while ``state == "queued"``.
    queue_position: int | None = None
    ci: CiStatus = field(default_factory=CiStatus)
    #: GitHub cannot merge it as it is: it conflicts with its base.
    conflicting: bool = False
    #: ``approved`` | ``changes_requested`` | ``review_required`` | "" (no review rule).
    review: str = ""
    author: str = ""
    #: Opened from a fork: its branch is not one of this repository's.
    fork: bool = False


@dataclass(slots=True)
class MergedInto:
    target: str
    #: ``git`` (ancestry) or ``pull_request`` (GitHub merged its PR).
    via: str
    number: int | None = None
    url: str = ""


@dataclass(slots=True)
class BranchRow:
    name: str
    current: bool = False
    #: Only on GitHub, no local branch of that name.
    remote_only: bool = False
    upstream: str = ""
    ahead: int = 0
    behind: int = 0
    head: str = ""
    committed_at: int = 0
    #: The checkout this branch is open in, when it is another worktree.
    worktree: str = ""
    #: The branch exists on GitHub (from the GitHub answer; False when unknown).
    on_github: bool = False
    merged_into: list[MergedInto] = field(default_factory=list)
    pull_requests: list[PullRequest] = field(default_factory=list)
    #: CI of the branch's newest pushed commit (its open PR's, when it has one).
    ci: CiStatus = field(default_factory=CiStatus)
    #: The local branch has commits that CI has not seen yet.
    ci_stale: bool = False
    #: The upstream is configured but was deleted on the remote.
    upstream_gone: bool = False
    #: GitHub has commits on this branch that were not fetched yet, so
    #: ``behind`` undercounts until the next fetch.
    unfetched: bool = False
    #: Commits it has that the default branch lacks, and the other way round
    #: (against ``RepoOverview.base_ref``); None when git cannot say.
    base_ahead: int | None = None
    base_behind: int | None = None


@dataclass(slots=True)
class GitHubState:
    available: bool = False
    reason: str = ""
    #: What the tab offers next: ``not_connected`` (connect GitHub),
    #: ``needs_repo`` (pick this folder's repository), another failure code, or "".
    code: str = ""
    #: The ``owner/name`` picked for this folder.
    repo: str = ""
    #: What the folder's git remote points at — the picker's recommendation.
    suggested_repo: str = ""
    #: ``app`` or ``gh``: which GitHub credential is in use.
    source: str = ""
    repo_url: str = ""
    #: Epoch seconds of the GitHub answer in use.
    fetched_at: float = 0.0
    #: A newer answer is being read right now; the tab asks again shortly.
    refreshing: bool = False


@dataclass(slots=True)
class RepoOverview:
    available: bool
    reason: str = ""
    root: str = ""
    branch: str = ""
    detached: bool = False
    head: str = ""
    default_branch: str = ""
    branches: list[BranchRow] = field(default_factory=list)
    remote_branches: list[BranchRow] = field(default_factory=list)
    truncated: bool = False
    github: GitHubState = field(default_factory=GitHubState)
    #: The folder's own state: uncommitted changes, ahead/behind, last fetch.
    checkout: git_local.Checkout = field(default_factory=git_local.Checkout)
    #: What ``base_ahead`` / ``base_behind`` compare with (``origin/main``).
    base_ref: str = ""
    #: Every pull request that is still open, the ones needing a look first.
    pull_requests: list[PullRequest] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ------------------------------------------------------------------ plumbing


def _run(args: list[str], cwd: Path, *, timeout: float = _GIT_TIMEOUT_S, program: str = "git"):
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GH_PROMPT_DISABLED"] = "1"
    env["GH_NO_UPDATE_NOTIFIER"] = "1"
    command = ["git", "-c", "core.quotePath=false", *args] if program == "git" else [program, *args]
    try:
        return subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=env,
            creationflags=NO_WINDOW_CREATIONFLAGS,
        )
    except FileNotFoundError:  # git/gh not installed: callers report it as unavailable
        return None
    except subprocess.TimeoutExpired:
        logger.info("Git overview: {} did not answer in time in {}", program, cwd)
        return None


def _out(args: list[str], cwd: Path) -> str | None:
    result = _run(args, cwd)
    if result is None or result.returncode != 0:
        return None
    return result.stdout


# ------------------------------------------------------------------ CI


def ci_from_rollup(rollup: dict[str, Any] | None, commit: str = "") -> CiStatus:
    """Fold a GitHub ``statusCheckRollup`` into one CI verdict with counts."""
    ci = CiStatus(commit=commit[:12])
    if not rollup:
        return ci
    contexts = rollup.get("contexts") or {}
    failed_names: list[str] = []
    running_names: list[str] = []
    failed_url = running_url = pending_url = first_url = ""
    for node in contexts.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if node.get("__typename") == "StatusContext":
            name = str(node.get("context") or "")
            url = str(node.get("targetUrl") or "")
            state = str(node.get("state") or "").upper()
            kind = (
                "success"
                if state == "SUCCESS"
                else "failure"
                if state in {"FAILURE", "ERROR"}
                else "pending"
            )
        else:
            name = str(node.get("name") or "")
            run = ((node.get("checkSuite") or {}).get("workflowRun") or {}).get("url")
            url = str(run or node.get("detailsUrl") or "")
            status = str(node.get("status") or "").upper()
            conclusion = str(node.get("conclusion") or "").upper()
            if status == "COMPLETED":
                kind = "success" if conclusion in _PASSED else "failure"
            elif status == "IN_PROGRESS":
                kind = "running"
            else:
                kind = "pending" if status in _QUEUED or not status else "running"
        ci.total += 1
        first_url = first_url or url
        if kind == "success":
            ci.passed += 1
        elif kind == "failure":
            ci.failed += 1
            failed_names.append(name)
            failed_url = failed_url or url
        elif kind == "running":
            ci.running += 1
            running_names.append(name)
            running_url = running_url or url
        else:
            ci.pending += 1
            pending_url = pending_url or url
    rollup_state = str(rollup.get("state") or "").upper()
    if ci.failed or rollup_state in {"FAILURE", "ERROR"}:
        ci.state = "failure"
    elif ci.running:
        ci.state = "running"
    elif ci.pending or rollup_state in {"PENDING", "EXPECTED"}:
        ci.state = "pending"
    elif ci.total or rollup_state == "SUCCESS":
        ci.state = "success"
    # The page shows at most 40 checks; the rollup's own count is the truth.
    total = contexts.get("totalCount")
    if isinstance(total, int) and total > ci.total:
        ci.total = total
    ci.names = (failed_names or running_names)[:MAX_CHECK_NAMES]
    ci.url = failed_url or running_url or pending_url or first_url
    return ci


def _pr_state(node: dict[str, Any]) -> str:
    state = str(node.get("state") or "").upper()
    if state == "MERGED":
        return "merged"
    if state == "CLOSED":
        return "closed"
    if node.get("isInMergeQueue") or node.get("mergeQueueEntry"):
        return "queued"
    return "draft" if node.get("isDraft") else "open"


# Most relevant first: what is still moving, then what landed, then the rest.
_PR_RANK = {"queued": 0, "open": 1, "draft": 2, "merged": 3, "closed": 4}


@dataclass(slots=True)
class _GitHubSnapshot:
    ok: bool
    reason: str = ""
    code: str = ""
    repo_url: str = ""
    fetched_at: float = 0.0
    prs: list[PullRequest] = field(default_factory=list)
    #: Branch name → (tip oid, CI of that tip).
    refs: dict[str, tuple[str, CiStatus]] = field(default_factory=dict)
    #: Branch name → its tip's commit time (unix seconds), for remote-only rows.
    ref_dates: dict[str, int] = field(default_factory=dict)

    @property
    def busy(self) -> bool:
        states = [pr.ci.state for pr in self.prs] + [ci.state for _, ci in self.refs.values()]
        return any(state in {"pending", "running"} for state in states) or any(
            pr.state == "queued" for pr in self.prs
        )


def parse_github(payload: dict[str, Any], fetched_at: float = 0.0) -> _GitHubSnapshot:
    """The parts of the GraphQL answer the tab shows."""
    repo = ((payload or {}).get("data") or {}).get("repository")
    if not isinstance(repo, dict):
        return _GitHubSnapshot(ok=False, reason="GitHub did not return this repository.")
    snap = _GitHubSnapshot(ok=True, repo_url=str(repo.get("url") or ""), fetched_at=fetched_at)
    nodes = [
        *((repo.get("openPullRequests") or {}).get("nodes") or []),
        *((repo.get("pullRequests") or {}).get("nodes") or []),
    ]
    seen: set[int] = set()
    for node in nodes:
        if not isinstance(node, dict) or int(node.get("number") or 0) in seen:
            continue
        seen.add(int(node.get("number") or 0))
        commits = (node.get("commits") or {}).get("nodes") or []
        commit = (commits[0] or {}).get("commit") if commits else None
        commit = commit if isinstance(commit, dict) else {}
        entry = node.get("mergeQueueEntry") or {}
        snap.prs.append(
            PullRequest(
                number=int(node.get("number") or 0),
                title=str(node.get("title") or ""),
                url=str(node.get("url") or ""),
                state=_pr_state(node),
                base=str(node.get("baseRefName") or ""),
                head=str(node.get("headRefName") or ""),
                head_oid=str(node.get("headRefOid") or "")[:12],
                merged_at=str(node.get("mergedAt") or ""),
                updated_at=str(node.get("updatedAt") or ""),
                queue_position=entry.get("position") if isinstance(entry, dict) else None,
                ci=ci_from_rollup(commit.get("statusCheckRollup"), str(commit.get("oid") or "")),
                conflicting=str(node.get("mergeable") or "").upper() == "CONFLICTING",
                review=str(node.get("reviewDecision") or "").lower(),
                author=str((node.get("author") or {}).get("login") or ""),
                fork=bool(node.get("isCrossRepository")),
            )
        )
    for node in (repo.get("refs") or {}).get("nodes") or []:
        if not isinstance(node, dict) or not node.get("name"):
            continue
        target = node.get("target") or {}
        oid = str(target.get("oid") or "")
        snap.refs[str(node["name"])] = (
            oid[:12],
            ci_from_rollup(target.get("statusCheckRollup"), oid),
        )
        stamp = _iso_to_unix(str(target.get("committedDate") or ""))
        if stamp:
            snap.ref_dates[str(node["name"])] = stamp
    return snap


def _iso_to_unix(value: str) -> int:
    """GitHub's ISO-8601 timestamp as unix seconds; 0 when it is missing or malformed."""
    if not value:
        return 0
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        # An unreadable date only hides the row's date; the row itself stays.
        return 0


def _repository(payload: dict[str, Any]) -> dict[str, Any]:
    repo = ((payload or {}).get("data") or {}).get("repository")
    return repo if isinstance(repo, dict) else {}


def _fetch_github(repo: str, token: str) -> _GitHubSnapshot:
    now = time.time()
    owner, _, name = repo.partition("/")
    variables = {"owner": owner, "name": name}

    def ask(query: str) -> dict[str, Any] | github_link.GitHubError:
        try:
            return github_link.graphql(token, query, variables)
        except github_link.GitHubError as exc:  # handed back to the caller below
            return exc

    open_job = git_local.Job(ask, _OPEN_QUERY + _PR_FRAGMENT + _ROLLUP_FRAGMENT)
    recent_job = git_local.Job(ask, _RECENT_QUERY + _PR_FRAGMENT)
    refs_job = git_local.Job(ask, _REFS_CI_QUERY + _ROLLUP_FRAGMENT)
    names_job = git_local.Job(_all_refs, token, owner, name)
    opened, recent, refs = open_job.result(), recent_job.result(), refs_job.result()
    names = names_job.result()
    for answer in (opened, refs):
        if isinstance(answer, github_link.GitHubError):  # shown in the tab as github.reason/code
            return _GitHubSnapshot(ok=False, reason=str(answer), code=answer.code, fetched_at=now)
    if isinstance(recent, github_link.GitHubError):
        # Open pull requests and CI landed; only "merged" marks are missing this round.
        logger.debug("Git overview: recent pull requests failed: {}", recent.code)
        recent = {}
    open_repo, refs_repo = _repository(opened), _repository(refs)
    if not open_repo and not refs_repo:
        return _GitHubSnapshot(ok=False, reason="GitHub did not return this repository.")
    merged = {
        "data": {
            "repository": {
                "url": open_repo.get("url") or refs_repo.get("url") or "",
                "openPullRequests": open_repo.get("pullRequests") or {},
                "pullRequests": _repository(recent).get("pullRequests") or {},
                "refs": refs_repo.get("refs") or {},
            }
        }
    }
    snap = parse_github(merged, fetched_at=now)
    for ref_name, oid, stamp in names:
        if ref_name not in snap.refs:
            snap.refs[ref_name] = (oid, CiStatus())
        if stamp:
            snap.ref_dates.setdefault(ref_name, stamp)
    return snap


def _all_refs(token: str, owner: str, name: str) -> list[tuple[str, str, int]]:
    """Every GitHub branch as (name, tip, commit time), without CI, page by page."""
    found: list[tuple[str, str, int]] = []
    after: str | None = None
    for _ in range(MAX_REF_PAGES):
        try:
            payload = github_link.graphql(
                token, _REFS_QUERY, {"owner": owner, "name": name, "after": after}
            )
        except github_link.GitHubError as exc:
            # The CI-bearing branches still land; older ones just stay hidden.
            logger.debug("Git overview: branch list page failed: {}", exc.code)
            break
        refs = _repository(payload).get("refs") or {}
        for node in refs.get("nodes") or []:
            if not isinstance(node, dict) or not node.get("name"):
                continue
            target = node.get("target") or {}
            found.append(
                (
                    str(node["name"]),
                    str(target.get("oid") or "")[:12],
                    _iso_to_unix(str(target.get("committedDate") or "")),
                )
            )
        page = refs.get("pageInfo") or {}
        after = page.get("endCursor")
        if not page.get("hasNextPage") or not after:
            break
    return found


class _GitHubCache:
    """One GitHub answer per repository, shared by every pane and window."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._entries: dict[str, _GitHubSnapshot] = {}
        #: Repositories whose answer is known to be outdated (a push, a new pull request).
        self._expired: set[str] = set()
        #: Repositories with a background read on its way.
        self._inflight: set[str] = set()

    def _fresh(self, key: str, snap: _GitHubSnapshot | None, now: float, force: bool) -> bool:
        if snap is None or key in self._expired:
            return False
        age = now - snap.fetched_at
        if force:
            return age < GITHUB_MIN_REFRESH_S
        return age < (GITHUB_BUSY_TTL_S if snap.busy else GITHUB_TTL_S)

    def _load(self, key: str, token: str, lock: threading.Lock, force: bool) -> _GitHubSnapshot:
        # One fetch per repository at a time; everyone else waits for its answer.
        try:
            with lock:
                snap = self._entries.get(key)
                if self._fresh(key, snap, time.time(), force):
                    assert snap is not None
                    return snap
                with self._guard:
                    # Whatever expires it from here on is newer than this read.
                    self._expired.discard(key)
                snap = _fetch_github(key, token)
                with self._guard:
                    self._entries[key] = snap
                return snap
        finally:
            with self._guard:
                self._inflight.discard(key)

    def _in_background(self, key: str, token: str, lock: threading.Lock, force: bool) -> None:
        with self._guard:
            if key in self._inflight:
                return
            self._inflight.add(key)
        threading.Thread(
            target=self._load,
            args=(key, token, lock, force),
            name="git-overview-github",
            daemon=True,
        ).start()

    def get(
        self, key: str, token: str, *, force: bool = False, wait: bool = True
    ) -> _GitHubSnapshot | None:
        """``key`` is the repository (``owner/name``).

        With ``wait=False`` nothing waits for GitHub, which takes seconds: a
        repository read for the first time answers None and loads in the
        background, and a forced refresh answers with what is known while the
        new answer is on its way (:meth:`loading` says so).
        """
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
            snap = self._entries.get(key)
        if wait and (force or snap is None):
            return self._load(key, token, lock, force)
        if snap is None:
            self._in_background(key, token, lock, False)
            return None
        if not self._fresh(key, snap, time.time(), force):
            # Stale-while-revalidate: a poll never waits seconds for GitHub;
            # it gets the last answer now and the new one on its next tick.
            self._in_background(key, token, lock, force)
        return snap

    def loading(self, key: str) -> bool:
        """A background read of ``key`` is on its way."""
        with self._guard:
            return key in self._inflight

    def peek(self, key: str) -> _GitHubSnapshot | None:
        """The answer already in memory, however old; never a network call."""
        with self._guard:
            return self._entries.get(key)

    def expire(self, key: str) -> None:
        """Keep showing the answer, but read a new one at the next chance."""
        with self._guard:
            if key in self._entries:
                self._expired.add(key)

    def clear(self) -> None:
        with self._guard:
            self._entries.clear()
            self._expired.clear()


_CACHE = _GitHubCache()


def clear_cache() -> None:
    _CACHE.clear()
    git_local.forget()


def clear_github(folder: str | Path) -> None:
    """Mark GitHub's answer for ``folder``'s repository as outdated — after a
    push or a new pull request it is. The tab keeps showing it and gets the new
    one as soon as it is read."""
    repo = github_link.bound_repository(folder)
    if repo:
        _CACHE.expire(repo)


# ------------------------------------------------------------------ local git


def _resolve_target(root: Path, target: str, local: set[str]) -> str | None:
    """The ref a "merged into ``target``" check reads: the local branch, else origin's."""
    if target in local:
        return f"refs/heads/{target}"
    ref = f"refs/remotes/origin/{target}"
    return ref if _out(["rev-parse", "--verify", "--quiet", ref], root) is not None else None


def _merged_by_git(root: Path, targets: list[str], local: set[str]) -> dict[str, list[str]]:
    """Branch name → targets whose history already contains all of its commits.

    For pull request bases other than the default branch (that one comes with
    the branch list). A branch whose tip IS the target's tip holds no work of
    its own and is not reported as merged.
    """
    merged: dict[str, list[str]] = {}
    for target in targets:
        ref = _resolve_target(root, target, local)
        if ref is None:
            continue
        tip = (_out(["rev-parse", ref], root) or "").strip()
        for name, oid in git_local.merged_into(root, ref).items():
            if name != target and oid != tip:
                merged.setdefault(name, []).append(target)
    return merged


def _row(branch: git_local.LocalBranch, current: str) -> BranchRow:
    row = BranchRow(
        name=branch.name,
        current=branch.name == current,
        upstream=branch.upstream,
        ahead=branch.ahead,
        behind=branch.behind,
        head=branch.head[:12],
        committed_at=branch.committed_at,
        upstream_gone=branch.upstream_gone,
        base_ahead=branch.base_ahead,
        base_behind=branch.base_behind,
        merged_into=[MergedInto(target=target, via="git") for target in branch.merged_into],
    )
    if branch.worktree and not row.current:
        row.worktree = branch.worktree
    return row


# ------------------------------------------------------------------ assembly


def _remote_name(row: BranchRow) -> str:
    """The branch's name on GitHub: its upstream on origin, else its own name."""
    if row.upstream.startswith("origin/"):
        return row.upstream[len("origin/") :]
    return row.name


def _attach_github(row: BranchRow, remote: str, snap: _GitHubSnapshot) -> None:
    prs = [pr for pr in snap.prs if pr.head == remote and not pr.fork]
    prs.sort(key=lambda pr: (_PR_RANK.get(pr.state, 9), -pr.number))
    row.pull_requests = prs[:MAX_PRS_PER_BRANCH]
    ref = snap.refs.get(remote)
    row.on_github = ref is not None
    live = next((pr for pr in prs if pr.state in {"queued", "open", "draft"}), None)
    if live is not None and live.ci.state != "none":
        row.ci = live.ci
    elif ref is not None:
        row.ci = ref[1]
    if row.ci.url == "" and row.ci.state != "none" and live is not None:
        row.ci.url = f"{live.url}/checks"
    if row.ci.state != "none" and row.head and row.ci.commit:
        row.ci_stale = row.ci.commit != row.head[: len(row.ci.commit)]
    # A merged pull request counts when the branch has not moved past it since.
    for pr in prs:
        if pr.state != "merged" or any(m.target == pr.base for m in row.merged_into):
            continue
        if row.remote_only or not pr.head_oid or row.head.startswith(pr.head_oid[:7]):
            row.merged_into.append(
                MergedInto(target=pr.base, via="pull_request", number=pr.number, url=pr.url)
            )


def _github_for(
    root: Path, info: RepoOverview, refresh: bool, wait: bool = True
) -> _GitHubSnapshot | None:
    """GitHub's answer for the repository picked for ``root``, or None with
    ``info.github`` saying what is missing (a connection, or the choice)."""
    state = info.github
    state.repo = github_link.bound_repository(root)
    cred = github_link.credential()
    if cred is None:
        state.code = "not_connected"
        state.reason = "GitHub is not connected yet."
        return None
    state.source = cred.source
    if not state.repo:
        state.code = "needs_repo"
        state.reason = "Pick which GitHub repository this folder is."
        state.suggested_repo = github_link.remote_repository(root)
        return None
    snap = _CACHE.get(state.repo, cred.token, force=refresh, wait=wait)
    if snap is None:
        state.code = "loading"
        state.reason = "Reading pull requests and CI from GitHub…"
        state.repo_url = f"https://github.com/{state.repo}"
        return None
    state.available = snap.ok
    state.reason = snap.reason
    state.code = snap.code
    state.repo_url = snap.repo_url or f"https://github.com/{state.repo}"
    state.fetched_at = snap.fetched_at
    state.refreshing = _CACHE.loading(state.repo)
    return snap if snap.ok else None


def branch_checkout(folder: str | Path, branch: str) -> Path | None:
    """The folder ``branch`` is checked out in — this one or a linked worktree.

    None when no checkout of that branch exists on this computer (or the folder
    is gone): the caller then has nothing local to open.
    """
    if not branch:
        return None
    path = Path(folder).expanduser()
    text = _out(["worktree", "list", "--porcelain"], path) if path.is_dir() else None
    tree = ""
    for line in (text or "").splitlines():
        key, _, value = line.partition(" ")
        if key == "worktree":
            tree = value.strip()
        elif key == "branch" and value.strip() == f"refs/heads/{branch}" and tree:
            found = Path(tree)
            return found if found.is_dir() else None
    return None


def overview(
    folder: str | Path,
    *,
    refresh: bool = False,
    github: bool = True,
    wait_for_github: bool = True,
) -> RepoOverview:
    """Branches of the repository ``folder`` is in, with merge, PR and CI state.

    ``wait_for_github=False`` answers a repository's very first read with the
    local branches only (``github.code == "loading"``) while GitHub loads.
    """
    path = Path(folder).expanduser()
    if not path.is_dir():
        return RepoOverview(available=False, reason="The workspace folder is missing.")
    if shutil.which("git") is None:
        return RepoOverview(available=False, reason="Git is not installed.")
    state = git_local.read(path, fresh=refresh)
    if state is None:
        return RepoOverview(available=False, reason="This folder is not a git repository.")
    root = state.root
    head = state.checkout.branch
    info = RepoOverview(
        available=True,
        root=str(root),
        branch=head,
        detached=state.checkout.detached,
        head=state.checkout.head,
        default_branch=state.default_branch,
        checkout=state.checkout,
        base_ref=state.base_ref,
    )

    rows = [_row(branch, head) for branch in state.branches]
    local = {row.name for row in rows}

    snap: _GitHubSnapshot | None = None
    if github:
        snap = _github_for(root, info, refresh, wait_for_github)

    # Current and default branch always make the list, however old they are.
    keep = {head, info.default_branch}
    pinned = [row for row in rows if row.name in keep]
    rest = [row for row in rows if row.name not in keep]
    info.truncated = len(rows) > MAX_BRANCHES
    rows = pinned + rest[: max(0, MAX_BRANCHES - len(pinned))]

    # Pull request bases other than the default branch (which the branch list covers).
    targets: list[str] = []
    for pr in snap.prs if snap and snap.ok else []:
        if pr.base and pr.base != info.default_branch and pr.base in local:
            if pr.base not in targets:
                targets.append(pr.base)
    extra = _merged_by_git(root, targets[: MAX_MERGE_TARGETS - 1], local) if targets else {}
    for row in rows:
        for target in extra.get(row.name, []):
            row.merged_into.append(MergedInto(target=target, via="git"))
        if snap is not None and snap.ok:
            _attach_github(row, _remote_name(row), snap)
    info.branches = rows

    if snap is not None and snap.ok:
        _mark_unfetched(root, rows, state.remote_heads, snap)
        known = {_remote_name(row) for row in rows} | local
        for name, (oid, _ci) in snap.refs.items():
            if name in known:
                continue
            row = BranchRow(
                name=name, remote_only=True, head=oid, committed_at=snap.ref_dates.get(name, 0)
            )
            _attach_github(row, name, snap)
            info.remote_branches.append(row)
            if len(info.remote_branches) >= MAX_REMOTE_ONLY:
                break
        # Newest first, like the local list; the later pages arrive in name order.
        info.remote_branches.sort(key=lambda row: row.committed_at, reverse=True)
        info.pull_requests = _open_pull_requests(snap)
    return info


#: Open pull requests listed in the tab (the ones needing a look come first).
MAX_OPEN_PRS = 60


def _pr_urgency(pr: PullRequest) -> int:
    """Lower sorts first: what is broken, then what moves, then what waits."""
    if pr.ci.state == "failure" or pr.conflicting:
        return 0
    if pr.review == "changes_requested":
        return 1
    if pr.state == "queued":
        return 2
    if pr.ci.state in {"running", "pending"}:
        return 3
    return 5 if pr.state == "draft" else 4


def _open_pull_requests(snap: _GitHubSnapshot) -> list[PullRequest]:
    live = [pr for pr in snap.prs if pr.state in {"queued", "open", "draft"}]
    live.sort(key=lambda pr: pr.updated_at, reverse=True)
    live.sort(key=_pr_urgency)
    return live[:MAX_OPEN_PRS]


def _mark_unfetched(
    root: Path, rows: list[BranchRow], remote_heads: dict[str, str], snap: _GitHubSnapshot
) -> None:
    """Flag branches whose GitHub tip this computer has not fetched yet.

    A tip that differs from the remote-tracking ref is not enough: right after
    a push GitHub's cached answer is the older one. Only a commit that is not
    in the local object store proves there is something to fetch.
    """
    candidates: dict[str, list[BranchRow]] = {}
    for row in rows:
        if not row.upstream.startswith("origin/"):
            continue
        ref = snap.refs.get(_remote_name(row))
        tracked = remote_heads.get(row.upstream, "")
        if ref is None or not ref[0] or not tracked or tracked.startswith(ref[0]):
            continue
        candidates.setdefault(ref[0], []).append(row)
    for oid in git_local.missing_commits(root, list(candidates)):
        for row in candidates[oid]:
            row.unfetched = True


def merged_pull_request(folder: str | Path, branch: str, head: str) -> int | None:
    """The merged pull request that carried exactly ``head`` of ``branch``, if GitHub
    already told us about one (no network call): proof that deleting the branch
    loses nothing even though git ancestry cannot see a squash merge."""
    repo = github_link.bound_repository(folder)
    snap = _CACHE.peek(repo) if repo else None
    if snap is None or not snap.ok or not head:
        return None
    for pr in snap.prs:
        if pr.state == "merged" and pr.head == branch and not pr.fork and pr.head_oid:
            if head.startswith(pr.head_oid[:7]):
                return pr.number
    return None
