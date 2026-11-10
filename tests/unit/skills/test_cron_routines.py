"""Scheduled skills run as lead routines: billing hold, written results, migration."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat import proactive_checks
from dodaios.brain import background_policy
from dodaios.brain.background_policy import BackgroundDeferred
from dodaios.skills import cron_routines
from dodaios.skills.schema import (
    Skill,
    SkillFrontmatter,
    SkillLifecycleState,
    SkillTrigger,
)
from dodaios.society import routine_runner
from dodaios.society.routines import is_agent_routine
from dodaios.tasks.schema import TaskSpec


class _TaskStore:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def insert(self, spec: TaskSpec) -> str:
        task_id = f"task-{len(self.rows) + 1}"
        self.rows.append(
            {"id": task_id, "state": "scheduled", "spec_json": spec.model_dump_json(), "spec": spec}
        )
        return task_id

    async def list(self, state_filter=None, *, limit: int = 100) -> list[dict[str, Any]]:
        return list(self.rows)

    async def get(self, task_id: str) -> dict[str, Any] | None:
        return next((r for r in self.rows if r["id"] == task_id), None)

    async def get_spec(self, task_id: str) -> TaskSpec | None:
        row = await self.get(task_id)
        return row["spec"] if row else None

    async def delete(self, task_id: str) -> bool:
        self.rows = [r for r in self.rows if r["id"] != task_id]
        return True


class _Scheduler:
    def __init__(self, store: _TaskStore) -> None:
        self.store = store

    async def schedule(self, spec: TaskSpec) -> str:
        return await self.store.insert(spec)

    async def update_task(self, task_id: str, spec: TaskSpec) -> None:
        row = await self.store.get(task_id)
        assert row is not None
        row["spec"] = spec
        row["spec_json"] = spec.model_dump_json()

    async def cancel_task(self, task_id: str, reason: str = "") -> bool:
        row = await self.store.get(task_id)
        if row:
            row["state"] = "cancelled"
        return True


class _Roster:
    async def get(self, agent_id: str) -> Any:
        return SimpleNamespace(
            agent_id=agent_id, name="Dodaios", title="", description="", focus=(),
            provider="gemini", model="m", effort="low", account_id="",
            state="active", session_id="jarvis", runtime="jarvis",
        )


def _runtime(tasks: _TaskStore) -> SimpleNamespace:
    scheduler = _Scheduler(tasks)
    return SimpleNamespace(
        roster=_Roster(), task_services=lambda: (tasks, scheduler), config=lambda: None,
        store=None,
    )


def _skill(name: str = "daily-triage", cron: str | None = "0 8 * * *",
           state: SkillLifecycleState = SkillLifecycleState.ACTIVE,
           body: str = "Read the inbox and list what needs a reply.") -> Skill:
    triggers = [SkillTrigger(type="schedule", cron=cron)] if cron else []
    fm = SkillFrontmatter(name=name, description="d", triggers=triggers)
    return Skill(path=Path(f"/skills/{name}/SKILL.md"), frontmatter=fm, body=body, state=state)


@pytest.fixture(autouse=True)
def _zone_and_seat(monkeypatch: pytest.MonkeyPatch) -> None:
    from dodaios.tasks import context

    monkeypatch.setattr(context, "_reported_ui_timezone", "Europe/Berlin")

    async def subscription(_cfg: Any) -> tuple[str, str, str]:
        return "claude-cli", "sonnet", "low"

    monkeypatch.setattr(routine_runner, "_subscription_seat", subscription)


async def test_an_existing_cron_skill_migrates_to_one_lead_routine_at_the_same_time() -> None:
    tasks = _TaskStore()
    counts = await cron_routines.sync_skill_routines(_runtime(tasks), [_skill()])
    assert counts["created"] == 1
    spec = tasks.rows[0]["spec"]
    assert spec.trigger.expression == "0 8 * * *"
    assert spec.trigger.timezone == "Europe/Berlin"
    assert cron_routines.tag_for("daily-triage") in spec.tags
    assert proactive_checks.QUIET_TAG in spec.tags
    assert proactive_checks.quiet_routine(spec.tags)
    assert is_agent_routine(tasks.rows[0], "jarvis")
    assert "Read the inbox" in spec.action.prompt
    # Pinned to the subscription seat, never the lead's own key seat.
    assert spec.action.provider == "claude-cli"
    # A second pass changes nothing.
    again = await cron_routines.sync_skill_routines(_runtime(tasks), [_skill()])
    assert again == {"created": 0, "updated": 0, "removed": 0} and len(tasks.rows) == 1


async def test_changed_schedule_or_instructions_update_and_a_lost_schedule_removes() -> None:
    tasks = _TaskStore()
    rt = _runtime(tasks)
    await cron_routines.sync_skill_routines(rt, [_skill()])
    moved = await cron_routines.sync_skill_routines(rt, [_skill(cron="30 9 * * 1-5")])
    assert moved["updated"] == 1
    assert tasks.rows[0]["spec"].trigger.expression == "30 9 * * 1-5"
    edited = await cron_routines.sync_skill_routines(rt, [_skill(cron="30 9 * * 1-5", body="New.")])
    assert edited["updated"] == 1 and "New." in tasks.rows[0]["spec"].action.prompt
    gone = await cron_routines.sync_skill_routines(rt, [_skill(cron=None)])
    assert gone["removed"] == 1 and not tasks.rows


async def test_disabled_skills_get_no_routine() -> None:
    tasks = _TaskStore()
    skill = _skill(state=SkillLifecycleState.DISABLED)
    counts = await cron_routines.sync_skill_routines(_runtime(tasks), [skill])
    assert counts["created"] == 0 and not tasks.rows


async def test_nothing_is_scheduled_until_the_zone_is_known(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dodaios.tasks import context

    monkeypatch.setattr(context, "_reported_ui_timezone", None)
    tasks = _TaskStore()
    counts = await cron_routines.sync_skill_routines(_runtime(tasks), [_skill()])
    assert counts["created"] == 0 and not tasks.rows


# -- what the routine path guarantees ----------------------------------------


def _run_runtime() -> SimpleNamespace:
    agent = SimpleNamespace(
        agent_id="jarvis", state="active", session_id="jarvis", runtime="jarvis",
        provider="gemini", account_id="", name="Dodaios",
    )

    async def kill_switch() -> bool:
        return False

    async def get(_agent_id: str) -> Any:
        return agent

    def create_session(**_kwargs: Any) -> Any:
        raise AssertionError("a routine chat was opened: a key would have been billed")

    service = SimpleNamespace(store=SimpleNamespace(create_session=create_session))
    return SimpleNamespace(
        store=SimpleNamespace(kill_switch=kill_switch),
        roster=SimpleNamespace(get=get),
        chat_service=lambda: service,
        config=lambda: None,
        task_services=lambda: (None, None),
    )


async def test_a_scheduled_skill_run_never_touches_a_key_seat_once_a_subscription_is_connected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    background_policy.note_connected("claude-cli")

    async def seat_for_run(runtime: Any, agent: Any, task_id: str) -> tuple[str, str, str, str]:
        return "gemini", "gemini-chosen", "", ""

    monkeypatch.setattr(routine_runner, "_seat_for_run", seat_for_run)
    monkeypatch.setattr(routine_runner, "_workspace", lambda cfg, agent: "workspace")
    monkeypatch.setattr(routine_runner, "_billed_via_api", lambda provider, account_id="": True)
    tasks = _TaskStore()
    await cron_routines.sync_skill_routines(_runtime(tasks), [_skill()])
    spec = tasks.rows[0]["spec"]
    # The key seat is held: no routine chat (hence no provider call) is opened.
    with pytest.raises(BackgroundDeferred):
        await routine_runner.run_owned_routine(
            _run_runtime(), "t1", tuple(spec.tags), spec.action.prompt
        )


async def test_a_scheduled_skill_result_and_failure_are_written_in_the_lead_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dodaios.agent_chat.lead as lead_mod
    from dodaios.society.runtime import SocietyRuntime

    posted: list[tuple[str, dict[str, Any]]] = []

    async def post(session_id: str, payload: dict[str, Any]) -> None:
        posted.append((session_id, payload))

    svc = SimpleNamespace(
        post_notice=post, store=SimpleNamespace(get_session=lambda sid: object()),
    )
    runtime = SocietyRuntime.__new__(SocietyRuntime)
    monkeypatch.setattr(runtime, "_get_chat", lambda: svc, raising=False)
    monkeypatch.setattr(lead_mod, "lead_session", lambda _svc: SimpleNamespace(session_id="lead"))
    lead = SimpleNamespace(agent_id="jarvis", session_id="society:jarvis")

    def notice(status: str, text: str) -> dict[str, Any]:
        return {"kind": "society_result", "status": status, "source": "routine", "text": text}

    await runtime._notify_chat(lead, notice("done", "Two mails need a reply."))
    await runtime._notify_chat(lead, notice("failed", "The routine failed."))
    await runtime._notify_chat(lead, notice("done", proactive_checks.NOTHING))
    # Result and failure are written to the lead chat; the quiet answer posts nothing.
    assert [(sid, p["status"]) for sid, p in posted] == [("lead", "done"), ("lead", "failed")]


def test_the_old_pipeline_cron_path_and_its_held_source_are_gone() -> None:
    from dodaios.speech import pipeline

    assert not hasattr(pipeline.SpeechPipeline, "_handle_cron_skill")
    assert not hasattr(pipeline.SpeechPipeline, "_skill_cron_loop")
    assert "skills.cron" not in pipeline._HELD_FOR_CALL_SOURCES
