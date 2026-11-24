"""The first_move domain: its check, the replay, the budget, own tasks, and the line learner.

No real model is asked: the replay runs a stand-in CLI (``fake_claude.py``), and
the night runs on a fake world whose answers follow a rule.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat import dodaios_harness
from dodaios.learners.lines import LineLearner
from dodaios.learners.tuner import Trial, Tuner
from dodaios.rsi import lines, params
from dodaios.rsi import night as nights
from dodaios.rsi import overlay as overlays
from dodaios.rsi.bench import first_move, lead_replay, run, seedsuite
from dodaios.rsi.bench.first_move import Expect, Move
from dodaios.rsi.bench.lead_cli import ClaudeReplay
from dodaios.rsi.bench.lead_replay import FirstMoveWorld, LeadInput, Platform
from dodaios.rsi.bench.model import Domain, Result, Role, Source, Split, Task, task_id
from dodaios.rsi.bench.own import lead as own_lead
from dodaios.rsi.bench.store import BenchStore
from dodaios.rsi.budget import BUDGET_SHARE, FIRST_MOVE_CALLS, Budget
from dodaios.rsi.gate.alpha import AlphaLedger
from dodaios.rsi.gate.decide import LIVE
from dodaios.self_change import Draft, State, Surface

SWITCH = "lead.first_line"
FAKE_CLI = Path(__file__).with_name("fake_claude.py")

# ------------------------------------------------------------------ the check


def _check(tools: tuple[str, ...], **more: Any) -> dict[str, Any]:
    expect = Expect(tools=tools, args=more.pop("args", {}))
    return {"expect": expect.to_json(), "opening": expect.expects_tool, **more}


def test_a_right_move_scores_one_and_a_missing_line_before_the_tool_half() -> None:
    check = _check(("delegate",), args={"target": "agent:Scout"})
    right = Move(tool="delegate", args={"target": "agent:Scout"}, opening="On it.")
    assert first_move.score(check, right, message="x" * 400).score == 1.0
    silent = Move(tool="delegate", args={"target": "agent:Scout"})
    assert first_move.score(check, silent, message="x" * 400).score == 0.5
    wrong = Move(tool="memory", opening="On it.")
    assert first_move.score(check, wrong, message="x").score == 0.0
    args = Move(tool="delegate", args={"target": "agent:Mailbox"}, opening="On it.")
    assert first_move.score(check, args, message="x").score == 0.0
    failed = first_move.score(check, Move(error="boom"), message="x")
    assert failed.void and failed.score == 0.0
    # The cost is the message the lead got, in tokens.
    assert first_move.score(check, right, message="x" * 400).tokens == 100


def test_a_text_answer_is_right_where_no_tool_is_and_needs_no_opening() -> None:
    check = _check(("none",))
    assert first_move.score(check, Move(text="Paris."), message="x").score == 1.0
    assert first_move.score(check, Move(tool="search_web"), message="x").score == 0.0


def test_the_app_server_prefix_is_not_part_of_the_tool() -> None:
    assert first_move.tool_name("mcp__dodaios__delegate") == "delegate"
    assert first_move.tool_name("dodaios__memory-search") == "memory-search"
    assert first_move.tool_name("Read") == "Read"


def test_the_seed_suite_carries_the_routing_cases_with_languages_grouped() -> None:
    tasks = seedsuite.first_move_tasks()
    assert len(tasks) == 226
    by_group: dict[str, set[str]] = {}
    for task in tasks:
        by_group.setdefault(task.group, set()).add(task.split.value)
    assert all(len(found) == 1 for found in by_group.values())  # a request and its translation
    en = next(
        t
        for t in tasks
        if t.id == task_id(Domain.FIRST_MOVE, Source.SEED, "delegate-scout-research-en")
    )
    de = next(
        t
        for t in tasks
        if t.id == task_id(Domain.FIRST_MOVE, Source.SEED, "delegate-scout-research-de")
    )
    assert en.group == de.group
    assert all(t.check["role"] == "gain" for t in tasks)


# ------------------------------------------------------------- the standing lines


def test_only_lines_a_benchmark_can_see_are_learnable() -> None:
    assert set(lines.LEARNABLE) == {SWITCH, "lead.brief_line"}
    switches = {p.name for p in params.CATALOG if isinstance(p.default, bool)}
    assert switches == {SWITCH}  # no switch without a measured line
    for line in lines.LINES:
        assert line.text(), line.name  # every listed line exists in the harness
        assert line.why, line.name
        if line.param:
            assert params.INDEX.by_name(line.param).domains == (line.domain,)
    names = {line.name for line in lines.LINES}
    assert {"REPLY_SHAPE_LINE", "BRIEF_LINE", "EFFORT_LINE", "QUESTION_CARD_LINE"} <= names
    learnable = {"FIRST_LINE", "BRIEF_LINE"}
    assert not any(lines.LEARNABLE.get(f"lead.{n.lower()}") for n in names - learnable)


def test_the_switch_takes_the_line_out_of_a_message_and_puts_it_back_in_its_place() -> None:
    def message() -> str:
        return dodaios_harness.lead_message(
            "Find me a train", continuation=False, brief=lambda: dodaios_harness.BRIEF_LINE
        )

    shipped = message()
    assert dodaios_harness.FIRST_LINE in shipped
    with overlays.active(overlays.Overlay(params={SWITCH: False})):
        dropped = message()
    assert dodaios_harness.FIRST_LINE not in dropped
    assert lines.apply(shipped, {SWITCH: False}) == dropped
    assert lines.apply(dropped, {SWITCH: True}) == shipped
    assert lines.apply("/project list", {SWITCH: True}) is None  # no place for it


def test_the_line_learner_offers_only_measurable_lines() -> None:
    seen: list[dict[str, Any]] = []

    def try_values(values: Mapping[str, Any]) -> Trial:
        seen.append(dict(values))
        return Trial(0.9, 90.0 if values else 100.0, 30)

    # The night hands the learner the first_move domain's lines only: never the brief's.
    current = {SWITCH: True, "lead.reply_shape_line": True}
    found = LineLearner().propose(current, try_values)
    assert found is not None and found.name == SWITCH and found.value is False
    assert seen == [{}, {SWITCH: False}]  # nothing else was ever tried


def test_the_line_learner_proposes_no_drop_that_loses_on_practice_or_saves_too_little() -> None:
    def table(score: float, cost: float) -> Callable[[Mapping[str, Any]], Trial]:
        return lambda values: Trial(score if values else 0.9, cost if values else 100.0, 30)

    assert LineLearner().propose({SWITCH: True}, table(0.7, 90.0)) is None  # worse
    assert LineLearner().propose({SWITCH: True}, table(0.9, 97.0)) is None  # 3 % cheaper
    assert LineLearner().propose({SWITCH: False}, table(0.9, 90.0)) is None  # already off
    skip = {(SWITCH, False)}
    assert LineLearner().propose({SWITCH: True}, table(0.9, 90.0), skip=skip) is None


def test_the_tuner_leaves_the_switches_to_the_line_learner() -> None:
    tried: list[dict[str, Any]] = []

    def try_values(values: Mapping[str, Any]) -> Trial:
        tried.append(dict(values))
        return Trial(0.9, 50.0 if values else 100.0, 30)

    assert Tuner(params.INDEX).propose("first_move", params.values(), try_values) is None
    assert tried == [{}]


# ------------------------------------------------------------------- the budget


def test_the_budget_stops_at_its_cap() -> None:
    budget = Budget(3)
    assert [budget.take() for _ in range(3)] == ["", "", ""]
    assert "3 model calls" in budget.take()
    assert budget.calls == 3 and budget.left == 0


def test_the_budget_never_starts_above_80_percent_and_stops_at_20_percent_of_a_window() -> None:
    full = Budget(40, usage=lambda: {"session": 81.0})
    assert "80 % full" in full.take() and full.calls == 0
    window = {"session": 30.0, "weekly": 10.0}
    budget = Budget(40, usage=lambda: dict(window))
    assert budget.take() == ""
    window["session"] = 30.0 + BUDGET_SHARE * 100 - 1
    assert budget.take() == ""
    window["session"] = 30.0 + BUDGET_SHARE * 100
    assert "20%" in budget.take()
    assert budget.take()  # stopped stays stopped for the night
    assert Budget(2, usage=lambda: None).take() == ""  # unreadable: the cap alone


def test_the_budget_stops_when_the_person_comes_back() -> None:
    here = {"away": True}
    budget = Budget(40, idle=lambda: here["away"])
    assert budget.take() == ""
    here["away"] = False
    assert budget.take() == "the person is back"


def test_the_cap_per_night_is_forty() -> None:
    assert FIRST_MOVE_CALLS == 40


# --------------------------------------------------------- the replay on a CLI


def _driver(tmp_path: Path, mode: str, timeout_s: float = 30.0) -> tuple[ClaudeReplay, Path]:
    out = tmp_path / "out"
    out.mkdir()
    tools = tmp_path / "tools.json"
    tools.write_text(json.dumps([{"name": "delegate", "description": "hand work"}]))
    driver = ClaudeReplay(
        tools_file=tools,
        scratch=tmp_path / "scratch",
        env=dict(__import__("os").environ),
        argv_prefix=[sys.executable, str(FAKE_CLI), mode, str(out)],
        timeout_s=timeout_s,
    )
    return driver, out


def test_the_replay_takes_the_first_move_and_stops_the_cli(tmp_path: Path) -> None:
    driver, out = _driver(tmp_path, "tool")
    started = time.monotonic()
    move = driver(
        LeadInput("SYSTEM PROMPT", "Let Scout compare note apps"), Platform("claude-cli", "opus")
    )
    assert time.monotonic() - started < 15  # stopped at the call, not after the CLI's 20 s
    assert move.tool == "delegate"  # the schema load before it is not the move
    assert move.args == {"target": "agent:Scout", "task": "compare note apps"}
    assert move.opening.startswith("On it")
    assert move.model == "opus-20991231" and not move.error
    # Every permission prompt is refused.
    answer = json.loads((out / "answer.json").read_text())
    assert answer["response"]["response"]["behavior"] == "deny"
    # The lead's flags, the replay's own tool server, nothing kept on disk.
    argv = json.loads((out / "argv.json").read_text())
    for flag in ("--strict-mcp-config", "--no-session-persistence", "--disallowedTools"):
        assert flag in argv
    # Whatever the person's settings allow, a replay can change no file.
    denied = argv[argv.index("--disallowedTools") + 1].split(",")
    assert {"Edit", "Write", "MultiEdit", "NotebookEdit", "Bash"} <= set(denied)
    assert argv.count("--disallowedTools") == 1
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert "bypassPermissions" not in argv
    assert argv[argv.index("--model") + 1] == "opus"
    assert "PowerShell" in denied and "Read" not in denied  # a first move keeps its reading tools
    stdin = (out / "stdin.jsonl").read_text().splitlines()
    assert json.loads(stdin[1])["message"]["content"] == "Let Scout compare note apps"
    time.sleep(1.0)
    assert not (out / "ran-on.txt").exists()
    # The run's own folder is removed; every replay works in the same empty folder.
    assert [p.name for p in (tmp_path / "scratch").iterdir()] == ["cwd"]
    assert not list((tmp_path / "scratch" / "cwd").iterdir())


def test_the_replay_offers_the_lead_tools_through_a_server_that_runs_none(tmp_path: Path) -> None:
    driver, out = _driver(tmp_path, "tool")
    seen: dict[str, Any] = {}
    real = driver._argv  # noqa: SLF001

    def keep(
        platform: Platform, work: Path, system_file: Path, answers: Path | None = None
    ) -> list[str]:
        argv = real(platform, work, system_file, answers)
        seen["config"] = json.loads((work / "mcp.json").read_text())
        seen["system"] = system_file.read_text()
        return argv

    driver._argv = keep  # type: ignore[method-assign]  # noqa: SLF001
    driver(LeadInput("SYSTEM PROMPT", "hi"), Platform("claude-cli", "opus"))
    server = seen["config"]["mcpServers"]["dodaios"]
    assert server["args"][-2:] == ["dodaios.rsi.bench.replay_tools", str(tmp_path / "tools.json")]
    assert seen["system"] == "SYSTEM PROMPT"


def test_the_replay_tool_server_lists_the_tools_and_answers_every_call_with_not_run(
    tmp_path: Path,
) -> None:
    import asyncio

    import mcp.types as types

    from dodaios.rsi.bench import replay_tools

    rows = [
        {"name": "delegate", "description": "hand work", "inputSchema": {"type": "object"}},
        {"name": "society_ask_user", "description": "ask", "meta": {"anthropic/alwaysLoad": True}},
    ]
    path = tmp_path / "tools.json"
    path.write_text(json.dumps(rows))
    server = replay_tools.build_server(replay_tools.load(path))
    listed = asyncio.run(server.request_handlers[types.ListToolsRequest](types.ListToolsRequest()))
    names = [tool.name for tool in listed.root.tools]
    assert names == ["delegate", "society_ask_user"]
    request = types.CallToolRequest(
        params=types.CallToolRequestParams(name="delegate", arguments={})
    )
    called = asyncio.run(server.request_handlers[types.CallToolRequest](request))
    assert called.root.isError and replay_tools.NOT_RUN in called.root.content[0].text


def test_a_text_answer_is_a_move_without_a_tool(tmp_path: Path) -> None:
    driver, _ = _driver(tmp_path, "text")
    move = driver(LeadInput("S", "What is 2+2?"), Platform("claude-cli", "opus"))
    assert move.tool is None and move.text.startswith("On it") and not move.error


# -------------------------------------------------- the runner, the arm, the pair


def _world(driver: lead_replay.Driver, *, cap: int = 10_000, model: str = "opus") -> FirstMoveWorld:
    def seed_input(utterance: str) -> LeadInput:
        message = dodaios_harness.lead_message(
            utterance, continuation=False, brief=lambda: dodaios_harness.BRIEF_LINE
        )
        return LeadInput("SYSTEM", message)

    return FirstMoveWorld(
        platform=Platform("claude-cli", model, tools="t1"),
        driver=driver,
        budget=Budget(cap),
        seed_input=seed_input,
    )


def _args(expect: Expect) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, want in expect.args.items():
        value = want[0] if isinstance(want, list) else want
        out["task" if key == "*" else key] = value
    return out


def many_tasks(n: int = 600) -> list[Task]:
    """Requests whose right move is known by rule: a quarter can show a gain, the rest guard."""
    out: list[Task] = []
    for i in range(n):
        role = Role.GAIN if i % 4 == 0 else Role.GUARD
        out.append(
            Task(
                id=task_id(Domain.FIRST_MOVE, Source.MADE, f"made-{i}"),
                domain=Domain.FIRST_MOVE,
                source=Source.MADE,
                group=f"made-group-{i}",
                payload={"utterance": f"Please handle request number {i:04d}."},
                check={**_check(("delegate",)), "role": role.value},
            )
        )
    return out


class FakeLead:
    """Answers every request with its expected move.

    ``harmful``: the line before the tool comes only while ``FIRST_LINE`` is in
    the message (dropping the line hurts). Otherwise it always comes.
    """

    def __init__(
        self, tasks: list[Task] | None = None, *, harmful: bool = False, model: str = ""
    ) -> None:
        self.harmful = harmful
        self.model = model
        self.expect = {
            t.payload["utterance"]: Expect.from_json(t.check["expect"])
            for t in (tasks if tasks is not None else seedsuite.first_move_tasks())
        }
        self.calls: list[tuple[str, bool]] = []

    def __call__(self, lead: LeadInput, platform: Platform) -> Move:
        utterance = next(u for u in self.expect if lead.message.startswith(u))
        has_line = dodaios_harness.FIRST_LINE in lead.message
        self.calls.append((utterance, has_line))
        expect = self.expect[utterance]
        model = self.model or platform.model
        if not expect.expects_tool:
            return Move(text="An answer.", model=model)
        opening = "On it." if has_line or not self.harmful else ""
        return Move(tool=expect.tools[0], args=_args(expect), opening=opening, model=model)


@pytest.fixture
def seed_box(tmp_path: Path):
    made: list[nights.Sandbox] = []

    def build(
        lead: FakeLead, *, cap: int = 10_000, tasks: list[Task] | None = None
    ) -> tuple[nights.Sandbox, FirstMoveWorld]:
        world = _world(lead, cap=cap)
        box = nights.sandbox(
            tmp_path,
            tasks=tasks if tasks is not None else seedsuite.first_move_tasks(),
            worlds={lead_replay.WORLD: world},
            sources=(Source.SEED,) if tasks is None else (Source.MADE,),
            learners=(nights.TUNER, nights.LINES),
        )
        made.append(box)
        return box, world

    yield build
    for box in made:
        box.close()


def test_an_unchanged_arm_is_never_paid_for_twice(seed_box) -> None:
    lead = FakeLead()
    box, _ = seed_box(lead)
    gate = box.night.gate
    candidate = overlays.Overlay(params={SWITCH: False})
    first = gate.compare(Domain.FIRST_MOVE, Split.GUARD, LIVE, candidate, seed="s", alpha=0.05)
    paid = len(lead.calls)
    assert paid == 2 * first.interval.n
    again = gate.compare(Domain.FIRST_MOVE, Split.GUARD, LIVE, candidate, seed="s", alpha=0.05)
    assert len(lead.calls) == paid  # every result came from bench.db
    assert again.interval.mean == first.interval.mean


def test_a_harmless_cheaper_drop_is_let_in_and_its_learner_proposed_it(seed_box) -> None:
    tasks = many_tasks()
    lead = FakeLead(tasks)
    box, _ = seed_box(lead, tasks=tasks)
    report = box.night.run()
    (proposed,) = report.proposed
    assert proposed["target"] == SWITCH and proposed["value"] is False
    assert proposed["learner"] == nights.LINES
    (decided,) = report.decided
    assert decided["outcome"] == "admitted", decided
    assert "as good on" in decided["evidence"]["reason"]
    assert "cheaper" in decided["evidence"]["reason"]
    assert params.get(SWITCH) is False
    (change,) = box.registry.learned()
    assert change.state is State.TRIAL and change.author == nights.LINES
    # No task was replayed twice under the same arm.
    assert len(lead.calls) == len(set(lead.calls))
    # The next night keeps it on the guard tasks and measures the advantage on the
    # sealed tasks whose right answer is known.
    later = box.night.run()
    assert [row["outcome"] for row in later.settled] == ["kept"]
    (point,) = later.measured
    assert point["domain"] == "first_move" and point["now_tokens"] < point["factory_tokens"]
    sealed_gain = box.night.gate.tasks(Domain.FIRST_MOVE, Split.SEALED, Role.GAIN)
    assert point["n"] == len(sealed_gain)
    # Undo puts the line back, like every self-change.
    box.registry.rollback(change.id, "owner")
    assert params.get(SWITCH) is True


def test_a_harmful_drop_is_turned_down_by_the_gate(seed_box) -> None:
    lead = FakeLead(harmful=True)
    box, _ = seed_box(lead)
    # The learner sees the harm on practice and proposes nothing...
    assert not box.night.run().proposed
    # ...and a drop that reaches the gate anyway is declined there.
    text = params.text_for(params.INDEX.by_name(SWITCH), False)
    box.registry.propose(Draft(Surface.PARAMETER, SWITCH, text, author=nights.LINES))
    (decided,) = box.night.run().decided
    assert decided["outcome"] == "declined"
    assert "worse" in decided["evidence"]["reason"]
    assert params.get(SWITCH) is True


def test_a_small_suite_cannot_prove_a_drop_as_good(seed_box) -> None:
    lead = FakeLead()
    box, _ = seed_box(lead)
    (decided,) = box.night.run().decided
    # 53 tasks bound a difference of zero only to about 10 points either way:
    # "as good" needs about 120. The drop is turned down, never let in on hope.
    assert decided["outcome"] == "declined"
    assert decided["evidence"]["reason"] == "no clear difference on 53 tasks"
    assert params.get(SWITCH) is True


def test_the_night_cap_holds_and_the_comparison_carries_on_the_next_night(seed_box) -> None:
    lead = FakeLead()
    box, world = seed_box(lead, cap=FIRST_MOVE_CALLS)
    ledger = AlphaLedger(box.bench)
    first = box.night.run()
    assert len(lead.calls) == FIRST_MOVE_CALLS
    assert first.calls["first_move"]["calls"] == FIRST_MOVE_CALLS
    assert "spent" in first.calls["first_move"]["stopped"]
    assert first.proposed and first.decided[0]["outcome"] == "waiting"
    assert "next night" in first.decided[0]["evidence"]["reason"]
    assert ledger.state(Domain.FIRST_MOVE, Split.SELECT)["decisions"] == 0  # no budget spent
    outcome, nights_run = "waiting", 1
    while outcome == "waiting" and nights_run < 8:
        world.budget = Budget(FIRST_MOVE_CALLS)
        report = box.night.run()
        nights_run += 1
        assert world.budget.calls <= FIRST_MOVE_CALLS
        assert not report.proposed  # one candidate at a time while every look costs calls
        outcome = report.decided[0]["outcome"]
    # 12 practice tasks twice and 53 select tasks twice: 130 calls, four nights of 40.
    assert outcome == "declined" and nights_run == 4
    assert len(lead.calls) == 130 == len(set(lead.calls))  # nothing was paid for twice
    assert ledger.state(Domain.FIRST_MOVE, Split.SELECT)["decisions"] == 1


def test_a_night_without_a_seat_to_replay_on_spends_nothing(seed_box) -> None:
    lead = FakeLead()
    box, _ = seed_box(lead)
    text = params.text_for(params.INDEX.by_name(SWITCH), False)
    box.registry.propose(Draft(Surface.PARAMETER, SWITCH, text, author=nights.LINES))
    # Tonight the lead is not on its plan: no replay world is built.
    box.night._worlds = box.night.gate._worlds = lambda: {}  # noqa: SLF001
    report = box.night.run()
    assert lead.calls == [] and not report.proposed
    assert report.decided[0]["outcome"] == "waiting"
    ledger = AlphaLedger(box.bench)
    assert ledger.state(Domain.FIRST_MOVE, Split.SELECT)["decisions"] == 0
    assert box.bench.results(report.decided[0]["evidence"]["baseline"]) == []


def test_a_gain_on_what_the_person_only_accepted_is_no_gain() -> None:
    from dodaios.rsi.gate.evidence import Verdict
    from dodaios.rsi.gate.rules import Compared, admit_verdict
    from dodaios.rsi.sequential import Interval

    whole = Compared("first_move", Interval(0.2, 0.1, 0.3, 200), 100.0, 100.0)
    few = Compared("first_move", Interval(0.2, -0.3, 0.6, 12), 100.0, 100.0)
    found = admit_verdict(whole, alpha=0.05, baseline="b", split="select", gain=few)
    assert found.verdict is Verdict.REJECT  # the rise rests on accepted turns only
    known = Compared("first_move", Interval(0.2, 0.05, 0.35, 40), 100.0, 100.0)
    found = admit_verdict(whole, alpha=0.05, baseline="b", split="select", gain=known)
    assert found.verdict is Verdict.ACCEPT and "right answer is known" in found.reason
    # Without accepted turns nothing changes: the whole is what can show a gain.
    assert admit_verdict(whole, alpha=0.05, baseline="b", split="select").accepted


def test_a_pair_whose_model_changed_does_not_count(seed_box) -> None:
    lead = FakeLead()
    box, world = seed_box(lead)
    tasks = box.night.gate.tasks(Domain.FIRST_MOVE, Split.GUARD)[:5]
    baseline = run.measure(tasks, LIVE, {lead_replay.WORLD: world})
    lead.model = "another-model"
    candidate = run.measure(
        tasks, overlays.Overlay(params={SWITCH: False}), {lead_replay.WORLD: world}
    )
    assert all(r.void == "the model changed" for r in candidate)
    assert run.pair(baseline, candidate).n == 0
    # Two counted results from different models are no pair either.
    a = Result("t", "d", "arm1", 1.0, seat="claude-cli:m1")
    b = Result("t", "d", "arm2", 1.0, seat="claude-cli:m2")
    assert run.pair([a], [b]).n == 0
    assert run.pair([a], [Result("t", "d", "arm2", 0.0, seat="claude-cli:m1")]).n == 1


def test_the_arm_names_what_answers_and_the_switch_and_nothing_else_learned(seed_box) -> None:
    box, world = seed_box(FakeLead())
    worlds = {lead_replay.WORLD: world}
    live = run.arm_of(LIVE, changes=["c1"], domain=Domain.FIRST_MOVE, worlds=worlds)
    factory = run.arm_of(overlays.FACTORY, domain=Domain.FIRST_MOVE, worlds=worlds)
    assert live.id == factory.id  # nothing learned touches the lead: one arm
    assert live.model == "opus" and live.cli == "claude-cli"
    dropped = run.arm_of(
        overlays.Overlay(params={SWITCH: False}), domain=Domain.FIRST_MOVE, worlds=worlds
    )
    assert dropped.id != live.id
    world.platform = Platform("claude-cli", "sonnet", tools="t1")
    assert run.arm_of(LIVE, domain=Domain.FIRST_MOVE, worlds=worlds).id != live.id


def test_nothing_is_spent_on_the_advantage_while_nothing_learned_touches_the_lead(seed_box) -> None:
    lead = FakeLead()
    box, _ = seed_box(lead)
    assert box.night._advantage(Domain.FIRST_MOVE, 0) is None  # noqa: SLF001
    assert lead.calls == []


def test_a_task_the_budget_does_not_cover_asks_nothing(seed_box) -> None:
    lead = FakeLead()
    box, world = seed_box(lead, cap=0)
    tasks = box.night.gate.tasks(Domain.FIRST_MOVE, Split.GUARD)[:3]
    found = run.measure(tasks, LIVE, {lead_replay.WORLD: world})
    assert all(r.void.startswith("budget:") for r in found)
    assert lead.calls == []


# ------------------------------------------------------- a recorded lead turn


def _row(seq: int, turn: str, *, tool: str = "", kind: str = "tool", **more: Any) -> Any:
    base = {
        "seq": seq,
        "session_id": "s1",
        "turn_id": turn,
        "cli": "claude-cli",
        "model": "opus",
        "effort": "high",
        "first_kind": kind,
        "first_tool": tool,
        "first_args": {},
        "continuation": False,
        "ts_ms": 0,
        "system": "SYSTEM",
        "message": "",
    }
    base.update(more)
    return SimpleNamespace(**base)


def _chat(turn: str, text: str, ts_ms: int, status: str = "done") -> Any:
    return SimpleNamespace(session_id="s1", turn_id=turn, text=text, ts_ms=ts_ms, status=status)


MIN = 60 * 1000
NOW = 10 * 24 * 3600 * 1000


def test_a_recorded_turn_replays_with_the_switch_applied(tmp_path: Path) -> None:
    message = dodaios_harness.lead_message(
        "Ask Scout for the report", continuation=False, brief=lambda: dodaios_harness.BRIEF_LINE
    )
    rows = {7: _row(7, "a", tool="mcp__dodaios__delegate", message=message)}
    seen: list[str] = []

    def driver(lead: LeadInput, platform: Platform) -> Move:
        seen.append(lead.message)
        return Move(tool="delegate", opening="On it.", model="opus")

    world = FirstMoveWorld(
        platform=Platform("claude-cli", "opus"), driver=driver, budget=Budget(10), recorded=rows.get
    )
    task = Task(
        id="t",
        domain=Domain.FIRST_MOVE,
        source=Source.MINED,
        group="g",
        payload={"turn": {"seq": 7}},
        check=_check(("delegate",)),
    )
    with overlays.active(overlays.Overlay(params={SWITCH: False})):
        assert lead_replay.run(task, world).score == 1.0
    assert seen == [lines.apply(message, {SWITCH: False})]
    gone = Task("t2", Domain.FIRST_MOVE, Source.MINED, "g", {"turn": {"seq": 8}}, task.check)
    assert lead_replay.run(gone, world).void == "the recorded turn is gone"
    other = FirstMoveWorld(
        platform=Platform("codex-cli", "gpt"), driver=driver, budget=Budget(10), recorded=rows.get
    )
    assert lead_replay.run(task, other).void.startswith("recorded on claude-cli")


# ------------------------------------------------ own tasks from the lead's turns


def test_only_a_corrected_then_accepted_turn_becomes_a_task_that_can_show_a_gain() -> None:
    rows = [
        _row(1, "a", tool="mcp__dodaios__message_agent"),
        _row(2, "b", tool="mcp__dodaios__delegate"),
        _row(3, "c", kind="text"),
    ]
    chat = [
        _chat("a", "Ask Scout for the quarterly report numbers", 0),
        _chat("b", "No, hand it to Scout as a job: the quarterly report numbers", 5 * MIN),
        _chat("c", "What is the capital of Peru?", 90 * MIN),
    ]
    mined = own_lead.mine(rows, chat, now_ms=NOW)
    by_turn = {t.payload["turn"]["turn"]: t for t in mined.tasks}
    assert set(by_turn) == {"a", "b", "c"}
    gain = by_turn["a"]
    assert gain.check["role"] == Role.GAIN.value
    assert gain.check["expect"]["tools"] == ["delegate"] and gain.check["was"] == "message_agent"
    assert by_turn["b"].check["role"] == by_turn["c"].check["role"] == Role.GUARD.value
    assert by_turn["c"].check["expect"]["tools"] == ["none"]
    assert gain.group == by_turn["b"].group != by_turn["c"].group  # one piece of work, one split
    stored = json.dumps([[dict(t.payload), dict(t.check)] for t in mined.tasks])
    assert "Scout" not in stored and "quarterly" not in stored  # no words of the person's


def test_a_correction_that_kept_the_first_move_gives_no_gain_task() -> None:
    rows = [
        _row(1, "a", tool="mcp__dodaios__delegate"),
        _row(2, "b", tool="mcp__dodaios__delegate"),
    ]
    chat = [
        _chat("a", "Ask Scout to research flights to Lisbon in March", 0),
        _chat("b", "No, I meant flights to Porto in March, ask Scout", 2 * MIN),
    ]
    mined = own_lead.mine(rows, chat, now_ms=NOW)
    assert [t.check["role"] for t in mined.tasks] == ["guard"]
    assert mined.skipped["corrected, but the first move stayed the same"] == 1


def test_nothing_is_learned_from_a_turn_that_was_undone_unfinished_too_new_or_carried_on() -> None:
    rows = [
        _row(1, "a", tool="mcp__dodaios__gmail"),
        _row(3, "c", tool="mcp__dodaios__navigate", continuation=True),
        _row(4, "d", tool="mcp__dodaios__navigate"),
    ]
    chat = [
        _chat("a", "Send the invoice to Anna", 0),
        _chat("b", "Undo that, take it back", 3 * MIN),
        _chat("c", "carry on", 60 * MIN),
        _chat("d", "Open the settings", NOW - MIN),
    ]
    mined = own_lead.mine(rows, chat, now_ms=NOW)
    assert mined.tasks == []
    assert set(mined.skipped) == {
        "undone, or it did not finish",
        "carried a running task on",
        "too new to know whether it was corrected",
    }


def test_a_schema_load_names_its_tool_only_when_the_record_says_which() -> None:
    picked = _row(1, "a", tool="ToolSearch", first_args={"query": "select:mcp__dodaios__node"})
    vague = _row(2, "b", tool="ToolSearch", first_args={"query": "calendar tools"})
    chat = [_chat("a", "Make me a page", 0), _chat("b", "What is on today?", 60 * MIN)]
    mined = own_lead.mine([picked, vague], chat, now_ms=NOW)
    assert [t.check["expect"]["tools"] for t in mined.tasks] == [["node"]]
    assert mined.skipped == {"the record does not say which tool it called": 1}


def test_a_task_whose_recorded_turn_is_gone_is_retired(tmp_path: Path) -> None:
    bench = BenchStore(tmp_path / "bench.db")
    rows = [_row(1, "a", kind="text"), _row(2, "b", kind="text")]
    chat = [_chat("a", "What is 2+2?", 0), _chat("b", "And 3+3?", 60 * MIN)]
    first = own_lead.take_in(bench, rows, chat, now_ms=NOW)
    assert first["lead_turns"] == 2 and first["lead_retired"] == 0
    later = own_lead.take_in(bench, rows[1:], chat[1:], now_ms=NOW)
    assert later["lead_retired"] == 1
    assert len(bench.tasks(Domain.FIRST_MOVE)) == 1
    bench.close()


def test_the_record_skips_a_schema_load_and_keeps_the_call_after_it() -> None:
    from dodaios.rsi import lead_turns

    written: list[tuple[str, str]] = []
    recorder = lead_turns.TurnRecorder("s1", "t1")
    recorder._write = lambda kind, tool="", args=None: written.append((kind, tool))  # type: ignore[method-assign]  # noqa: SLF001
    recorder.planned(SimpleNamespace(), resume=None)
    recorder.observe({"kind": "tool_call", "payload": {"name": "ToolSearch", "input": {}}})
    recorder.observe({"kind": "tool_call", "payload": {"name": "mcp__dodaios__node", "input": {}}})
    assert written == [("tool", "mcp__dodaios__node")]
