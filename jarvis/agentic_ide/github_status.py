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
from collections.abc import Callable, Sequence
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


_settings: dict[tuple[str, tuple[str, ...]], tuple[float, str]] = {}
_settings_lock = threading.Lock()
# A repository's remotes change when someone edits its configuration, not from
# one read to the next.
_SETTINGS_TTL = 60


def _setting(folder: Path, *args: str) -> str:
    """A remote's name or address, asked of git once a minute.

    Each git call is a process of its own, and three of them per branch were
    most of the git time a read spent. Only an answer git gave is kept: a
    call that failed (locked, timed out) is asked again on the next read.
    """
    key = (str(folder), args)
    now = time.monotonic()
    with _settings_lock:
        known = _settings.get(key)
    if known is not None and now - known[0] < _SETTINGS_TTL:
        return known[1]
    result = git_overview._run(list(args), folder)
    if result is None:
        return ""
    if result.returncode == 0:
        value = str(result.stdout).strip()
    elif args[0] == "config" and result.returncode == 1:
        # `git config --get` exits 1 for an option that is not set: an answer.
        value = ""
    else:
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


@lru_cache(maxsize=256)
def _slot(repo: str, branch: str, credential_id: str) -> _Snapshot:
    # Only a credential fingerprint is retained in the cache key, never a token.
    return _Snapshot()


_slot_lock = threading.Lock()


def _snapshot(target: Checkout, token: str, live_ttl: float = _LIVE_TTL) -> _Snapshot:
    # Reads run side by side: two of them must find the same slot, never make
    # one each and ask GitHub twice.
    with _slot_lock:
        cached = _slot(target.repo, target.branch, hashlib.sha256(token.encode()).hexdigest())
    with cached.lock:
        ttl = _SETTLED_TTL if cached.settled and not cached.reason else live_ttl
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


#: Git and GitHub calls one read of a workspace makes side by side.
_PARALLEL_READS = 6


def _each(function: Callable[[Any], Any], items: Sequence[Any]) -> list[Any]:
    """``function`` over ``items`` in order; side by side when there are several."""
    if len(items) <= 1:
        return [function(item) for item in items]
    with ThreadPoolExecutor(
        max_workers=min(_PARALLEL_READS, len(items)), thread_name_prefix="pane-github-read"
    ) as pool:
        return list(pool.map(function, items))


def _tolerant(function: Callable[[Any], Any], fallback: Any, what: str) -> Callable[[Any], Any]:
    """``function``, answering ``fallback`` where it fails for one item.

    One pane whose record or checkout cannot be read must not cost every other
    pane of the workspace its status.
    """

    def run(item: Any) -> Any:
        try:
            return function(item)
        except Exception:  # noqa: BLE001 - logged; the other panes still get read
            logger.opt(exception=True).warning("Session GitHub status: {} failed", what)
            return fallback

    return run


def _foreground(listed: list[BranchStatus]) -> BranchStatus:
    """The branch a header shows: unfinished work before finished work.

    ``listed`` leads with the branch the pane works in now. It stays in front
    unless its pull request is merged or closed while another branch of the
    session is still open; then the open one is what the pane still owes.
    """
    return next((status for status in listed if status.state not in SETTLED_STATES), listed[0])


def statuses(
    records: list[PaneBranchRecord] | dict[str, str], *, live_ttl: float = _LIVE_TTL
) -> dict[str, dict[str, Any] | None]:
    """One result per pane that works in a branch; shared GitHub reads.

    A session that worked on several branches gets the others under
    ``others``, newest first. GitHub is asked again about an unfinished
    branch whose last answer is older than ``live_ttl`` seconds.
    """
    result: dict[str, dict[str, Any] | None] = {}
    # Old route versions supplied only folders: those carry no ownership proof.
    if isinstance(records, dict):
        return {pane: None for pane in records}
    # Every step asks git or GitHub once per pane or branch and waits for the
    # answer. Asked one after another, a workspace with eight branches took
    # ten seconds; side by side it takes about as long as the slowest answer.
    owned_by_pane = _each(_tolerant(pane_branches, [], "reading a pane's branches"), records)
    keys = list(
        dict.fromkeys(
            (owned.folder, owned.branch, owned.created_at)
            for owned_branches in owned_by_pane
            for owned in owned_branches
        )
    )
    resolve = _tolerant(lambda key: checkout(*key), None, "resolving a branch's remote")
    targets = dict(zip(keys, _each(resolve, keys), strict=True))
    wanted = list(dict.fromkeys(target for target in targets.values() if target is not None))
    credential = github_link.credential() if wanted else None
    snapshots: dict[Checkout, _Snapshot] = {}
    if credential is not None:
        token = credential.token
        snapshots = dict(
            zip(
                wanted,
                _each(lambda target: _snapshot(target, token, live_ttl), wanted),
                strict=True,
            )
        )
    now = time.time()
    for record, owned_branches in zip(records, owned_by_pane, strict=True):
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


