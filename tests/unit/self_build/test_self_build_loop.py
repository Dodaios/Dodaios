"""The self-building loop end to end: observe, decide, build, prove, trial, keep or archive."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.core.bus import EventBus
from dodaios.core.config import SelfBuildConfig
from dodaios.core.events import TaskCompleted
from dodaios.self_build import Kind, Outcome, SelfBuild, State, brain, decide, judge, loop, policy
from dodaios.self_build.builders import ROUTINE_SHADOW_SYSTEM, Env, voice_pattern
from dodaios.self_build.ledger import now_ms
from dodaios.self_build.miner import Miner, Observation, same_need, stems
from dodaios.self_build.signals import SignalStore
from dodaios.skills.schema import SkillInvoked

DAY = 86_400_000


# ------------------------------------------------------------------ fixtures and fakes


ZONE = "UTC"


@pytest.fixture(autouse=True)
def _person_zone(monkeypatch):
    """The person's UI reported UTC: habits and routines use that wall clock."""
    from dodaios.tasks import context

    monkeypatch.setattr(context, "_reported_ui_timezone", ZONE)


def _today() -> date:
    return datetime.now(UTC).date()


def _ms(day: date, hour: int, minute: int = 0) -> int:
    return int(datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC).timestamp() * 1000)


def _days_ago(n: int, hour: int, minute: int = 0) -> int:
    return _ms(_today() - timedelta(days=n), hour, minute)


def _mondays() -> list[date]:
    today = _today()
    last = today - timedelta(days=today.weekday() + 7)
    return [last - timedelta(days=14), last - timedelta(days=7), last]


class FakeScheduler:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.specs: dict[str, Any] = {}
        self.paused: set[str] = set()

    async def schedule(self, spec: Any) -> str:
        task_id = f"task-{len(self.rows) + 1}"
        self.specs[task_id] = spec
        self.rows[task_id] = {
            "id": task_id,
            "title": spec.title,
            "state": "scheduled",
            "spec_json": spec.model_dump_json(),
        }
        return task_id

    async def pause(self, task_id: str) -> None:
        self.paused.add(task_id)

    async def resume(self, task_id: str) -> None:
        self.paused.discard(task_id)

    async def cancel_task(self, task_id: str) -> None:
        self.rows[task_id]["state"] = "cancelled"

    # the task store side
    async def list(self, limit: int = 1000) -> list[dict[str, Any]]:
        return list(self.rows.values())[:limit]

    async def delete(self, task_id: str) -> None:
        self.rows.pop(task_id, None)


class FakeBrain:
    """Answers the decide prompt from a script and every shadow run with text."""

    def __init__(self) -> None:
        self.answers: list[dict[str, Any]] = []
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, system: str, prompt: str, _max_tokens: int) -> str:
        self.calls.append((system, prompt))
        if system == decide.SYSTEM_PROMPT:
            allowed = json.loads(prompt)["allowed"]
            for answer in self.answers:
                if answer.get("build") in allowed:
                    return json.dumps(answer)
            return json.dumps({"build": "nothing", "why": "not scripted"})
        if system == ROUTINE_SHADOW_SYSTEM:
            return "Sales summary for last week: revenue and open deals, ready to read."
        return "Here is what I found for that request, step by step."

    @property
    def decide_calls(self) -> int:
        return sum(1 for system, _ in self.calls if system == decide.SYSTEM_PROMPT)


@pytest.fixture
def fake_brain():
    fake = FakeBrain()
    brain.set_override(fake, provider="sub-seat")
    yield fake
    brain.set_override(None)


