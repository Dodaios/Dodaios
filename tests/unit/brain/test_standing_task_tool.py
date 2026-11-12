"""``standing_task``: the turn decides who may start, widen, accept and report, not the args."""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from dodaios.brain.standing_task_tool import StandingTaskTool
from dodaios.core.protocols import ChatTurn, current_chat_turn
from dodaios.safety.reversibility import autonomy_origin, reversibility_of
from dodaios.standing_tasks.models import AUTONOMY, StandingError, StandingRun
from dodaios.standing_tasks.work_order import REPORTABLE
from tests.fakes.fake_standing_tasks import NOW_MS, FakeStandingService, install

LEAD = "lead-chat"
RUN = "society:jarvis:routine:task-1:0123abcd"

CAMPAIGN = {
    "title": "Meta ads campaign",
    "goal": "Keep the cost per lead under 4 EUR and tell me when a creative tires.",
    "how": "Meta Ads through the connected ads account.",
}


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> FakeStandingService:
    return install(monkeypatch)


@pytest.fixture
def tool() -> StandingTaskTool:
    return StandingTaskTool(lead_session=lambda session_id: session_id == LEAD)


@contextmanager
def _turn(
    text: str = "", *, session: str = LEAD, direct: bool = True, origin: str = "chat"
) -> Iterator[None]:
    token = current_chat_turn.set(ChatTurn(session, "turn-1", text, direct, "trace", origin=origin))
    try:
        yield
    finally:
        current_chat_turn.reset(token)


def _owner(text: str) -> Any:
    return _turn(text)


def _run(session: str = RUN) -> Any:
    return _turn("Scheduled routine", session=session, direct=False, origin="routine")


def _ctx(**config: Any) -> SimpleNamespace:
    return SimpleNamespace(trace_id=uuid4(), user_utterance="", config=config, memory_read=None)


async def _call(tool: StandingTaskTool, ctx: Any = None, **args: Any) -> Any:
    return await tool.execute(args, ctx or _ctx())


# ------------------------------------------------------------------ take_on


async def test_the_owners_own_request_with_their_words_starts_the_task(tool, service) -> None:
    said = "Please look after my Meta ads campaign from now on."
    with _owner(said):
        result = await _call(
            tool, action="take_on", **CAMPAIGN, check_every_min=240,
            request_quote="look after my Meta ads campaign",
        )
    assert result.success, result.error
    (call,) = service.called("take_on")
    assert call["origin"] == "owner" and call["origin_session"] == LEAD
    assert call["interval_min"] == 240 and call["autonomy"] == "prepare"
    assert not service.called("propose")
    # The answer reads back what was stored: state, pace and the next run.
    out = result.output
    assert out["state"] == "active" and out["pace"] == "every 4 hours"
    assert out["next_run"] == "2027-01-15T12:00:00Z" and "note" not in out


@pytest.mark.parametrize(
    "quote",
    ["", "look after my Google ads", "ads"],  # none, not their words, too short to stand alone
)
async def test_without_the_owners_words_a_take_on_becomes_a_proposal(tool, service, quote) -> None:
    with _owner("My Meta ads are a mess again."):
        result = await _call(tool, action="take_on", **CAMPAIGN, request_quote=quote)
    assert result.success, result.error
    assert not service.called("take_on")
    (call,) = service.called("propose")
    assert call["reason"]
    assert result.output["state"] == "proposed"
    assert "one sentence" in result.output["note"] and "wait" in result.output["note"]


async def test_a_run_nobody_started_can_only_propose(tool, service) -> None:
    with _run("society:jarvis:routine:needs-you:ffff"):
        result = await _call(
            tool, action="take_on", **CAMPAIGN,
            request_quote="Scheduled routine", reason="They asked about it three days running.",
        )
    assert result.success and result.output["state"] == "proposed"
    assert not service.called("take_on")
    assert service.called("propose")[0]["reason"] == "They asked about it three days running."
    assert "Do not start the work" in result.output["note"]


