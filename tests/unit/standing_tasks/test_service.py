"""Standing tasks: validation, proposals, taking one on, and its routine kept in step."""

from __future__ import annotations

from dataclasses import replace

import pytest

from dodaios.agent_chat.proactive_checks import QUIET_TAG
from dodaios.standing_tasks import service
from dodaios.standing_tasks.models import (
    DEFAULT_INTERVAL_MIN,
    MAX_INTERVAL_MIN,
    MAX_OPEN,
    MIN_INTERVAL_MIN,
    TAG_PREFIX,
    StandingError,
    StandingRun,
    StandingTask,
    now_ms,
)
from dodaios.standing_tasks.store import get_store
from tests.unit.standing_tasks.conftest import routine_row, routine_spec

ADS = {"title": "Meta ads campaign", "goal": "Keep cost per lead under 12 EUR."}


async def _code(awaitable) -> str:
    with pytest.raises(StandingError) as caught:
        await awaitable
    assert caught.value.message
    return caught.value.code


# ── models ──────────────────────────────────────────────────────────────────────


def test_to_dict_has_exactly_the_contract_keys() -> None:
    task = StandingTask(
        id="st_12345678", title="t", goal="g", how="", autonomy="prepare", limits="",
        state="active", interval_min=180, origin="owner", reason="", notes="", task_id="x",
        created_ms=1, updated_ms=2, last_run_ms=None, next_run_ms=None, last_outcome="",
        last_summary="", runs=0,
    )
    assert list(task.to_dict()) == [
        "id", "title", "goal", "how", "autonomy", "limits", "state", "interval_min", "origin",
        "reason", "notes", "task_id", "created_ms", "updated_ms", "last_run_ms", "next_run_ms",
        "last_outcome", "last_summary", "runs",
    ]
    run = StandingRun("sr_1", "st_12345678", 5, "quiet", "", ("a", "b"), 180, "chat")
    assert run.to_dict() == {
        "id": "sr_1", "standing_id": "st_12345678", "at_ms": 5, "outcome": "quiet",
        "summary": "", "actions": ["a", "b"], "next_interval_min": 180, "session_id": "chat",
    }


# ── validation ──────────────────────────────────────────────────────────────────


async def test_a_task_needs_a_title_a_goal_and_a_known_level(society) -> None:
    assert await _code(service.take_on(title=" ", goal="g")) == "invalid"
    assert await _code(service.take_on(title="t", goal="")) == "invalid"
    assert await _code(service.take_on(title="t" * 121, goal="g")) == "invalid"
    assert await _code(service.take_on(title="t", goal="g" * 2001)) == "invalid"
    assert await _code(service.take_on(title="t", goal="g", autonomy="everything")) == "invalid"
    assert await _code(service.take_on(title="t", goal="g", origin="nobody")) == "invalid"
    assert await service.list_tasks(include_ended=True) == []
    assert await society.task_store.list() == []


async def test_acting_needs_limits_the_owner_wrote(society) -> None:
    assert await _code(service.take_on(**ADS, autonomy="act")) == "invalid"
    limits = "Pause ad sets. Never raise budgets."
    task = await service.take_on(**ADS, autonomy="act", limits=limits)
    assert task.autonomy == "act" and task.limits == limits
    # Taking the limits away while it may act is refused too.
    assert await _code(service.update(task.id, limits="")) == "invalid"
    lowered = await service.update(task.id, autonomy="watch", limits="")
    assert lowered.autonomy == "watch"


async def test_the_pace_is_clamped_to_the_bounds(society) -> None:
    fast = await service.take_on(title="Fast", goal="g", interval_min=1)
    slow = await service.take_on(title="Slow", goal="g", interval_min=10**6)
    odd = await service.take_on(title="Odd", goal="g", interval_min="soon")  # type: ignore[arg-type]
    assert fast.interval_min == MIN_INTERVAL_MIN
    assert slow.interval_min == MAX_INTERVAL_MIN
    assert odd.interval_min == DEFAULT_INTERVAL_MIN


async def test_at_most_twelve_open_tasks(society) -> None:
    for index in range(MAX_OPEN):
        await service.propose(title=f"Task {index}", goal="g")
    assert await _code(service.propose(title="One more", goal="g")) == "limit"
    assert await _code(service.take_on(title="One more", goal="g")) == "limit"
    # An ended one makes room again.
    first = (await service.list_tasks())[0]
    await service.decline(first.id)
    assert (await service.take_on(title="One more", goal="g")).state == "active"


# ── proposals ───────────────────────────────────────────────────────────────────


