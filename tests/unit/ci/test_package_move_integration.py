"""A branch that predates the package move is carried across it by replaying
the rename script, and CI lanes read both names of the package directory.

The old package name appears all over this file on purpose; the codemod never
rewrites it (``FROZEN_FILES``).
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.ci import agent_integrate, classify_changes
from scripts.rename import rewrite_package as codemod

_REPO_ROOT = Path(__file__).resolve().parents[3]
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_BASE = {
    "jarvis/__init__.py": '__version__ = "1.0.0"\n',
    "jarvis/core/__init__.py": "",
    "jarvis/core/alpha.py": "from jarvis.core import beta\n\nVALUE = 1\n",
    "jarvis/core/beta.py": "NAME = 'beta'\n",
    "jarvis/core/gamma.py": "from jarvis.core.beta import NAME\n",
    "tests/test_alpha.py": "from jarvis.core.alpha import VALUE\n",
    "docs/guide.md": "Read `jarvis/core/alpha.py`.\n",
    "CHANGELOG.md": "# Changelog\n\n- base\n",
    "app.py": "VALUE = 1\n",
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        creationflags=_NO_WINDOW,
    ).stdout


def _write(repo: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")


def _commit(repo: Path, message: str, files: dict[str, str] | None = None) -> str:
    _write(repo, files or {})
    _git(repo, "add", "-A", ".")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path):
    """main with the old layout and the rename script, and a ``feature``
    branch cut from it. HEAD is main."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "core.autocrlf", "false")
    script = root / agent_integrate.RENAME_SCRIPT
    script.parent.mkdir(parents=True)
    shutil.copyfile(_REPO_ROOT / agent_integrate.RENAME_SCRIPT, script)
    _commit(root, "base", _BASE)
    _git(root, "branch", "feature")
    return root


def _move_on_main(repo: Path) -> str:
    """The move commit: exactly the rename script's output."""
    _git(repo, "checkout", "-q", "main")
    report = codemod.apply(repo, agent_integrate.OLD_PACKAGE, agent_integrate.NEW_PACKAGE)
    assert report.moves and not report.blocked
    _git(repo, "commit", "-q", "-m", "refactor: move the package")
    return _git(repo, "rev-parse", "HEAD").strip()


def _feature_work(repo: Path) -> None:
    _git(repo, "checkout", "-q", "feature")
    _commit(
        repo,
        "feature work",
        {
            # An import line the move rewrites too: a plain merge would conflict here.
            "jarvis/core/alpha.py": "from jarvis.core import beta, gamma\n\nVALUE = 2\n",
            "jarvis/core/delta.py": "from jarvis.core.alpha import VALUE\n",
            "docs/guide.md": "Read `jarvis/core/alpha.py` and `jarvis/core/delta.py`.\n",
        },
    )
    (repo / "jarvis/core/gamma.py").unlink()
    _commit(repo, "feature: drop gamma")


def _show(repo: Path, name: str) -> str:
    return _git(repo, "show", f"HEAD:{name}")


def _tree(repo: Path, rev: str = "HEAD") -> set[str]:
    return set(_git(repo, "ls-tree", "-r", "--name-only", rev).split())


# --------------------------------------------------------------------------- no move yet


def test_nothing_happens_while_main_still_has_the_old_layout(repo):
    _commit(repo, "main work", {"app.py": "VALUE = 2\n"})
    _feature_work(repo)

    assert agent_integrate.package_move("main", repo) is None
    assert agent_integrate.carried_package_move("main", repo) is None
    report = agent_integrate.update("main", "rebase", "", repo)

    assert report["status"] == "updated" and "package_move" not in report
    assert "jarvis/core/delta.py" in _tree(repo) and not (repo / "dodaios").exists()
    # A plain rebase: no merge commit was made.
    assert _git(repo, "rev-list", "--merges", "main..HEAD").strip() == ""


