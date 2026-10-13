"""Several spoken orders at once: actions run side by side and report back later.

A live call used to run one tool at a time and to hold every later order until
the running one returned. ``LiveTools`` now runs independent actions in
parallel and hands an action the user has moved on from to the background;
the session tells its receipt at the next pause, naming the request it answers.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from jarvis.core.protocols import SupervisorToolDescriptor
from jarvis.cu.direct import tool_schema
from jarvis.live import native
from jarvis.live import tools as live_tools
from jarvis.live.native import NativeLiveVoiceSession
from jarvis.live.state import LiveLedger
from jarvis.live.tools import LiveTools
from jarvis.realtime.protocol import RealtimeEvent
from tests.fakes.fake_native_voice import (
    FakeNativeConnection,
    FakeToolGateway,
    gemini_like_provider,
    local_voice_like_provider,
)

# Hang guard only, never the measured quantity.
_HANG_GUARD_S = 30.0
_FIRST_ORDER = "Brief the agent in terminal two about the login bug."
_SECOND_ORDER = "And create a new agent for the documentation."
_SCREEN_STEPS = {"steps": [{"action": "screenshot"}]}

PROVIDERS = {"gemini-like": gemini_like_provider, "local-voice-like": local_voice_like_provider}
both_providers = pytest.mark.parametrize("make_provider", PROVIDERS.values(), ids=PROVIDERS)


def _catalog() -> tuple[SupervisorToolDescriptor, ...]:
    return (
        SupervisorToolDescriptor("brief-agent", "Send an agent its task", {"type": "object"},
                                 "monitor", is_action_tool=True),
        SupervisorToolDescriptor("create-agent", "Create an agent", {"type": "object"},
                                 "monitor", is_action_tool=True),
        SupervisorToolDescriptor("search_web", "Search the web.", {"type": "object"}, "safe"),
        SupervisorToolDescriptor("computer", "Operate the screen", tool_schema(), "monitor"),
    )


def _call(name: str, args: dict | None = None) -> tuple[str, dict]:
    return "call_tool", {"name": name, "arguments_json": json.dumps(args or {})}


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    # The grace only decides how long a nearly finished action may still answer
    # its own call; the tests that need it set their own value.
    monkeypatch.setattr(live_tools, "MOVE_ON_GRACE_S", 0.01)
    gateway = FakeToolGateway(_catalog())
    ledger = LiveLedger(tmp_path / "live.sqlite3")
    tools = LiveTools(gateway, ledger, "call", language="en", backend_model="")
    tools.user_text = _FIRST_ORDER
    yield tools, gateway
    ledger.close()


# Parallel execution ------------------------------------------------------------


@pytest.mark.asyncio
async def test_independent_actions_run_side_by_side(runtime):
    tools, gateway = runtime
    release = gateway.hold("brief-agent")
    first = asyncio.create_task(tools.execute("c1", *_call("brief-agent"), 0))
    await asyncio.wait_for(gateway.execution_started.wait(), _HANG_GUARD_S)
    second = await asyncio.wait_for(
        tools.execute("c2", *_call("create-agent"), 0), _HANG_GUARD_S
    )
    assert second["success"] is True
    assert not first.done()  # the first order is still running
    release.set()
    assert (await asyncio.wait_for(first, _HANG_GUARD_S))["success"] is True
    assert gateway.finished == ["create-agent", "brief-agent"]


@pytest.mark.asyncio
async def test_the_screen_is_never_operated_by_two_calls_at_once(runtime):
    tools, gateway = runtime
    release = gateway.hold("computer")
    first = asyncio.create_task(tools.execute("c1", "computer", _SCREEN_STEPS, 0))
    await asyncio.wait_for(gateway.execution_started.wait(), _HANG_GUARD_S)
    second = asyncio.create_task(tools.execute("c2", "computer", _SCREEN_STEPS, 0))
    await asyncio.sleep(0.05)
    assert len(gateway.calls) == 1  # the second waits for the screen
    release.set()
    await asyncio.wait_for(asyncio.gather(first, second), _HANG_GUARD_S)
    assert len(gateway.calls) == 2


@pytest.mark.asyncio
async def test_one_call_seen_on_two_transports_executes_once(runtime):
    tools, gateway = runtime
    release = gateway.hold("brief-agent")
    first = asyncio.create_task(tools.execute("c1", *_call("brief-agent"), 0))
    await asyncio.wait_for(gateway.execution_started.wait(), _HANG_GUARD_S)
    copy = asyncio.create_task(tools.execute("c1", *_call("brief-agent"), 0))
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.wait_for(asyncio.gather(first, copy), _HANG_GUARD_S)
    assert [result["success"] for result in results] == [True, True]
    assert len(gateway.calls) == 1


# Leaving the turn ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_action_the_user_moved_on_from_becomes_a_background_task(runtime):
    tools, gateway = runtime
    release = gateway.hold("brief-agent")
    finished = []
    tools.on_task_finished = finished.append
    pending = asyncio.create_task(
        tools.execute_releasable("c1", *_call("brief-agent", {"agent": "T2"}), tools.revision)
    )
    await asyncio.wait_for(gateway.execution_started.wait(), _HANG_GUARD_S)
    tools.user_text = _SECOND_ORDER
    tools.revision += 1

    receipt = await asyncio.wait_for(pending, _HANG_GUARD_S)
    assert receipt["pending"] is True and receipt["success"] is False
    assert receipt["task_id"] == "task-1"
    assert gateway.finished == []  # nothing was cancelled
    task = tools.tasks.get("task-1")
    assert task.running and task.tool == "brief-agent"
    assert task.request_text == _FIRST_ORDER  # the order it answers, not the newer one
    assert task.obsolete_on_new_request is False
    assert [row["task_id"] for row in receipt["background_tasks"]] == ["task-1"]

    release.set()
    await asyncio.wait_for(task.work, _HANG_GUARD_S)
    assert finished == [task]
    assert task.status == "done" and task.result["success"] is True
    assert "superseded" not in task.result
    assert tools.ledger.operation("call", "c1")["success"] is True


@pytest.mark.asyncio
async def test_an_action_about_to_finish_still_answers_its_own_call(runtime, monkeypatch):
    monkeypatch.setattr(live_tools, "MOVE_ON_GRACE_S", _HANG_GUARD_S)
    tools, gateway = runtime
    release = gateway.hold("brief-agent")
    pending = asyncio.create_task(
        tools.execute_releasable("c1", *_call("brief-agent"), tools.revision)
    )
    await asyncio.wait_for(gateway.execution_started.wait(), _HANG_GUARD_S)
    tools.revision += 1
    release.set()
    receipt = await asyncio.wait_for(pending, _HANG_GUARD_S)
    assert receipt["success"] is True and "pending" not in receipt
    assert len(tools.tasks) == 0


@pytest.mark.asyncio
async def test_a_lookup_is_not_handed_to_the_background_by_new_speech(runtime):
    tools, gateway = runtime
    release = gateway.hold("search_web")
    pending = asyncio.create_task(
        tools.execute_releasable("c1", *_call("search_web"), tools.revision)
    )
    await asyncio.wait_for(gateway.execution_started.wait(), _HANG_GUARD_S)
    tools.revision += 1
    await asyncio.sleep(0.05)
    assert not pending.done()  # its answer belongs to the question that asked it
    release.set()
    receipt = await asyncio.wait_for(pending, _HANG_GUARD_S)
    assert receipt["success"] is True and len(tools.tasks) == 0


@pytest.mark.asyncio
async def test_a_deadline_releases_any_call_and_marks_what_goes_stale(runtime):
    tools, gateway = runtime
    release = gateway.hold("search_web")
    receipt = await asyncio.wait_for(
        tools.execute_releasable("c1", *_call("search_web"), tools.revision, deadline_s=0.01),
        _HANG_GUARD_S,
    )
    assert receipt["pending"] is True and "still running" in receipt["error"]
    task = tools.tasks.get(receipt["task_id"])
    assert task.obsolete_on_new_request is True  # a lookup only answers its own question
    release.set()
    await asyncio.wait_for(task.work, _HANG_GUARD_S)


# Asking about and stopping tasks ---------------------------------------------------


async def _released(tools, gateway, name="brief-agent"):
    gateway.hold(name)
    receipt = await asyncio.wait_for(
        tools.execute_releasable("c1", *_call(name), tools.revision, deadline_s=0.01),
        _HANG_GUARD_S,
    )
    return tools.tasks.get(receipt["task_id"])


@pytest.mark.asyncio
async def test_task_status_lists_what_runs_and_what_came_of_it(runtime):
    tools, gateway = runtime
    task = await _released(tools, gateway)
    listed = await tools.execute("c2", "task_status", {}, tools.revision)
    assert listed["success"] is True
    assert [(row["task_id"], row["status"]) for row in listed["tasks"]] == [("task-1", "running")]
    assert listed["tasks"][0]["requested"] == _FIRST_ORDER

    gateway.gates["brief-agent"].set()
    await asyncio.wait_for(task.work, _HANG_GUARD_S)
    listed = await tools.execute("c3", "task_status", {}, tools.revision)
    assert listed["tasks"][0]["status"] == "done"
    assert listed["tasks"][0]["result"]["success"] is True


@pytest.mark.asyncio
async def test_task_status_is_answered_even_after_the_user_said_more(runtime):
    tools, gateway = runtime
    await _released(tools, gateway)
    asked_at = tools.revision
    tools.revision += 1
    listed = await tools.execute("c2", "task_status", {}, asked_at)
    assert listed["success"] is True and listed["tasks"]


@pytest.mark.asyncio
async def test_one_task_can_be_stopped_by_its_id(runtime):
    tools, gateway = runtime
    task = await _released(tools, gateway)
    finished = []
    tools.on_task_finished = finished.append
    stopped = await tools.execute("c2", "task_status", {"cancel": "task-1"}, tools.revision)
    assert stopped["success"] is True and stopped["cancelled"] == "task-1"
    await asyncio.gather(task.work, return_exceptions=True)
    assert task.status == "cancelled" and gateway.finished == []
    assert finished == [task]
    again = await tools.execute("c3", "task_status", {"cancel": "task-1"}, tools.revision)
    assert again["success"] is False


@pytest.mark.asyncio
async def test_stop_cancels_every_running_background_task(runtime):
    tools, gateway = runtime
    task = await _released(tools, gateway)
    await tools.cancel_work()
    await asyncio.gather(task.work, return_exceptions=True)
    assert task.status == "cancelled"
    assert tools.tasks.running() == []


# The session tells the result ------------------------------------------------------


def _in_call(provider, tmp_path, gateway):
    async def send(_frame):
        return None

    session = NativeLiveVoiceSession(
        session_id="native-live",
        send_json=send,
        send_binary=send,
        providers=[provider],
        config=SimpleNamespace(
            brain=SimpleNamespace(reply_language="en", providers={}, realtime=None),
            voice=SimpleNamespace(realtime_tool_declaration_budget_tokens=0),
        ),
    )
    connection = FakeNativeConnection(creates_responses_automatically=provider._creates, model="m")
    ledger = LiveLedger(tmp_path / f"{provider.name}.sqlite3")
    session._connection = connection
    session._ledger = ledger
    session._tools = LiveTools(gateway, ledger, "native-live", language="en", backend_model="")
    session._tools.user_text = _FIRST_ORDER
    return session, connection


async def _settle(session) -> None:
    for _ in range(5):
        await asyncio.sleep(0)
    await asyncio.gather(*session._control_tasks, return_exceptions=True)


def _reports(connection) -> list[str]:
    return [payload for name, payload in connection.calls if name == "send_text"]


async def _order_then_move_on(session, connection, gateway):
    """The first order's action is running when the user gives the second order."""
    await session._native_event(RealtimeEvent(
        type="tool_call", call_id="c1", tool_name="call_tool",
        tool_args={"name": "brief-agent", "arguments_json": "{}"},
    ))
    await asyncio.wait_for(gateway.execution_started.wait(), _HANG_GUARD_S)
    await session._native_event(
        RealtimeEvent(type="input_transcript", text=_SECOND_ORDER, is_final=True)
    )
    await asyncio.wait_for(connection.tool_result_sent.wait(), _HANG_GUARD_S)
    await session._native_event(RealtimeEvent(type="turn_complete"))
    await _settle(session)