async def test_a_proposal_waits_for_the_owner_and_posts_one_notice(society) -> None:
    task = await service.propose(
        **ADS, how="Check Ads Manager.", interval_min=240, reason="You check it by hand each day."
    )
    assert task.state == "proposed" and task.origin == "suggested" and task.task_id == ""
    assert task.id.startswith("st_") and len(task.id) == 11
    assert await society.task_store.list() == [], "nothing runs before the owner says yes"
    assert len(society.notices) == 1
    notice = society.notices[0]
    assert {k: notice[k] for k in ("kind", "standing_id", "title", "autonomy", "interval_min")} == {
        "kind": "standing_proposal", "standing_id": task.id, "title": "Meta ads campaign",
        "autonomy": "prepare", "interval_min": 240,
    }
    assert notice["goal"] == ADS["goal"] and notice["limits"] == ""
    assert notice["reason"] == "You check it by hand each day."
    assert "Meta ads campaign" in notice["text"] and "\n" not in notice["text"]


async def test_suggesting_the_same_thing_twice_returns_the_open_task(society) -> None:
    first = await service.propose(**ADS)
    again = await service.propose(title="  meta ADS campaign! ", goal="Something else.")
    assert again.id == first.id and again.goal == ADS["goal"]
    assert society.kinds() == ["standing_proposal"], "no second notice"
    active = await service.accept(first.id)
    assert (await service.propose(**ADS)).id == active.id


async def test_a_declined_proposal_is_not_suggested_again_for_thirty_days(
    society, standing_store
) -> None:
    declined = await service.decline((await service.propose(**ADS)).id)
    assert declined.state == "ended"
    assert await _code(service.propose(**ADS)) == "state"
    assert society.kinds() == ["standing_proposal"]
    # The same holds for a task the owner ended.
    ended = await service.end((await service.take_on(title="Inbox", goal="g")).id)
    assert await _code(service.propose(title="inbox", goal="g")) == "state"
    # After thirty days it may be suggested again.
    long_ago = now_ms() - service.DECLINE_MEMORY_MS - 1000
    standing_store.save(replace(declined, updated_ms=long_ago))
    standing_store.save(replace(ended, updated_ms=long_ago))
    assert (await service.propose(**ADS)).state == "proposed"
    assert (await service.propose(title="Inbox", goal="g")).state == "proposed"
    # The owner may always take it on themselves.
    await service.decline((await service.list_tasks())[0].id)
    assert (await service.take_on(**ADS)).state == "active"


async def test_a_notice_that_fails_never_fails_the_proposal(society, monkeypatch) -> None:
    async def broken(agent, payload) -> None:
        raise RuntimeError("no conversation")

    monkeypatch.setattr(society, "post_chat_notice", broken)
    assert (await service.propose(**ADS)).state == "proposed"


async def test_only_a_proposal_is_accepted_or_declined(society) -> None:
    active = await service.take_on(**ADS)
    assert await _code(service.accept(active.id)) == "state"
    assert await _code(service.decline(active.id)) == "state"
    assert await _code(service.accept("st_missing0")) == "not_found"


# ── the backing routine ─────────────────────────────────────────────────────────


async def test_taking_a_task_on_creates_its_quiet_lead_routine(society) -> None:
    task = await service.take_on(**ADS, how="Check Ads Manager.", interval_min=90)
    assert task.state == "active" and task.origin == "owner" and task.task_id
    spec = await routine_spec(society, task.task_id)
    assert spec.tags == ("society", "agent:jarvis", TAG_PREFIX + task.id, QUIET_TAG)
    assert spec.trigger.type == "every" and spec.trigger.interval_seconds == 90 * 60
    assert spec.title == "[agent:Dodaios] Meta ads campaign"
    # The stored prompt is one stable line; the work order joins at run time.
    assert spec.action.prompt.endswith(f"Standing task {task.id}: Meta ads campaign")
    assert "Keep cost per lead" not in spec.action.prompt
    row = await routine_row(society, task.task_id)
    assert row["state"] == "scheduled"
    assert task.next_run_ms == row["due_at_ns"] // 1_000_000
    assert service.standing_id_of(spec.tags) == task.id
    assert service.standing_id_of(("society", "agent:jarvis")) == ""


async def test_the_routine_is_pinned_to_the_subscription_seat_like_the_checks(
    society, monkeypatch
) -> None:
    async def subscription(_cfg):
        return ("claude-cli", "sonnet", "medium")

    monkeypatch.setattr("dodaios.society.routine_runner._subscription_seat", subscription)
    task = await service.take_on(**ADS)
    spec = await routine_spec(society, task.task_id)
    assert (spec.action.provider, spec.action.model) == ("claude-cli", "sonnet")


