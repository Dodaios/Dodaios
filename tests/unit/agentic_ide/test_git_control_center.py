"""The Git tab as a control center: the fast local read and the actions it offers."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from jarvis.agentic_ide import git_local, git_ops, git_overview, github_link, github_pulls
from jarvis.agentic_ide.git_ops import GitError
from jarvis.agentic_ide.git_overview import CiStatus, PullRequest

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    git_overview.clear_cache()


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True, encoding="utf-8"
    ).stdout.strip()


def _commit(root: Path, name: str, text: str = "") -> str:
    (root / name).write_text(text or name, encoding="utf-8")
    _git(root, "add", name)
    _git(root, "commit", "-q", "-m", f"add {name}")
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    return bare


@pytest.fixture
def repo(tmp_path: Path, remote: Path) -> Path:
    """A clone on ``main`` with one pushed commit."""
    root = tmp_path / "project"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _commit(root, "a.txt")
    _git(root, "remote", "add", "origin", str(remote))
    _git(root, "push", "-q", "-u", "origin", "main")
    _git(root, "remote", "set-head", "origin", "main")
    return root


@pytest.fixture
def other(tmp_path: Path, remote: Path) -> Path:
    """A second clone: someone else pushing to the same remote."""
    clone = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(remote), str(clone))
    return clone


# ------------------------------------------------------------------ the local read


def test_checkout_reports_what_is_uncommitted_and_how_it_stands(repo: Path, other: Path) -> None:
    _commit(other, "theirs.txt")
    _git(other, "push", "-q")
    _git(repo, "fetch", "-q")
    _commit(repo, "mine.txt")
    (repo / "a.txt").write_text("edited", encoding="utf-8")
    (repo / "staged.txt").write_text("s", encoding="utf-8")
    _git(repo, "add", "staged.txt")
    (repo / "new.txt").write_text("n", encoding="utf-8")

    checkout = git_overview.overview(repo, github=False).checkout
    assert (checkout.branch, checkout.upstream) == ("main", "origin/main")
    assert (checkout.ahead, checkout.behind) == (1, 1)
    assert (checkout.staged, checkout.unstaged, checkout.untracked) == (1, 1, 1)
    assert checkout.files == 3 and checkout.conflicted == 0
    assert checkout.has_remote and checkout.last_fetch > 0
    assert checkout.operation == ""


def test_an_unfinished_merge_is_named(repo: Path) -> None:
    _git(repo, "switch", "-q", "-c", "side")
    _commit(repo, "a.txt", "side")
    _git(repo, "switch", "-q", "main")
    _commit(repo, "a.txt", "main")
    subprocess.run(["git", "merge", "side"], cwd=repo, capture_output=True, check=False)
    checkout = git_overview.overview(repo, github=False).checkout
    assert checkout.operation == "merge" and checkout.conflicted == 1


def test_branches_say_how_far_they_are_from_the_default_branch(repo: Path) -> None:
    _git(repo, "switch", "-q", "-c", "feature/wip")
    _commit(repo, "b.txt")
    _commit(repo, "c.txt")
    _git(repo, "switch", "-q", "main")
    _commit(repo, "d.txt")
    _git(repo, "push", "-q")
    info = git_overview.overview(repo, github=False)
    assert info.base_ref == "origin/main"
    wip = next(row for row in info.branches if row.name == "feature/wip")
    assert (wip.base_ahead, wip.base_behind) == (2, 1)
    assert wip.merged_into == [] and not wip.upstream_gone


def test_a_deleted_upstream_is_reported_as_gone(repo: Path) -> None:
    _git(repo, "switch", "-q", "-c", "feature/done")
    _commit(repo, "b.txt")
    _git(repo, "push", "-q", "-u", "origin", "feature/done")
    _git(repo, "switch", "-q", "main")
    _git(repo, "push", "-q", "origin", "--delete", "feature/done")
    rows = git_overview.overview(repo, github=False).branches
    assert next(row for row in rows if row.name == "feature/done").upstream_gone


def test_the_branch_list_is_reused_until_a_ref_moves(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads: list[Path] = []
    real = git_local._read_heads

    def counting(root: Path):
        reads.append(root)
        return real(root)

    monkeypatch.setattr(git_local, "_read_heads", counting)
    git_overview.overview(repo, github=False)
    git_overview.overview(repo, github=False)
    assert len(reads) == 1  # nothing moved: no branch listing ran again
    # An uncommitted edit changes the checkout, never the branch list.
    (repo / "a.txt").write_text("edited", encoding="utf-8")
    assert git_local.read(repo) is not None
    assert len(reads) == 1
    _commit(repo, "b.txt")
    names = [row.name for row in git_overview.overview(repo, github=False).branches]
    assert len(reads) == 2 and names == ["main"]
    _git(repo, "branch", "feature/new")
    names = [row.name for row in git_overview.overview(repo, github=False).branches]
    assert len(reads) == 3 and set(names) == {"main", "feature/new"}


def test_unfetched_commits_on_github_are_flagged(
    repo: Path, other: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    theirs = _commit(other, "theirs.txt")
    _git(other, "push", "-q")

    def snapshot(repo_name: str, token: str) -> git_overview._GitHubSnapshot:
        snap = git_overview._GitHubSnapshot(ok=True, fetched_at=git_overview.time.time())
        snap.refs["main"] = (theirs[:12], CiStatus())
        return snap

    monkeypatch.setattr(git_overview, "_fetch_github", snapshot)
    monkeypatch.setattr(github_link, "credential", lambda: github_link.Credential("t", "app"))
    monkeypatch.setattr(github_link, "bound_repository", lambda folder: "o/r")
    main = git_overview.overview(repo).branches[0]
    assert main.unfetched and main.behind == 0  # git cannot know yet; GitHub does
    _git(repo, "fetch", "-q")
    main = git_overview.overview(repo).branches[0]
    assert not main.unfetched and main.behind == 1


def test_open_pull_requests_list_what_is_broken_first() -> None:
    def pr(number: int, **extra: object) -> PullRequest:
        base = {"title": "t", "url": "u", "state": "open", "base": "main", "head": f"b{number}"}
        return PullRequest(number=number, **{**base, **extra})  # type: ignore[arg-type]

    snap = git_overview._GitHubSnapshot(ok=True)
    snap.prs = [
        pr(1, state="draft"),
        pr(2),
        pr(3, ci=CiStatus(state="failure")),
        pr(4, state="queued"),
        pr(5, state="merged"),
        pr(6, conflicting=True),
        pr(7, review="changes_requested"),
    ]
    assert [p.number for p in git_overview._open_pull_requests(snap)] == [3, 6, 7, 4, 2, 1]


# ------------------------------------------------------------------ pull / update / push


def test_pull_fast_forwards(repo: Path, other: Path) -> None:
    _commit(other, "theirs.txt")
    _git(other, "push", "-q")
    assert "up to date" in git_ops.pull(repo)
    assert (repo / "theirs.txt").is_file()


def test_pull_never_rewrites_a_diverged_branch_unasked(repo: Path, other: Path) -> None:
    _commit(other, "theirs.txt")
    _git(other, "push", "-q")
    mine = _commit(repo, "mine.txt")
    with pytest.raises(GitError) as exc:
        git_ops.pull(repo)
    assert exc.value.code == "diverged"
    assert _git(repo, "rev-parse", "HEAD") == mine  # untouched
    assert "Rebased" in git_ops.pull(repo, rebase=True)
    assert (repo / "theirs.txt").is_file() and (repo / "mine.txt").is_file()
    assert git_ops.inspect(repo).behind == 0


def test_a_conflicting_rebase_is_aborted(repo: Path, other: Path) -> None:
    _commit(other, "a.txt", "theirs")
    _git(other, "push", "-q")
    mine = _commit(repo, "a.txt", "mine")
    with pytest.raises(GitError) as exc:
        git_ops.pull(repo, rebase=True)
    assert exc.value.code == "conflict"
    assert _git(repo, "rev-parse", "HEAD") == mine
    assert git_overview.overview(repo, github=False).checkout.operation == ""


def test_update_branch_moves_a_branch_that_is_not_checked_out(repo: Path, other: Path) -> None:
    _git(repo, "switch", "-q", "-c", "feature/x")
    theirs = _commit(other, "theirs.txt")
    _git(other, "push", "-q")
    git_ops.update_branch(repo, "main")
    assert _git(repo, "rev-parse", "main") == theirs
    assert git_ops.inspect(repo).branch == "feature/x"  # never switched


def test_update_branch_refuses_to_drop_local_commits(repo: Path, other: Path) -> None:
    mine = _commit(repo, "mine.txt")
    _git(repo, "switch", "-q", "-c", "feature/x")
    _commit(other, "theirs.txt")
    _git(other, "push", "-q")
    with pytest.raises(GitError) as exc:
        git_ops.update_branch(repo, "main")
    assert exc.value.code == "diverged"
    assert _git(repo, "rev-parse", "main") == mine


def test_push_publishes_a_branch_without_switching_to_it(repo: Path, remote: Path) -> None:
    _git(repo, "switch", "-q", "-c", "feature/x")
    tip = _commit(repo, "b.txt")
    _git(repo, "switch", "-q", "main")
    assert git_ops.push(repo, "feature/x") == "origin/feature/x"
    assert _git(remote, "rev-parse", "feature/x") == tip
    assert git_ops.inspect(repo).branch == "main"


# ------------------------------------------------------------------ delete


def test_deleting_a_branch_asks_again_when_its_commits_exist_nowhere_else(repo: Path) -> None:
    _git(repo, "switch", "-q", "-c", "feature/x")
    _commit(repo, "b.txt")
    _commit(repo, "c.txt")
    _git(repo, "switch", "-q", "main")
    with pytest.raises(GitError) as exc:
        git_ops.delete_branch(repo, "feature/x")
    assert exc.value.code == "unmerged" and "2 commits" in str(exc.value)
    assert git_ops.branch_tip(repo, "feature/x")
    assert "Deleted feature/x" in git_ops.delete_branch(repo, "feature/x", force=True)
    assert git_ops.branch_tip(repo, "feature/x") == ""


def test_a_pushed_or_merged_branch_is_deleted_without_a_second_question(
    repo: Path, remote: Path
) -> None:
    _git(repo, "switch", "-q", "-c", "feature/pushed")
    _commit(repo, "b.txt")
    _git(repo, "push", "-q", "-u", "origin", "feature/pushed")
    _git(repo, "switch", "-q", "main")
    # Its work is in main, so both copies of the branch may go.
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge pushed", "feature/pushed")
    summary = git_ops.delete_branch(repo, "feature/pushed", remote=True)
    assert summary == "Deleted feature/pushed here and on origin."
    assert "feature/pushed" not in _git(remote, "branch", "--list")
    # A squash merge leaves commits git cannot find elsewhere; the caller's proof decides.
    _git(repo, "switch", "-q", "-c", "feature/squashed")
    _commit(repo, "c.txt")
    _git(repo, "switch", "-q", "main")
    assert "Deleted" in git_ops.delete_branch(repo, "feature/squashed", merged=True)


def test_the_current_and_the_default_branch_cannot_be_deleted(repo: Path) -> None:
    _git(repo, "switch", "-q", "-c", "feature/x")
    for name, code in (("feature/x", "current"), ("main", "invalid")):
        with pytest.raises(GitError) as exc:
            git_ops.delete_branch(repo, name, force=True)
        assert exc.value.code == code


def test_a_branch_in_a_worktree_goes_only_with_a_clean_unused_worktree(repo: Path) -> None:
    made = git_ops.prepare(repo, "new_worktree", branch="agent/one")
    tree = Path(made.folder)
    with pytest.raises(GitError) as exc:
        git_ops.delete_branch(repo, "agent/one")
    assert exc.value.code == "checked_out"
    with pytest.raises(GitError) as exc:
        git_ops.delete_branch(repo, "agent/one", with_worktree=True, open_folders=[str(tree)])
    assert exc.value.code == "in_use"
    (tree / "wip.txt").write_text("unsaved", encoding="utf-8")
    with pytest.raises(GitError) as exc:
        git_ops.delete_branch(repo, "agent/one", with_worktree=True)
    assert exc.value.code == "dirty"
    assert tree.is_dir() and git_ops.branch_tip(repo, "agent/one")  # nothing was removed
    (tree / "wip.txt").unlink()
    git_ops.delete_branch(repo, "agent/one", with_worktree=True)
    assert not tree.exists() and git_ops.branch_tip(repo, "agent/one") == ""


def test_the_delete_route_takes_a_merged_pull_request_as_proof(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import HTTPException

    from jarvis.ui.web import agentic_ide_git_routes as routes

    _git(repo, "switch", "-q", "-c", "feature/squashed")
    tip = _commit(repo, "b.txt")
    _git(repo, "switch", "-q", "main")
    request = routes.DeleteBranchRequest(folder=str(repo), branch="feature/squashed")
    with pytest.raises(HTTPException) as exc:
        routes.delete_branch(request)
    assert exc.value.detail["code"] == "unmerged"

    snap = git_overview._GitHubSnapshot(ok=True, fetched_at=git_overview.time.time())
    snap.prs = [
        PullRequest(
            number=8, title="t", url="u", state="merged", base="main",
            head="feature/squashed", head_oid=tip[:12],
        )
    ]  # fmt: skip
    git_overview._CACHE._entries["o/r"] = snap
    monkeypatch.setattr(github_link, "bound_repository", lambda folder: "o/r")
    assert routes.delete_branch(request)["ok"]
    assert git_ops.branch_tip(repo, "feature/squashed") == ""


# ------------------------------------------------------------------ pull requests


def test_a_pull_request_is_opened_through_the_github_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    def fake_graphql(token: str, query: str, variables: dict | None = None) -> dict:
        calls.append(variables or {})
        if "createPullRequest" not in query:
            return {"data": {"repository": {"id": "R_1"}}}
        return {
            "data": {"createPullRequest": {"pullRequest": {"number": 12, "url": "https://x/12"}}}
        }

    monkeypatch.setattr(github_link, "graphql", fake_graphql)
    created = github_pulls.create("o/r", "t", head="feature/x", base="main", title="Add x")
    assert (created.number, created.url) == (12, "https://x/12")
    assert calls[1]["input"] == {
        "repositoryId": "R_1",
        "baseRefName": "main",
        "headRefName": "feature/x",
        "title": "Add x",
        "draft": False,
    }


def test_github_refusing_a_pull_request_is_said_in_its_own_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_graphql(token: str, query: str, variables: dict | None = None) -> dict:
        if "createPullRequest" not in query:
            return {"data": {"repository": {"id": "R_1"}}}
        return {
            "data": {"createPullRequest": None},
            "errors": [{"message": "A pull request already exists for o:feature/x."}],
        }

    monkeypatch.setattr(github_link, "graphql", fake_graphql)
    with pytest.raises(github_link.GitHubError) as exc:
        github_pulls.create("o/r", "t", head="feature/x", base="main", title="Add x")
    assert "already exists" in str(exc.value) and exc.value.code == "refused"


def test_the_pull_request_route_pushes_and_titles_from_the_first_commit(
    repo: Path, remote: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from jarvis.ui.web import agentic_ide_git_routes as routes

    _git(repo, "switch", "-q", "-c", "feature/x")
    _commit(repo, "b.txt")
    tip = _commit(repo, "c.txt")
    seen: dict = {}

    def fake_create(repo_name: str, token: str, **kwargs: object):
        seen.update(kwargs, repo=repo_name)
        return github_pulls.CreatedPullRequest(number=3, url="https://x/3")

    monkeypatch.setattr(github_pulls, "create", fake_create)
    monkeypatch.setattr(github_link, "credential", lambda: github_link.Credential("t", "app"))
    monkeypatch.setattr(github_link, "bound_repository", lambda folder: "o/r")
    answer = routes.open_pull_request(routes.PullRequestRequest(folder=str(repo)))
    assert answer == {"ok": True, "url": "https://x/3"}
    assert seen == {
        "repo": "o/r", "head": "feature/x", "base": "main", "title": "add b.txt", "draft": False,
    }  # fmt: skip
    assert _git(remote, "rev-parse", "feature/x") == tip  # pushed first


# ------------------------------------------------------------------ reading GitHub


def _repo_payload(**parts: object) -> dict:
    return {"data": {"repository": {"url": "https://github.com/o/r", **parts}}}


def _pr_node(number: int, head: str, state: str = "OPEN") -> dict:
    return {
        "number": number,
        "title": f"PR {number}",
        "url": f"https://github.com/o/r/pull/{number}",
        "state": state,
        "headRefName": head,
        "baseRefName": "main",
        "mergeable": "CONFLICTING" if number == 2 else "MERGEABLE",
        "reviewDecision": "CHANGES_REQUESTED" if number == 2 else None,
        "author": {"login": "dana"},
    }


def test_github_is_asked_in_parts_and_a_missing_part_only_costs_its_own_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[str] = []

    def fake_graphql(token: str, query: str, variables: dict | None = None) -> dict:
        if "pageInfo" in query:
            return _repo_payload(refs={"pageInfo": {"hasNextPage": False}, "nodes": []})
        if "states: OPEN" in query:
            asked.append("open")
            return _repo_payload(pullRequests={"nodes": [_pr_node(1, "a"), _pr_node(2, "b")]})
        if "MERGED" in query:
            asked.append("recent")
            raise github_link.GitHubError("GitHub could not be reached.", code="unreachable")
        asked.append("refs")
        return _repo_payload(refs={"nodes": [{"name": "main", "target": {"oid": "0" * 40}}]})

    monkeypatch.setattr(github_link, "graphql", fake_graphql)
    snap = git_overview._fetch_github("o/r", "t")
    assert sorted(asked) == ["open", "recent", "refs"]
    # Recently merged pull requests are missing this round; everything else landed.
    assert snap.ok and [pr.number for pr in snap.prs] == [1, 2]
    assert (snap.prs[1].conflicting, snap.prs[1].review, snap.prs[1].author) == (
        True,
        "changes_requested",
        "dana",
    )
    assert "main" in snap.refs


def test_a_refresh_never_makes_the_tab_wait_for_github(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    release = threading.Event()
    reads: list[float] = []

    def slow_fetch(repo_name: str, token: str) -> git_overview._GitHubSnapshot:
        reads.append(git_overview.time.time())
        if len(reads) > 1:
            release.wait(5)
        snap = git_overview._GitHubSnapshot(ok=True, fetched_at=git_overview.time.time())
        snap.refs["main"] = ("0" * 12, CiStatus(state="success" if len(reads) > 1 else "none"))
        return snap

    monkeypatch.setattr(git_overview, "_fetch_github", slow_fetch)
    monkeypatch.setattr(github_link, "credential", lambda: github_link.Credential("t", "app"))
    monkeypatch.setattr(github_link, "bound_repository", lambda folder: "o/r")
    first = git_overview.overview(repo)
    assert first.github.available and not first.github.refreshing

    # A push makes the answer outdated: it stays on screen while the new one loads.
    git_overview.clear_github(repo)
    started = git_overview.time.time()
    stale = git_overview.overview(repo, refresh=True, wait_for_github=False)
    assert git_overview.time.time() - started < 2
    assert stale.github.available and stale.github.refreshing
    assert stale.branches[0].ci.state == "none"
    release.set()
    deadline = git_overview.time.time() + 5
    while git_overview.time.time() < deadline:
        later = git_overview.overview(repo, wait_for_github=False)
        if not later.github.refreshing:
            break
        git_overview.time.sleep(0.05)
    assert later.branches[0].ci.state == "success" and len(reads) == 2


# ------------------------------------------------------------------ hardening


def test_deleting_the_remote_branch_too_never_counts_it_as_a_safe_copy(
    repo: Path, remote: Path
) -> None:
    _git(repo, "switch", "-q", "-c", "feature/open")
    tip = _commit(repo, "b.txt")
    _git(repo, "push", "-q", "-u", "origin", "feature/open")
    _git(repo, "switch", "-q", "main")
    # Pushed but not merged: the remote copy is the only other place the work lives.
    with pytest.raises(GitError) as exc:
        git_ops.delete_branch(repo, "feature/open", remote=True)
    assert exc.value.code == "unmerged"
    assert git_ops.branch_tip(repo, "feature/open") == tip
    assert _git(remote, "rev-parse", "feature/open") == tip
    # Without the remote delete the pushed copy keeps the work, so the local branch may go.
    assert "Deleted feature/open." == git_ops.delete_branch(repo, "feature/open")
    assert _git(remote, "rev-parse", "feature/open") == tip


def test_a_worktree_an_agent_pane_runs_in_counts_as_open(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from jarvis.ui.web import agentic_ide_git_routes as routes

    pane = SimpleNamespace(cwd=lambda workspace: "/code/app/.worktrees/agent-x")
    plain = SimpleNamespace(cwd=lambda workspace: workspace)
    session = SimpleNamespace(folder="/code/app", terminals=[pane, plain])
    monkeypatch.setattr(routes, "get_registry", lambda: SimpleNamespace(sessions=[session]))
    assert routes._open_folders() == ["/code/app", "/code/app/.worktrees/agent-x", "/code/app"]


def test_a_local_merge_survives_a_rebase(repo: Path, other: Path) -> None:
    _commit(other, "theirs.txt")
    _git(other, "push", "-q")
    _git(repo, "switch", "-q", "-c", "side")
    _commit(repo, "side.txt")
    _git(repo, "switch", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    git_ops.pull(repo, rebase=True)
    assert _git(repo, "log", "-1", "--format=%s") == "merge side"
    assert len(_git(repo, "log", "-1", "--format=%P").split()) == 2  # still a merge


def test_a_failed_github_read_keeps_the_last_good_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = [
        git_overview._GitHubSnapshot(ok=True, fetched_at=git_overview.time.time() - 500),
        git_overview._GitHubSnapshot(ok=False, code="unreachable", fetched_at=0.0),
    ]
    reads: list[str] = []

    def fetch(repo_name: str, token: str) -> git_overview._GitHubSnapshot:
        reads.append(repo_name)
        return answers[min(len(reads), len(answers)) - 1]

    monkeypatch.setattr(git_overview, "_fetch_github", fetch)
    cache = git_overview._GitHubCache()
    good = cache.get("o/r", "t")
    assert good is answers[0]
    # Stale by now: a forced read fails, and the good answer stays.
    assert cache.get("o/r", "t", force=True) is good
    assert len(reads) == 2
    # ... and the failure is not retried on every poll.
    assert cache.get("o/r", "t", wait=False) is good
    assert not cache.loading("o/r") and len(reads) == 2


def test_a_git_call_that_fails_is_not_remembered_as_no_branches(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert [row.name for row in git_local.read(repo).branches] == ["main"]
    real = git_local.git_out
    broken = {"on": True}

    def flaky(args: list[str], cwd: Path) -> str | None:
        if broken["on"] and args[0] in {"for-each-ref", "status"}:
            return None
        return real(args, cwd)

    monkeypatch.setattr(git_local, "git_out", flaky)
    _git(repo, "branch", "feature/new")  # moves a ref: the branch list has to be re-read
    state = git_local.read(repo, fresh=True)
    # Git did not answer: the last known state is shown, not an empty repository.
    assert state is not None and [row.name for row in state.branches] == ["main"]
    assert state.checkout.branch == "main"
    broken["on"] = False
    names = {row.name for row in git_local.read(repo).branches}
    assert names == {"main", "feature/new"}