@pytest.fixture
def held_action(tmp_path, monkeypatch):
    # The voice budget must not be what releases the model in these tests.
    monkeypatch.setattr(native, "_TOOL_DEADLINE_S", _HANG_GUARD_S)
    monkeypatch.setattr(live_tools, "MOVE_ON_GRACE_S", 0.01)
    sessions = []

    def build(make_provider):
        gateway = FakeToolGateway(_catalog())
        release = gateway.hold("brief-agent")
        session, connection = _in_call(make_provider(), tmp_path, gateway)
        sessions.append(session)
        return session, connection, gateway, release

    yield build
    for session in sessions:
        session._cancel_report_timeout()
        session._ledger.close()


@both_providers
@pytest.mark.asyncio
async def test_the_model_is_free_for_the_next_order_while_the_first_still_runs(
    held_action, make_provider,
):
    session, connection, gateway, release = held_action(make_provider)
    await _order_then_move_on(session, connection, gateway)
    _, _, receipt = connection.tool_results[0]
    assert receipt["pending"] is True and receipt["task_id"] == "task-1"
    assert gateway.finished == []
    # A running background task keeps nobody waiting: other results may be told.
    assert not session._has_pending_work()
    assert session.ready_for_report
    release.set()
    await asyncio.wait_for(asyncio.gather(*session._background_work), _HANG_GUARD_S)