async def test_an_unattended_origin_or_another_chat_is_not_the_owners_turn(tool, service) -> None:
    said = "look after my Meta ads campaign"
    with _owner(said):
        trigger = await _call(
            tool, _ctx(autonomy_origin="trigger"), action="take_on", **CAMPAIGN, request_quote=said
        )
    with _turn(said, session="society:scout"):
        other_chat = await _call(tool, action="take_on", **CAMPAIGN, request_quote=said)
    with _owner(said), autonomy_origin("routine", task_id="t9"):
        inside_run = await _call(tool, action="take_on", **CAMPAIGN, request_quote=said)
    no_turn = await _call(tool, action="take_on", **CAMPAIGN, request_quote=said)
    for result in (trigger, other_chat, inside_run, no_turn):
        assert result.success and result.output["state"] == "proposed"
    assert not service.called("take_on") and len(service.called("propose")) == 4


async def test_act_needs_the_owners_limits(tool, service) -> None:
    said = "Run my Meta ads for me, pause anything above 4 EUR per lead."
    with _owner(said):
        missing = await _call(
            tool, action="take_on", **CAMPAIGN, autonomy="act", request_quote=said
        )
        proposal = await _call(tool, action="propose", **CAMPAIGN, autonomy="act")
        started = await _call(
            tool, action="take_on", **CAMPAIGN, autonomy="act",
            limits="Pause ads above 4 EUR per lead.", request_quote=said,
        )
    assert not missing.success and missing.output == {"code": "invalid"}
    assert "limits" in missing.error
    assert not proposal.success and "limits" in proposal.error
    assert started.success and service.called("take_on")[0]["autonomy"] == "act"
    assert service.called("take_on")[0]["limits"] == "Pause ads above 4 EUR per lead."


async def test_a_task_needs_a_goal_and_a_known_autonomy(tool, service) -> None:
    with _owner("look after it"):
        no_goal = await _call(tool, action="take_on", title="x", request_quote="look after it")
        odd = await _call(tool, action="propose", **CAMPAIGN, autonomy="everything")
        pace = await _call(tool, action="propose", **CAMPAIGN, check_every_min="soon")
    assert not no_goal.success and "goal" in no_goal.error
    assert not odd.success and "watch, prepare, act" in odd.error
    assert not pace.success and "minutes" in pace.error
    assert not service.calls


# ------------------------------------------------------------------ propose / accept


async def test_propose_is_allowed_from_any_turn(tool, service) -> None:
    with _run():
        from_run = await _call(tool, action="propose", **CAMPAIGN, reason="Asked about daily.")
    no_turn = await _call(tool, action="propose", **CAMPAIGN)
    assert from_run.success and no_turn.success
    assert service.called("propose")[0]["reason"] == "Asked about daily."
    assert from_run.output["state"] == "proposed" and "accept" in from_run.output["note"]


@pytest.mark.parametrize(
    ("said", "quote"),
    [("ja", "ja"), ("Yes", "Yes"), ("ok", "ok"), ("Yes please, do that.", "Yes please")],
)
async def test_the_owners_yes_accepts_a_proposal(tool, service, said, quote) -> None:
    service.add("st_p", state="proposed", task_id="")
    with _owner(said):
        result = await _call(tool, action="accept", standing_id="st_p", request_quote=quote)
    assert result.success, result.error
    assert service.called("accept") == [{"standing_id": "st_p", "origin_session": LEAD}]
    assert result.output["state"] == "active"


async def test_accept_without_the_owners_yes_is_refused(tool, service) -> None:
    service.add("st_p", state="proposed", task_id="")
    with _owner("ja, aber erst die Zahlen"):  # i18n-allow: simulated owner input
        short = await _call(tool, action="accept", standing_id="st_p", request_quote="ja")
    with _owner("What would that cost?"):
        invented = await _call(tool, action="accept", standing_id="st_p", request_quote="yes")
    with _run():
        from_run = await _call(
            tool, action="accept", standing_id="st_p", request_quote="Scheduled routine"
        )
    for result in (short, invented, from_run):
        assert not result.success and result.output == {"code": "state"}
        assert "stays open" in result.error
    assert not service.called("accept")


