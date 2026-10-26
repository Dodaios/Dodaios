"""A branch never carries its own frontend bundle: updating it puts main's back.

Two frontend pull requests that each committed a build conflicted the moment
one of them merged, and the merge queue ejected the other. The bundle is now
rebuilt on main after the merge (frontend-bundle.yml), so ``pin_bundle`` drops
whatever build a branch carries, except on the rebuild workflow's own branch.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.ci import agent_integrate

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DIST = agent_integrate.BUNDLE_DIR


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        creationflags=_NO_WINDOW,
    ).stdout


def _commit(repo: Path, message: str, files: dict[str, str | None]) -> str:
    for name, text in files.items():
        path = repo / name
        if text is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
    _git(repo, "add", "-A", ".")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "test")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    _commit(
        tmp_path,
        "base",
        {
            f"{DIST}/index.html": '<script src="/assets/index-AAAAAAAA.js"></script>\n',
            f"{DIST}/assets/index-AAAAAAAA.js": "base\n",
            "dodaios/ui/web/frontend/src/app.tsx": "base\n",
        },
    )
    return tmp_path


def _branch_with_own_build(repo: Path, name: str) -> None:
    _git(repo, "checkout", "-q", "-b", name, "main")
    _commit(
        repo,
        "feature with its own build",
        {
            "dodaios/ui/web/frontend/src/app.tsx": "feature\n",
            f"{DIST}/index.html": '<script src="/assets/index-BBBBBBBB.js"></script>\n',
            f"{DIST}/assets/index-AAAAAAAA.js": None,
            f"{DIST}/assets/index-BBBBBBBB.js": "feature\n",
        },
    )


def _bundle(repo: Path, rev: str) -> str:
    return _git(repo, "ls-tree", "-r", rev, "--", DIST)


def test_branch_build_is_replaced_by_mains(repo: Path) -> None:
    _branch_with_own_build(repo, "claude/feature")

    assert agent_integrate.pin_bundle("main", repo) is True

    assert _bundle(repo, "HEAD") == _bundle(repo, "main")
    # The source change stays; only the build goes.
    assert _git(repo, "show", "HEAD:dodaios/ui/web/frontend/src/app.tsx") == "feature\n"
    assert _git(repo, "status", "--porcelain", "--untracked-files=no") == ""


def test_nothing_to_do_when_the_branch_has_mains_bundle(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "claude/plain", "main")
    _commit(repo, "source only", {"dodaios/ui/web/frontend/src/app.tsx": "x\n"})
    head = _git(repo, "rev-parse", "HEAD")

    assert agent_integrate.pin_bundle("main", repo) is False
    assert _git(repo, "rev-parse", "HEAD") == head


def test_the_rebuild_branch_keeps_its_build(repo: Path) -> None:
    _branch_with_own_build(repo, agent_integrate.BUNDLE_BOT_BRANCH)
    head = _git(repo, "rev-parse", "HEAD")

    assert agent_integrate.pin_bundle("main", repo) is False
    assert _git(repo, "rev-parse", "HEAD") == head


def test_detached_train_worktree_uses_the_given_branch(repo: Path) -> None:
    _branch_with_own_build(repo, agent_integrate.BUNDLE_BOT_BRANCH)
    _git(repo, "checkout", "-q", "--detach")

    assert agent_integrate.pin_bundle("main", repo, agent_integrate.BUNDLE_BOT_BRANCH) is False
    assert agent_integrate.pin_bundle("main", repo, "claude/other") is True
    assert _bundle(repo, "HEAD") == _bundle(repo, "main")


def test_update_drops_the_build_even_when_up_to_date(repo: Path) -> None:
    _branch_with_own_build(repo, "claude/feature")

    report = agent_integrate.update("main", "merge", "", repo)

    assert report["status"] == "updated"
    assert _bundle(repo, "HEAD") == _bundle(repo, "main")


def test_conflicting_bundles_merge_without_a_rebuild(repo: Path) -> None:
    _branch_with_own_build(repo, "claude/feature")
    _git(repo, "checkout", "-q", "main")
    _commit(
        repo,
        "another frontend change landed with its build",
        {
            f"{DIST}/index.html": '<script src="/assets/index-CCCCCCCC.js"></script>\n',
            f"{DIST}/assets/index-AAAAAAAA.js": None,
            f"{DIST}/assets/index-CCCCCCCC.js": "main\n",
        },
    )
    _git(repo, "checkout", "-q", "claude/feature")

    report = agent_integrate.update("main", "merge", "", repo)

    assert report["status"] == "updated"
    assert "regenerated" not in report
    assert _bundle(repo, "HEAD") == _bundle(repo, "main")
