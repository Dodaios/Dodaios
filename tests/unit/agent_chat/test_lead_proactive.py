"""The lead's "needs you" checks: settings, prompt, rhythm, quiet delivery, adaptivity."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from dodaios.agent_chat import open_loops, proactive, proactive_checks
from dodaios.agent_chat.proactive_settings import (
    ProactiveSettings,
    load_settings,
    save_settings,
)
from dodaios.tasks.schema import TaskSpec

# ── fakes ───────────────────────────────────────────────────────────────────────


class _TaskStore:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.results: dict[str, str] = {}
        self._next = 0

    async def insert(self, spec: TaskSpec) -> str:
        # Ids never repeat, even after a delete (the real store uses UUIDs).
        self._next += 1
        task_id = f"task-{self._next}"
        self.rows.append(
            {"id": task_id, "state": "scheduled", "spec_json": spec.model_dump_json(), "spec": spec}
        )
        return task_id

    async def list(self, state_filter=None, *, limit: int = 100) -> list[dict]:
        return list(self.rows)

    async def get(self, task_id: str) -> dict | None:
        return next((r for r in self.rows if r["id"] == task_id), None)

    async def get_spec(self, task_id: str) -> TaskSpec | None:
        row = await self.get(task_id)
        return row["spec"] if row else None

    async def delete(self, task_id: str) -> bool:
        self.rows = [r for r in self.rows if r["id"] != task_id]
        return True

    async def latest_agent_results(self, task_ids, *, max_chars: int = 400) -> dict[str, str]:
        return {t: self.results[t][:max_chars] for t in task_ids if t in self.results}


class _Scheduler:
    def __init__(self, store: _TaskStore) -> None:
        self.store = store

    async def schedule(self, spec: TaskSpec) -> str:
        return await self.store.insert(spec)

    async def cancel_task(self, task_id: str, reason: str = "") -> bool:
        row = await self.store.get(task_id)
        if row:
            row["state"] = "cancelled"
        return True


class _Meta:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get_meta(self, key: str, default: str = "") -> str:
        return self.values.get(key, default)

    async def set_meta(self, key: str, value: str) -> None:
        self.values[key] = value


class _Roster:
    async def get(self, agent_id: str):
        return SimpleNamespace(
            agent_id=agent_id, name="Dodaios", title="", description="", focus=(),
            provider="openai", model="m", effort="low", account_id="",
        )


def _runtime(store: _TaskStore, meta: _Meta) -> SimpleNamespace:
    scheduler = _Scheduler(store)
    return SimpleNamespace(
        roster=_Roster(),
        task_services=lambda: (store, scheduler),
        store=meta,
        config=lambda: None,
    )


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> tuple[_TaskStore, _Meta]:
    store, meta = _TaskStore(), _Meta()
    runtime = _runtime(store, meta)
    monkeypatch.setattr(proactive_checks, "_runtime", lambda: runtime)
    monkeypatch.setattr(proactive, "_runtime", lambda: runtime)
    monkeypatch.setattr("dodaios.agent_chat.proactive_settings._store", lambda: meta)
    # No subscription seat on this box: the checks stay on the lead's own seat.

    async def no_subscription(_cfg):
        return None

    monkeypatch.setattr("dodaios.society.routine_runner._subscription_seat", no_subscription)
    monkeypatch.setattr("dodaios.society.routine_runner._billed_via_api", lambda *_: False)
    return store, meta


def _live(store: _TaskStore, tag: str) -> list[dict]:
    return [
        r for r in store.rows
        if r["state"] != "cancelled" and tag in json.loads(r["spec_json"])["tags"]
    ]


# ── settings ────────────────────────────────────────────────────────────────────


def test_settings_sanitise_unknown_values_and_round_trip() -> None:
    s = ProactiveSettings.from_dict(
        {"level": "LOUD", "topics": ["mail", "weather"], "interval_hours": 2, "from_hour": 30}
    )
    assert s.level == "off" and s.topics == ("mail",) and s.interval_hours == 3
    assert (s.from_hour, s.to_hour) == (8, 22)
    s = ProactiveSettings.from_dict({"level": "everything", "interval_hours": "6"})
    assert s.enabled and s.interval_hours == 6 and set(s.topics) == {
        "mail", "calendar", "agents", "deadlines"
    }
    assert ProactiveSettings.from_dict(s.to_dict()) == s
    assert ProactiveSettings.from_dict("garbage") == ProactiveSettings()


def test_settings_persist_in_the_society_meta_row(world) -> None:
    _, meta = world

    async def scenario() -> None:
        assert (await load_settings()).level == "off"
        await save_settings(ProactiveSettings(level="important", topics=("calendar",)))
        loaded = await load_settings()
        assert loaded.level == "important" and loaded.topics == ("calendar",)
        meta.values["lead_proactive"] = "{not json"
        assert (await load_settings()).level == "off"

    asyncio.run(scenario())


# ── prompt and rhythm ───────────────────────────────────────────────────────────


def test_check_prompt_follows_topics_and_level() -> None:
    important = ProactiveSettings(level="important", topics=("mail", "deadlines"))
    prompt = proactive_checks.check_prompt(important)
    assert "messages that wait" in prompt and "deadlines" in prompt
    assert "appointments" not in prompt and "agents finished" not in prompt
    assert "only what the user must act on" in prompt.lower()
    assert proactive_checks.NOTHING in prompt
    assert "Never send, change, book, delete or schedule" in prompt
    everything = ProactiveSettings(level="everything", topics=())
    prompt = proactive_checks.check_prompt(everything)
    assert "even small items" in prompt and "the user's calendar" in prompt


def test_cron_runs_inside_waking_hours_only() -> None:
    s = ProactiveSettings(level="important", interval_hours=3)
    assert proactive_checks.cron_expression(s) == "0 8-22/3 * * *"
    assert proactive_checks.runs_per_day(s) == 5
    hourly = ProactiveSettings(level="important", interval_hours=1, from_hour=9, to_hour=18)
    assert proactive_checks.cron_expression(hourly) == "0 9-18/1 * * *"
    assert proactive_checks.runs_per_day(hourly) == 10


def test_brief_prompt_follows_topics_too() -> None:
    assert proactive.brief_prompt(None) == proactive.BRIEF_PROMPT
    assert proactive.brief_prompt(ProactiveSettings()) == proactive.BRIEF_PROMPT
    only_mail = proactive.brief_prompt(ProactiveSettings(topics=("mail",)))
    assert "messages that wait" in only_mail and "calendar" not in only_mail
    nothing_on = proactive.brief_prompt(ProactiveSettings(topics=()))
    assert "today's calendar" in nothing_on


# ── quiet delivery ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "", "   ", "NOTHING_TO_REPORT", "nothing_to_report.", "**NOTHING_TO_REPORT**",
        "`NOTHING_TO_REPORT`",
    ],
)
def test_a_result_that_says_nothing_is_quiet(text: str) -> None:
    payload = {"kind": "society_result", "source": "routine", "status": "done", "text": text}
    assert proactive_checks.quiet_result(payload) is True


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "society_result", "source": "routine", "status": "done",
         "text": "Max replied and asks for the slides by noon."},
        {"kind": "society_result", "source": "routine", "status": "done",
         "text": "NOTHING_TO_REPORT, except the 3 pm meeting moved to 4 pm and Max wants a reply."},
        {"kind": "society_result", "source": "routine", "status": "failed", "text": ""},
        {"kind": "society_result", "source": "routine", "status": "skipped", "text": ""},
        {"kind": "society_result", "source": "delegation", "status": "done", "text": ""},
        {"kind": "memory_learned", "text": ""},
    ],
)
def test_real_results_failures_and_other_notices_keep_showing(payload: dict) -> None:
    assert proactive_checks.quiet_result(payload) is False


def test_quiet_routines_are_the_tagged_ones_and_living_page_refreshes() -> None:
    assert proactive_checks.quiet_routine(("society", "agent:jarvis", proactive_checks.QUIET_TAG))
    assert proactive_checks.quiet_routine(["society", "agent:jarvis", "living-page:abc123"])
    assert not proactive_checks.quiet_routine(("society", "agent:jarvis", proactive.BRIEF_TAG))
    assert not proactive_checks.quiet_routine(())


# ── the routine ─────────────────────────────────────────────────────────────────


def test_level_creates_rebuilds_and_removes_the_check_routine(world) -> None:
    store, _ = world

    async def scenario() -> None:
        state = await proactive_checks.checks_state()
        assert state["available"] and state["checks"]["enabled"] is False
        on = await proactive_checks.apply_settings(
            ProactiveSettings(level="important", timezone="Europe/Berlin")
        )
        assert on["checks"]["enabled"] and on["checks"]["runs_per_day"] == 5
        assert on["settings"]["level"] == "important"
        rows = _live(store, proactive_checks.CHECK_TAG)
        assert len(rows) == 1
        spec = rows[0]["spec"]
        assert spec.trigger.type == "cron" and spec.trigger.expression == "0 8-22/3 * * *"
        assert spec.trigger.timezone == "Europe/Berlin"
        assert proactive_checks.QUIET_TAG in spec.tags
        assert proactive_checks.ADAPTIVE_TAG in spec.tags
        assert proactive_checks.NOTHING in spec.action.prompt
        # A new rhythm or topic set replaces the routine; never two of them.
        moved = await proactive_checks.apply_settings(
            ProactiveSettings(level="everything", interval_hours=6, topics=("mail",),
                              timezone="Europe/Berlin")
        )
        assert moved["checks"]["runs_per_day"] == 3
        rows = _live(store, proactive_checks.CHECK_TAG)
        assert len(rows) == 1 and rows[0]["spec"].trigger.expression == "0 8-22/6 * * *"
        assert "appointments" not in rows[0]["spec"].action.prompt
        off = await proactive_checks.apply_settings(ProactiveSettings(level="off"))
        assert off["checks"]["enabled"] is False
        assert _live(store, proactive_checks.CHECK_TAG) == []
        assert (await load_settings()).level == "off"

    asyncio.run(scenario())


def test_checks_refuse_a_bad_zone_but_turn_off_without_one(world) -> None:
    with pytest.raises(ValueError):
        asyncio.run(
            proactive_checks.apply_settings(ProactiveSettings(level="important", timezone="Mars"))
        )
    assert asyncio.run(proactive_checks.apply_settings(ProactiveSettings(level="off")))


def test_checks_pin_the_subscription_seat_when_there_is_one(world, monkeypatch) -> None:
    store, _ = world

    async def subscription(_cfg):
        return ("claude-cli", "sonnet", "medium")

    monkeypatch.setattr("dodaios.society.routine_runner._subscription_seat", subscription)
    state = asyncio.run(
        proactive_checks.apply_settings(ProactiveSettings(level="important", timezone="UTC"))
    )
    assert state["checks"]["provider"] == "claude-cli"
    assert state["checks"]["model"] == "sonnet"
    assert state["checks"]["billed_via_key"] is False
    spec = _live(store, proactive_checks.CHECK_TAG)[0]["spec"]
    assert spec.action.provider == "claude-cli"


def test_topic_change_rebuilds_an_existing_brief(world) -> None:
    store, _ = world

    async def scenario() -> None:
        await proactive.set_brief(enabled=True, local_time="07:00", timezone="Europe/Berlin")
        before = _live(store, proactive.BRIEF_TAG)[0]["spec"]
        assert before.action.prompt.count("calendar") >= 1
        assert proactive_checks.ADAPTIVE_TAG in before.tags
        await proactive_checks.apply_settings(
            ProactiveSettings(level="important", topics=("mail",), timezone="Europe/Berlin")
        )
        briefs = _live(store, proactive.BRIEF_TAG)
        assert len(briefs) == 1
        after = briefs[0]["spec"]
        assert "calendar" not in after.action.prompt and "messages that wait" in after.action.prompt
        assert after.trigger.local_time == "07:00"
        # A paused brief is left alone: rebuilding it would turn it on or lose it.
        briefs[0]["state"] = "paused"
        await proactive_checks.apply_settings(
            ProactiveSettings(level="important", topics=("calendar",), timezone="Europe/Berlin")
        )
        paused = [r for r in _live(store, proactive.BRIEF_TAG) if r["state"] == "paused"]
        assert len(paused) == 1 and paused[0]["spec"] is after

    asyncio.run(scenario())


# ── run context: adaptive + open loops ──────────────────────────────────────────


def test_run_context_hands_over_the_previous_result_and_the_due_loops(
    world, monkeypatch, tmp_path
) -> None:
    from dodaios.memory.vault.store import MemoryVault

    store, _ = world
    store.results["task-9"] = "Max wants the slides by noon."
    vault = MemoryVault(tmp_path / "vault.db", clock=lambda: "2026-11-12T19:00:00+00:00")
    monkeypatch.setattr(open_loops, "_vault", lambda: vault)
    added = vault.remember(
        "Open loop: call Max", "project", origin="inferred",
        due_at="2026-11-11T17:00:00+00:00", source={"via": "open_loop"},
    )
    assert added.action == "added"
    vault.remember("Dentist appointment", "project", due_at="2026-11-12T08:00:00+00:00")
    tags = ("society", "agent:jarvis", proactive_checks.CHECK_TAG, proactive_checks.ADAPTIVE_TAG)

    async def scenario() -> None:
        extra = await proactive_checks.run_context(store, "task-9", tags)
        assert "Max wants the slides" in extra
        assert "- Open loop: call Max" in extra
        assert "Dentist" not in extra  # not an open loop; the check reads it from memory itself
        # Asked once: the next run sees no loop, and the memory is closed.
        again = await proactive_checks.run_context(store, "task-9", tags)
        assert "call Max" not in again
        assert vault.get(added.memory.id).is_current(vault.now()) is False
        # A quiet previous result is not worth handing over.
        store.results["task-9"] = proactive_checks.NOTHING
        adaptive_only = (proactive_checks.ADAPTIVE_TAG,)
        assert await proactive_checks.run_context(store, "task-9", adaptive_only) == ""
        assert await proactive_checks.run_context(store, "task-9", ("society",)) == ""

    asyncio.run(scenario())
    vault.close()


def test_run_context_survives_a_store_without_history(world) -> None:
    class _Bare:
        pass

    assert asyncio.run(
        proactive_checks.run_context(_Bare(), "x", (proactive_checks.ADAPTIVE_TAG,))
    ) == ""
