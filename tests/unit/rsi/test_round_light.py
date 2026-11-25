"""A learning round stays light on the person's machine.

It reads a repository at a commit without writing a file, answers the lead's
folder tools there as the tools answer on a checkout, starts its children at
low priority, and stops starting heavy work when the person comes back.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from dodaios.agent_chat import dodaios_harness
from dodaios.agent_chat import tools as app_tools
from dodaios.core import process_utils
from dodaios.rsi import night as nights
from dodaios.rsi.bench import at_commit, brief_replay
from dodaios.rsi.bench.at_commit import CommitFiles, look
from dodaios.rsi.bench.lead_replay import Platform
from dodaios.rsi.bench.model import Domain, Source, Task, task_id
from dodaios.rsi.budget import Budget


def _git(folder: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True, check=True)
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str]:
    """A checkout whose working tree is exactly its commit, for comparing with the tools."""
    folder = tmp_path / "repo"
    files = {
        "README.md": "the flicker project\n",
        "app/view.py": "def show():\n    return 'flicker'\n\n# no FLICKER here\n",
        "app/model.py": "class Thing:\n    pass\n",
        "app/sub/deep.ts": "export const flicker = 1;\r\nexport const calm = 2;\r\n",
        "docs/notes.md": "".join(f"line {i} flicker\n" for i in range(250)),
        "node_modules/pkg/index.js": "flicker inside a dependency\n",
        "tests/test_view.py": "def test_show():\n    assert 'flicker'\n",
    }
    for rel, text in files.items():
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    _git(folder, "init", "-q", "-b", "main")
    _git(folder, "config", "user.email", "t@example.com")
    _git(folder, "config", "user.name", "T")
    _git(folder, "config", "core.autocrlf", "false")
    _git(folder, "add", "-A")
    _git(folder, "commit", "-q", "-m", "one")
    return folder, _git(folder, "rev-parse", "HEAD")


def _tool(name: str, args: dict[str, Any], cwd: Path) -> tuple[str, bool]:
    return asyncio.run(app_tools.execute_tool(name, args, cwd=cwd))


def _lines(text: str) -> list[str]:
    # A walk's order differs between file systems; the hits do not.
    return sorted(text.splitlines())


CALLS: list[tuple[str, dict[str, Any], bool]] = [
    ("Read", {"file_path": "app/view.py"}, True),
    ("Read", {"file_path": "docs/notes.md", "offset": 10, "limit": 3}, True),
    ("Read", {"file_path": "app/sub/deep.ts"}, True),
    ("Read", {"file_path": "app/gone.py"}, True),
    ("Ls", {"path": "app"}, True),
    ("Ls", {"path": "app/view.py"}, True),
    ("Glob", {"pattern": "*.py", "path": "app"}, False),
    ("Glob", {"pattern": "*.rs"}, False),
    ("Grep", {"pattern": "flicker", "path": "app"}, False),
    ("Grep", {"pattern": "flick(er)?$", "glob": "*.py"}, False),
    ("Grep", {"pattern": "flicker", "path": "docs", "max_results": 5}, True),
    ("Grep", {"pattern": "(unclosed"}, True),
    ("Grep", {"pattern": "flicker", "path": "app/view.py"}, True),
]


@pytest.mark.parametrize(("tool", "args", "exact"), CALLS)
def test_the_folder_tools_answer_at_the_commit_as_on_a_checkout_of_it(
    repo: tuple[Path, str], tool: str, args: dict[str, Any], exact: bool
) -> None:
    folder, commit = repo
    files = CommitFiles(folder, commit)
    try:
        found = look(files, tool, args)
    finally:
        files.close()
    assert found is not None
    want = _tool(tool, args, folder)
    assert found[1] == want[1]
    if exact:
        assert found[0] == want[0]
    else:
        assert _lines(found[0]) == _lines(want[0])


def test_a_look_outside_the_repository_or_by_a_writing_tool_is_not_answered(
    repo: tuple[Path, str], tmp_path: Path
) -> None:
    folder, commit = repo
    (tmp_path / "secret.txt").write_text("flicker\n", encoding="utf-8")
    files = CommitFiles(folder, commit)
    try:
        for outside in (str(tmp_path / "secret.txt"), "../secret.txt", str(tmp_path)):
            assert look(files, "Read", {"file_path": outside}) is None
            assert look(files, "Grep", {"pattern": "x", "path": outside}) is None
        assert look(files, "Write", {"file_path": "app/x.py", "content": "x"}) is None
        assert look(files, "RunCommand", {"command": "dir"}) is None
        named = look(files, "Read", {"file_path": str(folder / "README.md")})
        assert named is not None and named[0].startswith("README.md (1 lines)")
    finally:
        files.close()


def test_the_kit_reads_the_commit_as_it_reads_a_checkout_of_it(repo: tuple[Path, str]) -> None:
    from dodaios.briefs import repo_facts

    folder, commit = repo
    files = CommitFiles(folder, commit)
    try:
        at = repo_facts.lookup(
            folder, "the flicker in show", kind="bug", deadline_s=30, files=files
        )
    finally:
        files.close()
    on_disk = repo_facts.lookup(folder, "the flicker in show", kind="bug", deadline_s=30)
    assert at.files == on_disk.files and at.checks == on_disk.checks
    assert [p.path for p in at.starting_points] == [p.path for p in on_disk.starting_points]


# ------------------------------------------------------------------ priority


def test_every_child_of_a_round_runs_at_low_priority(
    repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    folder, commit = repo
    seen: list[tuple[list[str], int]] = []
    real_run, real_popen = subprocess.run, subprocess.Popen

    def run(argv: Any, *args: Any, **kwargs: Any) -> Any:
        seen.append((list(argv), int(kwargs.get("creationflags") or 0)))
        return real_run(argv, *args, **kwargs)

    def popen(argv: Any, *args: Any, **kwargs: Any) -> Any:
        seen.append((list(argv), int(kwargs.get("creationflags") or 0)))
        return real_popen(argv, *args, **kwargs)

    monkeypatch.setattr(at_commit.subprocess, "run", run)
    monkeypatch.setattr(at_commit.subprocess, "Popen", popen)
    files = CommitFiles(folder, commit)
    try:
        assert files.exists() and files.read("README.md")
        assert files.files_with("flicker", float("inf"))
    finally:
        files.close()
    assert len(seen) >= 3
    for argv, flags in seen:
        _assert_low(argv, flags)
    # A shared git helper (the intake of past work, the repository's id) is low only
    # inside a round, and as before everywhere else.
    from dodaios.agentic_ide import git_local

    seen.clear()
    monkeypatch.setattr(git_local.subprocess, "run", run)
    git_local.run_git(["status"], folder)
    assert seen[-1][1] == process_utils.NO_WINDOW_CREATIONFLAGS
    with process_utils.background_children():
        git_local.run_git(["status"], folder)
    _assert_low(*seen[-1])


def _assert_low(argv: list[str], flags: int) -> None:
    if sys.platform == "win32":
        assert flags & 0x00004000, argv  # BELOW_NORMAL_PRIORITY_CLASS
        assert flags & process_utils.NO_WINDOW_CREATIONFLAGS, argv
    elif process_utils.shutil.which("nice"):
        assert Path(argv[0]).name == "nice" and argv[1:3] == ["-n", "10"], argv


def test_the_replay_cli_starts_at_low_priority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from dodaios.rsi.bench import lead_cli
    from dodaios.rsi.bench.lead_replay import LeadInput

    started: list[tuple[list[str], int]] = []
    real = subprocess.Popen

    def popen(argv: Any, *args: Any, **kwargs: Any) -> Any:
        started.append((list(argv), int(kwargs.get("creationflags") or 0)))
        return real(argv, *args, **kwargs)

    monkeypatch.setattr(lead_cli.subprocess, "Popen", popen)
    out = tmp_path / "out"
    out.mkdir()
    tools = tmp_path / "tools.json"
    tools.write_text(json.dumps([{"name": "delegate"}]))
    fake = Path(__file__).with_name("fake_claude.py")
    driver = lead_cli.ClaudeReplay(
        tools_file=tools,
        scratch=tmp_path / "scratch",
        env=dict(__import__("os").environ),
        argv_prefix=[sys.executable, str(fake), "text", str(out)],
        timeout_s=30.0,
    )
    driver(LeadInput("S", "hi"), Platform("claude-cli", "opus"))
    assert started
    _assert_low(*started[0])


# ---------------------------------------------------------------- the yield


def test_a_task_held_by_the_budget_reads_no_repository(tmp_path: Path) -> None:
    asked: list[str] = []
    budget = Budget(10, idle=lambda: False)  # the person is back

    template = brief_replay.template_of(
        "S",
        "x"
        + dodaios_harness.message_lines("x", continuation=False, brief=dodaios_harness.BRIEF_LINE),
    )
    assert isinstance(template, brief_replay.Template)
    world = brief_replay.BriefWorld(
        platform=Platform("claude-cli", "opus"),
        driver=lambda *a: pytest.fail("no replay starts"),
        budget=budget,
        template=template,
        clones={"github.com/acme/app": tmp_path},
        commit=lambda repo, base: asked.append(base) or "never",  # type: ignore[func-returns-value]
        kit=lambda *a: "",
        look=lambda *a: None,
    )
    task = Task(
        id=task_id(Domain.BRIEF, Source.MADE, "held"),
        domain=Domain.BRIEF,
        source=Source.MADE,
        group="g",
        payload={"repo": "github.com/acme/app", "base": "abc", "request": "Fix it."},
        check={"files": {"app/x.py": 1}},
    )
    found = brief_replay.run(task, world)
    assert found.void == "budget: the person is back"
    assert asked == [] and budget.calls == 0  # not even a git process for the commit


class Steps:
    """A round's steps, recorded; the person comes back after the first one."""

    def __init__(self) -> None:
        self.done: list[str] = []
        self.back_after = 1

    def held(self) -> str:
        return "the person came back" if len(self.done) >= self.back_after else ""

    def prepare(self) -> dict[str, Any]:
        self.done.append("prepare")
        return {}