async def test_decline_needs_no_quote(tool, service) -> None:
    service.add("st_p", state="proposed", task_id="")
    with _owner("no thanks"):
        result = await _call(tool, action="decline", standing_id="st_p")
    assert result.success and result.output["state"] == "ended"


# ------------------------------------------------------------------ update


async def test_narrowing_is_always_allowed(tool, service) -> None:
    service.add("st_a", autonomy="act", limits="Pause ads above 4 EUR per lead.")
    with _run():
        result = await _call(
            tool, action="update", standing_id="st_a", autonomy="prepare", check_every_min=60,
            how="Also read the comments.", limits="", title="",
        )
    assert result.success, result.error
    # Empty strings are fields the model left out, not fields to clear.
    assert service.called("update") == [
        {"standing_id": "st_a", "how": "Also read the comments.", "autonomy": "prepare",
         "interval_min": 60}
    ]
    assert result.output["pace"] == "every hour"


async def test_widening_autonomy_or_changing_limits_needs_the_owner(tool, service) -> None:
    service.add("st_w", autonomy="watch")
    service.add("st_a", autonomy="act", limits="Pause ads above 4 EUR per lead.")
    with _run():
        wider = await _call(tool, action="update", standing_id="st_w", autonomy="prepare")
        relimit = await _call(
            tool, action="update", standing_id="st_a", limits="Any budget change."
        )
    with _owner("How is the campaign doing?"):
        no_quote = await _call(
            tool, action="update", standing_id="st_w", autonomy="prepare",
            request_quote="you may prepare things",
        )
    for result in (wider, relimit, no_quote):
        assert not result.success and result.output == {"code": "state"}
        assert "Nothing changed" in result.error
    assert not service.called("update")

    said = "You may prepare drafts for the campaign from now on."
    with _owner(said):
        allowed = await _call(
            tool, action="update", standing_id="st_w", autonomy="prepare",
            request_quote="You may prepare drafts",
        )
    assert allowed.success and allowed.output["autonomy"] == "prepare"


async def test_raising_to_act_needs_limits_and_the_same_limits_are_no_change(
    tool, service
) -> None:
    service.add("st_p", autonomy="prepare")
    service.add("st_a", autonomy="act", limits="Pause ads above 4 EUR per lead.")
    said = "Go ahead and act on the campaign yourself."
    with _owner(said):
        bare = await _call(
            tool, action="update", standing_id="st_p", autonomy="act", request_quote=said
        )
    with _run():
        same = await _call(
            tool, action="update", standing_id="st_a", limits="Pause ads above 4 EUR per lead.",
            check_every_min=30,
        )
        nothing = await _call(tool, action="update", standing_id="st_a")
    assert not bare.success and bare.output == {"code": "invalid"} and "limits" in bare.error
    assert same.success
    assert not nothing.success and "at least one" in nothing.error


# ------------------------------------------------------------------ pause / resume / end / run_now


async def test_pause_is_open_but_resume_end_and_run_now_are_the_owners(tool, service) -> None:
    service.add("st_1")
    with _run():
        paused = await _call(tool, action="pause", standing_id="st_1")
        refused = [
            await _call(tool, action=action, standing_id="st_1")
            for action in ("resume", "run_now", "end")
        ]
    assert paused.success and paused.output["state"] == "paused"
    for result in refused:
        assert not result.success and result.output == {"code": "state"}
        assert "owner's own message" in result.error
    with _owner("carry on with the campaign and look now"):
        resumed = await _call(tool, action="resume", standing_id="st_1")
        ran = await _call(tool, action="run_now", standing_id="st_1")
        ended = await _call(tool, action="end", standing_id="st_1")
    assert resumed.success and ran.success and ended.output["state"] == "ended"
    # A run the assistant starts is not the owner's own start: the billing hold applies.
    assert service.run_started_by_user is False


# ------------------------------------------------------------------ report / note