@both_providers
@pytest.mark.asyncio
async def test_the_result_is_told_at_a_pause_with_the_request_it_answers(
    held_action, make_provider,
):
    session, connection, gateway, release = held_action(make_provider)
    await _order_then_move_on(session, connection, gateway)
    assert _reports(connection) == []
    release.set()
    await asyncio.wait_for(asyncio.gather(*session._background_work), _HANG_GUARD_S)
    await _settle(session)

    reports = _reports(connection)
    assert len(reports) == 1  # told although the user has said more since
    assert "background_task_completion" in reports[0]
    assert "task-1" in reports[0] and _FIRST_ORDER in reports[0]
    assert _SECOND_ORDER not in reports[0]
    assert len(connection.tool_results) == 1  # never a second function response
    assert gateway.calls == [("brief-agent", {})]  # and never a repeated action


@both_providers
@pytest.mark.asyncio
async def test_the_result_waits_while_the_user_is_speaking(held_action, make_provider):
    session, connection, gateway, release = held_action(make_provider)
    await _order_then_move_on(session, connection, gateway)
    session._input_active = True
    release.set()
    await asyncio.wait_for(asyncio.gather(*session._background_work), _HANG_GUARD_S)
    await _settle(session)
    assert _reports(connection) == []
    session._input_active = False
    session._notify_pause()
    await _settle(session)
    assert len(_reports(connection)) == 1