@pytest.fixture
async def world(tmp_path: Path, fake_brain: FakeBrain):
    from dodaios.memory.learning.notebook import JarvisNotebook
    from dodaios.skills.registry import SkillRegistry
    from dodaios.society.events import Tier
    from dodaios.society.roster import Roster
    from dodaios.society.store import SocietyStore

    settings: dict[str, Any] = {
        "silent_days": 0,
        "memory": "trial",
        "skill": "trial",
        "routine": "trial",
        "agent": "suggest",
    }
    config = SimpleNamespace(self_build=SelfBuildConfig(**settings))
    bus = EventBus()
    service = SelfBuild(tmp_path, lambda: config, publish=bus.publish)
    service.bind_loop(asyncio.get_running_loop())

    skill_state: dict[str, str] = {}
    (tmp_path / "skills").mkdir()
    registry = SkillRegistry(tmp_path / "skills", state_prefs_loader=lambda: dict(skill_state))
    registry.reload_sync()
    notebook = JarvisNotebook(tmp_path / "vault")
    scheduler = FakeScheduler()
    society_store = SocietyStore(tmp_path / "society.db")
    await society_store.open()
    roster = Roster(society_store)
    await roster.create(name="Jarvis", tier=Tier.LEAD)
    runtime = SimpleNamespace(roster=roster)

    async def society() -> Any:
        return runtime

    def switch(name: str, on: bool) -> None:
        skill_state[name] = "active" if on else "disabled"

    skill_runs: list[dict[str, Any]] = []

    async def run_skill(_config: Any, **kwargs: Any) -> Any:
        """The read-only replay of a skill's steps: every offered tool ran fine."""
        from dodaios.self_build.sandbox import Run, Step

        skill_runs.append(kwargs)
        return Run(
            kwargs["request"],
            "The latest CI run on main passed, nothing is failing.",
            tuple(Step(name, ok=True) for name in kwargs["tools"]),
        )

    env = Env(
        config=lambda: config,
        data_dir=tmp_path,
        bus=bus,
        notebook=lambda: notebook,
        skill_registry=lambda: registry,
        task_store=lambda: scheduler,
        scheduler=lambda: scheduler,
        society=society,
        set_skill_on=switch,
        run_skill=run_skill,
    )
    the_loop = loop.install(service, env=env, bus=bus)
    world = SimpleNamespace(
        config=config,
        settings=settings,
        bus=bus,
        service=service,
        loop=the_loop,
        registry=registry,
        notebook=notebook,
        scheduler=scheduler,
        roster=roster,
        brain=fake_brain,
        skill_state=skill_state,
        skill_runs=skill_runs,
        env=env,
    )

    def configure(**changes: Any) -> None:
        settings.update(changes)
        config.self_build = SelfBuildConfig(**settings)

    world.configure = configure
    yield world
    await the_loop.stop()
    loop.reset_for_tests()
    service.ledger.close()
    await society_store.close()


async def _say(
    world: Any, text: str, ts: int, *, tools: tuple[str, ...] = (), **extra: Any
) -> None:
    await world.loop.observe(
        Observation(
            text=text,
            channel=extra.pop("channel", "voice"),
            conversation=extra.pop("conversation", f"voice:{ts}"),
            ts_ms=ts,
            tools=tools,
            **extra,
        )
    )


async def _settle(world: Any, build_id: str, *, wait_s: float = 10.0) -> Any:
    deadline = asyncio.get_running_loop().time() + wait_s
    while True:
        record = world.service.ledger.get(build_id)
        if record.state not in (State.BUILDING, State.PROVING):
            return record
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"build stuck in {record.state}")
        await asyncio.sleep(0.02)


def _builds(world: Any) -> list[Any]:
    return world.service.ledger.list(limit=100)


# ------------------------------------------------------------------ the miner


def test_same_need_groups_paraphrases_not_neighbours() -> None:
    a = stems("Show me the sales summary for last week")
    b = stems("show me last week's sales summary please")
    c = stems("Show me the weather for next week")
    assert same_need(a, b)
    assert not same_need(a, c)


def test_weekly_habit_becomes_a_routine_candidate(tmp_path: Path) -> None:
    miner = Miner(SignalStore(tmp_path / "s.db"))
    needs = []
    for monday in _mondays():
        _, needs = miner.observe(
            Observation(
                text="Show me the sales summary for last week",
                channel="voice",
                conversation=f"voice:{monday}",
                ts_ms=_ms(monday, 8, 30),
                tools=("mcp:crm/report",),
            )
        )
    assert len(needs) == 1
    need = needs[0]
    assert "weekly" in need.reasons and "repeated" in need.reasons
    assert need.rungs == (Kind.SKILL, Kind.ROUTINE)
    assert need.schedule == {"kind": "calendar", "local_time": "08:15", "weekdays": [0]}
    assert need.occurrences == 3 and need.days == 3


