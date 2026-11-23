"""The output gate: which checkout is a run's own, and what the scan finds in it."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from dodaios.orchestrator.verification import gates, scope
from dodaios.orchestrator.verification.cheat_scan import AMBIGUOUS, VIOLATION

TEST = "def test_sum():\n    assert add(1, 2) == 3\n"
CODE = "def add(a, b):\n    return a + b\n"


def _git(folder: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=folder, capture_output=True, text=True, check=True, encoding="utf-8"
    )
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with one source file and one test, committed on ``main``."""
    folder = tmp_path / "main"
    folder.mkdir()
    _git(folder, "init", "-q", "-b", "main")
    _git(folder, "config", "user.email", "t@example.com")
    _git(folder, "config", "user.name", "T")
    (folder / "app").mkdir()
    (folder / "tests").mkdir()
    (folder / "app" / "calc.py").write_text(CODE, encoding="utf-8")
    (folder / "tests" / "test_calc.py").write_text(TEST, encoding="utf-8")
    _git(folder, "add", "-A")
    _git(folder, "commit", "-q", "-m", "first")
    return folder


@pytest.fixture
def worktree(repo: Path, tmp_path: Path) -> Path:
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", "-b", "work", str(linked))
    return linked


def _run(folder: Path, *, isolated: bool, started_ms: int = 0) -> dict[str, Any]:
    return {
        "run_id": "job_1",
        "workdir": str(folder),
        "isolated": int(isolated),
        "base_sha": _git(folder, "rev-parse", "HEAD"),
        "started_ms": started_ms,
    }


def _write(call: str, path: Path, ts_ms: int = 10) -> list[dict[str, Any]]:
    """The two thread events of one successful file-tool call."""
    return [
        {"kind": "tool_call", "ts_ms": ts_ms,
         "payload": {"call_id": call, "name": "Write", "input": {"file_path": str(path)}}},
        {"kind": "tool_result", "ts_ms": ts_ms + 1, "payload": {"call_id": call}},
    ]


# ----------------------------------------------------------------- work area


def test_a_thread_in_a_linked_worktree_owns_that_folder(worktree: Path):
    run = _run(worktree, isolated=True)
    area = gates.work_area(run)
    assert area is not None
    assert (Path(area.folder).resolve(), area.base, area.how) == (
        worktree.resolve(), run["base_sha"], "thread_worktree",
    )


def test_a_run_in_the_shared_checkout_has_no_work_area(repo: Path):
    events = _write("c1", repo / "app" / "calc.py")
    assert gates.work_area(_run(repo, isolated=False), events) is None
    assert gates.work_area(_run(repo, isolated=False), []) is None


def test_a_worktree_the_session_made_itself_is_its_work_area(repo: Path, worktree: Path):
    run = _run(repo, isolated=False)
    (worktree / "app" / "calc.py").write_text(CODE + "\n# more\n", encoding="utf-8")
    _git(worktree, "commit", "-qam", "work")
    area = gates.work_area(run, _write("c1", worktree / "app" / "calc.py"))
    assert area is not None
    assert area.how == "session_worktree"
    assert Path(area.folder).resolve() == worktree.resolve()
    # The start is where the worktree's branch left the line it came from.
    assert area.base == run["base_sha"]


def test_a_thread_in_its_own_worktree_that_moved_into_another_is_followed(
    repo: Path, worktree: Path, tmp_path: Path
):
    """Told to work in worktrees, an agent may make one more: its work is there."""
    nested = tmp_path / "nested"
    _git(worktree, "worktree", "add", "-q", "-b", "deeper", str(nested))
    run = _run(worktree, isolated=True)
    (nested / "app" / "calc.py").write_text(CODE + "\n# more\n", encoding="utf-8")
    area = gates.work_area(run, _write("c1", nested / "app" / "calc.py"))
    assert area is not None
    assert (Path(area.folder).resolve(), area.how) == (nested.resolve(), "session_worktree")
    assert area.base == run["base_sha"]


def test_a_thread_in_its_own_worktree_keeps_it_whatever_else_it_touched(
    repo: Path, worktree: Path, tmp_path: Path
):
    nested = tmp_path / "nested"
    _git(worktree, "worktree", "add", "-q", "-b", "deeper", str(nested))
    run = _run(worktree, isolated=True)
    here = _write("c1", worktree / "app" / "calc.py")
    there = _write("c2", nested / "app" / "calc.py", ts_ms=20)
    shared = _write("c3", repo / "app" / "calc.py", ts_ms=30)
    for events in ([*here, *there], shared, [*there, *shared]):
        area = gates.work_area(run, events)
        assert area is not None
        assert (Path(area.folder).resolve(), area.how) == (worktree.resolve(), "thread_worktree")


def test_writes_in_two_checkouts_cannot_be_pinned_on_the_run(repo: Path, worktree: Path):
    events = [
        *_write("c1", worktree / "app" / "calc.py"),
        *_write("c2", repo / "app" / "calc.py", ts_ms=20),
    ]
    assert gates.work_area(_run(repo, isolated=False), events) is None