@both_providers
@pytest.mark.asyncio
async def test_a_result_the_call_never_voiced_stays_owed_but_not_forever(
    held_action, make_provider,
):
    session, connection, gateway, release = held_action(make_provider)
    await _order_then_move_on(session, connection, gateway)
    release.set()
    await asyncio.wait_for(asyncio.gather(*session._background_work), _HANG_GUARD_S)
    await _settle(session)
    for expected in (2, 3, 3):
        session._report_start_timed_out()  # the model never started answering
        await _settle(session)
        assert len(_reports(connection)) == expected
    assert session._task_reports == []


@both_providers
@pytest.mark.asyncio
async def test_a_stopped_task_is_not_reported(held_action, make_provider):
    session, connection, gateway, release = held_action(make_provider)
    await _order_then_move_on(session, connection, gateway)
    await session._tools.cancel_work()
    await _settle(session)
    session._notify_pause()
    await _settle(session)
    assert _reports(connection) == []
    assert gateway.finished == []


# The continuous session (function calls answered on the backend wire) ---------------


class _Wire:
    """Records what the continuous session sends to its provider."""

    answer_sdp = ""

    def __init__(self) -> None:
        self.frames: list[dict] = []

    async def send(self, frame: dict) -> None:
        self.frames.append(frame)

    async def close(self) -> None:
        return None

    def outputs(self) -> list[dict]:
        return [
            json.loads(frame["item"]["output"]) for frame in self.frames
            if frame.get("item", {}).get("type") == "function_call_output"
        ]

    def reports(self) -> list[str]:
        return [
            frame["item"]["content"][0]["text"] for frame in self.frames
            if frame.get("item", {}).get("type") == "message"
        ]


