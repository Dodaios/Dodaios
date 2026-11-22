"""A worktree of its own for a delegated coding thread: made, put away, restored."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from dodaios.orchestrator.verification import workdir
from dodaios.orchestrator.verification.store import VerificationStore
from dodaios.orchestrator.verification.workdir import (
    MIN_FREE_BYTES,
    REST_AFTER_MS,
    REST_AFTER_TIGHT_MS,
    WorkDir,
    WorkDirs,
)
from dodaios.rsi import repo_identity

HOUR = 60 * 60 * 1000
ROOMY = 100 * 1024**3


def _git(folder: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=folder, capture_output=True, text=True, check=True, encoding="utf-8"
    )
    return done.stdout.strip()


def _init(folder: Path) -> Path:
    folder.mkdir(parents=True)
    _git(folder, "init", "-q", "-b", "main")
    _git(folder, "config", "user.email", "t@example.com")
    _git(folder, "config", "user.name", "T")
    (folder / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (folder / "pkg").mkdir()
    (folder / "pkg" / "mod.py").write_text("X = 1\n", encoding="utf-8")
    _git(folder, "add", "-A")
    _git(folder, "commit", "-q", "-m", "first")
    return folder


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return _init(tmp_path / "notes")


@pytest.fixture
def store(tmp_path: Path):
    made = VerificationStore(tmp_path / "verification.db")
    yield made
    made.close()


class World:
    """What the app knows about threads, the clock and the disk, set by the test."""

    def __init__(self) -> None:
        self.threads: set[str] = set()
        self.idle: dict[str, int] = {}
        self.now = 1_000_000_000
        self.free = ROOMY

    def dirs(self, store: VerificationStore, **more) -> WorkDirs:
        return WorkDirs(
            store,
            thread_exists=lambda sid: sid in self.threads,
            idle_ms=lambda sid: self.idle.get(sid, 0),
            free_bytes=lambda _folder: self.free,
            now_ms=lambda: self.now,
            **more,
        )


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture(autouse=True)
def _no_sweep_pause(monkeypatch):
    # Every call looks through the repository's worktrees, as if a minute had passed.
    monkeypatch.setattr(workdir, "_SWEEP_TTL_S", 0.0)


# ------------------------------------------------------------------- making


def test_a_new_thread_gets_a_worktree_on_a_new_branch_inside_the_project(repo, store, world):
    made = world.dirs(store).make(str(repo), "Claude Code 2")

    assert made is not None
    folder = Path(made.folder)
    assert folder.parent.resolve() == (repo / ".worktrees").resolve()
    assert made.branch.startswith("agent/claude-code-2-")
    assert folder.name == made.branch.replace("/", "-")
    assert (folder / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert _git(folder, "rev-parse", "--abbrev-ref", "HEAD") == made.branch
    assert made.base_sha == _git(repo, "rev-parse", "HEAD")
    assert made.project == str(repo)
    # The run record reads it as a checkout of its own, of the same repository.
    seen = repo_identity.describe(folder)
    assert seen.isolated is True
    assert seen.repo_id == made.repo_id == repo_identity.repo_id(repo)
    # The project's own checkout is as it was, and does not list the folder as a change.
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert _git(repo, "status", "--porcelain") == ""
    row = store.workdir(made.folder)
    assert row is not None
    assert Path(row["root"]).resolve() == repo.resolve()
    assert (row["branch"], row["base_sha"]) == (made.branch, made.base_sha)
    assert row["removed_ms"] is None


def test_two_threads_of_one_name_get_two_worktrees(repo, store, world):
    dirs = world.dirs(store)
    first, second = dirs.make(str(repo), "Codex"), dirs.make(str(repo), "Codex")
    assert first is not None and second is not None
    assert first.folder != second.folder
    assert first.branch != second.branch


def test_a_worktree_starts_from_the_remote_default_branch_not_a_stale_checkout(
    tmp_path, store, world
):
    upstream = _init(tmp_path / "upstream")
    _git(tmp_path, "clone", "-q", str(upstream), "clone")
    clone = tmp_path / "clone"
    # The remote moves on; the person's checkout was not pulled since.
    (upstream / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    _git(upstream, "commit", "-q", "-am", "second")
    newest = _git(upstream, "rev-parse", "HEAD")
    assert _git(clone, "rev-parse", "HEAD") != newest

    made = world.dirs(store).make(str(clone), "Codex")

    assert made is not None
    assert made.base_sha == newest
    assert (Path(made.folder) / "app.py").read_text(encoding="utf-8") == "VALUE = 2\n"


@pytest.mark.parametrize("label", ["", "!!!", "\u65e5\u672c\u8a9e", "caf\u00e9 notes/v2"])
def test_any_thread_name_makes_a_valid_branch(repo, store, world, label):
    made = world.dirs(store).make(str(repo), label)
    assert made is not None
    assert _git(repo, "check-ref-format", "--branch", made.branch) == made.branch


# -------------------------------------------------- when no worktree is made


def test_a_folder_that_is_no_repository_keeps_the_thread_where_it_is(tmp_path, store, world):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert world.dirs(store).make(str(plain), "Codex") is None
    assert world.dirs(store).make(str(tmp_path / "missing"), "Codex") is None
    assert store.workdirs() == []


def test_a_repository_without_a_commit_keeps_the_thread_where_it_is(tmp_path, store, world):
    empty = tmp_path / "empty"
    empty.mkdir()
    _git(empty, "init", "-q", "-b", "main")
    assert world.dirs(store).make(str(empty), "Codex") is None


def test_a_repository_that_opted_out_keeps_its_shared_folder(repo, store, world):
    repo_id = repo_identity.repo_id(repo)
    dirs = world.dirs(store, shared=[f"  {repo_id.upper()} "])
    assert dirs.make(str(repo), "Codex") is None
    assert not (repo / ".worktrees").exists()


def test_with_the_setting_off_nothing_is_made(repo, store, world):
    assert world.dirs(store, making=False).make(str(repo), "Codex") is None
    assert not (repo / ".worktrees").exists()


def test_a_nearly_full_disk_makes_no_worktree(repo, store, world):
    world.free = MIN_FREE_BYTES - 1
    assert world.dirs(store).make(str(repo), "Codex") is None
    assert not (repo / ".worktrees").exists()


def test_a_project_that_is_a_sub_folder_or_a_worktree_keeps_its_folder(repo, store, world):
    """The thread list places a thread by its folder: outside the project it would vanish."""
    dirs = world.dirs(store)
    assert dirs.make(str(repo / "pkg"), "Codex") is None
    linked = repo.parent / "linked"
    _git(repo, "worktree", "add", "-q", "-b", "side", str(linked))
    assert dirs.make(str(linked), "Codex") is None
    assert store.workdirs() == []


def test_a_git_failure_never_reaches_the_order(repo, store, world, monkeypatch):
    from dodaios.agentic_ide import git_ops

    def broken(*_args, **_kwargs):
        raise git_ops.GitError("git said no", code="failed")

    monkeypatch.setattr(git_ops, "prepare", broken)
    assert world.dirs(store).make(str(repo), "Codex") is None


# ---------------------------------------------------------------- putting away


def _thread(world: World, dirs: WorkDirs, repo: Path, sid: str, label: str = "Codex") -> WorkDir:
    made = dirs.make(str(repo), label)
    assert made is not None
    dirs.bind(made, sid)
    world.threads.add(sid)
    return made


def _commit(folder: str, name: str = "new.py") -> str:
    (Path(folder) / name).write_text("NEW = 1\n", encoding="utf-8")
    _git(Path(folder), "add", name)
    _git(Path(folder), "commit", "-q", "-m", "work")
    return _git(Path(folder), "rev-parse", "HEAD")


def test_the_clean_worktree_of_a_deleted_thread_goes_and_its_commits_stay(repo, store, world):
    dirs = world.dirs(store)
    made = _thread(world, dirs, repo, "s1")
    tip = _commit(made.folder)
    world.threads.discard("s1")

    removed = dirs.sweep(made.repo_id, str(repo))

    assert removed == [made.folder]
    assert not Path(made.folder).exists()
    assert _git(repo, "rev-parse", made.branch) == tip
    assert store.workdirs() == []
    row = store.workdir(made.folder)
    assert row is not None
    assert row["removed_ms"] == world.now
    assert row["head_sha"] == tip


def test_a_deleted_threads_branch_without_a_commit_goes_with_its_worktree(repo, store, world):
    dirs = world.dirs(store)
    made = _thread(world, dirs, repo, "s1")
    world.threads.discard("s1")

    dirs.sweep(made.repo_id, str(repo))

    assert made.branch not in _git(repo, "branch", "--list", "--format=%(refname:short)")


def test_uncommitted_or_untracked_work_is_never_removed(repo, store, world):
    dirs = world.dirs(store)
    edited = _thread(world, dirs, repo, "s1")
    (Path(edited.folder) / "app.py").write_text("VALUE = 3\n", encoding="utf-8")
    added = _thread(world, dirs, repo, "s2")
    (Path(added.folder) / "notes.txt").write_text("keep me\n", encoding="utf-8")
    world.threads.clear()
    world.idle = {"s1": 10 * REST_AFTER_MS, "s2": 10 * REST_AFTER_MS}

    assert dirs.sweep(edited.repo_id, str(repo)) == []

    assert (Path(edited.folder) / "app.py").read_text(encoding="utf-8") == "VALUE = 3\n"
    assert (Path(added.folder) / "notes.txt").is_file()
    assert len(store.workdirs()) == 2


def test_the_worktree_of_a_thread_in_use_stays(repo, store, world):
    dirs = world.dirs(store)
    made = _thread(world, dirs, repo, "s1")
    world.idle["s1"] = 0  # a turn runs
    assert dirs.sweep(made.repo_id, str(repo)) == []
    world.idle["s1"] = REST_AFTER_MS - 1
    assert dirs.sweep(made.repo_id, str(repo)) == []
    assert Path(made.folder).is_dir()


def test_a_resting_threads_clean_worktree_is_put_away_and_its_branch_kept(repo, store, world):
    dirs = world.dirs(store)
    made = _thread(world, dirs, repo, "s1")
    world.idle["s1"] = REST_AFTER_MS

    assert dirs.sweep(made.repo_id, str(repo)) == [made.folder]

    assert not Path(made.folder).exists()
    # No commit on it, yet the thread lives: the branch is what it returns to.
    assert _git(repo, "rev-parse", "--verify", made.branch) == made.base_sha
    assert store.workdirs_away() == 1


def test_a_tight_disk_puts_resting_worktrees_away_sooner(repo, store, world):
    dirs = world.dirs(store)
    made = _thread(world, dirs, repo, "s1")
    world.idle["s1"] = REST_AFTER_TIGHT_MS
    assert dirs.sweep(made.repo_id, str(repo)) == []
    world.free = 2 * MIN_FREE_BYTES - 1
    assert dirs.sweep(made.repo_id, str(repo)) == [made.folder]


def test_a_worktree_whose_thread_never_came_goes_after_an_hour(repo, store, world):
    dirs = world.dirs(store)
    made = dirs.make(str(repo), "Codex")
    assert made is not None
    world.now += HOUR - 1
    assert dirs.sweep(made.repo_id, str(repo)) == []
    world.now += 1
    assert dirs.sweep(made.repo_id, str(repo)) == [made.folder]


def test_a_folder_deleted_by_hand_is_only_noted(repo, store, world):
    import shutil

    dirs = world.dirs(store)
    made = _thread(world, dirs, repo, "s1")
    shutil.rmtree(made.folder)
    world.threads.discard("s1")
    assert dirs.sweep(made.repo_id, str(repo)) == []
    assert store.workdirs() == []


def test_making_the_next_worktree_puts_the_old_ones_away(repo, store, world):
    dirs = world.dirs(store)
    old = _thread(world, dirs, repo, "s1")
    world.threads.discard("s1")
    new = dirs.make(str(repo), "Codex")
    assert new is not None
    assert not Path(old.folder).exists()
    assert Path(new.folder).is_dir()


def test_worktrees_of_another_repository_are_left_alone(tmp_path, repo, store, world):
    other = _init(tmp_path / "other")
    _git(other, "remote", "add", "origin", "https://github.com/acme/other.git")
    dirs = world.dirs(store)
    theirs = _thread(world, dirs, other, "s1")
    world.threads.discard("s1")
    assert dirs.sweep(repo_identity.repo_id(repo), str(repo)) == []
    assert Path(theirs.folder).is_dir()


# ------------------------------------------------------------------ restoring


def test_a_thread_finds_its_worktree_again_where_and_as_it_was(repo, store, world):
    dirs = world.dirs(store)
    made = _thread(world, dirs, repo, "s1")
    tip = _commit(made.folder)
    world.idle["s1"] = REST_AFTER_MS
    dirs.sweep(made.repo_id, str(repo))
    assert not Path(made.folder).exists()

    assert dirs.restore(made.folder) is True

    folder = Path(made.folder)
    assert _git(folder, "rev-parse", "HEAD") == tip
    assert _git(folder, "rev-parse", "--abbrev-ref", "HEAD") == made.branch
    assert (folder / "new.py").is_file()
    assert [row["folder"] for row in store.workdirs()] == [made.folder]
    assert store.workdirs_away() == 0


def test_a_branch_the_agent_renamed_is_the_one_restored(repo, store, world):
    dirs = world.dirs(store)
    made = _thread(world, dirs, repo, "s1")
    _git(Path(made.folder), "branch", "-m", "feat/sum")
    tip = _commit(made.folder)
    world.idle["s1"] = REST_AFTER_MS
    dirs.sweep(made.repo_id, str(repo))

    assert dirs.restore(made.folder) is True

    assert _git(Path(made.folder), "rev-parse", "--abbrev-ref", "HEAD") == "feat/sum"
    assert _git(Path(made.folder), "rev-parse", "HEAD") == tip


def test_a_branch_that_is_gone_or_taken_still_gives_the_thread_its_commit(repo, store, world):
    dirs = world.dirs(store)
    gone = _thread(world, dirs, repo, "s1", "Gone")
    gone_tip = _commit(gone.folder)
    taken = _thread(world, dirs, repo, "s2", "Taken")
    taken_tip = _commit(taken.folder, "other.py")
    world.idle = {"s1": REST_AFTER_MS, "s2": REST_AFTER_MS}
    dirs.sweep(gone.repo_id, str(repo))
    _git(repo, "tag", "keep", gone_tip)
    _git(repo, "branch", "-D", gone.branch)
    elsewhere = repo.parent / "elsewhere"
    _git(repo, "worktree", "add", "-q", str(elsewhere), taken.branch)

    assert dirs.restore(gone.folder) is True
    assert dirs.restore(taken.folder) is True

    assert _git(Path(gone.folder), "rev-parse", "HEAD") == gone_tip
    assert _git(Path(gone.folder), "rev-parse", "--abbrev-ref", "HEAD") == gone.branch
    # Checked out elsewhere: the thread gets the commit without the branch.
    assert _git(Path(taken.folder), "rev-parse", "HEAD") == taken_tip
    assert _git(Path(taken.folder), "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"


def test_only_a_missing_folder_this_module_made_is_restored(repo, store, world, tmp_path):
    dirs = world.dirs(store)
    made = _thread(world, dirs, repo, "s1")
    assert dirs.restore(made.folder) is False  # it is there
    assert dirs.restore(str(tmp_path / "never-made")) is False
    assert not (tmp_path / "never-made").exists()


def test_restoring_works_with_the_setting_switched_off(repo, store, world):
    dirs = world.dirs(store)
    made = _thread(world, dirs, repo, "s1")
    world.idle["s1"] = REST_AFTER_MS
    dirs.sweep(made.repo_id, str(repo))

    later = world.dirs(store, making=False)

    assert later.restore(made.folder) is True
    assert Path(made.folder, "app.py").is_file()


def test_a_repository_that_moved_away_fails_quietly(repo, store, world):
    dirs = world.dirs(store)
    made = _thread(world, dirs, repo, "s1")
    world.idle["s1"] = REST_AFTER_MS
    dirs.sweep(made.repo_id, str(repo))
    repo.rename(repo.parent / "moved")
    assert dirs.restore(made.folder) is False
    assert not Path(made.folder).exists()


# ------------------------------------------------------------------ the brief


def _made(project: str, folder: str) -> WorkDir:
    return WorkDir(folder=folder, branch="agent/codex-1a2b3c", base_sha="abc", repo_id="r",
                   project=project)


def test_paths_into_the_project_become_paths_in_the_worktree():
    made = _made("/code/My Notes", "/code/My Notes/.worktrees/agent-codex-1a2b3c")
    told = workdir.localize(
        "Fix `/code/My Notes/app/calc.py` and run the tests in /code/My Notes. "
        "Compare with /code/My Notes-old/app/calc.py, leave /code/My Notes/.git/config and "
        "/code/My Notes/.worktrees/other/app.py alone. Config: /code/My Notes/.github/ci.yml",
        made,
    )
    brief = told.split("\n\nYou work in")[0]
    assert "`/code/My Notes/.worktrees/agent-codex-1a2b3c/app/calc.py`" in brief
    assert "tests in /code/My Notes/.worktrees/agent-codex-1a2b3c. Compare" in brief
    assert "/code/My Notes/.worktrees/agent-codex-1a2b3c/.github/ci.yml" in brief
    # Another folder, git's own files and another checkout keep their paths.
    assert "/code/My Notes-old/app/calc.py" in brief
    assert "leave /code/My Notes/.git/config" in brief
    assert "and /code/My Notes/.worktrees/other/app.py alone" in brief


def test_the_agent_is_told_where_it_is_and_whose_the_main_checkout_is():
    made = _made("/code/notes", "/code/notes/.worktrees/agent-codex-1a2b3c")
    told = workdir.localize("Add a sum function.", made)
    assert told.startswith("Add a sum function.\n\n")
    folder = "/code/notes/.worktrees/agent-codex-1a2b3c"
    assert f"on the new branch `agent/codex-1a2b3c`: {folder}" in told
    assert "the main checkout /code/notes at the same time" in told


def test_windows_paths_are_rewritten_too():
    made = _made("C:\\code\\notes", "C:\\code\\notes\\.worktrees\\agent-codex-1a2b3c")
    told = workdir.localize("Open C:\\code\\notes\\app.py", made)
    assert "Open C:\\code\\notes\\.worktrees\\agent-codex-1a2b3c\\app.py" in told


# ------------------------------------------------------------- process wiring


def test_without_an_instance_every_entry_point_is_a_no_op(repo):
    workdir.set_dirs(None)
    assert workdir.dirs() is None
    assert workdir.for_new_thread(str(repo), "Codex") is None
    workdir.bind(None, "s1")
    assert workdir.away(str(repo / "missing")) is False
    assert workdir.restore(str(repo / "missing")) is False


def test_the_entry_points_reach_the_instance(repo, store, world):
    dirs = world.dirs(store)
    workdir.set_dirs(dirs)
    try:
        made = workdir.for_new_thread(str(repo), "Codex")
        assert made is not None
        workdir.bind(made, "s1")
        world.threads.add("s1")
        assert store.workdir(made.folder)["session_id"] == "s1"
        assert workdir.away(made.folder) is False
        world.idle["s1"] = REST_AFTER_MS
        dirs.sweep(made.repo_id, str(repo))
        assert workdir.away(made.folder) is True
        assert workdir.restore(made.folder) is True
        assert workdir.away(made.folder) is False
    finally:
        workdir.set_dirs(None)