def test_a_branch_that_already_moved_is_updated_the_ordinary_way(repo):
    move = _move_on_main(repo)
    _git(repo, "checkout", "-q", "-b", "later")
    _commit(repo, "later work", {"dodaios/core/beta.py": "NAME = 'later'\n"})
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "main work", {"app.py": "VALUE = 2\n"})
    _git(repo, "checkout", "-q", "later")

    assert agent_integrate.package_move("main", repo) is None
    assert agent_integrate.carried_package_move("main", repo) is None
    report = agent_integrate.update("main", "rebase", "", repo)
    assert report["status"] == "updated" and "package_move" not in report
    assert _git(repo, "merge-base", "--is-ancestor", move, "HEAD") == ""
    # Still a plain rebase: a branch born in the new layout carries no merge.
    assert _git(repo, "rev-list", "--merges", "main..HEAD").strip() == ""


def test_a_move_made_by_hand_is_not_replayed(repo):
    _git(repo, "rm", "-q", agent_integrate.RENAME_SCRIPT)
    _git(repo, "mv", "jarvis", "dodaios")
    _git(repo, "commit", "-q", "-m", "move by hand")
    _git(repo, "checkout", "-q", "feature")

    assert agent_integrate.package_move("main", repo) is None


# --------------------------------------------------------------------------- the replay


@pytest.mark.parametrize("mode", ["merge", "rebase"])
def test_a_branch_from_before_the_move_is_carried_across_without_conflicts(repo, mode):
    _commit(repo, "main work before the move", {"app.py": "VALUE = 2\n"})
    move = _move_on_main(repo)
    after = _commit(repo, "main work after the move", {"dodaios/core/beta.py": "NAME = 'new'\n"})
    _feature_work(repo)

    assert agent_integrate.package_move("main", repo) == (
        _git(repo, "rev-parse", f"{move}^").strip(),
        move,
    )
    report = agent_integrate.update("main", mode, "", repo)

    assert report["status"] == "updated", report
    assert report["package_move"] == move
    assert _git(repo, "status", "--porcelain").strip() == ""
    assert _git(repo, "merge-base", "--is-ancestor", after, "HEAD") == ""
    tree = _tree(repo)
    # The branch's own changes arrived in the new layout, rewritten ...
    assert _show(repo, "dodaios/core/alpha.py") == (
        "from dodaios.core import beta, gamma\n\nVALUE = 2\n"
    )
    assert _show(repo, "dodaios/core/delta.py") == "from dodaios.core.alpha import VALUE\n"
    assert _show(repo, "docs/guide.md") == (
        "Read `dodaios/core/alpha.py` and `dodaios/core/delta.py`.\n"
    )
    assert "dodaios/core/gamma.py" not in tree  # ... and so did its deletion.
    # Everything it did not touch is main's.
    assert _show(repo, "dodaios/core/beta.py") == "NAME = 'new'\n"
    assert _show(repo, "tests/test_alpha.py") == "from dodaios.core.alpha import VALUE\n"
    assert _show(repo, "app.py") == "VALUE = 2\n"
    # Nothing of the package is left under the old name but the compatibility file.
    assert {name for name in tree if name.startswith("jarvis/")} == {"jarvis/__init__.py"}
    assert _show(repo, "jarvis/__init__.py") == _git(repo, "show", "main:jarvis/__init__.py")
    check = ["--from", "jarvis", "--to", "dodaios", "--root", str(repo), "--check"]
    assert codemod.main(check) == 0


def test_the_script_of_the_move_commit_is_the_one_that_replays(repo):
    """A branch never needs the script itself, and a later edit to it on main
    cannot change what an old branch is carried across with."""
    move = _move_on_main(repo)
    _commit(repo, "main: retire the script", {agent_integrate.RENAME_SCRIPT: "raise SystemExit\n"})
    _git(repo, "checkout", "-q", "feature")
    _commit(repo, "feature work", {"jarvis/core/alpha.py": "from jarvis.core import gamma\n"})

    report = agent_integrate.update("main", "merge", "", repo)

    assert report["status"] == "updated" and report["package_move"] == move, report
    assert _show(repo, "dodaios/core/alpha.py") == "from dodaios.core import gamma\n"
    assert _show(repo, agent_integrate.RENAME_SCRIPT) == "raise SystemExit\n"