async def test_a_run_reports_through_its_own_routine_chat(tool, service) -> None:
    service.add("st_1", task_id="task-1")
    with _run():
        result = await _call(
            tool, action="report", standing_id="st_1", outcome="prepared",
            summary="Cost per lead rose to 4.60 EUR; a new creative is drafted.",
            notes="CPL 4.60 on 2027-01-15. Creative B is tiring.",
            actions=["Drafted creative C", " "], next_check_min=120,
        )
    assert result.success, result.error
    assert service.called("report") == [
        {
            "standing_id": "st_1",
            "outcome": "prepared",
            "summary": "Cost per lead rose to 4.60 EUR; a new creative is drafted.",
            "notes": "CPL 4.60 on 2027-01-15. Creative B is tiring.",
            "actions": ("Drafted creative C",),
            "next_check_min": 120,
            "session_id": RUN,
        }
    ]
    assert result.output["last_outcome"] == "prepared" and result.output["pace"] == "every 2 hours"


async def test_a_run_is_also_known_by_its_autonomy_origin(tool, service) -> None:
    service.add("st_1", task_id="task-1")
    with autonomy_origin("routine", task_id="task-1", agent_id="jarvis"):
        result = await _call(
            tool, action="report", standing_id="st_1", outcome="quiet", summary="No change."
        )
    assert result.success, result.error
    call = service.called("report")[0]
    assert call["notes"] is None and call["actions"] == () and call["next_check_min"] is None


async def test_a_report_from_anywhere_else_is_refused_plainly(tool, service) -> None:
    service.add("st_1", task_id="task-1")
    service.add("st_none", state="proposed", task_id="")
    args = {"action": "report", "outcome": "acted", "summary": "Paused two ads."}
    with _owner("report that you paused two ads"):
        from_chat = await _call(tool, standing_id="st_1", **args)
    with _run("society:jarvis:routine:task-2:0123abcd"):
        other_run = await _call(tool, standing_id="st_1", **args)
    with _run("society:jarvis:routine::0123abcd"):
        no_backing = await _call(tool, standing_id="st_none", **args)
    with _owner("x"), autonomy_origin("routine", task_id="task-1"):
        typed_inside = await _call(tool, standing_id="st_1", **args)
    nowhere = await _call(tool, standing_id="st_1", **args)
    for result in (from_chat, other_run, no_backing, typed_inside, nowhere):
        assert not result.success and result.output == {"code": "state"}
        assert "only for a run of this standing task" in result.error
    assert not service.called("report")


async def test_a_report_needs_a_known_outcome_and_a_summary(tool, service) -> None:
    service.add("st_1", task_id="task-1")
    with _run():
        odd = await _call(
            tool, action="report", standing_id="st_1", outcome="great", summary="x"
        )
        # ``failed`` and ``skipped`` are written by the app, never reported by a model.
        apps = await _call(
            tool, action="report", standing_id="st_1", outcome="failed", summary="x"
        )
        empty = await _call(tool, action="report", standing_id="st_1", outcome="asked")
        quiet = await _call(tool, action="report", standing_id="st_1", outcome="quiet")
    assert not odd.success and "quiet" in odd.error
    assert not apps.success and apps.output == {"code": "invalid"}
    assert not empty.success and "summary" in empty.error
    assert quiet.success and len(service.called("report")) == 1


async def test_a_note_is_added_from_any_turn(tool, service) -> None:
    service.add("st_1")
    with _owner("the campaign budget is 50 EUR a day"):
        result = await _call(
            tool, action="note", standing_id="st_1", text="Budget is 50 EUR a day."
        )
        empty = await _call(tool, action="note", standing_id="st_1")
    assert result.success and result.output["notes"] == "Budget is 50 EUR a day."
    assert not empty.success


# ------------------------------------------------------------------ reads


async def test_list_and_status_read_back_tasks_and_runs(tool, service) -> None:
    service.add("st_1", notes="n" * 900)
    service.add("st_old", state="ended")
    service.runs["st_1"] = [
        StandingRun("sr_1", "st_1", NOW_MS, "quiet", "No change.", (), 180, RUN)
    ]
    listed = await _call(tool, action="list")
    everything = await _call(tool, action="status", include_ended=True)
    one = await _call(tool, action="status", standing_id="st_1")
    assert [t["id"] for t in listed.output["tasks"]] == ["st_1"]
    assert len(listed.output["tasks"][0]["notes"]) == 400  # a list quotes the notes, cut
    assert {t["id"] for t in everything.output["tasks"]} == {"st_1", "st_old"}
    assert one.output["task"]["notes"] == "n" * 900
    assert one.output["task"]["pace"] == "every 3 hours"
    assert one.output["runs"] == [service.runs["st_1"][0].to_dict()]