def test_two_requests_or_one_day_are_not_a_need(tmp_path: Path) -> None:
    miner = Miner(SignalStore(tmp_path / "s.db"))
    needs = []
    for minute in (0, 5, 10, 15):  # four times, but on one day: retries, not a habit
        _, needs = miner.observe(
            Observation(
                text="check the build status of the release",
                channel="chat",
                conversation="chat:a",
                ts_ms=_days_ago(1, 10, minute),
                tools=("mcp:github/list_runs",),
            )
        )
    assert needs == []


def test_requests_answered_without_tools_are_not_skills(tmp_path: Path) -> None:
    miner = Miner(SignalStore(tmp_path / "s.db"))
    needs = []
    for days in (1, 3, 5):
        _, needs = miner.observe(
            Observation(
                text="explain the difference between latency and throughput",
                channel="voice",
                conversation=f"v{days}",
                ts_ms=_days_ago(days, 10 + days),
            )
        )
    assert needs == []


def test_voice_pattern_matches_the_phrase_words_in_order() -> None:
    import re

    pattern = re.compile(voice_pattern("check the build status"), re.IGNORECASE)
    assert pattern.search("Hey, could you check the build-status of the repo?")
    assert not pattern.search("status of the build check")


# ------------------------------------------------------------------ routine, end to end


async def test_weekly_request_becomes_one_proven_routine_on_trial(world: Any) -> None:
    world.brain.answers = [
        {
            "build": "routine",
            "why": "asked every Monday morning",
            "title": "A Monday 8:15 routine that prepares last week's sales summary.",
            "case": "Saves the weekly request; checked against the three Mondays.",
            "routine": {
                "title": "Weekly sales summary",
                "prompt": "Prepare the sales summary for last week from the CRM report.",
                "schedule": {"kind": "calendar", "local_time": "08:15", "weekdays": [0]},
            },
        }
    ]
    for monday in _mondays():
        await _say(
            world,
            "Show me the sales summary for last week",
            _ms(monday, 8, 30),
            tools=("mcp:crm/report",),
        )
    opened = await world.loop.run_queue()
    assert len(opened) == 1
    record = await _settle(world, opened[0].id)
    assert record.kind == Kind.ROUTINE
    assert record.state == State.TRIAL, record.note
    assert record.proof["passed"] is True
    assert record.title.startswith("A Monday 8:15 routine")
    assert len(record.evidence) == 3 and record.evidence[0].startswith("turn:")
    # Exactly one routine, owned by the lead, labelled, on the subscription seat,
    # with no plugin grants and no spoken announcement.
    assert len(world.scheduler.specs) == 1
    spec = world.scheduler.specs[record.artefact["task_id"]]
    assert record.artefact["id"] == record.artefact["task_id"]
    assert "self-built" in spec.tags and "agent:jarvis" in spec.tags
    assert spec.action.provider == "sub-seat"
    assert spec.action.plugin_grants == ()
    assert spec.announce_on_success is None
    assert world.brain.decide_calls == 1
    # The same need does not open a second build.
    await _say(world, "show me the sales summary for last week", _days_ago(0, 9))
    assert await world.loop.run_queue() == []
    assert len(_builds(world)) == 1

    # Real runs count as uses; a manual request right after a run is a correction.
    await world.bus.publish(TaskCompleted(task_id=record.artefact["task_id"]))
    await world.loop.drain()
    await _say(world, "show me the sales summary for last week again", _days_ago(0, 10))
    measured = world.service.ledger.get(record.id)
    assert measured.outcomes == {"used": 1, "corrected": 1}