# --------------------------------------------------------------- the board
#
# Reading a workspace takes seconds: every session's record, git in every
# checkout, then GitHub. A header that waited for that showed nothing, or an
# outdated symbol, for as long. So nothing waits: `board` answers with the last
# read at once and brings an outdated one up to date in the background.


@dataclass
class _Board:
    """A workspace's last answer, and whether a newer one is being read."""

    panes: dict[str, dict[str, Any] | None] = field(default_factory=dict)
    # The pane each answer was read for (see `_identity`): a pane that is
    # someone else now is never shown its predecessor's branch.
    read_for: dict[str, str] = field(default_factory=dict)
    # Wall clock of the last read that finished; None before the first.
    read_at: float | None = None
    reading: bool = False
    # The last read failed: what is on the board is no longer being kept current.
    failed: bool = False
    # Monotonic: when the last read started, and when the board was last asked for.
    tried_at: float = float("-inf")
    used_at: float = 0


#: A board this old is read again when it is asked for.
_BOARD_TTL = 10
#: A board whose panes changed, or that has no answer yet, waits only this long
#: between attempts, so a read that fails is not retried on every request.
_RETRY_S = 1
#: A tab behind the front one is read again once its answer is this old, so a
#: switch to it finds an answer recent enough to show without a spinner.
_WARM_S = 50
#: How old GitHub's answer about an unfinished branch may get in a tab behind
#: the front one: it keeps the hourly GitHub budget for the tab in front.
_WARM_GITHUB_TTL = 60
#: The longest a request that asked to wait holds on for a running read.
_MAX_WAIT_S = 15
_MAX_BOARDS = 64
_boards: dict[str, _Board] = {}
_boards_lock = threading.Lock()
# Notified whenever a read finishes, for the requests that wait for one.
_boards_read = threading.Condition(_boards_lock)
# Workspaces in background tabs, queued to be read one after another.
_ahead: dict[str, list[PaneBranchRecord]] = {}
_ahead_running = False
# Set while no read for a tab in front is running: reads ahead wait for it, so
# they never take the machine from the tab someone is looking at.
_front_reads = 0
_front_idle = threading.Event()
_front_idle.set()


def _identity(record: PaneBranchRecord) -> str:
    return "\n".join((record.pane, record.history_id, record.folder, record.created_branch))