def test_a_conflict_after_the_move_keeps_the_replay_and_says_how_to_go_on(repo):
    move = _move_on_main(repo)
    _commit(repo, "main work after the move", {"app.py": "VALUE = 2\n"})
    _git(repo, "checkout", "-q", "feature")
    _commit(
        repo,
        "feature work",
        {"app.py": "VALUE = 3\n", "jarvis/core/alpha.py": "from jarvis.core import gamma\n"},
    )

    report = agent_integrate.update("main", "rebase", "", repo)

    assert report["status"] == "conflict" and report["unresolved"] == ["app.py"]
    # The branch is across the move and whole; what is left is an ordinary
    # conflict between two trees of the new layout.
    assert report["package_move"] == move
    assert _git(repo, "status", "--porcelain").strip() == ""
    assert _show(repo, "dodaios/core/alpha.py") == "from dodaios.core import gamma\n"
    assert _show(repo, "app.py") == "VALUE = 3\n"


def test_a_carried_branch_is_updated_by_merge_from_then_on(repo):
    """A rebase would drop the merge that carries the move and replay the
    branch's old-layout commits onto the new layout, file by file."""
    move = _move_on_main(repo)
    _feature_work(repo)
    assert agent_integrate.update("main", "rebase", "", repo)["status"] == "updated"
    _git(repo, "checkout", "-q", "main")
    later = _commit(repo, "main work after the carry", {"app.py": "VALUE = 9\n"})
    _git(repo, "checkout", "-q", "feature")
    _commit(repo, "feature work in the new layout", {"dodaios/core/beta.py": "NAME = 'own'\n"})

    assert agent_integrate.package_move("main", repo) is None
    assert agent_integrate.carried_package_move("main", repo) == move
    report = agent_integrate.update("main", "rebase", "", repo)

    assert report["status"] == "updated" and report["package_move"] == move, report
    assert _git(repo, "status", "--porcelain").strip() == ""
    assert _git(repo, "merge-base", "--is-ancestor", later, "HEAD") == ""
    assert _show(repo, "dodaios/core/alpha.py") == (
        "from dodaios.core import beta, gamma\n\nVALUE = 2\n"
    )
    assert _show(repo, "dodaios/core/beta.py") == "NAME = 'own'\n"
    assert _show(repo, "app.py") == "VALUE = 9\n"
    assert {name for name in _tree(repo) if name.startswith("jarvis/")} == {"jarvis/__init__.py"}
    check = ["--from", "jarvis", "--to", "dodaios", "--root", str(repo), "--check"]
    assert codemod.main(check) == 0


def test_a_conflict_on_a_carried_branch_is_a_merge_to_continue(repo):
    move = _move_on_main(repo)
    _feature_work(repo)
    assert agent_integrate.update("main", "rebase", "", repo)["status"] == "updated"
    head = _commit(repo, "feature work", {"app.py": "VALUE = 3\n"})
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "main work after the carry", {"app.py": "VALUE = 9\n"})
    _git(repo, "checkout", "-q", "feature")

    report = agent_integrate.update("main", "rebase", "", repo)

    assert report["status"] == "conflict" and report["unresolved"] == ["app.py"]
    assert report["package_move"] == move
    assert _git(repo, "rev-parse", "HEAD").strip() == head
    assert _git(repo, "status", "--porcelain").strip() == ""


def test_a_conflict_from_before_the_move_is_reported_against_that_commit(repo):
    before = _commit(repo, "main work before the move", {"app.py": "VALUE = 2\n"})
    _move_on_main(repo)
    _git(repo, "checkout", "-q", "feature")
    head = _commit(repo, "feature work", {"app.py": "VALUE = 3\n"})

    report = agent_integrate.update("main", "rebase", "", repo)

    assert report["status"] == "conflict"
    assert report["unresolved"] == ["app.py"]
    assert report["onto"] == before
    # Nothing half-done: the branch is where it was, in the old layout.
    assert _git(repo, "rev-parse", "HEAD").strip() == head
    assert not (repo / "dodaios").exists()


