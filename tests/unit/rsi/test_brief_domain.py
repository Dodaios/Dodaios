"""The brief domain: the replay up to the brief, the served kit, the shared budget, the wordings.

No real model is asked: the replay runs a stand-in CLI (``fake_claude.py``), and
the night runs on a fake world whose briefs follow a rule.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from dodaios.agent_chat import dodaios_harness
from dodaios.learners.lines import LineLearner
from dodaios.learners.tuner import Trial
from dodaios.rsi import lines, params
from dodaios.rsi import night as nights
from dodaios.rsi import overlay as overlays
from dodaios.rsi.bench import brief_replay, lead_replay, replay_tools, run
from dodaios.rsi.bench.brief_replay import BriefWorld, Template, template_of
from dodaios.rsi.bench.first_move import Expect, Move
from dodaios.rsi.bench.lead_cli import ClaudeReplay
from dodaios.rsi.bench.lead_replay import FirstMoveWorld, LeadInput, Platform
from dodaios.rsi.bench.model import Domain, Source, Task, task_id
from dodaios.rsi.budget import Budget
from dodaios.rsi.gate.decide import LIVE
from dodaios.self_change import Draft, State, Surface

WORDING = "lead.brief_line"
FIRST = "lead.first_line"
REPO = "github.com/acme/app"
FAKE_CLI = Path(__file__).with_name("fake_claude.py")


def _template(system: str = "SYSTEM PROMPT") -> Template:
    tail = (
        dodaios_harness.message_lines("x", continuation=False, brief=dodaios_harness.BRIEF_LINE)
        + "\nRespond in this language: en"
    )
    note = (
        "<jarvis_turn_settings>\nReasoning effort for this turn: high.\n</jarvis_turn_settings>\n\n"
    )
    found = template_of(system, note + "An earlier request." + tail)
    assert isinstance(found, Template)
    return found


def _task(i: int = 0, *, repo: str = REPO, files: Mapping[str, int] | None = None) -> Task:
    return Task(
        id=task_id(Domain.BRIEF, Source.MADE, f"brief-{i}"),
        domain=Domain.BRIEF,
        source=Source.MADE,
        group=f"{repo}#{i}",
        payload={"repo": repo, "base": f"base{i:04d}", "request": f"Please fix thing {i:04d}."},
        check={"files": dict(files or {f"app/mod{i}.py": 40, f"tests/test_mod{i}.py": 10})},
    )


class Reader:
    """A stand-in for one commit of a repository: it only counts that it was let go of."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


def _world(
    driver: Any, tmp_path: Path, *, budget: Budget | None = None, clones: dict | None = None
) -> BriefWorld:
    return BriefWorld(
        platform=Platform("claude-cli", "opus", tools="t1"),
        driver=driver,
        budget=budget or Budget(10_000),
        template=_template(),
        clones=clones if clones is not None else {REPO: tmp_path},
        commit=lambda repo, base: Reader(tmp_path),  # type: ignore[arg-type, return-value]
        kit=lambda task, files, args: f"KIT for {args.get('task')}",
        look=lambda files, tool, args: (f"{tool} found nothing", False),
    )


# ------------------------------------------------------ the input and the template


def test_a_recorded_turn_gives_the_frame_a_request_is_put_into() -> None:
    recorded = (
        "<since_your_last_turn>\nYou: earlier\n</since_your_last_turn>\n\n"
        "<jarvis_turn_settings>\nhigh\n</jarvis_turn_settings>\n\n"
        "Find me a train"
        + dodaios_harness.message_lines("Find me a train", continuation=True, brief="BRIEF")
    )
    found = template_of("SYSTEM", recorded)
    assert isinstance(found, Template)
    assert found.head.startswith("<jarvis_turn_settings>") and "earlier" not in found.head
    assert found.tail.startswith(dodaios_harness.EFFORT_LINE)
    assert template_of("", recorded) == "the recorded turn has no system prompt"
    assert (
        template_of("SYSTEM", "/project list") == "the recorded message carries no standing lines"
    )
    # Put back into it, the request gets the lines a new request gets today.
    made = brief_replay.lead_input(found, "Fix the flicker")
    assert isinstance(made, LeadInput) and made.system == "SYSTEM"
    assert made.message.startswith(found.head + "Fix the flicker" + dodaios_harness.EFFORT_LINE)
    assert dodaios_harness.FIRST_LINE in made.message  # a new request, not a continuation