async def test_accepting_a_proposal_creates_the_routine(society) -> None:
    proposal = await service.propose(**ADS, interval_min=60)
    active = await service.accept(proposal.id)
    assert active.state == "active" and active.origin == "suggested"
    spec = await routine_spec(society, active.task_id)
    assert TAG_PREFIX + active.id in spec.tags and spec.trigger.interval_seconds == 3600
    # Asking for what was suggested is a yes to that proposal, with the owner's wording.
    other = await service.propose(title="Inbox", goal="Keep it empty.")
    taken = await service.take_on(title="inbox", goal="Answer what is urgent.")
    assert taken.id == other.id and taken.state == "active"
    assert taken.goal == "Answer what is urgent." and taken.title == "inbox"
    assert await _code(service.take_on(title="Inbox", goal="g")) == "state"


async def test_nothing_is_half_created_without_a_scheduler(society) -> None:
    society.up = False
    assert await _code(service.take_on(**ADS)) == "unavailable"
    assert await service.list_tasks(include_ended=True) == []
    society.up = True
    proposal = await service.propose(**ADS)
    society.up = False
    assert await _code(service.accept(proposal.id)) == "unavailable"
    assert (await service.get_task(proposal.id)).state == "proposed"
    assert (await service.overview())["available"] is False
    society.up = True
    assert await society.task_store.list() == []


async def test_no_society_at_all_is_unavailable(standing_store, monkeypatch) -> None:
    monkeypatch.setattr(service, "_runtime", lambda: None)
    assert await _code(service.take_on(**ADS)) == "unavailable"
    assert (await service.overview())["available"] is False


async def test_a_failed_store_write_leaves_no_routine_behind(
    society, standing_store, monkeypatch
) -> None:
    def broken(task) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(standing_store, "save", broken)
    with pytest.raises(OSError):
        await service.take_on(**ADS)
    assert await society.task_store.list() == []


async def test_pause_resume_and_end_keep_the_routine_in_step(society) -> None:
    task = await service.take_on(**ADS)
    paused = await service.pause(task.id)
    assert paused.state == "paused" and paused.next_run_ms is None
    assert (await routine_row(society, task.task_id))["state"] == "paused"
    assert await _code(service.pause(task.id)) == "state"
    assert await _code(service.run_now(task.id)) == "state"
    resumed = await service.resume(task.id)
    assert resumed.state == "active" and resumed.task_id == task.task_id
    row = await routine_row(society, task.task_id)
    assert row["state"] == "scheduled" and resumed.next_run_ms == row["due_at_ns"] // 1_000_000
    assert await _code(service.resume(task.id)) == "state"
    ended = await service.end(task.id)
    assert ended.state == "ended" and ended.task_id == ""
    assert await routine_row(society, task.task_id) is None
    assert await _code(service.end(task.id)) == "state"
    assert await _code(service.update(task.id, goal="again")) == "state"
    assert await service.list_tasks() == []
    assert [t.id for t in await service.list_tasks(include_ended=True)] == [task.id]


async def test_declining_a_proposal_touches_no_routine(society) -> None:
    proposal = await service.propose(**ADS)
    society.up = False  # a proposal has no routine, so no scheduler is needed
    assert (await service.decline(proposal.id)).state == "ended"
    other = await service.propose(title="Other", goal="g")
    assert (await service.end(other.id)).state == "ended"


async def test_an_update_moves_the_routine_with_the_title_and_the_pace(society) -> None:
    task = await service.take_on(**ADS, interval_min=180)
    changed = await service.update(task.id, title="Meta ads", interval_min=45, how="Use the API.")
    assert (changed.title, changed.interval_min, changed.how) == ("Meta ads", 45, "Use the API.")
    assert changed.goal == ADS["goal"] and changed.task_id == task.task_id
    spec = await routine_spec(society, task.task_id)
    assert spec.trigger.interval_seconds == 45 * 60
    assert spec.title == "[agent:Dodaios] Meta ads"
    assert spec.action.prompt.endswith(f"Standing task {task.id}: Meta ads")
    assert TAG_PREFIX + task.id in spec.tags and QUIET_TAG in spec.tags
    assert (await routine_row(society, task.task_id))["state"] == "scheduled"
    # A second task may not take the first one's name.
    other = await service.take_on(title="Inbox", goal="g")
    assert await _code(service.update(other.id, title="meta ads")) == "state"


async def test_pausing_while_a_run_is_under_way_takes_effect_when_it_ends(society) -> None:
    task = await service.take_on(**ADS)
    await society.task_store.update_state(task.task_id, "running")
    paused = await service.pause(task.id)
    assert paused.state == "paused"
    assert (await routine_row(society, task.task_id))["state"] == "running"
    # The run ends (the task runner hands the routine back), then the upkeep pauses it.
    await society.task_store.update_state(task.task_id, "scheduled")
    await service.settle(task.id)
    assert (await routine_row(society, task.task_id))["state"] == "paused"