# --------------------------------------------------------------------------- the merge train


class _FakeGh:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str) -> int:
        self.calls.append(args)
        return 0


def _machines(tmp_path: Path, repo: Path) -> tuple[Path, Path, Path, dict]:
    origin = tmp_path / "origin.git"
    _git(tmp_path, "clone", "-q", "--bare", str(repo), str(origin))
    clones = []
    for name in ("integrate", "apply"):
        clone = tmp_path / name
        _git(tmp_path, "clone", "-q", str(origin), str(clone))
        _git(clone, "config", "user.email", "t@example.invalid")
        _git(clone, "config", "user.name", "t")
        _git(clone, "config", "core.autocrlf", "false")
        clones.append(clone)
    plan = {
        "repo": "example/project",
        "main": _git(origin, "rev-parse", "main").strip(),
        "queue": True,
        "entries": [
            {
                "number": 3,
                "branch": "feature",
                "head": _git(origin, "rev-parse", "feature").strip(),
                "id": "PR_node",
                "action": "update",
                "run_id": None,
                "note": "",
            }
        ],
    }
    return origin, clones[0], clones[1], plan


def _tick(tmp_path: Path, name: str, origin: Path, integrate: Path, applier: Path, plan: dict):
    work = tmp_path / name
    for clone in (integrate, applier):
        _git(clone, "fetch", "-q", "origin")
    plan = json.loads(json.dumps(plan))
    plan["entries"][0]["head"] = _git(origin, "rev-parse", "feature").strip()
    assert agent_integrate.integrate_merge(work, plan, integrate) == 0
    agent_integrate.integrate_finish(work, plan)
    agent_integrate.cleanup_worktrees(work, integrate)
    state = json.loads((work / "state" / "pr-3.json").read_text(encoding="utf-8"))
    outcome = agent_integrate.apply_update(work, plan, plan["entries"][0], False, applier)
    return state, outcome


def test_the_train_carries_a_pull_request_across_the_move_in_two_ticks(tmp_path, repo, monkeypatch):
    before = _commit(repo, "main work before the move", {"app.py": "VALUE = 2\n"})
    move = _move_on_main(repo)
    _feature_work(repo)
    origin, integrate, applier, plan = _machines(tmp_path, repo)
    monkeypatch.setattr(agent_integrate, "gh", _FakeGh())

    # Tick 1: up to the last commit of the old layout, an ordinary merge.
    state, outcome = _tick(tmp_path, "tick-1", origin, integrate, applier, plan)
    assert state["status"] == "ready" and state["onto"] == before, state
    assert outcome.startswith("updated with main"), outcome
    assert "jarvis/core/delta.py" in _tree(origin, "feature")
    assert _git(origin, "show", "feature:app.py") == "VALUE = 2\n"

    # Tick 2: the move is replayed on top of that.
    state, outcome = _tick(tmp_path, "tick-2", origin, integrate, applier, plan)
    assert state["status"] == "ready" and "onto" not in state, state
    assert outcome.startswith("updated with main"), outcome
    tree = _tree(origin, "feature")
    assert "dodaios/core/delta.py" in tree and "jarvis/core/delta.py" not in tree
    assert _git(origin, "show", "feature:dodaios/core/alpha.py").startswith(
        "from dodaios.core import beta, gamma"
    )
    assert _git(origin, "merge-base", "--is-ancestor", move, "feature") == ""