def test_the_wording_in_effect_is_the_one_the_message_carries() -> None:
    template = _template()
    with overlays.active(overlays.Overlay(params={WORDING: 1})):
        made = brief_replay.lead_input(template, "Fix it")
        live = dodaios_harness.lead_message("Fix it", continuation=False)
    assert isinstance(made, LeadInput)
    assert dodaios_harness.BRIEF_LINE_SHORT_LOOK in made.message
    assert dodaios_harness.BRIEF_LINE not in made.message
    assert dodaios_harness.BRIEF_LINE_SHORT_LOOK in live  # the live lead reads the same setting
    shipped = dodaios_harness.lead_message("Fix it", continuation=False)
    assert dodaios_harness.BRIEF_LINE in shipped


def test_every_wording_keeps_what_no_domain_measures() -> None:
    texts = dodaios_harness.BRIEF_LINE_WORDINGS
    assert texts[0] == dodaios_harness.BRIEF_LINE and len(texts) == 3
    rest = "in English unless their brief wishes name another language"
    for text in texts:
        tail = text[text.index(rest) :]
        assert tail == texts[0][texts[0].index(rest) :]  # word for word
        assert "no payments" in text and "agent-briefs-set" in text
    assert all(a not in b for a in texts for b in texts if a is not b)
    assert "options.prepare" not in texts[2]
    param = params.INDEX.by_name(WORDING)
    assert (param.default, param.low, param.high) == (0, 0, len(texts) - 1)
    assert param.domains == ("brief",)


def test_a_recorded_message_takes_another_wording_and_a_message_without_one_has_no_place() -> None:
    shipped = dodaios_harness.lead_message(
        "Fix it", continuation=False, brief=dodaios_harness.brief_line
    )
    lean = lines.apply(shipped, {WORDING: 2})
    assert lean is not None and dodaios_harness.BRIEF_LINE_NO_LOOK in lean
    assert lines.apply(lean, {WORDING: 0}) == shipped
    bare = {FIRST: False}  # only the wording is asked about here
    assert lines.apply("/project list", {**bare, WORDING: 0}) == "/project list"  # no change
    assert lines.apply("/project list", {**bare, WORDING: 1}) is None


# --------------------------------------------------- the replay serves the kit once


def _driver(tmp_path: Path, mode: str) -> tuple[ClaudeReplay, Path]:
    out = tmp_path / "out"
    out.mkdir()
    tools = tmp_path / "tools.json"
    tools.write_text(json.dumps([{"name": "delegate", "description": "hand work"}]))
    driver = ClaudeReplay(
        tools_file=tools,
        scratch=tmp_path / "scratch",
        env=dict(os.environ),
        argv_prefix=[sys.executable, str(FAKE_CLI), mode, str(out)],
        timeout_s=30.0,
    )
    return driver, out


def test_the_replay_answers_the_kit_request_and_takes_the_brief_after_it(tmp_path: Path) -> None:
    driver, out = _driver(tmp_path, "brief")
    asked: list[tuple[str, dict[str, Any]]] = []

    def serve(tool: str, args: Mapping[str, Any]) -> str | None:
        asked.append((tool, dict(args)))
        return "THE KIT" if replay_tools.served(tool, args) else None

    started = time.monotonic()
    move = driver(LeadInput("S", "Fix the flicker"), Platform("claude-cli", "opus"), serve)
    assert time.monotonic() - started < 15  # stopped at the brief, not after the CLI's 20 s
    assert move.tool == "delegate" and "dodaios/x.py" in move.args["task"]
    assert asked == [
        (
            "delegate",
            {"target": "coding_agent", "task": "Fix the flicker", "options": {"prepare": True}},
        )
    ]
    answer = json.loads((out / "answer.json").read_text())["response"]["response"]
    assert answer["behavior"] == "allow" and answer["updatedInput"]["options"]["prepare"]
    assert (out / "kit.txt").read_text() == "THE KIT"
    time.sleep(1.0)
    assert not (out / "ran-on.txt").exists()
    # A replay that answers calls reads the repository as it was, never the disk as it is:
    # the CLI's own file tools are gone, the app's own (answered at the commit) stay.
    argv = json.loads((out / "argv.json").read_text())
    removed = set(argv[argv.index("--disallowedTools") + 1].split(","))
    assert {"Read", "Grep", "Glob", "Edit", "Write", "Bash"} <= removed
    assert argv[argv.index("--permission-mode") + 1] == "default"
    # Its tool server runs the code of this replay, not an installed copy of the app.
    config = json.loads((out / "mcp.json").read_text())  # kept by the stand-in
    import dodaios

    code = str(Path(dodaios.__file__).resolve().parent.parent)
    assert config["mcpServers"]["dodaios"]["env"]["PYTHONPATH"].startswith(code)


