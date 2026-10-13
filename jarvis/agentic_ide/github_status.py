"""Read-only GitHub status for the branch each coding session works in.

Unlike the repository overview, this queries the exact remote branch, including
its historical PR when GitHub has deleted the branch after merging. No local
ancestry, terminal output or CI success is treated as proof of a GitHub merge.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from loguru import logger

from jarvis.agentic_ide import git_overview, github_link
from jarvis.agentic_ide.github_checks import CheckStatus, checks
from jarvis.agentic_ide.session_branches import PaneBranchRecord, pane_branches

_QUERY = """
query($owner: String!, $name: String!, $branch: String!, $ref: String!, $prIds: [ID!]!) {
  nodes(ids: $prIds) { ... on PullRequest { ...PR } }
  repository(owner: $owner, name: $name) {
    ref(qualifiedName: $ref) {
      target { ... on Commit { oid statusCheckRollup { ...Rollup } } }
      associatedPullRequests(first: 20, orderBy: {field: UPDATED_AT, direction: DESC}) {
        nodes { ...PR }
      }
    }
    pullRequests(headRefName: $branch, first: 20,
                 orderBy: {field: UPDATED_AT, direction: DESC}) { nodes { ...PR } }
    openPullRequests: pullRequests(headRefName: $branch, states: [OPEN], first: 20,
                 orderBy: {field: UPDATED_AT, direction: DESC}) { nodes { ...PR } }
  }
}
fragment PR on PullRequest {
  id number url title state isDraft isInMergeQueue headRefName headRefOid createdAt
  locked mergeable mergeStateStatus reviewDecision
  headRepository { nameWithOwner }
  commits(last: 1) { nodes { commit { oid statusCheckRollup { ...Rollup } } } }
}
fragment Rollup on StatusCheckRollup {
  state contexts(first: 100) {
    totalCount checkRunCountsByState { state count } statusContextCountsByState { state count }
    nodes {
    __typename
    ... on CheckRun { name status conclusion detailsUrl checkSuite { workflowRun { url } } }
    ... on StatusContext { context state targetUrl }
  } }
}
"""


@dataclass(frozen=True, slots=True)
class Checkout:
    repo: str
    branch: str
    head: str
    created_at: float = 0


def _git(folder: Path, *args: str) -> str:
    return (git_overview._out(list(args), folder) or "").strip()


def _answered(folder: Path, *args: str) -> str | None:
    """Git's answer, or None when git gave none (locked, timed out, no repository)."""
    result = git_overview._run(list(args), folder)
    if result is None:
        return None
    if result.returncode == 0:
        return str(result.stdout).strip()
    # `git config --get` exits 1 for an option that is not set: that is an answer.
    return "" if args[0] == "config" and result.returncode == 1 else None


_settings: dict[tuple[str, tuple[str, ...]], tuple[float, str]] = {}
_settings_lock = threading.Lock()


def _setting(folder: Path, *args: str) -> str:
    """A remote's name or address: asked of git once a minute, not on every poll.

    Each git call is a new process, and a workspace with a handful of branches
    spent most of a read asking for values that change when someone edits the
    repository's configuration. Only an answer git gave is kept: a call that
    failed is asked again on the next read.
    """
    key = (str(folder), args)
    now = time.monotonic()
    with _settings_lock:
        known = _settings.get(key)
    if known is not None and now - known[0] < 60:
        return known[1]
    value = _answered(folder, *args)
    if value is None:
        return ""
    with _settings_lock:
        if len(_settings) >= 512:
            _settings.clear()
        _settings[key] = (now, value)
    return value


def _repository(url: str) -> str:
    """Accept GitHub hosts exactly, never a hostname containing github.com."""
    match = re.fullmatch(r"git@github\.com:([^/]+/[^/]+?)(?:\.git)?/?", url)
    if match:
        repo = match[1]
    else:
        try:
            parsed = urlsplit(url)
        except ValueError:
            logger.debug("Session GitHub status: ignoring a malformed remote URL")
            return ""
        if parsed.scheme not in {"https", "ssh"} or parsed.hostname != "github.com":
            return ""
        repo = parsed.path.strip("/").removesuffix(".git")
    return repo if github_link.REPO_RE.fullmatch(repo) else ""