@pytest.mark.asyncio
async def test_the_continuous_session_releases_and_reports_the_same_way(tmp_path, monkeypatch):
    from jarvis.live.session import LiveVoiceSession

    monkeypatch.setattr(live_tools, "MOVE_ON_GRACE_S", 0.01)

    async def send(_frame):
        return None

    session = LiveVoiceSession(
        session_id="live", bus=None, send_json=send, send_binary=send,
        providers=[SimpleNamespace(name="test")],
        config=SimpleNamespace(brain=SimpleNamespace(reply_language="en")),
    )
    wire = _Wire()
    gateway = FakeToolGateway(_catalog())
    release = gateway.hold("brief-agent")
    ledger = LiveLedger(tmp_path / "live.sqlite3")
    session._connection = wire
    session._ledger = ledger
    session._tools = LiveTools(gateway, ledger, "live", language="en", backend_model="")
    session._tools.user_text = _FIRST_ORDER
    try:
        name, args = _call("brief-agent")
        calls = asyncio.create_task(session._run_calls(
            [{"call_id": "c1", "name": name, "arguments": json.dumps(args)}],
            session._tools.revision,
        ))
        await asyncio.wait_for(gateway.execution_started.wait(), _HANG_GUARD_S)
        session._tools.user_text = _SECOND_ORDER
        session._tools.revision += 1
        await asyncio.wait_for(calls, _HANG_GUARD_S)
        assert wire.outputs()[0]["pending"] is True  # the backend is free for the next order
        assert wire.outputs()[0]["task_id"] == "task-1"
        assert wire.frames[-1] == {"type": "response.create"}
        assert wire.reports() == []

        release.set()
        await asyncio.wait_for(asyncio.gather(*session._background_work), _HANG_GUARD_S)
        await _settle(session)
        reports = wire.reports()
        assert len(reports) == 1
        assert "background_task_completion" in reports[0] and _FIRST_ORDER in reports[0]
        assert len(wire.outputs()) == 1  # the receipt is a report, never a second output
    finally:
        session._cancel_report_timeout()
        ledger.close()


# Approvals, listings and report bookkeeping -----------------------------------------


@pytest.mark.asyncio
async def test_a_released_action_that_needs_approval_keeps_its_question(runtime):
    """The order is not dropped as superseded: its yes is asked with the report."""
    from jarvis.core.protocols import ToolResult
    from jarvis.safety.tool_executor import VOICE_CONFIRM_SENTINEL

    tools, gateway = runtime
    gateway.results["brief-agent"] = ToolResult(
        False, {"impact": "sends a task"}, VOICE_CONFIRM_SENTINEL
    )
    release = gateway.hold("brief-agent")
    pending = asyncio.create_task(
        tools.execute_releasable("c1", *_call("brief-agent"), tools.revision)
    )
    await asyncio.wait_for(gateway.execution_started.wait(), _HANG_GUARD_S)
    tools.revision += 1
    receipt = await asyncio.wait_for(pending, _HANG_GUARD_S)
    task = tools.tasks.get(receipt["task_id"])
    release.set()
    await asyncio.wait_for(task.work, _HANG_GUARD_S)
    assert task.status == "needs_approval"
    assert task.result["confirmation_required"] is True
    approval_id = task.result["approval_id"]
    assert approval_id in tools._pending  # the question is still open

    # A yes the user gave to something else, before this question was told,
    # must not approve it.
    tools.user_text = "yes"
    tools.revision += 1
    early = await tools.execute(
        "c2", "confirm_action", {"approval_id": approval_id}, tools.revision
    )
    assert early["success"] is False and approval_id in tools._pending
    # Once the report was told, a yes said after it counts.
    tools.approval_presented(approval_id)
    same_yes = await tools.execute(
        "c3", "confirm_action", {"approval_id": approval_id}, tools.revision
    )
    assert same_yes["success"] is False  # still the earlier yes
    tools.revision += 1
    approved = await tools.execute(
        "c4", "confirm_action", {"approval_id": approval_id}, tools.revision
    )
    assert approved["success"] is True and approval_id not in tools._pending