def test_only_a_call_of_the_apps_own_server_is_ever_answered(tmp_path: Path) -> None:
    from dodaios.rsi.bench.lead_cli import _Served  # noqa: PLC2701

    served = _Served(lambda tool, args: "ANSWER", tmp_path)
    assert served.answer("mcp__dodaios__Grep", {"pattern": "x"})
    assert not served.answer("Grep", {"pattern": "x"})  # the CLI's own tool: the CLI runs it
    assert not served.answer("mcp__dodaios__run_shell", {"command": "dir"})  # does more than read


def test_without_a_server_answer_the_kit_request_is_the_move_and_refused(tmp_path: Path) -> None:
    driver, out = _driver(tmp_path, "brief")
    move = driver(LeadInput("S", "Fix the flicker"), Platform("claude-cli", "opus"))
    assert move.tool == "delegate" and move.args["options"] == {"prepare": True}
    assert not (out / "kit.txt").exists()


def test_the_tool_server_answers_the_kit_request_alone_and_only_from_the_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    import mcp.types as types

    answers = tmp_path / "answers"
    answers.mkdir()
    kit_call = {"target": "coding_agent", "task": "x", "options": {"prepare": True}}
    (answers / f"{replay_tools.call_key('delegate', kit_call)}.json").write_text(
        json.dumps({"text": "THE KIT"})
    )
    server = replay_tools.build_server([{"name": "delegate"}, {"name": "run_shell"}], answers)
    monkeypatch.setattr(replay_tools, "ANSWER_WAIT_S", 0.3)

    def call(name: str, arguments: dict[str, Any]) -> Any:
        request = types.CallToolRequest(
            params=types.CallToolRequestParams(name=name, arguments=arguments)
        )
        return asyncio.run(server.request_handlers[types.CallToolRequest](request)).root

    found = call("delegate", kit_call)
    assert not found.isError and found.content[0].text == "THE KIT"
    for name, arguments in [
        ("delegate", {"target": "coding_agent", "task": "the brief"}),  # a hand-off
        ("delegate", {"target": "agent:Scout", "task": "x", "options": {"prepare": True}}),
        ("delegate", {**kit_call, "task": "unanswered"}),  # no answer was written for it
        ("run_shell", {"command": "dir"}),
    ]:
        refused = call(name, arguments)
        assert refused.isError and replay_tools.NOT_RUN in refused.content[0].text


# ------------------------------------------------------------------ the runner


def test_the_runner_scores_the_brief_the_lead_wrote_after_the_kit(tmp_path: Path) -> None:
    driver, out = _driver(tmp_path, "brief")
    task = _task(1, files={"dodaios/x.py": 30, "dodaios/y.py": 10})
    budget = Budget(10)
    found = brief_replay.run(task, _world(driver, tmp_path, budget=budget))
    assert not found.void, found.detail
    assert found.score == pytest.approx(0.8571, abs=1e-4)  # found 0.75 of the change, none astray
    assert found.detail.startswith("after the kit; found 0.75")
    assert found.calls == 2 and budget.calls == 2  # the run, and the answered kit request
    assert found.seat == "claude-cli:opus-20991231"
    stdin = (out / "stdin.jsonl").read_text().splitlines()
    message = json.loads(stdin[1])["message"]["content"]
    said = "Please fix thing 0001." + brief_replay.REPOSITORY_LINE.format(
        repo=REPO, folder=tmp_path
    )
    assert said in message and dodaios_harness.BRIEF_LINE in message
    assert (out / "kit.txt").read_text() == "KIT for Fix the flicker"  # built for the lead's words
    # The cost is the message and the brief: the line rides in one, the agent reads the other.
    sys.path.insert(0, str(FAKE_CLI.parent))
    from fake_claude import BRIEF

    assert found.tokens == round(len(message) / 4) + round(len(BRIEF) / 4)


class Briefs:
    """A stand-in lead for the runner: what it does is set per test."""

    def __init__(
        self, move: Move, *, ask_kit: bool = True, looks: tuple[dict[str, Any], ...] = ()
    ) -> None:
        self.move = move
        self.ask_kit = ask_kit
        self.looks = looks
        self.calls: list[LeadInput] = []
        self.kits: list[Any] = []
        self.answers: list[Any] = []

    def __call__(self, lead: LeadInput, platform: Platform, serve: Any = None) -> Move:
        self.calls.append(lead)
        for look in self.looks:
            found = serve("Grep", look) if serve is not None else None
            self.answers.append(found)
            if found is None:
                return Move(tool="Grep", args=look, model="opus")  # not answered: the move
        if self.ask_kit and serve is not None:
            self.kits.append(
                serve(
                    "delegate",
                    {"target": "coding_agent", "task": "t", "options": {"prepare": True}},
                )
            )
        return self.move


