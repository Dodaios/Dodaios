"""A drafted skill's steps run read-only on the person's past requests before it goes live."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from dodaios.core.protocols import BrainDelta, BrainRequest, ToolResult
from dodaios.self_build import State, brain, builders, judge, sandbox
from dodaios.self_build.sandbox import Run, Step

from .test_self_build_loop import (  # noqa: F401 - _person_zone is an autouse fixture
    SKILL_ANSWER,
    _ask_for_status,
    _days_ago,
    _person_zone,
    _say,
    _settle,
)

TOOL = "mcp:github/list_runs"


def _exists(path: str | Path) -> bool:
    return Path(path).exists()


def _runner(world: Any, make: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def run_skill(_config: Any, **kwargs: Any) -> Run:
        calls.append(kwargs)
        return make(kwargs)

    world.env.run_skill = run_skill
    return calls


async def _built(world: Any) -> Any:
    world.brain.answers = [SKILL_ANSWER]
    await _ask_for_status(world)
    (opened,) = await world.loop.run_queue()
    return await _settle(world, opened.id)


# ------------------------------------------------------------------ end to end


async def test_a_skill_whose_steps_fail_in_the_sandbox_never_goes_on_trial(world: Any) -> None:
    _runner(
        world,
        lambda kw: Run(
            kw["request"], "Could not read the runs.", (Step(TOOL, False, error="403"),)
        ),
    )
    record = await _built(world)
    assert record.state == State.FAILED
    assert record.proof["passed"] is False
    assert "replay caught 3 of 3" in record.proof["detail"]  # routing held, execution did not
    assert f"step {TOOL!r} failed" in record.proof["detail"]
    assert world.registry.list() == []
    assert world.loop.store.lessons(record.signature)[0][0] == "skill"


async def test_a_run_that_does_not_finish_or_answer_fails(world: Any) -> None:
    _runner(world, lambda kw: Run(kw["request"], "", error="TimeoutError"))
    record = await _built(world)
    assert record.state == State.FAILED and "did not finish" in record.proof["detail"]


async def test_steps_that_miss_the_tools_of_the_accepted_answer_fail(world: Any) -> None:
    _runner(
        world,
        lambda kw: Run(kw["request"], "I think the build is probably fine today.", ()),
    )
    record = await _built(world)
    assert record.state == State.FAILED
    assert "did not reach the tools" in record.proof["detail"]


async def test_held_back_side_effects_do_not_fail_the_proof(world: Any) -> None:
    _runner(
        world,
        lambda kw: Run(
            kw["request"],
            "The latest run on main passed; I would have posted it to the team channel.",
            (Step(TOOL, True), Step("slack/post_message", False, held=True)),
        ),
    )
    record = await _built(world)
    assert record.state == State.TRIAL, record.note
    assert "ran the steps read-only on 2 past request(s)" in record.proof["detail"]
    assert "1 step(s) with side effects held back" not in record.proof["detail"]  # two runs
    assert "2 step(s) with side effects held back" in record.proof["detail"]


async def test_replays_use_accepted_requests_on_different_days(world: Any) -> None:
    calls = _runner(
        world,
        lambda kw: Run(kw["request"], "The latest run on main passed.", (Step(TOOL, True),)),
    )
    world.brain.answers = [SKILL_ANSWER]
    # The newest request was corrected by the person's next turn: not accepted.
    for days, hour in ((5, 9), (3, 14)):
        await _say(
            world,
            "Please check the build status of the dodaios repo",
            _days_ago(days, hour),
            tools=(TOOL,),
        )
    stamp = _days_ago(1, 17)
    await _say(
        world,
        "check the build status of the dodaios repo now",
        stamp,
        tools=(TOOL,),
        conversation="c",
    )
    await _say(world, "no, that's wrong, the other repository", stamp + 30_000, conversation="c")
    (opened,) = await world.loop.run_queue()
    record = await _settle(world, opened.id)
    assert record.state == State.TRIAL, record.note
    assert len(calls) == 2
    assert all(c["request"] == "Please check the build status of the dodaios repo" for c in calls)
    assert TOOL in calls[0]["tools"]
    assert calls[0]["skill_body"].startswith("## Check Build Status")


async def test_without_budget_or_seat_the_skill_waits_in_building(world: Any, monkeypatch) -> None:
    async def no_seat(_config: Any, **_kwargs: Any) -> Run:
        raise brain.BackgroundDeferred("no seat can run a skill's steps")

    world.env.run_skill = no_seat
    world.brain.answers = [SKILL_ANSWER]
    await _ask_for_status(world)
    (opened,) = await world.loop.run_queue()
    for _ in range(25):
        await asyncio.sleep(0.02)
    record = world.service.ledger.get(opened.id)
    assert record.state == State.BUILDING and world.registry.list() == []

    monkeypatch.setattr(builders, "DAILY_MODEL_CALLS", 0)
    _runner(world, lambda kw: Run(kw["request"], "The latest run on main passed.", ()))
    await world.loop.builders.build(record)
    assert world.service.ledger.get(record.id).state == State.BUILDING


def test_execution_judge_rules() -> None:
    ok = Run("check the build", "The latest run on main passed fine.", (Step(TOOL, True),))
    assert judge.skill_execution([ok], accepted=[(TOOL,)]).passed
    # The accepted answer used no tool: reaching none is fine.
    bare = Run("explain the build", "It compiles the sources and runs tests.", ())
    assert judge.skill_execution([bare], accepted=[()]).passed
    assert not judge.skill_execution([], accepted=[]).passed
    other = Run(
        "check the build", "Searched the web for it, all good.", (Step("web_search", True),)
    )
    assert not judge.skill_execution([other], accepted=[(TOOL,)]).passed
    # Same family, other operation: reached.
    sibling = Run("check", "The latest run on main passed.", (Step("mcp:github/get_run", True),))
    assert judge.skill_execution([sibling], accepted=[(TOOL,)]).passed


# ------------------------------------------------------------------ the sandbox itself


class _ReadTool:
    name = "wiki-recall"
    read_only = True
    schema: dict[str, Any] = {}
    description = "read the wiki"


class _WriteTool:
    name = "send_email"
    schema: dict[str, Any] = {}
    description = "send an email"


class _Executor:
    def __init__(self, result: ToolResult | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.result = result or ToolResult(True, "the page says: CI is green")

    async def execute(self, tool: Any, args: dict[str, Any], **kwargs: Any) -> ToolResult:
        self.calls.append((tool.name, dict(kwargs.get("config_snapshot") or {})))
        return self.result


async def test_the_recorder_runs_reads_and_holds_back_everything_else() -> None:
    executor = _Executor()
    recorder = sandbox._Recorder(executor)
    held = await recorder.execute(_WriteTool(), {"to": "x"}, config_snapshot={})
    assert held.success is False and sandbox.HELD_MARKER in held.error
    assert executor.calls == []  # never reached the executor
    await recorder.execute(_ReadTool(), {"q": "ci"}, config_snapshot={"cwd": "x"})
    ((name, snapshot),) = executor.calls
    assert name == "wiki-recall" and snapshot["chat_read_only"] is True
    assert snapshot["approval_surface"] == "unattended"
    assert [(s.name, s.ok, s.held) for s in recorder.steps] == [
        ("send_email", False, True),
        ("wiki-recall", True, False),
    ]
    refused = sandbox._Recorder(_Executor(ToolResult(False, None, "Plan mode permits reads only")))
    await refused.execute(_ReadTool(), {}, config_snapshot={})
    assert refused.steps[0].held and not refused.steps[0].ok
    broken = sandbox._Recorder(_Executor(ToolResult(False, None, "HTTP 500")))
    await broken.execute(_ReadTool(), {}, config_snapshot={})
    assert not broken.steps[0].held and broken.steps[0].error == "HTTP 500"


class _ToolBrain:
    """Reads the wiki, tries to send an email, then answers."""

    name = "local"
    supports_tools = True
    supports_vision = False
    context_window = 32_000

    def __init__(self) -> None:
        self.requests: list[BrainRequest] = []

    def estimate_cost(self, _req: BrainRequest) -> float:
        return 0.0

    async def complete(self, req: BrainRequest) -> AsyncIterator[BrainDelta]:
        self.requests.append(req)
        if len(self.requests) == 1:
            yield BrainDelta(tool_call={"id": "a", "name": "wiki-recall", "input": {"q": "ci"}})
            yield BrainDelta(tool_call={"id": "b", "name": "send_email", "input": {"to": "x"}})
            yield BrainDelta(finish_reason="tool_use")
            return
        yield BrainDelta(content="CI is green on main. The email step was held back.")
        yield BrainDelta(finish_reason="stop")


async def test_a_local_seat_drives_the_tool_loop_read_only(monkeypatch, tmp_path: Path) -> None:
    executor = _Executor()
    tools = {"wiki-recall": _ReadTool(), "send_email": _WriteTool(), "other": _ReadTool()}
    monkeypatch.setattr(sandbox, "_live_tools", lambda: (tools, executor))
    monkeypatch.setattr(brain, "seats", lambda _c: [brain.Seat("ollama", "m", "local")])
    fake = _ToolBrain()
    monkeypatch.setattr(brain, "_instantiate", lambda _seat: fake)
    made: list[str] = []
    real_mkdtemp = sandbox.tempfile.mkdtemp

    def mkdtemp(**kwargs: Any) -> str:
        made.append(real_mkdtemp(dir=tmp_path, **kwargs))
        return made[-1]

    monkeypatch.setattr(sandbox.tempfile, "mkdtemp", mkdtemp)
    run = await sandbox.run(
        None,
        skill_name="CI status",
        skill_body="1. Read the wiki page about CI.\n2. Email the team.",
        request="how is CI doing",
        tools=("wiki-recall", "send_email"),
    )
    assert run.error == "" and run.seat == "ollama"
    assert "CI is green" in run.answer
    assert [(s.name, s.ok, s.held) for s in run.steps] == [
        ("wiki-recall", True, False),
        ("send_email", False, True),
    ]
    assert [name for name, _ in executor.calls] == ["wiki-recall"]
    # Only the named tools were offered, and the working folder is gone.
    offered = {t["name"] for t in fake.requests[0].tools or ()} if fake.requests[0].tools else set()
    assert "other" not in offered
    assert made and not _exists(made[0])


async def test_no_executor_or_no_seat_defers_and_bills_nothing(monkeypatch) -> None:
    monkeypatch.setattr(sandbox, "_live_tools", lambda: ({}, None))
    with pytest.raises(brain.BackgroundDeferred):
        await sandbox.run(None, skill_name="x", skill_body="1. x", request="x", tools=())
    monkeypatch.setattr(sandbox, "_live_tools", lambda: ({}, _Executor()))
    monkeypatch.setattr(brain, "seats", lambda _c: [])
    with pytest.raises(brain.BackgroundDeferred):
        await sandbox.run(None, skill_name="x", skill_body="1. x", request="x", tools=())


async def test_a_subscription_seat_runs_a_scoped_read_only_cli_turn(monkeypatch) -> None:
    from dodaios.agent_chat import runner_cli
    from dodaios.core import task_agent, tool_read_only

    tools = {"wiki-recall": _ReadTool(), "send_email": _WriteTool()}
    monkeypatch.setattr(sandbox, "_live_tools", lambda: (tools, _Executor()))
    monkeypatch.setattr(brain, "seats", lambda _c: [brain.Seat("codex", None, "subscription")])

    async def seat(_provider: str) -> tuple[str, str]:
        return ("openai-codex", "codex-cli")

    monkeypatch.setattr(task_agent, "subscription_seat_off_loop", seat)
    seen: dict[str, Any] = {}

    async def fake_turn(handle: Any, prompt: str, runner: str, *, identity: bool = False) -> None:
        sid = handle.session.session_id
        seen.update(
            runner=runner,
            identity=identity,
            gateway_only=handle.gateway_only,
            mode=handle.session.permission_mode,
            cwd_exists=_exists(handle.session.cwd),
            cwd=handle.session.cwd,
            scope=task_agent.scope_for(sid),
            read_only=tool_read_only.chat_is_read_only(sid),
            prompt=prompt,
        )
        assert await handle.request_approval("send_email", "x", {}, "y") == "deny"
        emit = handle.emit
        refused = "Plan mode permits reads only"
        for kind, payload in (
            ("tool_call", {"call_id": "1", "name": "mcp__dodaios__wiki-recall"}),
            ("tool_result", {"call_id": "1", "output": "ok", "is_error": False}),
            ("tool_call", {"call_id": "2", "name": "mcp__dodaios__send_email"}),
            ("tool_result", {"call_id": "2", "output": refused, "is_error": True}),
        ):
            await emit({"kind": kind, "payload": payload})
        await emit({"kind": "assistant_text", "payload": {"text": "CI is green on main."}})
        await emit({"kind": "turn_finished", "payload": {"status": "done"}})

    monkeypatch.setattr(runner_cli, "run_cli_turn", fake_turn)
    run = await sandbox.run(
        None,
        skill_name="CI status",
        skill_body="1. Read the wiki.\n2. Email the team.",
        request="how is CI doing",
        tools=("wiki-recall", "send_email"),
    )
    assert seen["runner"] == "codex-cli" and seen["identity"] and seen["gateway_only"]
    assert seen["mode"] == "read-only" and seen["cwd_exists"] and seen["read_only"]
    assert seen["scope"].names == frozenset({"wiki-recall", "send_email"})
    assert "how is CI doing" in seen["prompt"] and "dry run" in seen["prompt"]
    assert not _exists(seen["cwd"])  # the temporary folder is gone
    sid_scopes = [s for s in task_agent._scopes if s.startswith("skill-proof-")]
    assert sid_scopes == []  # scope released
    assert run.error == "" and run.answer == "CI is green on main."
    assert [(s.name, s.ok, s.held) for s in run.steps] == [
        ("wiki-recall", True, False),
        ("send_email", False, True),
    ]


def test_cli_tool_names_map_back_to_registered_names() -> None:
    allowed = ("mcp:github/list_runs", "wiki-recall")
    assert sandbox.registered_name("mcp__dodaios__wiki_recall", allowed) == "wiki-recall"
    assert sandbox.registered_name("wiki-recall", allowed) == "wiki-recall"
    assert sandbox.registered_name("mcp__dodaios__mcp_github_list_runs", allowed) == (
        "mcp:github/list_runs"
    )
    assert sandbox.registered_name("Bash", allowed) == "Bash"


def test_the_daily_budget_covers_the_replays() -> None:
    assert builders.SKILL_REPLAYS <= builders.DAILY_MODEL_CALLS
    assert asyncio.iscoroutinefunction(sandbox.run)


def test_a_codex_task_turn_with_identity_gives_each_flag_once() -> None:
    """Live 2026-10-20: identity + gateway_only passed --ignore-user-config twice; codex refused."""
    from dodaios.agent_chat.runner_cli import isolate_task_tools

    argv = ["codex", "exec", "--json", "--ignore-user-config", "--ignore-rules"]
    argv += ["--disable", "browser_use", "--disable", "plugins"]
    isolate_task_tools(argv, "codex-cli")
    assert argv.count("--ignore-user-config") == 1 and argv.count("--ignore-rules") == 1
    features = [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "--disable"]
    assert len(features) == len(set(features)) and "shell_tool" in features
    claude = ["claude", "-p"]
    isolate_task_tools(claude, "claude-cli")
    assert claude[-3:] == ["--tools", "", "--strict-mcp-config"]
    with pytest.raises(Exception, match="cannot isolate"):
        isolate_task_tools([], "agy-cli")