@pytest.mark.asyncio
async def test_an_approval_reached_in_the_grace_after_moving_on_is_kept(runtime, monkeypatch):
    """Whether the question survives must not depend on how fast it was reached."""
    from jarvis.core.protocols import ToolResult
    from jarvis.safety.tool_executor import VOICE_CONFIRM_SENTINEL

    monkeypatch.setattr(live_tools, "MOVE_ON_GRACE_S", _HANG_GUARD_S)
    tools, gateway = runtime
    gateway.results["brief-agent"] = ToolResult(False, {}, VOICE_CONFIRM_SENTINEL)
    release = gateway.hold("brief-agent")
    call = asyncio.create_task(
        tools.execute_releasable("c1", *_call("brief-agent"), tools.revision)
    )
    await asyncio.wait_for(gateway.execution_started.wait(), _HANG_GUARD_S)
    tools.revision += 1
    release.set()  # the gate answers inside the grace: the call was not released
    result = await asyncio.wait_for(call, _HANG_GUARD_S)
    assert result["confirmation_required"] is True and result["approval_id"] in tools._pending
    assert len(tools.tasks) == 0


@pytest.mark.asyncio
async def test_an_overtaken_call_nobody_waits_for_still_withdraws_its_approval(runtime):
    from jarvis.core.protocols import ToolResult
    from jarvis.safety.tool_executor import VOICE_CONFIRM_SENTINEL

    tools, gateway = runtime
    gateway.results["brief-agent"] = ToolResult(False, {}, VOICE_CONFIRM_SENTINEL)
    release = gateway.hold("brief-agent")
    call = asyncio.create_task(tools.execute("c1", *_call("brief-agent"), tools.revision))
    await asyncio.wait_for(gateway.execution_started.wait(), _HANG_GUARD_S)
    tools.revision += 1
    release.set()
    result = await asyncio.wait_for(call, _HANG_GUARD_S)
    assert result["status"] == "superseded" and tools._pending == {}


class _SlowApprovalGateway(FakeToolGateway):
    """The approved effect itself takes long (a delivery, an upload)."""

    def __init__(self) -> None:
        super().__init__(_catalog())
        self.confirmed_started = asyncio.Event()
        self.confirm = asyncio.Event()

    async def execute_confirmed(self, trace, request):
        from jarvis.core.protocols import ToolResult

        del trace, request
        self.confirmed_started.set()
        await self.confirm.wait()
        return ToolResult(True, {"verified": True})