def checkout(folder: str | Path, branch: str = "", created_at: float = 0) -> Checkout | None:
    """Resolve the owned branch's remote; never follow a shared checkout's HEAD."""
    path = Path(folder)
    if not path.is_dir():
        return None
    if not branch:
        return None
    fields = _git(
        path,
        "for-each-ref",
        "--count=1",
        "--format=%(objectname)%09%(upstream:remotename)%09%(upstream:remoteref)%09%(refname)",
        f"refs/heads/{branch}",
    ).split("\t")
    head, upstream, ref, full_ref = (fields + ["", "", ""])[:4]
    if full_ref != f"refs/heads/{branch}":
        head = upstream = ref = ""
    # A configured push remote takes precedence in triangular fork workflows.
    push = _setting(path, "config", "--get", f"branch.{branch}.pushRemote")
    push = push or _setting(path, "config", "--get", "remote.pushDefault")
    remote = push or upstream or "origin"
    if remote == ".":
        return None
    url = _setting(path, "remote", "get-url", remote)
    repo = _repository(url)
    if not repo:
        return None
    remote_branch = (
        ref.removeprefix("refs/heads/") if ref and (not push or push == upstream) else branch
    )
    return Checkout(repo, remote_branch, head, created_at)


@dataclass(slots=True)
class BranchStatus:
    repo: str
    branch: str
    url: str
    published: bool = False
    owned: bool = True
    available: bool = True
    reason: str = ""
    fetched_at: float = 0
    # branch | draft | open | queued | merged | closed
    state: str = "branch"
    number: int | None = None
    ci: CheckStatus = field(default_factory=CheckStatus)
    ci_stale: bool = False
    merge_status: str = ""
    review: str = ""
    locked: bool = False
    # The session's other branches, newest first; set on the one a header shows.
    others: list[BranchStatus] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _Snapshot:
    lock: threading.Lock = field(default_factory=threading.Lock)
    payload: dict[str, Any] = field(default_factory=dict)
    fetched_at: float = 0
    reason: str = ""
    pr_ids: list[str] = field(default_factory=list)
    # The pull request is merged or closed: that verdict is read again rarely.
    settled: bool = False


#: States a pull request does not leave by itself.
SETTLED_STATES = frozenset({"merged", "closed"})
_LIVE_TTL = 20
# A session's finished branches are listed beside its current one. Reading each
# of them every 20 seconds would spend the hourly GitHub budget on answers that
# no longer change; a reopened or reused branch shows up after this long.
_SETTLED_TTL = 300
#: GitHub requests one read of a workspace makes at a time.
_GITHUB_READS = 4


@lru_cache(maxsize=256)
def _slot(repo: str, branch: str, credential_id: str) -> _Snapshot:
    # Only a credential fingerprint is retained in the cache key, never a token.
    return _Snapshot()


def _snapshot(target: Checkout, token: str) -> _Snapshot:
    cached = _slot(target.repo, target.branch, hashlib.sha256(token.encode()).hexdigest())
    with cached.lock:
        ttl = _SETTLED_TTL if cached.settled and not cached.reason else _LIVE_TTL
        if time.time() - cached.fetched_at < ttl:
            return cached
        owner, name = target.repo.split("/", 1)
        try:
            payload = github_link.graphql(
                token,
                _QUERY,
                {
                    "owner": owner,
                    "name": name,
                    "branch": target.branch,
                    "ref": f"refs/heads/{target.branch}",
                    "prIds": cached.pr_ids,
                },
            )
            if not isinstance((payload.get("data") or {}).get("repository"), dict):
                raise github_link.GitHubError("GitHub did not return this repository.")
            cached.payload = payload
            candidates = _pull_requests(payload)
            matching = [pr for pr in candidates if pr.get("id") and _same_branch(pr, target)]
            matching.sort(key=lambda pr: (pr.get("state") != "OPEN", -int(pr.get("number") or 0)))
            cached.pr_ids = [str(matching[0]["id"])] if matching else cached.pr_ids
            cached.reason = ""
            read = parse_status(target, payload, 0)
            # Neither a finished pull request nor a branch that exists nowhere
            # changes from one poll to the next.
            cached.settled = read.state in SETTLED_STATES or not (read.published or target.head)
        except github_link.GitHubError as exc:
            # Retain only identity evidence on failure. The UI suppresses all
            # previous success/merge colours while available is false.
            cached.reason = str(exc)
        cached.fetched_at = time.time()
        return cached


def _pull_requests(payload: dict[str, Any]) -> list[dict[str, Any]]:
    repo = (payload.get("data") or {}).get("repository") or {}
    ref = repo.get("ref") or {}
    prs = list((ref.get("associatedPullRequests") or {}).get("nodes") or [])
    prs += (repo.get("pullRequests") or {}).get("nodes") or []
    prs += (repo.get("openPullRequests") or {}).get("nodes") or []
    prs += (payload.get("data") or {}).get("nodes") or []
    return [pr for pr in prs if isinstance(pr, dict)]


def _same_branch(pr: dict[str, Any], target: Checkout) -> bool:
    from datetime import datetime

    owner = (pr.get("headRepository") or {}).get("nameWithOwner", "")
    if owner.casefold() != target.repo.casefold() or pr.get("headRefName") != target.branch:
        return False
    if target.created_at and pr.get("createdAt"):
        try:
            created = datetime.fromisoformat(pr["createdAt"].replace("Z", "+00:00")).timestamp()
        except ValueError:
            logger.debug("Session GitHub status: malformed pull request creation time")
            return False
        if created < target.created_at - 5:
            return False
    return True