def _entry(key: str) -> _Board:
    """The board for ``key``, made on first use; holds ``_boards_lock``."""
    entry = _boards.get(key)
    if entry is None:
        if len(_boards) >= _MAX_BOARDS:
            idle = sorted(
                (name for name, old in _boards.items() if not old.reading),
                key=lambda name: _boards[name].used_at,
            )
            for name in idle[: max(1, len(idle) // 2)]:
                del _boards[name]
        entry = _boards[key] = _Board()
    entry.used_at = time.monotonic()
    return entry


def _read(entry: _Board, records: list[PaneBranchRecord], *, front: bool) -> None:
    global _front_reads
    panes: dict[str, dict[str, Any] | None] | None = None
    try:
        panes = statuses(records, live_ttl=_LIVE_TTL if front else _WARM_GITHUB_TTL)
    except Exception:  # noqa: BLE001 - nothing may leave a board "reading" for good
        logger.opt(exception=True).warning("Session GitHub status: a background read failed")
    finally:
        with _boards_lock:
            if panes is not None:
                entry.panes = panes
                entry.read_for = {record.pane: _identity(record) for record in records}
                entry.read_at = time.time()
            entry.failed = panes is None
            entry.reading = False
            if front:
                _front_reads -= 1
                if not _front_reads:
                    _front_idle.set()
            _boards_read.notify_all()


def _start(target: Callable[[], None], name: str) -> bool:
    try:
        threading.Thread(target=target, name=name, daemon=True).start()
    except RuntimeError:
        # No thread to be had: the read did not start, so nothing may wait for it.
        logger.warning("Session GitHub status: a background read could not start")
        return False
    return True


def board(key: str, records: list[PaneBranchRecord], *, wait: float = 0) -> dict[str, Any]:
    """What is known about a workspace's panes, at once.

    ``refreshing`` says a newer answer is being read and worth asking for again;
    ``age`` is how many seconds ago the answer was read (None before the first
    read); ``waiting`` names the panes that have no answer yet; ``failed`` says
    the last read failed, so the answer is not being kept current.

    With ``wait`` the answer waits up to that many seconds for a running read
    to finish, so the caller learns of it the moment it lands instead of on
    its next poll.
    """
    global _front_reads
    with _boards_lock:
        entry = _entry(key)
        # A read for the tab in front replaces its read ahead, if that has not begun.
        _ahead.pop(key, None)
        current = {record.pane: _identity(record) for record in records}
        changed = any(entry.read_for.get(pane) != identity for pane, identity in current.items())
        pause = _RETRY_S if changed or entry.read_at is None else _BOARD_TTL
        start = not entry.reading and time.monotonic() - entry.tried_at >= pause
        if start:
            entry.reading = True
            entry.tried_at = time.monotonic()
            _front_reads += 1
            _front_idle.clear()
    if start and not _start(lambda: _read(entry, records, front=True), "pane-github-status"):
        with _boards_lock:
            entry.reading = False
            _front_reads -= 1
            if not _front_reads:
                _front_idle.set()
    with _boards_lock:
        deadline = time.monotonic() + min(max(wait, 0), _MAX_WAIT_S)
        while entry.reading and (left := deadline - time.monotonic()) > 0:
            _boards_read.wait(left)
        panes = {
            pane: entry.panes[pane]
            for pane, identity in current.items()
            if pane in entry.panes and entry.read_for.get(pane) == identity
        }
        reading = entry.reading
        failed = entry.failed and not reading
        age = None if entry.read_at is None else max(0.0, time.time() - entry.read_at)
    return {
        "panes": panes,
        "refreshing": reading,
        "age": age,
        "waiting": [pane for pane in current if pane not in panes] if reading else [],
        "failed": failed,
    }


def _due(entry: _Board | None) -> bool:
    """Is a board behind the front one worth reading now? Holds ``_boards_lock``."""
    if entry is None:
        return True
    if entry.reading or time.monotonic() - entry.tried_at < _WARM_S:
        return False
    return entry.read_at is None or time.time() - entry.read_at >= _WARM_S


def due(key: str) -> bool:
    """Should the tab ``key``, behind the front one, be read ahead now?"""
    with _boards_lock:
        return key not in _ahead and _due(_boards.get(key))


def _drain_ahead() -> None:
    global _ahead_running
    while True:
        _front_idle.wait(timeout=30)
        with _boards_lock:
            if not _ahead:
                _ahead_running = False
                return
            key = next(iter(_ahead))
            records = _ahead.pop(key)
            entry = _boards.get(key)
            if entry is None or not _due(entry):
                continue
            entry.reading = True
            entry.tried_at = time.monotonic()
        _read(entry, records, front=False)


def read_ahead(key: str, records: list[PaneBranchRecord]) -> None:
    """Read a tab nobody is looking at, one after another with the others.

    A tab is read before its first visit, and again whenever its answer is
    older than ``_WARM_S``, for as long as a tab in front is being shown. Its
    header then has a recent answer the moment someone switches to it.
    """
    global _ahead_running
    with _boards_lock:
        if key in _ahead or not _due(_boards.get(key)):
            return
        _entry(key)
        _ahead[key] = records
        if _ahead_running:
            return
        _ahead_running = True
    if not _start(_drain_ahead, "pane-github-ahead"):
        with _boards_lock:
            _ahead_running = False
            _ahead.clear()