def test_a_task_whose_repository_or_commit_is_missing_is_void_and_costs_nothing(
    tmp_path: Path,
) -> None:
    lead = Briefs(Move(tool="delegate", args={"task": "app/mod0.py"}, model="opus"))
    budget = Budget(10)
    world = _world(lead, tmp_path, budget=budget, clones={})
    found = brief_replay.run(_task(), world)
    assert found.void == f"the repository {REPO} is not on this machine"
    world = _world(lead, tmp_path, budget=budget)
    world.commit = lambda repo, base: "the commit the work started from is not in the local clone"
    assert brief_replay.run(_task(), world).void.startswith("the commit")
    pictured = Task(
        id="brief-p",
        domain=Domain.BRIEF,
        source=Source.MADE,
        group="g",
        payload={**_task().payload, "attached": [".jarvis/drops/shot.png"]},
        check=_task().check,
    )
    assert brief_replay.run(pictured, world).void == "the request showed a picture"
    assert lead.calls == [] and budget.calls == 0  # nothing was asked, nothing spent
    # In a whole measurement such a task is a void result, not a failure of the run.
    results = run.measure([_task()], LIVE, {brief_replay.WORLD: _world(lead, tmp_path, clones={})})
    assert results[0].void.endswith("not on this machine") and not results[0].counts


def test_what_ends_a_replay_without_a_brief(tmp_path: Path) -> None:
    def run_with(move: Move) -> Any:
        return brief_replay.run(_task(), _world(Briefs(move), tmp_path))

    text = run_with(Move(text="Which file do you mean?", model="opus"))
    assert text.score == 0 and not text.void and text.detail == "no brief: it answered in text"
    # Not handing over must never look cheaper than handing over.
    assert text.tokens >= brief_replay.NO_BRIEF_TOKENS
    asked = run_with(Move(tool="society_ask_user", args={}, model="opus"))
    assert asked.score == 0 and not asked.void
    looked = run_with(Move(tool="run_shell", args={"command": "dir"}, model="opus"))
    assert looked.void == "used a tool a replay cannot answer" and "run_shell" in looked.detail
    again = run_with(
        Move(
            tool="delegate",
            args={"target": "coding_agent", "task": "t", "options": {"prepare": True}},
            model="opus",
        )
    )
    assert again.void == "it asked for the brief kit a second time"
    other = run_with(Move(tool="delegate", args={"task": "app/mod0.py"}, model="sonnet"))
    assert other.void == "the model changed"
    failed = run_with(Move(error="the CLI ended before a first move (exit 1)"))
    assert failed.void == "could not run"


def test_the_leads_own_look_into_the_repository_is_answered_there(tmp_path: Path) -> None:
    found = brief_replay.run(
        _task(),
        _world(
            Briefs(
                Move(tool="delegate", args={"task": "Start in app/mod0.py"}, model="opus"),
                ask_kit=False,
                looks=({"pattern": "flicker"}, {"pattern": "scroll"}),
            ),
            tmp_path,
        ),
    )
    assert not found.void and found.calls == 3
    assert found.detail.startswith("without the kit, after 2 look-ups")
    # A look outside the repository is not answered: the run is void, not a failure.
    world = _world(Briefs(Move(tool="delegate", args={}), looks=({"pattern": "x"},)), tmp_path)
    world.look = lambda files, tool, args: None
    outside = brief_replay.run(_task(), world)
    assert outside.void == "it read outside the repository"
    # A tool that does more than read the code ends the run, void.
    shell = brief_replay.run(
        _task(), _world(Briefs(Move(tool="run_shell", args={}, model="opus")), tmp_path)
    )
    assert shell.void == "used a tool a replay cannot answer" and "run_shell" in shell.detail


def test_a_replay_on_the_cli_answers_the_leads_search_at_the_commit(
    tmp_path: Path, clone: tuple[Path, str, str]
) -> None:
    from dodaios.rsi.bench import brief_world
    from dodaios.rsi.bench.at_commit import CommitFiles

    driver, out = _driver(tmp_path, "look")
    source, base, _ = clone
    (out / "clone.txt").write_text(str(source), encoding="utf-8")
    world = _world(driver, tmp_path, clones={REPO: source})
    world.commit = lambda repo, at: CommitFiles(source, base)
    world.look = brief_world.look_answer
    found = brief_replay.run(_task(files={"app/flicker.py": 10}), world)
    assert found.score == 0.0 and found.detail.startswith("without the kit, after 1 look-up")
    answer = json.loads((out / "answer.json").read_text())["response"]["response"]
    assert answer["behavior"] == "allow"
    seen = (out / "look.txt").read_text(encoding="utf-8")
    # Read where the work started: the old line, not today's commit or the person's edit.
    assert "OLD = 'flicker'" in seen and "NEW" not in seen and "THEIRS" not in seen