@pytest.mark.asyncio
async def test_an_approved_effect_leaves_its_turn_like_any_other_action(tmp_path, monkeypatch):
    from jarvis.core.protocols import ToolResult
    from jarvis.safety.tool_executor import VOICE_CONFIRM_SENTINEL

    monkeypatch.setattr(live_tools, "MOVE_ON_GRACE_S", 0.01)
    gateway = _SlowApprovalGateway()
    gateway.results["brief-agent"] = ToolResult(False, {}, VOICE_CONFIRM_SENTINEL)
    ledger = LiveLedger(tmp_path / "live.sqlite3")
    tools = LiveTools(gateway, ledger, "call", language="en", backend_model="")
    tools.user_text = _FIRST_ORDER
    try:
        asked = await tools.execute("c1", *_call("brief-agent", {"agent": "T2"}), tools.revision)
        tools.user_text = "yes"
        tools.revision += 1
        approved = asyncio.create_task(tools.execute_releasable(
            "c2", "confirm_action", {"approval_id": asked["approval_id"]}, tools.revision
        ))
        await asyncio.wait_for(gateway.confirmed_started.wait(), _HANG_GUARD_S)
        # The hang-up control is not held up by the running effect.
        ended = await asyncio.wait_for(tools.execute("c3", "end_call", {}, tools.revision), 5)
        assert ended["success"] is False  # nobody asked to hang up; it answered at once
        # The same yes delivered a second time is told what is happening.
        twice = await tools.execute(
            "c4", "confirm_action", {"approval_id": asked["approval_id"]}, tools.revision
        )
        assert twice["status"] == "already_running"
        tools.user_text = _SECOND_ORDER
        tools.revision += 1
        receipt = await asyncio.wait_for(approved, _HANG_GUARD_S)
        assert receipt["pending"] is True
        task = tools.tasks.get(receipt["task_id"])
        assert task.tool == "brief-agent" and task.arguments == {"agent": "T2"}
        gateway.confirm.set()
        await asyncio.wait_for(task.work, _HANG_GUARD_S)
        assert task.status == "done"
    finally:
        gateway.confirm.set()
        ledger.close()


@pytest.mark.asyncio
async def test_task_status_shows_no_pictures_and_no_page_long_results(runtime):
    from jarvis.core.protocols import ToolResult

    tools, gateway = runtime
    gateway.results["brief-agent"] = ToolResult(
        True,
        {"log": "line of output. " * 600, "_image": {"mime": "image/png", "data": "QUJD" * 4000}},
    )
    task = await _released(tools, gateway)
    gateway.gates["brief-agent"].set()
    await asyncio.wait_for(task.work, _HANG_GUARD_S)
    listed = await tools.execute("c2", "task_status", {}, tools.revision)
    shown = json.dumps(listed)
    assert "QUJDQUJD" not in shown and len(shown) < 4000
    assert listed["tasks"][0]["status"] == "done"
    # The report still has the whole result, picture included.
    assert any(item.get("type") == "image" for item in task.result["artifacts"])
    assert len(task.result["output"]["log"]) > 9000


@both_providers
@pytest.mark.asyncio
async def test_a_report_that_was_never_sent_does_not_claim_the_next_outcome(
    held_action, make_provider,
):
    """Otherwise an agent's reply voiced later would be settled as this task's."""
    session, connection, gateway, release = held_action(make_provider)
    await _order_then_move_on(session, connection, gateway)

    async def overtaken(_task):
        return True  # dropped while preparing: nothing went to the model

    session._deliver_task_report = overtaken
    release.set()
    await asyncio.wait_for(asyncio.gather(*session._background_work), _HANG_GUARD_S)
    await _settle(session)
    assert session._task_report_told is None
    assert _reports(connection) == []


@both_providers
@pytest.mark.asyncio
async def test_a_background_approval_can_be_given_once_its_question_was_told(
    held_action, make_provider,
):
    import sys

    from jarvis.core.protocols import ToolResult
    from jarvis.safety.tool_executor import VOICE_CONFIRM_SENTINEL

    session, connection, gateway, release = held_action(make_provider)
    gateway.results["brief-agent"] = ToolResult(False, {}, VOICE_CONFIRM_SENTINEL)
    await _order_then_move_on(session, connection, gateway)
    release.set()
    await asyncio.wait_for(asyncio.gather(*session._background_work), _HANG_GUARD_S)
    await _settle(session)
    tools = session._tools
    approval_id = next(iter(tools._pending))
    assert tools._pending[approval_id][3] == sys.maxsize  # nobody has heard the question
    assert "needs_approval" in _reports(connection)[0]

    # The model tells the question: its reply to the report ends.
    await session._native_event(RealtimeEvent(type="output_transcript_delta", text="May I?"))
    await session._native_event(RealtimeEvent(type="turn_complete"))
    assert tools._pending[approval_id][3] == tools.revision
    tools.user_text = "yes"
    tools.revision += 1
    approved = await tools.execute(
        "c9", "confirm_action", {"approval_id": approval_id}, tools.revision
    )
    assert approved["success"] is True