async def test_unused_trial_is_archived_and_its_routine_paused(world: Any, monkeypatch) -> None:
    world.brain.answers = [
        {
            "build": "routine",
            "title": "A Monday routine for the sales summary.",
            "routine": {
                "title": "Weekly sales summary",
                "prompt": "Prepare the sales summary for last week.",
                "schedule": {"kind": "calendar", "local_time": "08:15", "weekdays": [0]},
            },
        }
    ]
    for monday in _mondays():
        await _say(
            world,
            "Show me the sales summary for last week",
            _ms(monday, 8, 30),
            tools=("mcp:crm/report",),
        )
    (opened,) = await world.loop.run_queue()
    record = await _settle(world, opened.id)
    assert record.state == State.TRIAL
    later = record.trial_started_ms + 15 * DAY
    monkeypatch.setattr(policy, "now_ms", lambda: later)
    settled = await world.service.sweep()
    assert [r.state for r in settled] == [State.ARCHIVED]
    for _ in range(50):
        if record.artefact["task_id"] in world.scheduler.paused:
            break
        await asyncio.sleep(0.02)
    assert record.artefact["task_id"] in world.scheduler.paused
    # Keeping it again wakes it up; undo removes it.
    await world.service.keep(record.id)
    for _ in range(50):
        if record.artefact["task_id"] not in world.scheduler.paused:
            break
        await asyncio.sleep(0.02)
    assert record.artefact["task_id"] not in world.scheduler.paused
    await world.service.undo_build(record.id)
    assert record.artefact["task_id"] not in world.scheduler.rows


# ------------------------------------------------------------------ skill, end to end


SKILL_ANSWER = {
    "build": "skill",
    "title": "A skill that checks the build status of your repository.",
    "case": "Asked on three days; replayed against those requests.",
    "skill": {
        "name": "Check Build Status",
        "description": "Check the latest CI run of the repository and report its status.",
        "triggers": ["check the build status"],
        "requires_tools": ["mcp:github/list_runs", "web_search"],
        "body": "## Check Build Status\n\n1. Call mcp:github/list_runs for the repository.\n"
        "2. Tell the user whether the latest run passed, in one sentence.",
    },
}


async def _ask_for_status(world: Any) -> None:
    for days, hour in ((5, 9), (3, 14), (1, 17)):
        await _say(
            world,
            "Please check the build status of the dodaios repo",
            _days_ago(days, hour),
            tools=("mcp:github/list_runs",),
        )


async def test_repeated_request_becomes_one_proven_live_skill(world: Any) -> None:
    for days, text in (
        (6, "play some music from the eighties"),
        (4, "what's the weather in Berlin"),
    ):
        await _say(world, text, _days_ago(days, 12))
    world.brain.answers = [SKILL_ANSWER]
    await _ask_for_status(world)
    (opened,) = await world.loop.run_queue()
    record = await _settle(world, opened.id)
    assert record.state == State.TRIAL, record.note
    assert "replay caught 3 of 3" in record.proof["detail"]
    skill = world.registry.get(record.artefact["name"])
    assert record.artefact["id"] == skill.name
    # ADR-0043: proven by the replay, so live (active) instead of a draft.
    assert skill.state.value == "active"
    assert "self-built" in skill.frontmatter.tags
    # A tool the assistant never used for this need is dropped from the skill.
    assert list(skill.frontmatter.requires_tools) == ["mcp:github/list_runs"]
    # The skill firing counts as a use; the person's next turn correcting it
    # counts against it. The turn that fired it is not judged.
    await world.bus.publish(SkillInvoked(skill_name=skill.name, source="trigger"))
    await world.loop.drain()
    now = now_ms()
    await _say(world, "check the build status of the dodaios repo", now, conversation="c")
    await _say(
        world, "no, I meant the other repository, that's wrong", now + 20_000, conversation="c"
    )
    assert world.service.ledger.get(record.id).outcomes == {"used": 1, "corrected": 1}
    # A scheduled run is not the person using it; while paused nothing is counted.
    uses = world.service.ledger.get(record.id).uses
    await world.bus.publish(SkillInvoked(skill_name=skill.name, source="cron"))
    world.service.set_paused(True)
    await world.bus.publish(SkillInvoked(skill_name=skill.name, source="trigger"))
    await world.loop.drain()
    world.service.set_paused(False)
    assert world.service.ledger.get(record.id).uses == uses
    # Undo removes it from the registry.
    await world.service.undo_build(record.id)
    with pytest.raises(KeyError):
        world.registry.get(skill.name)