# --------------------------------------------------------- the shared budget


def test_the_shared_budget_stops_both_domains(tmp_path: Path) -> None:
    budget = Budget(4)
    lead = Briefs(Move(tool="delegate", args={"task": "Work in app/mod0.py"}, model="opus"))
    brief_world = _world(lead, tmp_path, budget=budget)
    first_calls: list[LeadInput] = []

    def first_driver(lead_input: LeadInput, platform: Platform) -> Move:
        first_calls.append(lead_input)
        return Move(tool="delegate", args={}, opening="On it.", model="opus")

    first_world = FirstMoveWorld(
        platform=Platform("claude-cli", "opus", tools="t1"),
        driver=first_driver,
        budget=budget,
        seed_input=lambda utterance: LeadInput("S", utterance),
    )
    move_task = Task(
        id="first_move-1",
        domain=Domain.FIRST_MOVE,
        source=Source.MADE,
        group="m",
        payload={"utterance": "Let Scout compare note apps"},
        check={"expect": Expect(tools=("delegate",)).to_json(), "opening": True},
    )
    worlds = {brief_replay.WORLD: brief_world, lead_replay.WORLD: first_world}
    done = brief_replay.run(_task(0), brief_world)  # the run and its kit: 2 of 4
    assert not done.void and done.calls == 2 and budget.calls == 2
    assert not lead_replay.run(move_task, first_world).void  # 3 of 4
    # The last call starts a brief replay; its kit request finds the night spent.
    cut = brief_replay.run(_task(1), brief_world)
    assert cut.void.startswith("budget:") and budget.calls == 4 and budget.stopped
    for found in run.measure([_task(2), move_task], LIVE, worlds):
        assert found.void.startswith("budget:"), found
    assert len(lead.calls) == 2 and len(first_calls) == 1  # nothing ran past the cap
    # A brief replay never asks for more than what is left: a first move may still fit.
    other = Budget(3)
    assert other.take(2) == "" and other.take(2) and not other.stopped and other.take() == ""


# ------------------------------------------------- what is learnable, and the gate


def test_only_the_lines_a_domain_can_see_are_offered_there() -> None:
    assert lines.alternatives(WORDING, 0) == [1, 2]
    assert lines.alternatives(WORDING, 1) == [2]  # back to the shipped wording is an undo
    assert lines.alternatives(FIRST, True) == [False] and lines.alternatives(FIRST, False) == []
    tried: list[dict[str, Any]] = []

    def try_values(values: Mapping[str, Any]) -> Trial:
        tried.append(dict(values))
        return Trial(0.5, 100.0, 12)

    LineLearner().propose({WORDING: 0}, try_values)
    assert tried == [{}, {WORDING: 1}, {WORDING: 2}]
    tried.clear()
    LineLearner().propose({FIRST: True}, try_values)
    assert tried == [{}, {FIRST: False}]


def many_tasks(n: int = 600) -> list[Task]:
    return [_task(i) for i in range(n)]


class FakeLead:
    """Writes briefs by rule: the wording in the message decides what the brief holds.

    ``harmful``: wording 1 drops the file from the brief (a worse brief).
    Otherwise wording 1 writes the same brief, shorter. Wording 2 never looks
    the files up and names none.
    """

    def __init__(self, *, harmful: bool = False) -> None:
        self.harmful = harmful
        self.calls: list[tuple[str, int]] = []
        self.kits = 0

    def __call__(self, lead: LeadInput, platform: Platform, serve: Any = None) -> Move:
        number = lead.message.split("Please fix thing ", 1)[1][:4]
        wording = next(
            i for i, text in enumerate(dodaios_harness.BRIEF_LINE_WORDINGS) if text in lead.message
        )
        self.calls.append((number, wording))
        assert dodaios_harness.FIRST_LINE in lead.message  # never switched by this domain
        if wording != 2 and serve is not None:
            serve(
                "delegate", {"target": "coding_agent", "task": number, "options": {"prepare": True}}
            )
            self.kits += 1
        names_file = wording == 0 or (wording == 1 and not self.harmful)
        place = f" Start in app/mod{int(number)}.py." if names_file else ""
        filler = " Keep it working." * (40 if wording == 0 else 10)
        return Move(
            tool="delegate", args={"task": f"Fix thing {number}.{place}{filler}"}, model="opus"
        )


