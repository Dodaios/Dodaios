"""Source control for the Git tab, against a real ``git``."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dodaios.agentic_ide import git_changes, scm
from dodaios.agentic_ide.git_ops import GitError

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


@pytest.fixture(autouse=True)
def _identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    # Untracked files go away for good in tests, never into the real trash.
    monkeypatch.setattr(scm, "_trash", lambda target: False)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True, encoding="utf-8"
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "old.txt").write_text("old\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "feat: app")
    return root


@pytest.fixture
def cloned(tmp_path: Path, repo: Path) -> tuple[Path, Path]:
    """A bare remote, the repo pushed to it, and a second clone that can push more."""
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "-u", "origin", "main")
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(remote), str(other))
    return remote, other


def _letters(files: list[scm.ScmFile]) -> dict[str, str]:
    return {entry.path: entry.letter for entry in files}


def test_status_groups_staged_unstaged_untracked_and_renames(repo: Path) -> None:
    (repo / "app.py").write_text("print('changed')\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    (repo / "staged.txt").write_text("s\n", encoding="utf-8")
    _git(repo, "add", "staged.txt")
    _git(repo, "mv", "old.txt", "renamed.txt")
    (repo / "dir").mkdir()
    (repo / "dir" / "deep.txt").write_text("d\n", encoding="utf-8")

    status = scm.read_status(repo)

    assert status.available and status.branch == "main" and not status.detached
    assert _letters(status.changes) == {"app.py": "M", "new.txt": "U", "dir/deep.txt": "U"}
    assert _letters(status.staged) == {"staged.txt": "A", "renamed.txt": "R"}
    renamed = next(entry for entry in status.staged if entry.path == "renamed.txt")
    assert renamed.original == "old.txt" and renamed.status == "index_renamed"
    assert status.head_message == "feat: app"


def test_status_outside_a_repository_is_unavailable(tmp_path: Path) -> None:
    status = scm.read_status(tmp_path)
    assert not status.available and status.reason


def test_stage_unstage_and_discard(repo: Path) -> None:
    (repo / "app.py").write_text("print('changed')\n", encoding="utf-8")
    (repo / "new file.txt").write_text("n\n", encoding="utf-8")
    (repo / "old.txt").unlink()

    scm.stage(repo, ["app.py", "new file.txt", "old.txt"])
    status = scm.read_status(repo)
    assert _letters(status.staged) == {"app.py": "M", "new file.txt": "A", "old.txt": "D"}
    assert status.changes == []

    scm.unstage(repo, ["app.py"])
    status = scm.read_status(repo)
    assert _letters(status.changes) == {"app.py": "M"}

    scm.discard(repo, ["app.py"])
    assert (repo / "app.py").read_text(encoding="utf-8") == "print('hi')\n"

    scm.unstage_all(repo)
    scm.discard(repo, ["new file.txt", "old.txt"])
    assert not (repo / "new file.txt").exists()
    assert (repo / "old.txt").exists()
    assert scm.read_status(repo).changes == []


def test_paths_outside_the_repository_are_refused(repo: Path) -> None:
    for bad in ["../escape.txt", "/etc/passwd", "C:/Windows/x", ""]:
        with pytest.raises(GitError) as exc:
            scm.stage(repo, [bad])
        assert exc.value.code == "invalid"


def test_discard_all_keeps_untracked_unless_asked(repo: Path) -> None:
    (repo / "app.py").write_text("x\n", encoding="utf-8")
    (repo / "new.txt").write_text("n\n", encoding="utf-8")
    scm.discard_all(repo, untracked=False)
    assert _letters(scm.read_status(repo).changes) == {"new.txt": "U"}
    scm.discard_all(repo, untracked=True)
    assert scm.read_status(repo).changes == []


def test_commit_amend_all_and_undo(repo: Path) -> None:
    (repo / "app.py").write_text("print('two')\n", encoding="utf-8")
    with pytest.raises(GitError) as exc:
        scm.commit(repo, "fix: nothing staged")
    assert exc.value.code == "clean"

    scm.commit(repo, "fix: two\n\nbody line", all_changes=True)
    assert _git(repo, "log", "-1", "--format=%B").strip() == "fix: two\n\nbody line"

    (repo / "more.txt").write_text("m\n", encoding="utf-8")
    scm.stage(repo, ["more.txt"])
    scm.commit(repo, "", amend=True)
    assert _git(repo, "rev-list", "--count", "HEAD") == "2"
    assert "more.txt" in _git(repo, "show", "--name-only", "--format=", "HEAD")

    message = scm.undo_last_commit(repo)
    assert message.startswith("fix: two")
    status = scm.read_status(repo)
    assert {"app.py", "more.txt"} <= {entry.path for entry in status.staged}
    assert _git(repo, "rev-list", "--count", "HEAD") == "1"


def test_undo_the_first_commit_keeps_the_files_staged(tmp_path: Path) -> None:
    root = tmp_path / "fresh"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "a.txt").write_text("a\n", encoding="utf-8")
    scm.stage(root, ["a.txt"])
    scm.commit(root, "first")
    scm.undo_last_commit(root)
    status = scm.read_status(root)
    assert status.unborn and _letters(status.staged) == {"a.txt": "A"}
    scm.unstage(root, ["a.txt"])
    assert _letters(scm.read_status(root).changes) == {"a.txt": "U"}


def test_ignore_appends_once(repo: Path) -> None:
    (repo / "build.log").write_text("x\n", encoding="utf-8")
    scm.ignore(repo, ["build.log"])
    scm.ignore(repo, ["build.log"])
    assert (repo / ".gitignore").read_text(encoding="utf-8") == "/build.log\n"
    assert "build.log" not in {entry.path for entry in scm.read_status(repo).changes}


def test_branches_tags_checkout_and_merge_conflict(repo: Path) -> None:
    scm.create_branch(repo, "feature/x")
    assert scm.read_status(repo).branch == "feature/x"
    (repo / "app.py").write_text("print('feature')\n", encoding="utf-8")
    scm.commit(repo, "feat: feature", all_changes=True)
    scm.create_tag(repo, "v1.0", message="first release")
    refs = scm.list_refs(repo)
    names = {(ref["kind"], ref["name"]) for ref in refs["refs"]}
    assert {("head", "main"), ("head", "feature/x"), ("tag", "v1.0")} <= names
    assert refs["current"] == "feature/x"

    scm.checkout(repo, "main")
    (repo / "app.py").write_text("print('main')\n", encoding="utf-8")
    scm.commit(repo, "feat: main", all_changes=True)
    assert scm.merge(repo, "feature/x") == "conflict"
    status = scm.read_status(repo)
    assert status.operation == "merge"
    assert [(entry.path, entry.letter) for entry in status.merge] == [("app.py", "!")]

    scm.abort_operation(repo)
    assert scm.read_status(repo).operation == ""

    with pytest.raises(GitError) as exc:
        scm.delete_branch(repo, "feature/x")
    assert exc.value.code == "unmerged"
    scm.delete_branch(repo, "feature/x", force=True)
    scm.delete_tag(repo, "v1.0")
    assert {ref["name"] for ref in scm.list_refs(repo)["refs"]} == {"main"}

    with pytest.raises(GitError):
        scm.create_branch(repo, "bad..name")
    with pytest.raises(GitError):
        scm.checkout(repo, "--orphan")


def test_stash_round_trip(repo: Path) -> None:
    (repo / "app.py").write_text("stashed\n", encoding="utf-8")
    (repo / "new.txt").write_text("n\n", encoding="utf-8")
    scm.stash(repo, message="wip", include_untracked=True)
    assert scm.read_status(repo).changes == []
    stashes = scm.list_stashes(repo)
    assert len(stashes) == 1 and "wip" in stashes[0]["message"]
    assert scm.read_status(repo).stashes == 1

    scm.stash_apply(repo, stashes[0]["ref"])
    assert (repo / "app.py").read_text(encoding="utf-8") == "stashed\n"
    scm.discard_all(repo, untracked=True)
    scm.stash_apply(repo, pop=True)
    assert scm.list_stashes(repo) == []
    with pytest.raises(GitError):
        scm.stash_drop(repo, "HEAD")


def test_graph_commit_details_and_file_diff(repo: Path) -> None:
    (repo / "app.py").write_text("print('v2')\n", encoding="utf-8")
    _git(repo, "mv", "old.txt", "moved.txt")
    scm.commit(repo, "feat: v2", all_changes=True)

    page = scm.graph(repo, limit=1)
    assert len(page["commits"]) == 1 and page["more"]
    top = page["commits"][0]
    assert top["subject"] == "feat: v2" and top["id"] == page["head"]
    assert any("HEAD" in ref for ref in top["refs"])
    rest = scm.graph(repo, skip=1, limit=10)
    assert [entry["subject"] for entry in rest["commits"]] == ["feat: app"]
    assert rest["commits"][0]["parents"] == [] and not rest["more"]

    details = scm.commit_details(repo, top["id"])
    assert details["message"] == "feat: v2"
    files = {entry["path"]: entry for entry in details["files"]}
    assert files["app.py"]["letter"] == "M"
    assert files["moved.txt"]["letter"] == "R" and files["moved.txt"]["original"] == "old.txt"

    diff = scm.commit_file_diff(repo, top["id"], "app.py")
    assert diff["before"] == "print('hi')\n" and diff["after"] == "print('v2')\n"
    first = scm.commit_details(repo, rest["commits"][0]["id"])
    assert {entry["letter"] for entry in first["files"]} == {"A"}
    added = scm.commit_file_diff(repo, rest["commits"][0]["id"], "app.py")
    assert added["before"] is None and added["after"] == "print('hi')\n"


def test_index_text_reads_the_staged_copy(repo: Path) -> None:
    (repo / "app.py").write_text("staged\n", encoding="utf-8")
    scm.stage(repo, ["app.py"])
    (repo / "app.py").write_text("worktree\n", encoding="utf-8")
    assert git_changes.head_text(repo, "app.py", git_changes.INDEX_REF) == "staged\n"
    assert git_changes.head_text(repo, "app.py") == "print('hi')\n"
    assert git_changes.head_text(repo, "missing.txt", git_changes.INDEX_REF) is None


def test_remote_sync_publish_and_incoming(repo: Path, cloned: tuple[Path, Path]) -> None:
    _, other = cloned
    (other / "remote.txt").write_text("r\n", encoding="utf-8")
    _git(other, "add", ".")
    _git(other, "commit", "-q", "-m", "feat: from elsewhere")
    _git(other, "push", "-q")

    scm.fetch(repo)
    status = scm.read_status(repo)
    assert status.upstream == "origin/main" and status.behind == 1 and status.ahead == 0
    page = scm.graph(repo)
    assert len(page["incoming"]) == 1
    assert page["commits"][0]["subject"] == "feat: from elsewhere"

    (repo / "local.txt").write_text("l\n", encoding="utf-8")
    scm.commit(repo, "feat: local", all_changes=True)
    scm.sync(repo)
    status = scm.read_status(repo)
    assert status.ahead == 0 and status.behind == 0
    assert (repo / "remote.txt").exists()

    scm.create_branch(repo, "topic")
    assert scm.read_status(repo).upstream == ""
    assert scm.push(repo) == "origin/topic"
    assert scm.read_status(repo).upstream == "origin/topic"

    scm.checkout(repo, "main")
    scm.delete_branch(repo, "topic", force=True)
    scm.fetch(repo, prune=True)
    assert scm.checkout(repo, "origin/topic") == "topic"
    assert scm.read_status(repo).upstream == "origin/topic"

    scm.add_remote(repo, "mirror", str(cloned[0]))
    assert "mirror" in scm.read_status(repo).remotes
    scm.remove_remote(repo, "mirror")
    with pytest.raises(GitError):
        scm.remove_remote(repo, "mirror")


def test_status_parser_reads_conflicts_and_branch_headers() -> None:
    text = "\0".join(
        [
            "# branch.oid 1234567890abcdef1234567890abcdef12345678",
            "# branch.head topic",
            "# branch.upstream origin/topic",
            "# branch.ab +2 -3",
            "u UU N... 100644 100644 100644 100644 a b c both.txt",
            "1 .D N... 100644 100644 000000 a a gone.txt",
            "1 MM N... 100644 100644 100644 a b both sides.txt",
            "2 R. N... 100644 100644 100644 a a R100 new name.txt",
            "old name.txt",
            "? fresh.txt",
            "",
        ]
    )
    status = scm.ScmStatus(available=True)
    scm.parse_status(text, status)
    assert status.branch == "topic" and status.upstream == "origin/topic"
    assert (status.ahead, status.behind) == (2, 3)
    assert [(entry.path, entry.status) for entry in status.merge] == [("both.txt", "both_modified")]
    assert _letters(status.staged) == {"both sides.txt": "M", "new name.txt": "R"}
    assert status.staged[1].original == "old name.txt"
    assert _letters(status.changes) == {"gone.txt": "D", "both sides.txt": "M", "fresh.txt": "U"}


def test_session_file_diff_reads_the_base_and_the_disk(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    # Bytes, so the disk side has the same line ending on every OS.
    (repo / "app.py").write_bytes(b"print('agent')\n")
    scm.commit(repo, "feat: agent work", all_changes=True)
    (repo / "added.py").write_bytes(b"x = 1\n")
    (repo / "old.txt").unlink()

    changed = scm.session_file_diff(repo, "app.py", base)
    assert changed["before"] == "print('hi')\n" and changed["after"] == "print('agent')\n"
    added = scm.session_file_diff(repo, "added.py", base)
    assert added["before"] is None and added["after"] == "x = 1\n"
    gone = scm.session_file_diff(repo, "old.txt", base)
    assert gone["before"] == "old\n" and gone["after"] is None
    with pytest.raises(GitError):
        scm.session_file_diff(repo, "../outside.txt", base)
    with pytest.raises(GitError):
        scm.session_file_diff(repo, "app.py", "not-a-commit")