def test_the_round_stops_starting_heavy_work_when_the_person_comes_back(tmp_path: Path) -> None:
    steps = Steps()
    box = nights.sandbox(tmp_path / "box")
    try:
        night = box.night
        night._prepare = steps.prepare  # noqa: SLF001
        night._held = steps.held  # noqa: SLF001
        measured: list[str] = []
        real_settle, real_consider = night._settle, night.gate.consider_all  # noqa: SLF001

        def settle(everything: bool) -> Any:
            measured.append("settle")
            return real_settle(everything)

        def consider() -> Any:
            measured.append("decide")
            return real_consider()

        night._settle = settle  # type: ignore[method-assign]  # noqa: SLF001
        night.gate.consider_all = consider  # type: ignore[method-assign]
        report = night.run()
        assert steps.done == ["prepare"] and measured == []
        assert report.parked == "the person came back"
        assert report.lines()[0].startswith("Stopped early (the person came back)")
        assert report.public()["parked"] == "the person came back"
        # Not a round done: the next one may start as soon as the person is away again.
        assert night.last_ms() == 0 and night.due()
        steps.back_after = 99
        again = night.run()
        assert not again.parked and measured == ["settle", "decide"]
        assert night.last_ms() > 0 and not night.due()
    finally:
        box.close()


def test_a_round_that_ran_through_reports_no_stop(tmp_path: Path) -> None:
    box = nights.sandbox(tmp_path / "box")
    try:
        report = box.night.run()
        assert not report.parked and "parked" not in report.public()
    finally:
        box.close()