@pytest.fixture
def brief_box(tmp_path: Path):
    made: list[nights.Sandbox] = []

    def build(lead: FakeLead, *, cap: int = 100_000) -> tuple[nights.Sandbox, BriefWorld]:
        world = _world(lead, tmp_path, budget=Budget(cap))
        box = nights.sandbox(
            tmp_path / "box",
            tasks=many_tasks(),
            worlds={brief_replay.WORLD: world},
            sources=(Source.MADE,),
            learners=(nights.TUNER, nights.LINES),
        )
        made.append(box)
        return box, world

    yield build
    for box in made:
        box.close()


def test_a_harmless_change_that_shortens_briefs_is_let_in_as_good_and_cheaper(brief_box) -> None:
    lead = FakeLead()
    box, _ = brief_box(lead)
    report = box.night.run()
    (proposed,) = report.proposed
    assert proposed["target"] == WORDING and proposed["value"] == 1
    assert proposed["learner"] == nights.LINES
    (decided,) = report.decided
    assert decided["outcome"] == "admitted", decided
    reason = decided["evidence"]["reason"]
    assert "as good on" in reason and "cheaper" in reason
    assert params.get(WORDING) == 1
    (change,) = box.registry.learned()
    assert change.state is State.TRIAL and change.author == nights.LINES
    assert len(lead.calls) == len(set(lead.calls))  # nothing paid for twice
    assert {wording for _, wording in lead.calls} <= {0, 1, 2}
    box.registry.rollback(change.id, "owner")
    assert params.get(WORDING) == 0


def test_a_harmful_change_to_the_briefs_is_turned_down(brief_box) -> None:
    lead = FakeLead(harmful=True)
    box, _ = brief_box(lead)
    assert not box.night.run().proposed  # the learner sees the harm on practice
    text = params.text_for(params.INDEX.by_name(WORDING), 1)
    box.registry.propose(Draft(Surface.PARAMETER, WORDING, text, author=nights.LINES))
    (decided,) = box.night.run().decided
    assert decided["outcome"] == "declined"
    assert "worse" in decided["evidence"]["reason"]
    assert params.get(WORDING) == 0


def test_the_arm_holds_the_wording_and_the_input_it_was_measured_on(tmp_path: Path) -> None:
    world = _world(Briefs(Move(text="x")), tmp_path)
    worlds = {brief_replay.WORLD: world}
    live = run.arm_of(LIVE, domain=Domain.BRIEF, worlds=worlds)
    worded = run.arm_of(overlays.Overlay(params={WORDING: 1}), domain=Domain.BRIEF, worlds=worlds)
    first = run.arm_of(overlays.Overlay(params={FIRST: False}), domain=Domain.BRIEF, worlds=worlds)
    assert len({live.id, worded.id, first.id}) == 3  # every line in the message is in the arm
    world.platform = Platform("claude-cli", "opus", tools="t1", base="another input")
    assert run.arm_of(LIVE, domain=Domain.BRIEF, worlds=worlds).id != live.id
    # The first_move arm holds the brief wording too: it is in every replayed message.
    first_world = FirstMoveWorld(Platform("claude-cli", "opus"), lambda *a: Move(), Budget(1))
    on = {lead_replay.WORLD: first_world}
    assert (
        run.arm_of(LIVE, domain=Domain.FIRST_MOVE, worlds=on).id
        != run.arm_of(overlays.Overlay(params={WORDING: 2}), domain=Domain.FIRST_MOVE, worlds=on).id
    )


# ----------------------------------------------------- the night's brief world


def _git(folder: Path, *args: str) -> str:
    import subprocess

    done = subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True, check=True)
    return done.stdout.strip()


@pytest.fixture
def clone(tmp_path: Path) -> tuple[Path, str, str]:
    """The person's clone: two commits, an origin, and an uncommitted change of theirs."""
    folder = tmp_path / "person"
    folder.mkdir()
    _git(folder, "init", "-q", "-b", "main")
    _git(folder, "config", "user.email", "t@example.com")
    _git(folder, "config", "user.name", "T")
    _git(folder, "remote", "add", "origin", "git@github.com:Acme/App.git")
    (folder / "app").mkdir()
    (folder / "app" / "flicker.py").write_text("OLD = 'flicker'\n", encoding="utf-8")
    (folder / "AGENTS.md").write_text("Before you push, run `pytest -q`.\n", encoding="utf-8")
    _git(folder, "add", ".")
    _git(folder, "commit", "-q", "-m", "first")
    base = _git(folder, "rev-parse", "HEAD")
    (folder / "app" / "flicker.py").write_text("NEW = 'flicker fixed'\n", encoding="utf-8")
    (folder / "app" / "added.py").write_text("ADDED = 'flicker'\n", encoding="utf-8")
    _git(folder, "add", ".")
    _git(folder, "commit", "-q", "-m", "second")
    head = _git(folder, "rev-parse", "HEAD")
    # The person's own uncommitted edit.
    (folder / "app" / "flicker.py").write_text("THEIRS = 'flicker mine'\n", encoding="utf-8")
    return folder, base, head