async def test_a_failed_replay_records_the_lesson_and_is_not_retried(world: Any) -> None:
    bad = json.loads(json.dumps(SKILL_ANSWER))
    bad["skill"]["triggers"] = ["deploy the frontend bundle"]
    bad["skill"]["name"] = "Deploy Bundle"
    bad["skill"]["description"] = "Deploys the frontend bundle."
    world.brain.answers = [bad]
    await _ask_for_status(world)
    (opened,) = await world.loop.run_queue()
    record = await _settle(world, opened.id)
    assert record.state == State.FAILED
    assert record.proof["passed"] is False and "replay caught" in record.proof["detail"]
    assert world.loop.store.lessons(record.signature)[0][0] == "skill"
    with pytest.raises(KeyError):
        world.registry.get("Deploy Bundle")
    calls = world.brain.decide_calls
    await _say(
        world,
        "check the build status of the dodaios repo",
        _days_ago(0, 8),
        tools=("mcp:github/list_runs",),
    )
    assert await world.loop.run_queue() == []
    assert world.brain.decide_calls == calls


async def test_an_installed_skill_that_serves_the_need_costs_no_model_call(world: Any) -> None:
    from dodaios.skills.authoring.service import SkillAuthoringService, SkillCreateRequest

    await SkillAuthoringService(registry=world.registry).create(
        SkillCreateRequest(
            name="build-status",
            description="Report the CI build status of a repository.",
            triggers=({"type": "voice", "pattern": "check the build status"},),
            body="1. Look up the latest CI run.\n2. Report it.",
        )
    )
    world.brain.answers = [SKILL_ANSWER]
    await _ask_for_status(world)
    assert await world.loop.run_queue() == []
    assert world.brain.decide_calls == 0
    assert world.loop.store.decision(_builds_signature(world))[1] == "served"


def _builds_signature(world: Any) -> str:
    rows = world.loop.store.recent_turns(since_ms=0)
    return world.loop.store.cluster(rows[0].cluster).signature


# ------------------------------------------------------------------ memory, end to end


async def test_repeated_correction_becomes_a_memory_entry(world: Any) -> None:
    world.brain.answers = [
        {
            "build": "memory",
            "title": "Remember that your office is the Berlin one.",
            "memory": {
                "target": "memory",
                "text": "The user's office is the Berlin office, not Munich.",
                "evidence": "I meant the Berlin office",
                "importance": 8,
            },
        }
    ]
    await _say(world, "No, I meant the Berlin office, not Munich", _days_ago(3, 10))
    await _say(world, "that's wrong, I meant the Berlin office", _days_ago(1, 11))
    (opened,) = await world.loop.run_queue()
    record = await _settle(world, opened.id)
    assert record.kind == Kind.MEMORY and record.state == State.TRIAL, record.note
    assert record.artefact["id"] == "society/jarvis/MEMORY.md"
    texts = [e.text for e in world.notebook.entries()["memory"]]
    assert "The user's office is the Berlin office, not Munich." in texts
    await world.service.undo_build(record.id)
    texts = [e.text for e in world.notebook.entries()["memory"]]
    assert "The user's office is the Berlin office, not Munich." not in texts


# ------------------------------------------------------------------ agent: last rung, a card