def test_writes_before_the_run_started_are_not_its_work(repo: Path, worktree: Path):
    events = _write("c1", worktree / "app" / "calc.py", ts_ms=10)
    run = _run(repo, isolated=False, started_ms=5_000)
    assert gates.work_area(run, events) is None


def test_a_folder_that_is_no_repository_has_no_work_area(tmp_path: Path):
    run = {"workdir": str(tmp_path), "isolated": 0, "base_sha": "", "started_ms": 0}
    assert gates.work_area(run) is None


# ---------------------------------------------------------------------- gate


def test_an_honest_change_is_clean_and_counted(worktree: Path):
    run = _run(worktree, isolated=True)
    (worktree / "app" / "calc.py").write_text(CODE + "\n\ndef sub(a, b):\n    return a - b\n")
    (worktree / "tests" / "test_sub.py").write_text("def test_sub():\n    assert sub(3, 1) == 2\n")
    result = gates.check_run(run)
    assert result.status == gates.CLEAN
    assert sorted(result.files) == ["app/calc.py", "tests/test_sub.py"]
    assert (result.added, result.deleted) == (6, 0)
    assert result.tree_id
    assert result.to_detail()["work_area"] == "thread_worktree"


def test_the_scan_sees_committed_uncommitted_and_untracked_work(worktree: Path):
    run = _run(worktree, isolated=True)
    (worktree / "tests" / "test_calc.py").write_text("@pytest.mark.skip\n" + TEST)
    _git(worktree, "commit", "-qam", "skip it")  # committed
    (worktree / "app" / "calc.py").write_text(CODE + "x = f()  # noqa\n")  # not committed
    (worktree / "AGENTS.md").write_text("be nice\n")  # never added
    result = gates.check_run(run)
    assert result.status == gates.VIOLATIONS
    assert sorted((f.rule, f.path) for f in result.findings) == [
        ("C2", "tests/test_calc.py"), ("C3", "app/calc.py"), ("C5", "AGENTS.md"),
    ]


def test_a_test_file_removed_from_the_shell_is_found(worktree: Path):
    """No tool record names this deletion; the tree difference does."""
    run = _run(worktree, isolated=True)
    (worktree / "tests" / "test_calc.py").unlink()
    result = gates.check_run(run)
    assert result.status == gates.VIOLATIONS
    assert [(f.rule, f.path) for f in result.findings] == [("C1", "tests/test_calc.py")]


def test_only_points_to_look_at_is_findings_not_violations(worktree: Path):
    run = _run(worktree, isolated=True)
    (worktree / "app" / "calc.py").write_text(
        CODE + "y = g()  # noqa: BLE001 - the import is optional\n"
    )
    result = gates.check_run(run)
    assert result.status == gates.FINDINGS
    assert result.to_detail()["ambiguous"] == 1


def test_the_gate_leaves_the_index_and_the_files_as_they_were(worktree: Path):
    run = _run(worktree, isolated=True)
    (worktree / "app" / "new.py").write_text("x = 1\n")
    before = _git(worktree, "status", "--porcelain")
    gates.check_run(run)
    assert _git(worktree, "status", "--porcelain") == before
    assert _git(worktree, "diff", "--cached", "--name-only") == ""


def test_a_run_without_a_work_area_is_unattributed(repo: Path):
    (repo / "tests" / "test_calc.py").unlink()
    result = gates.check_run(_run(repo, isolated=False))
    assert result.status == gates.UNATTRIBUTED
    assert result.findings == []
    assert "checkout of its own" in result.reason


def test_lockfiles_are_listed_but_not_counted_as_churn(worktree: Path):
    run = _run(worktree, isolated=True)
    (worktree / "uv.lock").write_text("a\n" * 500)
    (worktree / "app" / "calc.py").write_text(CODE + "z = 1\n")
    result = gates.check_run(run)
    assert "uv.lock" in result.files
    assert result.churn == 1


def test_an_unreadable_work_area_says_so(worktree: Path):
    result = gates.check_run(_run(worktree, isolated=True), snapshot=lambda _folder: None)
    assert result.status == gates.UNREADABLE


# --------------------------------------------------------------------- scope


def test_secrets_and_deployment_files_are_off_limits():
    found = scope.check(["app/calc.py", ".env", "deploy/prod.yaml", "infra/main.tf"])
    assert [(f.rule, f.severity, f.path) for f in found] == [
        ("S1", VIOLATION, ".env"),
        ("S1", VIOLATION, "deploy/prod.yaml"),
        ("S1", VIOLATION, "infra/main.tf"),
    ]


def test_what_the_cheat_scan_reports_is_not_reported_twice():
    assert scope.check([".github/workflows/ci.yml", "AGENTS.md", "CLAUDE.md"]) == []


def test_the_apps_own_judges_are_points_to_look_at_only_in_its_own_repository():
    paths = ["dodaios/orchestrator/verification/cheat_scan.py", "tests/eval/cases.py"]
    assert scope.check(paths) == []
    # The person sends agents to these files every day: never a violation by itself.
    assert [(f.rule, f.severity, f.path) for f in scope.check(paths, own_repo=True)] == [
        ("S2", AMBIGUOUS, "dodaios/orchestrator/verification/cheat_scan.py"),
        ("S2", AMBIGUOUS, "tests/eval/cases.py"),
    ]