def _state(source: Path) -> tuple[str, ...]:
    return (
        _git(source, "status", "--porcelain"),
        _git(source, "rev-parse", "HEAD"),
        _git(source, "worktree", "list"),
        _git(source, "branch", "--list"),
    )


def _files(root: Path) -> dict[str, tuple[int, int]]:
    """Every file below ``root`` (its .git included): path -> (size, modified ns)."""
    return {
        str(path.relative_to(root)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def test_the_repository_is_read_at_the_commit_and_nothing_is_written(
    tmp_path: Path, clone: tuple[Path, str, str]
) -> None:
    from dodaios.rsi.bench import brief_world

    source, base, head = clone
    before = _state(source)  # git status itself may refresh the clone's index
    written = _files(source)
    clones = brief_world._clones([source, tmp_path / "gone"])  # noqa: SLF001
    assert clones == {"github.com/acme/app": source}
    at_base = brief_world.commit_files(clones, "github.com/acme/app", base)
    assert not isinstance(at_base, str)
    assert at_base.read("app/flicker.py") == "OLD = 'flicker'\n"
    assert not at_base.is_file("app/added.py")  # the merged work is not there yet
    assert at_base.is_dir("app") and sorted(at_base.names("")) == ["AGENTS.md", "app"]
    assert at_base.files_with("FLICKER", float("inf")) == ["app/flicker.py"]
    at_head = brief_world.commit_files(clones, "github.com/acme/app", head)
    assert not isinstance(at_head, str) and at_head.is_file("app/added.py")
    missing = brief_world.commit_files(clones, "github.com/acme/app", "0" * 40)
    assert isinstance(missing, str) and missing.startswith("the commit")
    other = brief_world.commit_files(clones, "github.com/acme/other", base)
    assert isinstance(other, str) and other.endswith("not on this machine")
    at_base.close()
    at_head.close()
    # The person's clone is as it was, to the byte: nothing checked out, nothing written.
    assert _files(source) == written
    assert _state(source) == before


def test_a_comparison_writes_no_file(tmp_path: Path, clone: tuple[Path, str, str]) -> None:
    """Both arms of a comparison on tasks at two commits: kit and look-ups run, nothing is written.

    The earlier version moved one scratch checkout per task: on 34 tasks of this
    repository's own history that wrote 52,871 to 92,678 files per comparison.
    """
    from dodaios.rsi.bench import brief_world

    source, base, head = clone
    clones = {REPO: source}
    home = tmp_path / "data"
    home.mkdir()

    class Looks:
        calls: list[str] = []

        def __call__(self, lead: LeadInput, platform: Platform, serve: Any = None) -> Move:
            assert serve is not None
            looked = serve("Grep", {"pattern": "flicker", "path": str(source)})
            kit = serve(
                "delegate",
                {"target": "coding_agent", "task": "the flicker", "options": {"prepare": True}},
            )
            self.calls.append(f"{looked[0] if looked else ''}|{kit}")
            return Move(tool="delegate", args={"task": "Fix app/flicker.py"}, model="opus")

    lead = Looks()
    world = BriefWorld(
        platform=Platform("claude-cli", "opus", tools="t1"),
        driver=lead,
        budget=Budget(10_000),
        template=_template(),
        clones=clones,
        commit=lambda repo, at: brief_world.commit_files(clones, repo, at),
        kit=brief_world.kit_answer,
        look=brief_world.look_answer,
    )
    tasks = [
        Task(
            id=task_id(Domain.BRIEF, Source.MADE, f"c{i}"),
            domain=Domain.BRIEF,
            source=Source.MADE,
            group=f"g{i}",
            payload={"repo": REPO, "base": (base, head)[i % 2], "request": f"Fix the flicker {i}."},
            check={"files": {"app/flicker.py": 10}},
        )
        for i in range(4)
    ]
    before, folders = _files(source), sorted(p.name for p in tmp_path.iterdir())
    worlds = {brief_replay.WORLD: world}
    for arm in (LIVE, overlays.Overlay(params={WORDING: 1})):
        results = run.measure(tasks, arm, worlds)
        assert all(r.counts and r.score == 1.0 for r in results), results
    assert len(lead.calls) == 8
    # The kit and the look-up were answered at each task's own commit.
    assert sum("OLD = 'flicker'" in c for c in lead.calls) == 4
    assert sum("NEW = 'flicker fixed'" in c for c in lead.calls) == 4
    assert all("THEIRS" not in c for c in lead.calls)
    assert all('"state": "prepared"' in c for c in lead.calls)
    assert _files(source) == before  # not one file written in the person's clone
    assert sorted(p.name for p in tmp_path.iterdir()) == folders  # and no scratch folder
    assert not list(home.rglob("*"))


def test_an_earlier_versions_scratch_checkouts_are_removed(tmp_path: Path) -> None:
    from dodaios.rsi.bench import brief_world

    old = tmp_path / "rsi" / "brief" / "a273315d3773" / "app"
    old.mkdir(parents=True)
    (old / "x.py").write_text("left behind\n", encoding="utf-8")
    brief_world._remove_old_scratch(tmp_path)  # noqa: SLF001
    assert not (tmp_path / "rsi" / "brief").exists() and (tmp_path / "rsi").is_dir()


class Turns:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def turns(self, *, limit: int = 100) -> list[Any]:
        return sorted(self.rows, key=lambda r: -r.seq)[:limit]

    def turn(self, seq: int) -> Any:
        return next((r for r in self.rows if r.seq == seq), None)


class Meta:
    readonly = False

    def __init__(self) -> None:
        self.meta: dict[str, Any] = {}

    def get_meta(self, key: str) -> dict[str, Any]:
        return dict(self.meta.get(key) or {})

    def set_meta(self, key: str, value: dict[str, Any]) -> None:
        self.meta[key] = value


def _row(seq: int, *, model: str = "opus", message: str | None = None) -> Any:
    from types import SimpleNamespace

    lined = "Hi" + dodaios_harness.message_lines("Hi", continuation=False, brief="B")
    return SimpleNamespace(
        seq=seq,
        cli="claude-cli",
        model=model,
        system=f"SYSTEM {seq}",
        message=lined if message is None else message,
    )


def test_the_input_a_request_is_put_into_stays_pinned_while_its_turn_exists() -> None:
    from dodaios.rsi.bench import brief_world

    bench = Meta()
    turns = Turns([_row(1), _row(2), _row(3, message="/project list"), _row(4, model="sonnet")])
    found = brief_world.pinned_template(bench, turns, cli="claude-cli", model="opus")
    assert not isinstance(found, str)
    assert found[1] == 2 and found[0].system == "SYSTEM 2"  # newest on this model with lines
    turns.rows.append(_row(5))
    again = brief_world.pinned_template(bench, turns, cli="claude-cli", model="opus")
    assert not isinstance(again, str) and again[1] == 2  # a newer turn does not move it
    turns.rows = [r for r in turns.rows if r.seq != 2]
    moved = brief_world.pinned_template(bench, turns, cli="claude-cli", model="opus")
    assert not isinstance(moved, str) and moved[1] == 5  # its turn is gone: the newest now
    assert bench.get_meta(brief_world.META_KEY)["seq"] == 5
    none = brief_world.pinned_template(Meta(), Turns([]), cli="claude-cli", model="opus")
    assert isinstance(none, str)


def test_the_kit_is_the_apps_answer_at_the_commit_and_writes_nothing(
    clone: tuple[Path, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from dodaios.briefs import glossary
    from dodaios.rsi.bench import brief_world

    source, base, _ = clone
    files = brief_world.commit_files({"github.com/acme/app": source}, "github.com/acme/app", base)
    assert not isinstance(files, str)
    counted: list[bool] = []
    real = glossary.lookup

    def lookup(folder: Any, words: str, *, count: bool = True) -> Any:
        counted.append(count)
        return real(folder, words, count=False)

    monkeypatch.setattr(glossary, "lookup", lookup)
    call = {"target": "coding_agent", "task": "Stop the flicker", "options": {"prepare": True}}
    found = json.loads(brief_world.kit_answer(_task(), files, call))
    files.close()
    assert found["state"] == "prepared" and found["detail"]["nothing_sent"] is True
    kit = found["detail"]["brief_kit"]
    assert "without options.prepare" in found["next_step"]
    # Read at the commit: the file of then, and the project's own check of then.
    assert [p["path"] for p in kit["starting_points"]] == ["app/flicker.py"]
    assert "pytest -q" in kit["project_checks"]
    assert counted == [False]  # the glossary was read without raising a use counter