async def test_a_domain_of_needs_proposes_an_agent_and_builds_it_on_accept(world: Any) -> None:
    world.brain.answers = [
        {
            "build": "agent",
            "title": "A repository agent for the GitHub work you keep doing.",
            "agent": {
                "name": "Octo",
                "title": "Repository caretaker",
                "description": "You look after the user's GitHub repositories: open issues, "
                "pull requests and CI runs. Report findings briefly.",
                "focus": ["mcp:github/list_runs", "mcp:github/list_issues", "mcp:other/x"],
            },
        }
    ]
    plan = [
        (16, "list the open issues in the dodaios repo", "mcp:github/list_issues"),
        (13, "show the pull requests waiting for review", "mcp:github/list_prs"),
        (12, "check the ci run of the main branch", "mcp:github/list_runs"),
        (10, "list the open issues in the dodaios repo", "mcp:github/list_issues"),
        (8, "show the pull requests waiting for review", "mcp:github/list_prs"),
        (6, "check the ci run of the main branch", "mcp:github/list_runs"),
        (4, "list the open issues in the dodaios repo", "mcp:github/list_issues"),
        (3, "show the pull requests waiting for review", "mcp:github/list_prs"),
        (2, "check the ci run of the main branch", "mcp:github/list_runs"),
        (1, "list the open issues in the dodaios repo", "mcp:github/list_issues"),
    ]
    for days, text, tool in plan:
        await _say(world, text, _days_ago(days, 9 + days % 7), tools=(tool,))
    await world.loop.run_queue()
    agents = [r for r in _builds(world) if r.kind == Kind.AGENT]
    assert len(agents) == 1
    card = agents[0]
    assert card.state == State.PROPOSED and card.signature == "domain:mcp:github"
    assert not [a for a in await world.roster.list() if a.name == "Octo"]
    accepted = await world.service.accept(card.id)
    record = await _settle(world, accepted.id)
    assert record.state == State.TRIAL, record.note
    octo = await world.roster.get(record.artefact["agent_id"])
    assert record.artefact["id"] == octo.agent_id
    assert octo.name == "Octo" and octo.provider == "sub-seat"
    assert octo.focus == ["mcp:github/list_runs", "mcp:github/list_issues"]
    # Talking to it counts.
    await _say(
        world,
        "any new issues today?",
        _days_ago(0, 9),
        channel="agent",
        agent_id=octo.agent_id,
        conversation="chat:society:octo",
    )
    assert world.service.ledger.get(record.id).outcomes == {"used": 1}
    await world.service.undo_build(record.id)
    assert (await world.roster.get(octo.agent_id)).state.value == "archived"


# ------------------------------------------------------------------ control: nothing is built


@pytest.mark.parametrize("mode", ["paused", "off", "silent", "suggest"])
async def test_paused_off_silent_and_suggest_build_nothing(world: Any, mode: str) -> None:
    world.brain.answers = [SKILL_ANSWER]
    if mode == "paused":
        world.service.set_paused(True)
    elif mode == "off":
        world.configure(enabled=False)
    elif mode == "silent":
        world.configure(silent_days=7)
    else:
        world.configure(skill="suggest")
    await _ask_for_status(world)
    await world.loop.run_queue()
    records = _builds(world)
    assert world.registry.list() == []
    if mode in ("paused", "off"):
        assert records == [] and world.brain.calls == []
        assert world.loop.store.recent_turns(since_ms=0) == []  # not even observed
    else:
        assert [r.state for r in records] == [State.PROPOSED]


async def test_a_rejected_need_is_not_offered_again(world: Any) -> None:
    world.configure(skill="suggest")
    world.brain.answers = [SKILL_ANSWER]
    await _ask_for_status(world)
    (card,) = await world.loop.run_queue()
    await world.service.undo_build(card.id)  # the person rejects the card
    assert world.service.ledger.get(card.id).state == State.REJECTED
    calls = world.brain.decide_calls
    for days in (0, 0, 0):
        await _say(
            world,
            "check the build status of the dodaios repo",
            _days_ago(days, 8),
            tools=("mcp:github/list_runs",),
        )
    assert await world.loop.run_queue() == []
    assert world.brain.decide_calls == calls
    world.configure(max_rejections=1)
    assert world.service.admit(Kind.SKILL, card.signature).start is None


async def test_build_nothing_holds_the_need_for_a_month(world: Any) -> None:
    world.brain.answers = []  # every answer is "nothing"
    await _ask_for_status(world)
    assert await world.loop.run_queue() == []
    assert world.brain.decide_calls == 1
    await _say(
        world,
        "check the build status of the dodaios repo",
        _days_ago(0, 8),
        tools=("mcp:github/list_runs",),
    )
    assert await world.loop.run_queue() == []
    assert world.brain.decide_calls == 1