def parse_status(target: Checkout, payload: dict[str, Any], fetched_at: float) -> BranchStatus:
    status = BranchStatus(
        repo=target.repo,
        branch=target.branch,
        url=f"https://github.com/{target.repo}/tree/{quote(target.branch, safe='')}",
        fetched_at=fetched_at,
    )
    repo = (payload.get("data") or {}).get("repository") or {}
    ref = repo.get("ref") or {}
    tip = ref.get("target") or {}
    oid = str(tip.get("oid") or "")
    status.published = bool(oid)
    prs = _pull_requests(payload)
    relevant = []
    for pr in prs:
        if not _same_branch(pr, target):
            continue
        live = pr.get("state") == "OPEN"
        # A reused branch must not inherit a historical merge/close verdict.
        if live or (not oid or pr.get("headRefOid") == oid):
            relevant.append(pr)
    relevant.sort(key=lambda pr: (pr.get("state") != "OPEN", -int(pr.get("number") or 0)))
    pr = relevant[0] if relevant else None
    rollup = tip.get("statusCheckRollup")
    if pr:
        status.published = True  # Survives GitHub's delete-branch-after-merge.
        status.state = git_overview._pr_state(pr)
        status.number = int(pr["number"])
        status.url = str(pr["url"])
        status.merge_status = str(pr.get("mergeStateStatus") or "UNKNOWN").lower()
        status.review = str(pr.get("reviewDecision") or "").lower()
        status.locked = bool(pr.get("locked"))
        commits = (pr.get("commits") or {}).get("nodes") or []
        commit = (commits[-1].get("commit") or {}) if commits else {}
        # PR checks are usable only for the current remote tip (or a deleted
        # branch). A stale PR must never override a newer pushed commit's CI.
        if not oid or commit.get("oid") == oid:
            oid = str(commit.get("oid") or oid)
            rollup = commit.get("statusCheckRollup") or rollup
    status.ci = checks(rollup, oid)
    status.ci_stale = bool(oid and target.head != oid)
    if status.ci.state != "none" and not status.ci.url:
        status.ci.url = (
            f"{status.url}/checks"
            if pr
            else f"https://github.com/{target.repo}/commit/{oid}/checks"
        )
    return status


def _foreground(listed: list[BranchStatus]) -> BranchStatus:
    """The branch a header shows: unfinished work before finished work.

    ``listed`` leads with the branch the pane works in now. It stays in front
    unless its pull request is merged or closed while another branch of the
    session is still open; then the open one is what the pane still owes.
    """
    return next((status for status in listed if status.state not in SETTLED_STATES), listed[0])


def statuses(records: list[PaneBranchRecord] | dict[str, str]) -> dict[str, dict[str, Any] | None]:
    """One result per pane that works in a branch; shared GitHub reads.

    A session that worked on several branches gets the others under
    ``others``, newest first.
    """
    result: dict[str, dict[str, Any] | None] = {}
    # Old route versions supplied only folders: those carry no ownership proof.
    if isinstance(records, dict):
        return {pane: None for pane in records}
    targets: dict[tuple[str, str, float], Checkout | None] = {}
    now = time.time()
    panes = []
    for record in records:
        owned_branches = pane_branches(record)
        for owned in owned_branches:
            key = (owned.folder, owned.branch, owned.created_at)
            if key not in targets:
                targets[key] = checkout(*key)
        panes.append((record, owned_branches))
    wanted = list(dict.fromkeys(target for target in targets.values() if target is not None))
    credential = github_link.credential() if wanted else None
    snapshots: dict[Checkout, _Snapshot] = {}
    if credential is not None:
        token = credential.token
        if len(wanted) > 1:
            # One request per branch, side by side: a session with eight
            # branches must not take eight round trips in a row.
            with ThreadPoolExecutor(
                max_workers=min(_GITHUB_READS, len(wanted)), thread_name_prefix="pane-github-read"
            ) as pool:
                reads = pool.map(lambda target: _snapshot(target, token), wanted)
                snapshots = dict(zip(wanted, reads, strict=True))
        else:
            snapshots = {target: _snapshot(target, token) for target in wanted}
    for record, owned_branches in panes:
        listed: list[BranchStatus] = []
        for owned in owned_branches:
            target = targets[(owned.folder, owned.branch, owned.created_at)]
            if target is None:
                continue
            if credential is None:
                status = parse_status(target, {}, 0)
                status.available = False
                status.reason = "GitHub is not connected."
            else:
                snapshot = snapshots[target]
                # A settled verdict is served from a longer cache and does not
                # go stale the way a running check does.
                read_at = now if snapshot.settled else snapshot.fetched_at
                status = parse_status(target, snapshot.payload, read_at)
                status.available = not snapshot.reason
                status.reason = snapshot.reason
            # A branch that is gone locally belongs to this pane only if GitHub
            # shows a pull request opened from it after the pane created it.
            if owned.unproven and (status.number is None or not status.available):
                continue
            listed.append(status)
        if not listed:
            result[record.pane] = None
            continue
        shown = _foreground(listed)
        shown.others = [status for status in listed if status is not shown]
        result[record.pane] = shown.to_dict()
    return result


