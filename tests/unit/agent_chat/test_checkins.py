"""Check-ins: "check on me in 25 minutes" becomes one quiet one-shot lead routine."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from dodaios.agent_chat import checkins
from dodaios.agent_chat.proactive_checks import QUIET_TAG
from dodaios.tasks.schema import TaskSpec


@pytest.mark.parametrize(
    ("text", "minutes", "doing"),
    [
        ("Check on me in 25 minutes, I'm writing the report.", 25, "writing the report"),
        ("check in on me in 2 hours", 120, ""),
        ("Can you check back on me in ten min while I clean the kitchen", 10, "clean the kitchen"),
        (
            "check in with me in half an hour, I am working on the slides",
            30,
            "working on the slides",
        ),
        (
            "Melde dich in 25 Minuten, ich schreibe den Bericht.",  # i18n-allow
            25,
            "schreibe den Bericht",  # i18n-allow
        ),
        ("Frag in einer Stunde nach.", 60, ""),  # i18n-allow
        ("Melde dich in einer halben Stunde", 30, ""),  # i18n-allow
    ],
)
def test_parses_a_check_in_request(text: str, minutes: int, doing: str) -> None:
    request = checkins.parse_checkin(text)
    assert request is not None
    assert (request.minutes, request.doing) == (minutes, doing)


@pytest.mark.parametrize(
    "text",
    [
        "Remind me in 25 minutes to call Max.",
        "Check the mail in 10 minutes.",
        "I'll check on you in 5 minutes.",
        "check on me in 900 minutes",
    ],
)
def test_other_requests_are_not_check_ins(text: str) -> None:
    assert checkins.parse_checkin(text) is None


def test_prompt_is_short_warm_and_schedules_nothing() -> None:
    prompt = checkins.checkin_prompt(checkins.CheckinRequest(25, "writing the report"))
    assert "25 minutes" in prompt and '"writing the report"' in prompt
    assert "Do not schedule anything" in prompt
    assert "2 hours" in checkins.checkin_prompt(checkins.CheckinRequest(120, ""))


class _Store:
    def __init__(self) -> None:
        self.specs: list[TaskSpec] = []

    async def insert(self, spec: TaskSpec) -> str:
        self.specs.append(spec)
        return f"task-{len(self.specs)}"


def _runtime(store: _Store) -> SimpleNamespace:
    scheduler = SimpleNamespace(schedule=store.insert)

    async def get(agent_id: str):
        return SimpleNamespace(
            agent_id=agent_id, name="Dodaios", title="", description="", focus=(),
            provider="openai", model="m", effort="low", account_id="",
        )

    return SimpleNamespace(
        roster=SimpleNamespace(get=get), task_services=lambda: (store, scheduler)
    )


def test_schedule_creates_one_quiet_one_shot_lead_routine(monkeypatch) -> None:
    store = _Store()
    monkeypatch.setattr(checkins, "_runtime", lambda: _runtime(store))
    result = asyncio.run(checkins.schedule_checkin(checkins.CheckinRequest(25, "the report")))
    assert result == {"task_id": "task-1", "minutes": 25, "doing": "the report"}
    spec = store.specs[0]
    assert spec.trigger.type == "after_delay" and spec.trigger.delay_seconds == 1500
    assert checkins.CHECKIN_TAG in spec.tags and QUIET_TAG in spec.tags
    assert "agent:jarvis" in spec.tags
    assert spec.title.endswith(checkins.CHECKIN_TITLE)
    with pytest.raises(ValueError):
        asyncio.run(checkins.schedule_checkin(checkins.CheckinRequest(0, "")))


def test_note_skips_when_the_turn_already_scheduled_something(monkeypatch) -> None:
    store = _Store()
    monkeypatch.setattr(checkins, "_runtime", lambda: _runtime(store))
    text = "check on me in 25 minutes"
    assert asyncio.run(checkins.note_user_text(text, tool_names=("create_routine",))) is None
    assert asyncio.run(checkins.note_user_text("hello there")) is None
    assert store.specs == []
    assert asyncio.run(checkins.note_user_text(text, tool_names=("web_search",))) is not None
    assert len(store.specs) == 1


def test_note_without_a_society_is_not_an_error(monkeypatch) -> None:
    monkeypatch.setattr(checkins, "_runtime", lambda: None)
    assert asyncio.run(checkins.note_user_text("check on me in 5 minutes")) is None
