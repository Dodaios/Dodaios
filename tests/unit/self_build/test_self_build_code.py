"""The code builder end to end: an issue in a sandbox repository becomes a draft
pull request with a green check, recorded in the ledger and undoable; and every
guard (other people's repositories, risky issues, pause, off, silent days, caps,
failing tests, protected files) produces nothing."""

from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.core.config import SelfBuildConfig
from dodaios.self_build import Kind, Outcome, SelfBuild, State, policy
from dodaios.self_build.code import brief as brief_mod
from dodaios.self_build.code import commands, judge, seat
from dodaios.self_build.code.context import Context, branch_name, parse_signature, signature
from dodaios.self_build.code.github import (
    CreatedPull,
    Issue,
    PullRef,
    PullState,
    Snapshot,
    Viewer,
)
from dodaios.self_build.code.loop import CodeLoop
from dodaios.self_build.code.planner import Plan, parse
from dodaios.self_build.code.runner import RunResult
from dodaios.self_build.code.seat import Seat
from dodaios.self_build.code.store import CodeStore

from .code_sandbox import ISSUE_BODY, git, make_issue, sandbox

# ------------------------------------------------------------------ fakes


@dataclass
class FakeGitHub:
    login: str = "me"
    issues: dict[str, list[Issue]] = field(default_factory=dict)
    pulls: dict[int, dict[str, Any]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    open_refs: tuple[PullRef, ...] = ()
    #: What :meth:`issue` answers now, when it differs from the poll.
    fresh: dict[int, Any] = field(default_factory=dict)

    def viewer(self) -> Viewer:
        self.calls.append("viewer")
        return Viewer(login=self.login)

    def snapshot(self, repo: str) -> Snapshot:
        self.calls.append(f"snapshot {repo}")
        return Snapshot(
            repo=repo,
            permission="ADMIN",
            default_branch="main",
            issues=tuple(self.issues.get(repo, [])),
            pulls=self.open_refs,
        )

    def create_pull(
        self, repo: str, *, head: str, base: str, title: str, body: str, draft: bool
    ) -> CreatedPull:
        number = 100 + len(self.pulls)
        self.calls.append(f"create {repo} {head}")
        self.pulls[number] = {
            "repo": repo,
            "head": head,
            "base": base,
            "title": title,
            "body": body,
            "draft": draft,
            "state": "OPEN",
            "checks": "PENDING",
            "head_oid": "",
            "merged": 0,
        }
        return CreatedPull(id=f"PR_{number}", number=number, url=f"https://x/{repo}/pull/{number}")

    def pull(self, repo: str, number: int) -> PullState:
        data = self.pulls[number]
        return PullState(
            id=f"PR_{number}",
            number=number,
            url="",
            state=data["state"],
            draft=data["draft"],
            head_oid=data["head_oid"],
            checks=data["checks"],
            failing=("tests",) if data["checks"] == "FAILURE" else (),
        )

    def close_pull(self, pull_id: str) -> None:
        self.calls.append(f"close {pull_id}")
        self.pulls[int(pull_id.split("_")[1])]["state"] = "CLOSED"

    def issue(self, repo: str, number: int) -> Issue | None:
        self.calls.append(f"issue {repo}#{number}")
        if number in self.fresh:
            found = self.fresh[number]
            if isinstance(found, Exception):
                raise found
            return found
        return next((i for i in self.issues.get(repo, []) if i.number == number), None)

    def merge_pull(self, pull_id: str, *, head_oid: str) -> None:
        self.calls.append(f"merge {pull_id}")
        self.pulls[int(pull_id.split("_")[1])]["state"] = "MERGED"
        self.pulls[int(pull_id.split("_")[1])]["head_oid"] = head_oid


@dataclass
class FakeRunner:
    """The coding agent: writes the change it is told to (or a bad one)."""

    change: str = "good"
    prompts: list[str] = field(default_factory=list)
    stopped: list[str] = field(default_factory=list)
    dropped: list[tuple[str, ...]] = field(default_factory=list)

    async def run(
        self,
        *,
        provider: str,
        folder: str,
        prompt: str,
        title: str,
        timeout_s: float,
        should_stop: Any,
        on_session: Any = None,
        drop_env: tuple[str, ...] = (),
    ) -> RunResult:
        self.prompts.append(prompt)
        self.dropped.append(drop_env)
        if on_session is not None:
            await on_session("thread-1")
        root = Path(folder)
        if self.change == "nothing":
            return RunResult(True, summary="Nothing to do.", session_id="thread-1")
        if self.change == "fail":
            return RunResult(False, error="the CLI crashed", session_id="thread-1")
        calc = root / "calc.py"
        calc.write_text(
            calc.read_text(encoding="utf-8")
            + "\n\ndef mul(a: int, b: int) -> int:\n"
            + ("    return a * b\n" if self.change != "broken" else "    return a + b\n"),
            encoding="utf-8",
        )
        (root / "tests" / "test_mul.py").write_text(
            "from calc import mul\n\n\ndef test_mul():\n    assert mul(2, 3) == 6\n",
            encoding="utf-8",
        )
        if self.change == "protected":
            (root / ".github" / "workflows").mkdir(parents=True)
            (root / ".github" / "workflows" / "ci.yml").write_text("on: push\n", encoding="utf-8")
        return RunResult(True, summary="Added mul() and a test.", session_id="thread-1")

    async def outcome(self, session_id: str) -> RunResult | None:
        return RunResult(True, summary="Added mul() and a test.", session_id=session_id)

    async def stop(self, session_id: str) -> None:
        self.stopped.append(session_id)


@dataclass
class World:
    service: SelfBuild
    loop: CodeLoop
    github: FakeGitHub
    runner: FakeRunner
    work: Path
    remote: Path
    cfg: SimpleNamespace
    idle: list[bool]
    seat_calls: list[int]

    def tick(self) -> dict[str, Any]:
        async def go() -> dict[str, Any]:
            summary = await self.loop.tick()
            if self.loop._building is not None:
                await self.loop._building
            return summary

        return asyncio.run(go())

    def records(self) -> list[Any]:
        return self.service.ledger.list(kinds=[Kind.CODE])

    def remote_branches(self) -> list[str]:
        out = git(self.remote, "branch", "--list", "--format=%(refname:short)")
        return [b for b in out.splitlines() if b]


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    monkeypatch.setattr(commands, "_python", lambda folder: sys.executable)
    work = sandbox(tmp_path)
    cfg = SimpleNamespace(
        self_build=SelfBuildConfig(silent_days=0, code="trial"),
        ui=SimpleNamespace(language="en"),
    )
    service = SelfBuild(tmp_path / "data", lambda: cfg)
    github = FakeGitHub(issues={"me/proj": [make_issue()]})
    runner = FakeRunner()
    idle = [True]
    seat_calls: list[int] = []

    async def pick() -> tuple[Seat | None, str]:
        seat_calls.append(1)
        return Seat(provider="claude-api", runner="claude-cli", label="Claude Code"), ""

    project = SimpleNamespace(
        path=str(work), name="proj", last_opened_at=time.time(), scratch=False, archived=False
    )
    ctx = Context(
        service=service,
        store=CodeStore(tmp_path / "data" / "self_build_code.db"),
        github=lambda: github,
        runner=runner,
        seat=pick,
        idle=lambda: idle[0],
        projects=lambda: [project],
        plan=None,
        dodaios_root=None,
    )
    loop = CodeLoop(ctx)
    loop.attach()
    yield World(
        service,
        loop,
        github,
        runner,
        work,
        tmp_path / "github.com" / "me" / "proj.git",
        cfg,
        idle,
        seat_calls,
    )
    ctx.store.close()
    service.ledger.close()


# ------------------------------------------------------------------ the whole way


def test_issue_becomes_draft_pull_request_proven_by_ci_and_undoable(world: World) -> None:
    summary = world.tick()
    assert summary["projects"] == ["me/proj"]
    assert summary["opened"] == 1
    [record] = world.records()
    assert record.signature == "code:me/proj#1"
    assert record.state == State.PROVING
    assert record.evidence == ("https://github.com/me/proj/issues/1",)
    assert record.title == "Fix issue #1 in me/proj: Add a mul function"

    pull = world.github.pulls[100]
    assert pull["draft"] is True
    assert pull["base"] == "main"
    assert pull["body"].startswith("Closes #1")
    assert "passed in" in pull["body"]
    # The provenance join key every "built by Dodaios" badge reads.
    assert record.artefact["type"] == "code"
    assert record.artefact["id"] == "https://x/me/proj/pull/100"
    assert record.artefact["repo"] == "me/proj"
    assert record.artefact["draft"] is True
    # The coding thread stays linked from the build detail.
    assert record.artefact["thread"] == "thread-1"
    branch = record.undo["branch"]
    assert branch.startswith("dodaios/issue-1-")
    assert branch in world.remote_branches()
    worktree = Path(record.undo["worktree"])
    assert worktree.is_dir() and ".worktrees" in worktree.parts
    # The person's own checkout was never touched.
    assert git(world.work, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert "mul" not in (world.work / "calc.py").read_text(encoding="utf-8")
    # The coding agent got the brief and the repository's rules.
    prompt = world.runner.prompts[0]
    assert "Use type hints in new code." in prompt
    assert "pytest" in prompt and ISSUE_BODY in prompt
    # The agent is told the exact command the judge runs (the real interpreter).
    assert sys.executable.replace(chr(92), "/") in prompt.replace(chr(92), "/")

    world.github.pulls[100]["checks"] = "SUCCESS"
    world.tick()
    record = world.service.ledger.get(record.id)
    assert record.state == State.TRIAL
    assert record.proof["passed"] is True
    assert record.proof["judge"] == "tests+ci"
    assert "merge PR_100" not in world.github.calls  # draft, no opt-in: never merged

    undone = asyncio.run(world.service.undo_build(record.id))
    assert undone.state == State.UNDONE
    assert world.github.pulls[100]["state"] == "CLOSED"
    assert branch not in world.remote_branches()
    assert not worktree.exists()
    assert not worktree.parent.exists()  # no empty .worktrees folder left behind
    assert branch not in git(world.work, "branch", "--list", branch)


def test_merged_pull_request_is_kept_and_teaches_the_profile(world: World) -> None:
    world.tick()
    [record] = world.records()
    world.github.pulls[100].update(checks="SUCCESS")
    world.tick()
    world.github.pulls[100].update(state="MERGED", head_oid=record.undo["head"])
    world.tick()
    record = world.service.ledger.get(record.id)
    assert record.state == State.KEPT
    assert record.outcomes == {Outcome.ACCEPTED.value: 1}
    profile = world.loop.ctx.store.profile("me/proj")
    assert [e["number"] for e in profile["merged"]] == [1]
    assert profile["merged"][0]["changed"] is False
    stored = brief_mod.load(world.loop.ctx.store, world.work)
    assert stored is not None and stored.parts["outcomes"]["merged"] == 1
    # One build per issue, ever: the merged issue is not offered again.
    world.tick()
    assert len(world.records()) == 1


def test_changed_before_merge_counts_as_corrected(world: World) -> None:
    world.tick()
    [record] = world.records()
    world.github.pulls[100].update(state="MERGED", head_oid="someone-else-pushed")
    world.tick()
    record = world.service.ledger.get(record.id)
    assert record.state == State.KEPT
    assert record.outcomes == {Outcome.CORRECTED.value: 1}


def test_red_ci_fails_the_build_closes_the_pull_request_and_keeps_the_lesson(world: World) -> None:
    world.tick()
    [record] = world.records()
    branch = record.undo["branch"]
    world.github.pulls[100]["checks"] = "FAILURE"
    world.tick()
    record = world.service.ledger.get(record.id)
    assert record.state == State.FAILED
    assert record.proof == {"passed": False, "judge": "tests+ci", "detail": record.proof["detail"]}
    assert world.github.pulls[100]["state"] == "CLOSED"
    assert branch not in world.remote_branches()
    lessons = world.loop.ctx.store.profile("me/proj")["lessons"]
    assert "CI failed" in lessons[-1]["lesson"]


def test_person_closing_the_pull_request_undoes_the_build(world: World) -> None:
    world.tick()
    [record] = world.records()
    world.github.pulls[100]["state"] = "CLOSED"
    world.tick()
    record = world.service.ledger.get(record.id)
    assert record.state == State.UNDONE
    assert world.loop.ctx.store.profile("me/proj")["closed"][0]["number"] == 1


def test_landing_opt_in_merges_after_green_ci(world: World) -> None:
    world.cfg.self_build = SelfBuildConfig(silent_days=0, code="trial", code_land_repos=["Me/Proj"])
    world.tick()
    assert world.github.pulls[100]["draft"] is False
    world.github.pulls[100]["checks"] = "SUCCESS"
    world.tick()
    assert "merge PR_100" in world.github.calls
    world.tick()
    [record] = world.records()
    assert record.state == State.KEPT


def test_repository_without_ci_is_judged_by_local_tests(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dodaios.self_build.code import watch

    world.tick()
    world.github.pulls[100]["checks"] = ""
    monkeypatch.setattr(watch, "NO_CI_GRACE_MS", 0)
    world.tick()
    [record] = world.records()
    assert record.state == State.TRIAL
    assert record.proof["judge"] == "tests"


# ------------------------------------------------------------------ failures without a PR


@pytest.mark.parametrize(
    ("change", "lesson"),
    [
        ("broken", "the tests failed"),
        ("protected", "protected files"),
        ("nothing", "changed nothing"),
        ("fail", "did not finish"),
    ],
)
def test_a_bad_run_fails_without_a_pull_request(world: World, change: str, lesson: str) -> None:
    world.runner.change = change
    world.tick()
    [record] = world.records()
    assert record.state == State.FAILED
    assert lesson in record.note
    assert world.github.pulls == {}
    assert world.remote_branches() == ["main"]
    assert not Path(record.undo["worktree"]).exists()
    assert lesson in world.loop.ctx.store.profile("me/proj")["lessons"][-1]["lesson"]


def test_large_estimate_stops_before_any_coding(world: World) -> None:
    async def big(build_id: str, issue: Issue, text: str) -> Plan:
        return Plan(text="- redesign everything", size="large")

    world.loop.ctx.plan = big
    world.tick()
    [record] = world.records()
    assert record.state == State.FAILED
    assert world.runner.prompts == []


# ------------------------------------------------------------------ guards: nothing happens


def test_other_peoples_repositories_are_never_polled(tmp_path: Path, world: World) -> None:
    other = sandbox(tmp_path / "x", owner="someone", name="lib")
    world.loop.ctx.projects = lambda: [
        SimpleNamespace(path=str(other), name="lib", last_opened_at=time.time())
    ]
    world.github.issues = {"someone/lib": [make_issue()]}
    summary = world.tick()
    assert summary["projects"] == []
    assert not [c for c in world.github.calls if c.startswith("snapshot")]
    assert world.records() == []


def test_dodaios_own_source_is_outside_the_loop(world: World) -> None:
    (world.work / "dodaios" / "self_build").mkdir(parents=True)
    assert world.tick()["projects"] == []


@pytest.mark.parametrize(
    "issue",
    [
        make_issue(title="Rotate the API key in settings"),
        make_issue(body="Update the deploy script so production uses the new bucket name."),
        make_issue(body="Fix the GitHub Actions workflow that runs the nightly tests now."),
        make_issue(author="stranger", labels=()),
        make_issue(labels=("agent", "question")),
        make_issue(assignees=1),
        make_issue(labels=()),
        make_issue(body="short"),
    ],
)
def test_unfit_issues_open_nothing(world: World, issue: Issue) -> None:
    world.github.issues = {"me/proj": [issue]}
    assert world.tick()["opened"] == 0
    assert world.records() == []


def test_paused_or_off_makes_no_call_at_all(world: World) -> None:
    policy.set_paused(world.service.ledger, True)
    assert world.tick() == {"skipped": "paused"}
    policy.set_paused(world.service.ledger, False)
    world.cfg.self_build = SelfBuildConfig(silent_days=0, code="off")
    assert world.tick() == {"skipped": "off"}
    assert world.github.calls == []
    assert world.records() == []


def test_suggest_and_silent_days_only_propose(world: World) -> None:
    world.cfg.self_build = SelfBuildConfig(silent_days=0, code="suggest")
    world.tick()
    [record] = world.records()
    assert record.state == State.PROPOSED
    assert world.runner.prompts == [] and world.github.pulls == {}
    # Accepting the card builds it (on the next idle pass).
    asyncio.run(world.service.accept(record.id))
    world.tick()
    assert world.service.ledger.get(record.id).state == State.PROVING


def test_silent_first_days_record_without_building(world: World) -> None:
    world.cfg.self_build = SelfBuildConfig(silent_days=7, code="full")
    world.tick()
    [record] = world.records()
    assert record.state == State.PROPOSED
    assert world.runner.prompts == []


def test_daily_code_cap_turns_a_build_into_a_proposal(world: World) -> None:
    world.cfg.self_build = SelfBuildConfig(silent_days=0, code="trial", max_code_runs_per_day=0)
    world.tick()
    [record] = world.records()
    assert record.state == State.PROPOSED
    assert world.runner.prompts == []


def test_one_new_case_per_pass(world: World) -> None:
    world.github.issues = {"me/proj": [make_issue(1), make_issue(2, title="Add a div function")]}
    world.tick()
    assert len(world.records()) == 1


def test_busy_person_or_no_subscription_waits(world: World) -> None:
    world.idle[0] = False
    world.tick()
    [record] = world.records()
    assert record.state == State.BUILDING
    assert world.runner.prompts == [] and world.seat_calls == []
    world.idle[0] = True

    async def none() -> tuple[Seat | None, str]:
        return None, "Claude Code: plan not signed in"

    world.loop.ctx.seat = none
    assert world.tick()["build"] == "waiting: Claude Code: plan not signed in"
    assert world.service.ledger.get(record.id).state == State.BUILDING


def _slow_run(world: World) -> asyncio.Event:
    """Make the fake agent work until it is stopped (or the event is set)."""
    released = asyncio.Event()

    async def slow(**kwargs: Any) -> RunResult:
        await kwargs["on_session"]("thread-9")
        while not released.is_set() and not kwargs["should_stop"]():  # noqa: ASYNC110 - polls should_stop too
            await asyncio.sleep(0.02)
        return RunResult(False, error="stopped", session_id="thread-9")

    async def stop(session_id: str) -> None:
        world.runner.stopped.append(session_id)
        released.set()

    world.runner.run = slow  # type: ignore[method-assign]
    world.runner.stop = stop  # type: ignore[method-assign]
    return released


async def _until_coding(world: World, build_id: str) -> None:
    for _ in range(3000):  # up to a minute on a loaded machine
        if world.service.ledger.get(build_id).undo.get("session_id"):
            return
        await asyncio.sleep(0.02)
    raise AssertionError("the run never started")


def test_undo_while_coding_stops_the_run(world: World) -> None:
    world.idle[0] = False
    world.tick()
    [record] = world.records()
    world.idle[0] = True

    async def go() -> Any:
        _slow_run(world)
        await world.loop.tick()
        await _until_coding(world, record.id)
        undone = await world.service.undo_build(record.id)
        await world.loop._building
        return undone

    undone = asyncio.run(go())
    assert undone.state == State.UNDONE
    assert world.service.ledger.get(record.id).state == State.UNDONE
    assert "thread-9" in world.runner.stopped
    assert not Path(undone.undo["worktree"]).exists()
    assert world.github.pulls == {}
    # An undone issue is not offered again.
    world.tick()
    assert len(world.records()) == 1


def test_pause_mid_run_puts_the_case_back_in_the_queue(world: World) -> None:
    world.idle[0] = False
    world.tick()
    [record] = world.records()
    world.idle[0] = True

    async def go() -> None:
        _slow_run(world)
        await world.loop.tick()
        await _until_coding(world, record.id)
        policy.set_paused(world.service.ledger, True)
        await world.loop._building

    asyncio.run(go())
    record = world.service.ledger.get(record.id)
    assert record.state == State.BUILDING
    assert record.artefact == {} and record.undo == {}
    assert world.remote_branches() == ["main"]
    assert world.loop.ctx.store.profile("me/proj")["lessons"] == []
    # After the pause the case is built from scratch.
    policy.set_paused(world.service.ledger, False)
    world.runner = FakeRunner()
    world.loop.ctx.runner = world.runner
    world.tick()
    assert world.service.ledger.get(record.id).state == State.PROVING


def test_undo_keeps_a_branch_the_person_added_commits_to(world: World) -> None:
    world.tick()
    [record] = world.records()
    branch = record.undo["branch"]
    worktree = Path(record.undo["worktree"])
    (worktree / "extra.py").write_text("x = 1\n", encoding="utf-8")
    git(worktree, "add", "extra.py")
    git(worktree, "commit", "-m", "person's own work")
    git(worktree, "push", "origin", branch)
    undone = asyncio.run(world.service.undo_build(record.id))
    assert undone.state == State.UNDONE
    assert world.github.pulls[100]["state"] == "CLOSED"
    assert branch in world.remote_branches()  # their commit lives on
    assert worktree.exists()


def test_existing_branch_stops_the_build(world: World) -> None:
    branch = branch_name(1, "Add a mul function")
    git(world.work, "branch", branch)
    world.tick()
    [record] = world.records()
    assert record.state == State.FAILED
    assert "already exists" in record.note
    assert branch in git(world.work, "branch", "--list", branch)  # the person's branch stays


def test_pull_request_targets_githubs_default_branch(world: World) -> None:
    git(world.work, "checkout", "-b", "feature")
    git(world.work, "push", "-u", "origin", "feature")
    git(world.work, "remote", "set-head", "origin", "feature")
    world.tick()
    assert world.github.pulls[100]["base"] == "main"


def test_stale_case_may_be_offered_again(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from dodaios.self_build.code import loop as loop_mod

    world.idle[0] = False
    world.tick()
    monkeypatch.setattr(loop_mod, "STALE_BUILDING_MS", -1)
    world.tick()
    [record] = world.records()
    assert record.state == State.FAILED and record.note.startswith("not run: ")
    world.loop.ctx.store.set_poll("me/proj", 0)
    world.tick()
    assert len(world.records()) == 2


# ------------------------------------------------------------------ parts


def test_judge_guard_and_names() -> None:
    assert judge.guard(["src/a.py", ".github/workflows/ci.yml", "AGENTS.md", ".env.local"]) == [
        ".github/workflows/ci.yml",
        "AGENTS.md",
        ".env.local",
    ]
    assert branch_name(12, "Fix: the CLI's --help!") == "dodaios/issue-12-fix-the-cli-s-help"
    assert parse_signature(signature("me/proj", 4)) == ("me/proj", 4)
    assert parse_signature("routine:weekly") is None


def test_plan_answer_is_parsed() -> None:
    plan = parse("SIZE: Medium\nPLAN:\n- edit calc.py\n- add a test")
    assert plan.size == "medium" and plan.text.startswith("- edit")
    assert parse("no idea").size == ""


def test_seat_never_uses_a_cli_that_would_bill_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from dodaios.brain import background_policy

    row = SimpleNamespace(id="claude-api", agent="claude", label="Claude Code")
    monkeypatch.setattr(seat, "_rows", lambda: [row])
    monkeypatch.setattr(
        "dodaios.agent_chat.service.resolve_runner", lambda provider, surface="agent": "claude-cli"
    )
    monkeypatch.setattr(seat, "_cooling", lambda runner: False)
    monkeypatch.setattr(seat, "_window_full", lambda platform: False)
    monkeypatch.setattr(background_policy, "login_state", lambda provider: True)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    chosen, _ = seat.choose({"claude": True})
    assert chosen is not None and chosen.provider == "claude-api"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    chosen, why = seat.choose({"claude": True})
    assert chosen is None and "API key" in why
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setattr(background_policy, "login_state", lambda provider: None)
    assert seat.choose({"claude": True})[0] is None
    assert seat.choose({"claude": False})[0] is None


# ------------------------------------------------------------------ the thread runner


class FakeChat:
    """The agent-chat service surface the thread runner uses."""

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.script = events
        self.events: list[dict[str, Any]] = []
        self.sessions: list[dict[str, Any]] = []
        self.cancelled: list[str] = []
        self.store = SimpleNamespace(list_events=lambda sid, tail=None: list(self.events))

    def create_session(self, **kwargs: Any) -> Any:
        self.sessions.append(kwargs)
        return SimpleNamespace(session_id="s1")

    async def send(self, sid: str, text: str, *, author: dict[str, str]) -> str:
        self.sent = (text, author)
        self.events = [
            {"kind": e["kind"], "payload": {"turn_id": "t1", **e["payload"]}} for e in self.script
        ]
        return "t1"

    def is_running(self, sid: str) -> bool:
        return any(e["kind"] == "question_required" for e in self.events) and not self.cancelled

    async def cancel(self, sid: str) -> bool:
        self.cancelled.append(sid)
        return True


def test_thread_runner_opens_a_full_access_thread_in_the_worktree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dodaios.self_build.code.runner import ThreadRunner

    monkeypatch.setattr(
        "dodaios.agent_chat.service.resolve_runner", lambda provider, surface="agent": "claude-cli"
    )
    chat = FakeChat(
        [
            {"kind": "assistant_text", "payload": {"text": "Added mul()."}},
            {"kind": "turn_finished", "payload": {"status": "done"}},
        ]
    )
    seen: list[str] = []

    async def note(sid: str) -> None:
        seen.append(sid)

    result = asyncio.run(
        ThreadRunner(lambda: chat).run(
            provider="claude-api",
            folder="/w",
            prompt="do it",
            title="#1 x",
            timeout_s=60,
            should_stop=lambda: False,
            on_session=note,
        )
    )
    assert result.ok and result.summary == "Added mul()." and seen == ["s1"]
    [opened] = chat.sessions
    assert opened["cwd"] == "/w" and opened["surface"] == "agent"
    assert opened["permission_mode"]  # the runner's bypass mode, never empty
    assert chat.sent[1]["name"] == "Dodaios"


def test_thread_runner_stops_at_a_question(monkeypatch: pytest.MonkeyPatch) -> None:
    from dodaios.self_build.code.runner import ThreadRunner

    monkeypatch.setattr(
        "dodaios.agent_chat.service.resolve_runner", lambda provider, surface="agent": "claude-cli"
    )
    chat = FakeChat(
        [
            {"kind": "question_required", "payload": {"question_id": "q1", "questions": []}},
        ]
    )
    result = asyncio.run(
        ThreadRunner(lambda: chat).run(
            provider="claude-api",
            folder="/w",
            prompt="do it",
            title="t",
            timeout_s=60,
            should_stop=lambda: False,
        )
    )
    assert not result.ok and "question" in result.error
    assert chat.cancelled == ["s1"]  # the waiting turn is ended, not left open


def test_plan_call_uses_the_loops_seats_and_is_attributed(monkeypatch: pytest.MonkeyPatch) -> None:
    from dodaios.self_build import brain
    from dodaios.self_build.code import planner

    seen: list[str] = []

    async def answer(system: str, prompt: str, max_tokens: int) -> str:
        from dodaios.costs.ledger import current_caller

        seen.append(current_caller() or "")
        return "SIZE: small\nPLAN:\n- edit calc.py"

    brain.set_override(answer, provider="claude-cli")
    try:
        plan = asyncio.run(planner.plan("b1", make_issue(), "brief", config=lambda: None))
    finally:
        brain.set_override(None)
    assert plan.size == "small" and plan.text == "- edit calc.py"
    assert seen == ["self_build:b1"]


def test_no_seat_means_no_plan_call(monkeypatch: pytest.MonkeyPatch) -> None:
    from dodaios.brain.background_policy import BackgroundDeferred
    from dodaios.self_build import brain
    from dodaios.self_build.code import planner

    async def refuse(config: Any, system: str, prompt: str, *, max_tokens: int) -> str:
        raise BackgroundDeferred("none")

    monkeypatch.setattr(brain, "ask", refuse)
    plan = asyncio.run(planner.plan("b1", make_issue(), "brief", config=lambda: None))
    assert plan == Plan()


# ------------------------------------------------------------------ re-check before the build


@pytest.mark.parametrize(
    ("now", "note"),
    [
        (None, "is closed"),
        ("closed", "is closed"),
        ("someone", "assigned to someone else"),
        ("unlabelled", "no longer fits"),
        ("risky", "no longer fits"),
    ],
)
def test_an_issue_that_changed_before_the_build_is_not_built(
    world: World, now: str | None, note: str
) -> None:
    world.cfg.self_build = SelfBuildConfig(silent_days=0, code="suggest")
    world.tick()
    [record] = world.records()
    assert record.state == State.PROPOSED
    world.github.fresh[1] = {
        None: None,
        "closed": make_issue(state="CLOSED"),
        "someone": make_issue(assignees=1, assigned_to=("someone",)),
        "unlabelled": make_issue(labels=()),
        "risky": make_issue(body="Rotate the deploy credentials on the production servers."),
    }[now]
    asyncio.run(world.service.accept(record.id))
    world.tick()
    record = world.service.ledger.get(record.id)
    assert record.state == State.FAILED
    assert record.note.startswith("not built: ") and note in record.note
    assert world.runner.prompts == [] and world.github.pulls == {}
    assert world.remote_branches() == ["main"]
    assert not (world.work / ".worktrees").exists()
    assert world.loop.ctx.store.profile("me/proj")["lessons"] == []  # not a lesson


def test_an_issue_the_person_took_on_themselves_is_still_built(world: World) -> None:
    world.github.fresh[1] = make_issue(assignees=1, assigned_to=("Me",))
    world.tick()
    [record] = world.records()
    assert record.state == State.PROVING
    assert "issue me/proj#1" in world.github.calls


def test_a_repository_no_longer_owned_is_not_built(world: World) -> None:
    world.cfg.self_build = SelfBuildConfig(silent_days=0, code="suggest")
    world.tick()
    [record] = world.records()
    asyncio.run(world.service.accept(record.id))
    world.github.login = "someone-else"
    world.loop.ctx._viewer = None
    world.tick()
    record = world.service.ledger.get(record.id)
    assert record.state == State.FAILED and "no longer the person's own" in record.note
    assert world.runner.prompts == []


def test_github_not_answering_the_recheck_keeps_the_case_waiting(world: World) -> None:
    from dodaios.agentic_ide.github_link import GitHubError

    world.github.fresh[1] = GitHubError("GitHub could not be reached.", code="unreachable")
    world.tick()
    [record] = world.records()
    assert record.state == State.BUILDING and record.artefact == {}
    assert world.runner.prompts == []
    del world.github.fresh[1]
    world.tick()
    assert world.service.ledger.get(record.id).state == State.PROVING