async def test_ending_while_a_run_is_under_way_stops_it_and_removes_the_routine(society) -> None:
    task = await service.take_on(**ADS)
    await society.task_store.update_state(task.task_id, "running")
    ended = await service.end(task.id)
    assert ended.state == "ended"
    assert (await routine_row(society, task.task_id))["state"] == "cancelled"
    await service.drain()
    assert await routine_row(society, task.task_id) is None
    assert (await service.get_task(task.id)).task_id == ""


async def test_run_now_fires_the_backing_routine(society) -> None:
    task = await service.take_on(**ADS)
    assert (await service.run_now(task.id)).id == task.id
    for job in list(society.scheduler._runner_tasks):
        await job
    assert society.scheduler._runner.ran == [task.task_id]
    await society.task_store.update_state(task.task_id, "running")
    assert await _code(service.run_now(task.id)) == "state"
    assert await _code(service.run_now("st_missing0")) == "not_found"


# ── what happened to the routine behind the task's back ─────────────────────────


async def test_a_routine_the_owner_removed_rests_the_task(society) -> None:
    task = await service.take_on(**ADS)
    await society.scheduler.cancel_task(task.task_id)
    seen = await service.get_task(task.id)
    assert seen.state == "paused" and seen.task_id == "" and seen.next_run_ms is None
    # Resuming makes a new routine.
    resumed = await service.resume(task.id)
    assert resumed.state == "active" and resumed.task_id not in ("", task.task_id)
    assert (await routine_row(society, resumed.task_id))["state"] == "scheduled"
    await society.task_store.delete(resumed.task_id)
    assert [t.state for t in await service.list_tasks()] == ["paused"]


async def test_a_routine_an_app_exit_ended_is_replaced(society) -> None:
    task = await service.take_on(**ADS, interval_min=60)
    await society.task_store.update_state(task.task_id, "running")
    assert await society.task_store.cleanup_interrupted() == 1
    healed = await service.get_task(task.id)
    assert healed.state == "active" and healed.task_id not in ("", task.task_id)
    assert await routine_row(society, task.task_id) is None
    spec = await routine_spec(society, healed.task_id)
    assert TAG_PREFIX + task.id in spec.tags and spec.trigger.interval_seconds == 3600


async def test_the_start_hook_replaces_a_routine_an_app_exit_ended(society) -> None:
    task = await service.take_on(**ADS, interval_min=60)
    await society.task_store.update_state(task.task_id, "running")
    assert await society.task_store.cleanup_interrupted() == 1
    await service.heal_after_start(wait_s=1.0)
    healed = get_store().get(task.id)
    assert healed.state == "active" and healed.task_id not in ("", task.task_id)
    assert (await routine_row(society, healed.task_id))["state"] == "scheduled"


async def test_the_start_hook_gives_up_quietly_without_a_scheduler(
    society, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = await service.take_on(**ADS)
    monkeypatch.setattr(society, "task_services", lambda: (None, None))
    await service.heal_after_start(wait_s=0.0)
    assert get_store().get(task.id).task_id == task.task_id


# ── reading ─────────────────────────────────────────────────────────────────────


async def test_overview_lists_open_tasks_with_bounds_and_levels(society) -> None:
    first = await service.take_on(**ADS)
    second = await service.propose(title="Inbox", goal="g")
    await service.end((await service.take_on(title="Gone", goal="g")).id)
    seen = await service.overview()
    assert seen["available"] is True
    assert [t["id"] for t in seen["tasks"]] == [first.id, second.id]
    assert seen["tasks"][0]["next_run_ms"] and seen["tasks"][1]["next_run_ms"] is None
    assert seen["limits"] == {
        "min_interval_min": 15, "max_interval_min": 10080, "default_interval_min": 180,
        "max_open": 12,
    }
    assert seen["autonomy"] == ["watch", "prepare", "act"]
    assert await service.get_task("st_missing0") is None


async def test_a_note_is_appended_and_the_newest_lines_survive(society) -> None:
    task = await service.take_on(**ADS)
    noted = await service.add_note(task.id, "The owner prefers\nvideo ads.")
    assert noted.notes.endswith("] The owner prefers video ads.")
    assert await _code(service.add_note(task.id, "  ")) == "invalid"
    for index in range(8):
        noted = await service.add_note(task.id, f"note {index} " + "x" * 900)
    assert len(noted.notes) == 4000 and noted.notes.startswith("…")
    assert "note 7" in noted.notes and "video ads" not in noted.notes
    await service.end(task.id)
    assert await _code(service.add_note(task.id, "late")) == "state"


async def test_accepting_twice_at_once_leaves_one_routine(society) -> None:
    import asyncio

    proposal = await service.propose(**ADS)
    first, second = await asyncio.gather(service.accept(proposal.id), service.accept(proposal.id))
    assert first.state == second.state == "active" and first.task_id == second.task_id
    live = [r for r in await society.task_store.list() if r["state"] == "scheduled"]
    assert [r["id"] for r in live] == [first.task_id]