def test_apply_rejects_a_stopping_point_that_is_not_in_mains_history(tmp_path, repo, monkeypatch):
    _commit(repo, "main work", {"app.py": "VALUE = 2\n"})
    _feature_work(repo)
    origin, integrate, applier, plan = _machines(tmp_path, repo)
    monkeypatch.setattr(agent_integrate, "gh", _FakeGh())
    work = tmp_path / "train"
    assert agent_integrate.integrate_merge(work, plan, integrate) == 0
    agent_integrate.integrate_finish(work, plan)
    agent_integrate.cleanup_worktrees(work, integrate)
    state_file = work / "state" / "pr-3.json"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    # A bundle that claims to stop at the pull request's own head.
    state["onto"] = plan["entries"][0]["head"]
    state_file.write_text(json.dumps(state), encoding="utf-8")

    outcome = agent_integrate.apply_update(work, plan, plan["entries"][0], False, applier)

    assert outcome.startswith("update bundle rejected"), outcome
    assert _git(origin, "rev-parse", "feature").strip() == plan["entries"][0]["head"]


# --------------------------------------------------------------------------- CI lanes

_LANE_PATHS = [
    "jarvis/ui/web/frontend/src/lib/tasksApi.ts",
    "jarvis/ui/web/update_routes.py",
    "jarvis/realtime/factory.py",
    "jarvis/cli_ctl/commands/system.py",
    "jarvis/overlay/drop_target.py",
    "jarvis/society/browser/runner.py",
    "jarvis/core/branding.py",
    "jarvis/setup/prefetch.py",
    "jarvis/__main__.py",
    "jarvis/agent_runtimes/hermes.py",
    "jarvis/assets/browser/requirements.lock",
    "jarvis/society/roster.py",
    "jarvis/ui/desktop_app.py",
    "jarvis/brain/router.py",
]


@pytest.mark.parametrize("path", _LANE_PATHS)
def test_both_names_of_the_package_directory_turn_on_the_same_lanes(path):
    old = classify_changes.classify([path])
    new = classify_changes.classify([path.replace("jarvis/", "dodaios/", 1)])
    assert old == new
    assert old["python"] is True and old["full"] is False


def test_every_lane_a_package_change_can_reach_is_reached_under_both_names():
    reached_old: set[str] = set()
    reached_new: set[str] = set()
    for path in _LANE_PATHS:
        for seen, spelled in ((reached_old, path), (reached_new, "dodaios" + path[6:])):
            seen.update(lane for lane, on in classify_changes.classify([spelled]).items() if on)
    assert reached_old == reached_new
    assert reached_old >= set(classify_changes.LANES) - {"full"}


def test_a_file_that_is_not_in_the_package_is_not_mistaken_for_it():
    assert classify_changes.classify(["jarvis.spec"])["macos_desktop"] is True
    assert classify_changes.classify(["docs/jarvis/notes.md"])["frontend"] is False
    assert classify_changes.classify(["dodaios.md"]) == classify_changes.classify(["notes.md"])


def _after_the_move(relative: str, tmp_path: Path):
    """A script of this repository as the move commit will leave it, loaded."""
    rewriter = codemod.Rewriter.from_tree(_REPO_ROOT, "jarvis", "dodaios")
    source = rewriter.transform(relative, (_REPO_ROOT / relative).read_bytes())
    path = tmp_path / ("moved_" + Path(relative).name)
    path.write_bytes(source)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_classifier_still_reads_both_names_once_it_has_been_moved_itself(tmp_path):
    moved = _after_the_move("scripts/ci/classify_changes.py", tmp_path)
    # The lane table it borrows moves in the same commit.
    moved.agent_runtime_suite = _after_the_move("scripts/ci/agent_runtime_suite.py", tmp_path)
    for path in _LANE_PATHS:
        new = moved.classify([path.replace("jarvis/", "dodaios/", 1)])
        assert new == classify_changes.classify([path]), path
        assert new == moved.classify([path]), path


def test_the_integration_script_keeps_its_two_package_names_through_the_move(tmp_path):
    relative = "scripts/ci/agent_integrate.py"
    rewriter = codemod.Rewriter.from_tree(_REPO_ROOT, "jarvis", "dodaios")
    source = rewriter.transform(relative, (_REPO_ROOT / relative).read_bytes()).decode("utf-8")
    assert 'OLD_PACKAGE = "jarvis"' in source and 'NEW_PACKAGE = "dodaios"' in source
    assert "ui/web/frontend" in source and '"jarvis/ui/web/frontend"' not in source