# ------------------------------------------------------------------ failures


@pytest.mark.parametrize(
    ("code", "message", "expected"),
    [
        ("not_found", "No standing task st_x.", "No standing task st_x. Use action list"),
        ("invalid", "The goal is too long.", "The goal is too long."),
        ("state", "An ended task cannot be paused.", "An ended task cannot be paused."),
        ("limit", "12 standing tasks are open already.", "12 standing tasks are open already."),
        ("unavailable", "the agent society is not running", "Standing tasks are unavailable"),
    ],
)
async def test_service_refusals_read_as_plain_failures(
    tool, service, code, message, expected
) -> None:
    service.add("st_1")
    service.fail = StandingError(code, message)
    result = await _call(tool, action="pause", standing_id="st_1")
    assert not result.success and result.output == {"code": code}
    assert expected in result.error and message in result.error


async def test_unknown_ids_actions_and_a_broken_store_fail_readably(tool, service) -> None:
    missing = await _call(tool, action="status", standing_id="st_nope")
    no_id = await _call(tool, action="pause")
    unknown = await _call(tool, action="delete")
    service.fail = RuntimeError("database is locked")
    broken = await _call(tool, action="list")
    assert not missing.success and missing.output == {"code": "not_found"}
    assert not no_id.success and "standing_id" in no_id.error
    assert not unknown.success and "take_on" in unknown.error
    assert not broken.success and broken.output == {"code": "unavailable"}
    assert "database is locked" in broken.error


# ------------------------------------------------------------------ the tool's own contract


def test_reads_reports_and_proposals_need_no_card_everything_else_is_monitored(tool) -> None:
    for action in ("list", "status", "report", "note", "propose"):
        assert tool.risk_tier_for_args({"action": action}) == "safe", action
    for action in ("take_on", "accept", "decline", "update", "pause", "resume", "end", "run_now"):
        assert tool.risk_tier_for_args({"action": action}) == "monitor", action
    assert tool.read_only_for_args({"action": "status"})
    assert not tool.read_only_for_args({"action": "report"})
    # A run nobody started may report without the reversibility gate asking for approval.
    assert reversibility_of(tool, {"action": "report"}, tier="monitor") == "reversible"
    assert tool.describe_args({"action": "list"}) == {"level": "read"}
    assert tool.describe_args({"action": "pause", "standing_id": "st_1"}) == {
        "level": "modify", "task": "st_1",
    }


def test_the_description_says_when_to_use_it_and_the_schema_follows_the_models(tool) -> None:
    text = tool.description
    for needle in ("no end date", "not a routine", "is a routine", "is a project", "proposal"):
        assert needle in text, needle
    properties = tool.schema["properties"]
    assert properties["autonomy"]["enum"] == list(AUTONOMY)
    assert properties["outcome"]["enum"] == list(REPORTABLE)
    assert set(properties["action"]["enum"]) == {
        "take_on", "propose", "accept", "decline", "list", "status", "update", "pause",
        "resume", "end", "run_now", "report", "note",
    }
    assert tool.schema["required"] == ["action"]


def test_the_fake_service_has_the_real_services_signatures() -> None:
    """The tool is tested against a fake; this pins the fake to the real functions."""
    import importlib

    try:
        real = importlib.import_module("dodaios.standing_tasks.service")
    except ImportError:
        pytest.skip("dodaios.standing_tasks.service is not in this checkout yet")
    fake = FakeStandingService()
    for name in (
        "list_tasks", "get_task", "runs_of", "propose", "take_on", "accept", "decline",
        "update", "pause", "resume", "end", "run_now", "report", "add_note", "overview",
    ):
        wanted = inspect.signature(getattr(real, name))
        have = inspect.signature(getattr(fake, name))
        assert list(have.parameters) == list(wanted.parameters), name
        assert inspect.iscoroutinefunction(getattr(real, name)), name