async def test_idle_turns_cost_nothing(world: Any) -> None:
    for i in range(40):
        word = "".join(chr(97 + (i * 7 + k * 3) % 26) for k in range(7))
        await _say(world, f"tell me about {word} {word[::-1]}", _days_ago(i % 20, 10))
    assert world.loop._queue == {}
    assert await world.loop.run_queue() == []
    assert world.brain.calls == []


async def test_kept_build_unused_for_a_month_is_archived(world: Any) -> None:
    world.brain.answers = [SKILL_ANSWER]
    await _ask_for_status(world)
    (opened,) = await world.loop.run_queue()
    record = await _settle(world, opened.id)
    await world.service.keep(record.id)
    await world.loop.maintain(now=record.trial_started_ms + 31 * DAY)
    archived = world.service.ledger.get(record.id)
    assert archived.state == State.ARCHIVED and "unused" in archived.note
    assert world.skill_state[record.artefact["name"]] == "disabled"


async def test_agent_and_routine_turns_are_not_the_person(world: Any) -> None:
    completion = SimpleNamespace(
        turn=SimpleNamespace(direct_user=False, user_text="x", turn_id="t"),
        events_json=json.dumps(
            [{"kind": "user_message", "payload": {"text": "check the build status now"}}]
        ),
    )
    await world.loop.chat_turn_completed(
        SimpleNamespace(session_id="s"), completion, surface="jarvis"
    )
    await world.loop.drain()
    assert world.loop.store.recent_turns(since_ms=0) == []


# ------------------------------------------------------------------ cost: never a key


def test_seats_never_include_a_per_token_key(monkeypatch) -> None:
    from dodaios.brain import background_policy
    from dodaios.brain import resolver as brain_resolver

    billing = {
        "openai": "api",
        "claude-code": "subscription",
        "ollama": "local",
        "codex": "subscription_or_api",
    }
    monkeypatch.setattr(brain, "_brain_provider_ids", lambda: list(billing))
    monkeypatch.setattr(background_policy, "_billing", lambda name: billing.get(name, "api"))
    logins = {"claude-code": True, "codex": False}
    monkeypatch.setattr(background_policy, "login_state", lambda name: logins.get(name))
    monkeypatch.setattr(
        brain_resolver, "_get_registry", lambda: SimpleNamespace(available=lambda: list(billing))
    )
    names = [seat.provider for seat in brain.seats(SimpleNamespace(brain=None))]
    assert names == ["claude-code", "ollama"]


async def test_without_a_seat_the_loop_proposes_and_bills_nothing(world: Any, monkeypatch) -> None:
    brain.set_override(None)
    monkeypatch.setattr(brain, "seats", lambda _config: [])
    monkeypatch.setattr(brain, "_instantiate", lambda _seat: pytest.fail("no brain may be built"))
    await _ask_for_status(world)
    (card,) = await world.loop.run_queue()
    assert card.state == State.PROPOSED
    assert "Written from the counts alone" in card.case
    assert card.title  # from the phrase catalog, in the person's language
    accepted = await world.service.accept(card.id)
    await asyncio.sleep(0.1)
    # Accepted, but nothing can write the spec: it waits, nothing is billed.
    assert world.service.ledger.get(accepted.id).state == State.BUILDING
    assert world.registry.list() == []


def test_judge_refuses_outbound_routines() -> None:
    proof = judge.routine(
        {
            "prompt": "Send an email to all customers with the weekly summary.",
            "schedule": {
                "kind": "calendar",
                "local_time": "08:00",
                "weekdays": [0],
                "timezone": "UTC",
            },
        },
        asked=[(0, 510), (0, 515), (0, 505)],
        stems=frozenset({"summar", "weekly"}),
        shadow="A long enough answer for the shadow run.",
    )
    assert not proof.passed and "outside" in proof.detail


def test_outcomes_enum_is_what_the_loop_reports() -> None:
    assert {o.value for o in Outcome} >= {"used", "corrected", "ignored"}


# ------------------------------------------------------------------ review regressions


async def _weekly_sales(world: Any) -> None:
    for monday in _mondays():
        await _say(
            world,
            "Show me the sales summary for last week",
            _ms(monday, 8, 30),
            tools=("mcp:crm/report",),
        )