@dataclass
class _Board:
    """A workspace's last answer, and whether a newer one is being read."""

    panes: dict[str, dict[str, Any] | None] = field(default_factory=dict)
    # Which session each pane's answer was read for: a pane that now runs
    # another one is never shown its predecessor's branch.
    read_for: dict[str, str] = field(default_factory=dict)
    read_at: float | None = None
    # A read for the tab in front is running.
    refreshing: bool = False
    # The read ahead of this workspace's first visit is queued or running.
    ahead: bool = False


_BOARD_TTL = 5
_MAX_BOARDS = 64
_boards: dict[str, _Board] = {}
_boards_lock = threading.Lock()
# Workspaces in background tabs are read ahead one at a time: nobody is waiting
# for them, and they must not take the machine from the tab in front.
_ahead_turn = threading.Lock()


def _identity(record: PaneBranchRecord) -> str:
    return "\n".join((record.history_id, record.session_id, record.folder))


def _read(entry: _Board, records: list[PaneBranchRecord], ahead: bool) -> None:
    panes: dict[str, dict[str, Any] | None] | None = None
    try:
        if ahead:
            with _ahead_turn:
                panes = statuses(records)
        else:
            panes = statuses(records)
    except Exception:  # noqa: BLE001 - nothing may leave a board "refreshing" for good
        logger.opt(exception=True).warning("Session GitHub status: the background read failed")
    with _boards_lock:
        if panes is not None:
            entry.panes = panes
            entry.read_for = {record.pane: _identity(record) for record in records}
        # A failed read waits its turn like a good one instead of retrying at once.
        entry.read_at = time.monotonic()
        if ahead:
            entry.ahead = False
        else:
            entry.refreshing = False


def known(key: str) -> bool:
    """Has this workspace been read, or is its first read on its way?"""
    with _boards_lock:
        return key in _boards


def board(key: str, records: list[PaneBranchRecord], *, ahead: bool = False) -> dict[str, Any]:
    """What is known about a workspace's panes, at once.

    Reading it takes seconds: every session's record, git in every checkout,
    then GitHub. A header that has to wait for that is empty for as long, so
    nothing waits: the caller gets the last answer now, and an outdated one is
    brought up to date in the background. ``refreshing`` says a newer answer
    is on its way and worth asking for again shortly. ``sessions`` names the
    session each pane runs, so a caller holding an older answer can tell
    whether it still belongs to the pane.

    ``ahead`` is the one read of a workspace nobody is looking at yet, so that
    it has an answer by the time someone does.
    """
    with _boards_lock:
        entry = _boards.get(key)
        if entry is None:
            if len(_boards) >= _MAX_BOARDS:
                idle = [name for name, old in _boards.items() if not (old.refreshing or old.ahead)]
                idle.sort(key=lambda name: _boards[name].read_at or 0)
                for name in idle[: max(1, len(idle) // 2)]:
                    del _boards[name]
            entry = _boards[key] = _Board()
        current = {record.pane: _identity(record) for record in records}
        if ahead:
            start = entry.read_at is None and not (entry.refreshing or entry.ahead)
            entry.ahead = entry.ahead or start
        else:
            outdated = (
                entry.read_at is None
                or time.monotonic() - entry.read_at >= _BOARD_TTL
                or any(entry.read_for.get(pane) != identity for pane, identity in current.items())
            )
            start = outdated and not entry.refreshing
            entry.refreshing = entry.refreshing or start
        panes = {
            pane: entry.panes[pane]
            for pane, identity in current.items()
            if pane in entry.panes and entry.read_for.get(pane) == identity
        }
        refreshing = entry.refreshing or entry.ahead
    if start:
        try:
            threading.Thread(
                target=_read,
                args=(entry, records, ahead),
                name="pane-github-status",
                daemon=True,
            ).start()
        except RuntimeError:
            # No thread to be had: the read did not start, so nothing may wait for it.
            logger.warning("Session GitHub status: the background read could not start")
            with _boards_lock:
                if ahead:
                    entry.ahead = False
                else:
                    entry.refreshing = False
                refreshing = entry.refreshing or entry.ahead
    return {"panes": panes, "refreshing": refreshing, "sessions": current}