ROUTINE_ANSWER = {
    "build": "routine",
    "title": "A Monday routine for the sales summary.",
    "routine": {
        "title": "Weekly sales summary",
        "prompt": "Prepare the sales summary for last week.",
        "schedule": {"kind": "calendar", "local_time": "08:15", "weekdays": [0]},
    },
}


async def test_a_build_that_must_wait_stays_building_and_is_retried(world: Any) -> None:
    brain.set_override(world.brain, provider="")  # no seat to run the routine on yet
    world.brain.answers = [ROUTINE_ANSWER]
    await _weekly_sales(world)
    (opened,) = await world.loop.run_queue()
    for _ in range(20):
        await asyncio.sleep(0.02)
    waiting = world.service.ledger.get(opened.id)
    assert waiting.state == State.BUILDING  # never stuck in proving
    assert world.scheduler.specs == {}
    brain.set_override(world.brain, provider="sub-seat")
    await world.loop.maintain(now=waiting.updated_ms + loop.RETRY_MS + 1)
    record = await _settle(world, opened.id)
    assert record.state == State.TRIAL, record.note
    assert len(world.scheduler.specs) == 1


async def test_undo_during_a_build_creates_nothing(world: Any) -> None:
    world.brain.answers = [ROUTINE_ANSWER]
    original = world.brain.__call__

    async def undo_mid_build(system: str, prompt: str, max_tokens: int) -> str:
        if system == ROUTINE_SHADOW_SYSTEM:
            for record in world.service.ledger.list(states=[State.BUILDING]):
                await world.service.undo_build(record.id)
        return await original(system, prompt, max_tokens)

    brain.set_override(undo_mid_build, provider="sub-seat")
    await _weekly_sales(world)
    (opened,) = await world.loop.run_queue()
    for _ in range(20):
        await asyncio.sleep(0.02)
    assert world.service.ledger.get(opened.id).state == State.UNDONE
    assert world.scheduler.specs == {}


async def test_the_daily_decide_budget_holds(world: Any, monkeypatch) -> None:
    monkeypatch.setattr(loop, "DECIDE_PER_DAY", 1)
    world.brain.answers = []
    await _ask_for_status(world)
    await _weekly_sales(world)
    await world.loop.run_queue()
    assert world.brain.decide_calls == 1


def test_no_habit_when_no_zone_can_be_named(tmp_path: Path, monkeypatch) -> None:
    from dodaios.self_build import clock
    from dodaios.tasks import context

    monkeypatch.setattr(context, "_reported_ui_timezone", None)
    monkeypatch.setattr(clock, "system_zone_name", lambda: None)
    miner = Miner(SignalStore(tmp_path / "s.db"))
    needs = []
    for monday in _mondays():
        _, needs = miner.observe(
            Observation(
                text="Show me the sales summary for last week",
                channel="voice",
                conversation=f"voice:{monday}",
                ts_ms=_ms(monday, 8, 30),
                tools=("mcp:crm/report",),
            )
        )
    (need,) = needs
    assert need.schedule is None and need.rungs == (Kind.SKILL,)


async def test_self_built_agents_ask_before_they_act(world: Any) -> None:
    world.configure(agent="trial")
    world.brain.answers = [
        {
            "build": "agent",
            "title": "A repository agent.",
            "agent": {
                "name": "Octo",
                "title": "Repository caretaker",
                "description": "You look after the user's GitHub repositories and report briefly.",
                "focus": ["mcp:github/list_issues"],
            },
        }
    ]
    texts = [
        "list the open issues in the repo",
        "show the pull requests waiting",
        "check the ci run of main",
    ]
    for i in range(10):
        await _say(world, texts[i % 3], _days_ago(1 + 2 * i, 9), tools=("mcp:github/list_issues",))
    await world.loop.run_queue()
    agents = [r for r in _builds(world) if r.kind == Kind.AGENT]
    assert len(agents) == 1
    record = await _settle(world, agents[0].id)
    assert record.state == State.TRIAL, record.note
    octo = await world.roster.get(record.artefact["agent_id"])
    assert str(octo.approval_mode) == "ask"
