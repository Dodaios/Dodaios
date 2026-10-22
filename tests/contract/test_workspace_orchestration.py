"""Addressed coding delivery is independent of UI focus and voice provider."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from dodaios.agentic_ide import library, orchestration, resume_store, task_state
from dodaios.agentic_ide.folders import probe_project
from dodaios.agentic_ide.orchestration import WorkspaceOrchestrator
from dodaios.agentic_ide.session import (
    AgentBusyError,
    Registry,
    Session,
    Terminal,
)
from dodaios.brain.tool_gateway import BrainSupervisorToolGateway
from dodaios.brain.workspace_tool import WorkspaceOrchestrationTool
from dodaios.core.protocols import ExecutionContext, SupervisorToolRequest
from dodaios.live.state import LiveLedger
from dodaios.live.tools import LiveTools
from tests.fakes.fake_pty_manager import FakePtyManager


class Sessions:
    """The coding-session gateway; ``refused`` is a pane in a running turn."""

    def __init__(self):
        self.calls = []
        self.fail = False
        self.refused = False
        self.steerable = True  # the CLI takes input mid-turn
        self.settles = True  # Stop ends the turn in time
        self.typed = []  # every prompt that actually reached the pane

    async def run(self, args):
        self.calls.append(args)
        await asyncio.sleep(0)
        mid_turn = False
        if self.refused:
            mode = args.get("when_busy", "refuse") if args["action"] == "send" else "refuse"
            if mode == "steer" and self.steerable:
                mid_turn = True
            elif mode == "interrupt" and self.settles:
                self.refused = False
            else:
                raise AgentBusyError(
                    "The selected coding agent is busy; nothing was sent.",
                    interrupted=mode == "interrupt",
                )
        if self.fail:
            raise RuntimeError("transport interrupted after possible write")
        if args["action"] in {"input", "observe"}:
            return {"input_token": "token-1", "response_mode": "dialog", "screen_excerpt": "?"}
        if args["action"] == "send":
            self.typed.append(args["prompt"])
        return {"delivery": "accepted", "submitted": True, "completed": False,
                **({"mid_turn": True} if mid_turn else {})}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    # The panes below are stamped idle once, at setup. A slow runner can take
    # longer than the stamp's freshness window to reach the step under test,
    # and the pane then reads as unknown instead of idle; keep it fresh here.
    from dodaios.agentic_ide import activity

    # These fake panes have no resume or PTY identity, so separate rigs can
    # share a task-state cache key. Never let one test's lifecycle evidence
    # decide whether another test's freshly-created pane is available.
    task_state.reset()
    monkeypatch.setattr(activity, "STAMP_FRESH_S", 3600.0)
    monkeypatch.setattr(library, "_root", lambda: tmp_path / "library")
    monkeypatch.setattr(resume_store, "_store_path", lambda: tmp_path / "snapshot.json")
    registry = Registry(pty_manager=FakePtyManager())
    for name in ("Personal Jarvis", "Other project"):
        path = tmp_path / name
        path.mkdir()
        project = library.ensure_project(path)
        term = Terminal(
            "t1",
            "Alex",
            "codex",
            "Codex",
            0,
            status="live",
            activity="idle",
            activity_at=time.time(),
        )
        workspace = Session(
            id=uuid4().hex,
            folder=str(path),
            name=name,
            profile=probe_project(path),
            terminals=[term],
            created_at=1,
            project_id=project.id,
        )
        registry._sessions[workspace.id] = workspace
        registry._active = workspace.id
    ledger = LiveLedger(tmp_path / "receipts.db")
    sessions = Sessions()
    orchestrator = WorkspaceOrchestrator(registry, sessions, ledger)
    try:
        yield orchestrator, registry, sessions
    finally:
        try:
            ledger.close()
        finally:
            task_state.reset()


async def target(rig, **refs):
    result = await rig[0].run({"action": "resolve", **refs})
    assert result["status"] == "resolved", result
    return result["target"]


def test_rig_clears_stale_task_state_before_setup(tmp_path, monkeypatch, request):
    now = time.time()
    term = Terminal("stale", "Stale", "codex", "Codex", 0, status="live")
    key = task_state._key(term)
    stale = task_state.Evidence("stopped", at=now, checked_at=now)
    task_state._readings[key] = stale
    task_state._files[key] = (("stale.jsonl", 0, 0), stale)

    request.getfixturevalue("rig")

    assert task_state.evidence(term) is None
    assert task_state._files == {}


async def test_named_background_workspace_wins_without_ui_switch(rig):
    before = rig[1].active_id
    resolved = await target(rig, workspace="Personal Jarvis")
    receipt = await rig[0].run(
        {
            "action": "send",
            **resolved,
            "prompt": "Fix the Linux installer",
            "request_id": uuid4().hex,
        }
    )
    assert receipt["target"] == {
        k: resolved[k] for k in ("project_id", "workspace_id", "terminal_id")
    }
    assert receipt["submitted"] and receipt["completed"] is False
    assert rig[2].calls[0]["workspace_id"] != before
    assert rig[1].active_id == before


async def test_no_reference_uses_visible_workspace_without_focused_pane(rig):
    resolved = await target(rig)
    assert resolved["workspace_id"] == rig[1].active_id
    assert rig[1].session.surface_terminal == ""


@pytest.mark.parametrize("reference", ["", "idle", "free", "available", "empty", "unused"])
async def test_free_session_prefers_empty_over_interrupted_and_completed(rig, reference):
    owner = rig[1].session
    interrupted = owner.terminals[0]
    interrupted.activity = "stopped"
    interrupted.prompts_sent = 1
    owner.terminals.extend([
        Terminal("t2", "Completed", "codex", "Codex", 1, status="live",
                 activity="waiting", activity_at=time.time(), prompts_sent=2),
        Terminal("t3", "Fresh", "codex", "Codex", 2, status="live",
                 activity="waiting", activity_at=time.time()),
    ])
    result = await rig[0].run({"action": "resolve", "workspace": owner.name, "agent": reference})
    assert result["target"]["terminal_id"] == "pane:" + owner.terminals[-1].history_id
    assert result["selection"] == "empty_session"
    assert result["session"]["has_history"] is False
    assert not rig[2].calls


@pytest.mark.parametrize("word", ["working", "asking", "starting", "stopped", "failed", "unknown"])
async def test_automatic_selection_excludes_unavailable_activity(rig, word):
    rig[1].session.terminals[0].activity = word
    result = await rig[0].run({"action": "resolve", "agent": "free"})
    assert result["status"] == "unavailable"
    assert not rig[2].calls


async def test_empty_selector_does_not_reuse_completed_conversation(rig):
    rig[1].session.terminals[0].prompts_sent = 1
    empty = await rig[0].run({"action": "resolve", "agent": "empty"})
    assert empty["status"] == "unavailable"
    idle = await rig[0].run({"action": "resolve", "agent": "idle"})
    assert idle["selection"] == "first_idle_agent"


async def test_custom_name_idle_remains_an_explicit_target(rig):
    term = rig[1].session.terminals[0]
    term.name, term.activity = "Idle", "working"
    result = await rig[0].run({"action": "resolve", "agent": "Idle"})
    assert result["selection"] == "explicit_agent"
    assert result["target"]["terminal_id"] == "pane:" + term.history_id


async def test_explicit_ids_resolve_exact_background_pane(rig):
    owner = rig[1].sessions[0]
    second = Terminal("t2", "Second", "codex", "Codex", 1, status="live")
    owner.terminals.append(second)
    result = await rig[0].run({
        "action": "resolve", "project_id": owner.project_id, "workspace_id": owner.id,
        "terminal_id": "pane:" + second.history_id,
    })
    assert result["selection"] == "explicit_agent"
    assert result["target"]["terminal_id"] == "pane:" + second.history_id
    assert result["target"]["workspace_id"] == owner.id
    assert rig[1].active_id != owner.id


@pytest.mark.parametrize("key", ["project_id", "workspace_id", "terminal_id"])
async def test_invalid_explicit_id_never_falls_back_to_free_session(rig, key):
    owner = rig[1].session
    result = await rig[0].run({
        "action": "resolve", "project_id": owner.project_id, "workspace_id": owner.id,
        "terminal_id": "pane:" + owner.terminals[0].history_id, key: "missing",
    })
    assert result["status"] != "resolved"
    assert not rig[2].calls


async def test_scoped_inspect_only_reads_selected_workspace_history(rig, monkeypatch):
    from dodaios.agentic_ide import agent_transcript
    from dodaios.agentic_ide.agent_sessions import ResumeHandle

    owner = rig[1].session
    for space in rig[1].sessions:
        space.terminals[0].resume = ResumeHandle("codex", space.id, 0.0)
    reads = []

    def read(agent, session_id, **kwargs):
        reads.append(session_id)
        return agent_transcript.TimelineRead([
            {"kind": "user_message", "ts_ms": 1, "payload": {"text": "Repair the queue"}},
            {"kind": "tool_call", "ts_ms": 2,
             "payload": {"name": "read_file", "summary": "queue.py"}},
        ])

    monkeypatch.setattr(agent_transcript, "read_timeline", read)
    graph = await rig[0].run({"action": "inspect", "workspace_id": owner.id})
    assert reads == [owner.id]
    assert len(graph["projects"]) == 1
    agents = graph["projects"][0]["workspaces"][0]["agents"]
    assert agents[0]["last_user_message"] == "Repair the queue"
    assert agents[0]["has_history"] is True
    assert agents[0]["recent_events"][-1]["name"] == "read_file"


async def test_context_cursor_reaches_session_gateway(rig):
    resolved = await target(rig)
    cursor = {"source": "native-session", "offset": 30, "prefix": "fingerprint"}
    await rig[0].run({"action": "context", **resolved, "cursor": cursor, "limit": 10})
    assert rig[2].calls[-1]["cursor"] == cursor
    assert rig[2].calls[-1]["limit"] == 10
    assert "cursor" in WorkspaceOrchestrationTool.schema["properties"]


async def test_free_session_excludes_a_pane_with_an_assignment_being_written(rig, monkeypatch):
    from dodaios.agentic_ide import fanout

    owner = rig[1].session
    monkeypatch.setattr(fanout, "in_flight_briefs", lambda space: {"Alex": 5.0})
    result = await rig[0].run({"action": "resolve", "workspace_id": owner.id, "agent": "free"})
    assert result["status"] == "unavailable"
    assert not rig[2].calls


async def test_inspect_project_includes_all_its_workspaces(rig):
    owner = rig[1].session
    sibling = Session(
        id=uuid4().hex, folder=owner.folder, name="Sibling", profile=owner.profile,
        terminals=[], created_at=2, project_id=owner.project_id,
    )
    rig[1]._sessions[sibling.id] = sibling
    graph = await rig[0].run({"action": "inspect", "project_id": owner.project_id})
    assert {w["id"] for w in graph["projects"][0]["workspaces"]} == {owner.id, sibling.id}


async def test_unique_named_agent_can_be_addressed_in_background_workspace(rig):
    owner = rig[1].sessions[0]
    owner.terminals[0].name = "Installer expert"
    resolved = await target(rig, agent="Installer expert")
    assert resolved["workspace_id"] == owner.id
    assert rig[1].active_id != owner.id


async def test_duplicate_workspace_names_require_clarification(rig):
    for workspace in rig[1].sessions:
        workspace.name = "Installer"
    result = await rig[0].run({"action": "resolve", "workspace": "Installer"})
    assert result["status"] == "needs_clarification"
    assert len(result["candidates"]) == 2
    assert not rig[2].calls
    resolved = await target(rig, workspace="Installer", project="Personal Jarvis")
    assert resolved["project_id"] == rig[1].sessions[0].project_id


async def test_duplicate_agent_names_fail_closed_but_idle_choice_is_stable(rig):
    owner = rig[1].session
    owner.terminals.append(Terminal("t2", "Alex", "codex", "Codex", 1, status="live"))
    result = await rig[0].run({"action": "resolve", "agent": "Alex"})
    assert result["status"] == "needs_clarification"
    resolved = await target(rig)
    assert resolved["terminal_id"] == "pane:" + owner.terminals[0].history_id


async def test_rename_and_workspace_switch_cannot_retarget_send(rig):
    resolved = await target(rig, project="Personal Jarvis")
    owner = rig[1].get(resolved["workspace_id"])
    owner.name = "Renamed workspace"
    owner.terminals[0].name = "Renamed agent"
    result = await rig[0].run(
        {"action": "send", **resolved, "request_id": uuid4().hex, "prompt": "Task"}
    )
    assert result["status"] == "accepted"
    assert rig[2].calls[0]["terminal_id"] == resolved["terminal_id"]


async def test_closed_or_cross_project_target_cannot_fall_back(rig):
    resolved = await target(rig)
    del rig[1]._sessions[resolved["workspace_id"]]
    result = await rig[0].run(
        {"action": "send", **resolved, "request_id": uuid4().hex, "prompt": "Task"}
    )
    assert result["status"] == "stale_target"
    assert not rig[2].calls


async def test_concurrent_and_reopened_receipts_never_duplicate_delivery(rig):
    resolved = await target(rig)
    args = {"action": "send", **resolved, "request_id": uuid4().hex, "prompt": "Task"}
    first, second = await asyncio.gather(rig[0].run(args), rig[0].run(args))
    assert len(rig[2].calls) == 1
    assert "accepted" in {first.get("status"), second.get("status")}
    reopened = WorkspaceOrchestrator(rig[1], rig[2], rig[0].ledger)
    assert (await reopened.run(args))["status"] == "accepted"
    collision = await reopened.run({**args, "prompt": "Different task"})
    assert collision["success"] is False
    assert len(rig[2].calls) == 1


async def test_uncertain_delivery_stays_uncertain_and_is_not_replayed(rig):
    resolved = await target(rig)
    rig[2].fail = True
    args = {"action": "send", **resolved, "request_id": uuid4().hex, "prompt": "Task"}
    assert (await rig[0].run(args))["status"] == "uncertain"
    assert (await rig[0].run(args))["status"] == "uncertain"
    assert len(rig[2].calls) == 1


@pytest.mark.parametrize("available", [True, False])
async def test_capability_probe_is_provider_and_os_independent(rig, monkeypatch, available):
    from dodaios.workspace import agents

    monkeypatch.setattr(agents, "pty_available", lambda: available)
    graph = await rig[0].run({"action": "inspect"})
    assert graph["available"] is available
    assert len(graph["projects"]) == 2


class Executor:
    def __init__(self):
        self.calls = []

    async def execute(self, tool, args, **kwargs):
        self.calls.append((tool.name, args))
        ctx = ExecutionContext(kwargs["trace_id"], kwargs["user_utterance"], {}, None)
        return await tool.execute(args, ctx)


async def test_live_roundtrip_uses_gateway_executor_and_durable_addressed_receipt(rig, tmp_path):
    executor = Executor()
    tool = WorkspaceOrchestrationTool(rig[0])
    gateway = BrainSupervisorToolGateway(
        SimpleNamespace(_tools={"agentic-ide-prompt": tool}, _tool_executor=executor),
        workspace_tool=tool,
    )
    catalog = {row.name for row in gateway.voice_catalog()}
    assert tool.name in catalog and "agentic-ide-prompt" not in catalog
    # The controller is not put in a worker's ordinary catalog.
    assert tool.name not in {row.name for row in gateway.catalog()}
    ledger = LiveLedger(tmp_path / "live.db")
    try:
        live = LiveTools(gateway, ledger, "voice", language="en", backend_model="")
        live.user_text = "Fix the Linux installer in the Personal Jarvis workspace"
        resolved = await live.execute(
            "resolve",
            tool.name,
            {
                "action": "resolve",
                "workspace": "Personal Jarvis",
            },
            0,
        )
        assert resolved["success"], resolved
        args = {
            "action": "send",
            **resolved["output"]["target"],
            "request_id": resolved["output"]["request_id"],
            "prompt": live.user_text,
        }
        # The resolved display labels are UI metadata, not accepted send fields.
        args = {k: v for k, v in args.items() if k in tool.schema["properties"]}
        receipt = await live.execute("send", tool.name, args, 0)
        assert receipt["success"] and receipt["output"]["status"] == "accepted"
        assert (await live.execute("send", tool.name, args, 0)) == receipt
        assert len(rig[2].calls) == 1
        assert len(executor.calls) == 2
        denied = await gateway.execute(
            tool.name, args, SupervisorToolRequest(uuid4(), "mission", "Task")
        )
        assert not denied.success
    finally:
        ledger.close()


def test_send_runs_without_a_spoken_question_and_reads_remain_safe(rig):
    # Live 2026-10-01: a hand-off the user ordered three times was still met
    # with "shall I send it?". Sending to the user's own agent is logged only.
    tool = WorkspaceOrchestrationTool(rig[0])
    assert tool.risk_tier_for_args({"action": "send"}) == "monitor"
    for action in ("inspect", "resolve", "context"):
        assert tool.risk_tier_for_args({"action": action}) == "safe"


async def test_prewrite_refusal_is_recorded_without_claiming_uncertainty(rig):
    # Live 2026-10-07: an approved brief refused as "busy" kept echoing that
    # receipt for its request_id after the pane was idle; nothing ever went.
    resolved = await target(rig)
    rig[2].refused = True
    args = {"action": "send", **resolved, "request_id": uuid4().hex, "prompt": "Task"}
    first = await rig[0].run(args)
    assert first["status"] == "not_accepted"
    again = await rig[0].run(args)
    assert again["status"] == "not_accepted"
    assert again["request_id"] == first["request_id"]
    assert len(rig[2].calls) == 2
    rig[2].refused = False
    delivered = await rig[0].run(args)
    assert delivered["status"] == "accepted"
    assert delivered["request_id"] == first["request_id"]
    # Once typed, the same request is a receipt read, never a second write.
    assert (await rig[0].run(args))["status"] == "accepted"
    assert len(rig[2].calls) == 3
    # A refused request ID still cannot carry a different assignment.
    assert (await rig[0].run({**args, "prompt": "Correction"}))["success"] is False
    assert len(rig[2].calls) == 3


async def test_retry_after_uncertain_write_is_never_retyped(rig):
    resolved = await target(rig)
    args = {"action": "send", **resolved, "request_id": uuid4().hex, "prompt": "Task"}
    rig[2].refused = True
    assert (await rig[0].run(args))["status"] == "not_accepted"
    rig[2].refused, rig[2].fail = False, True
    assert (await rig[0].run(args))["status"] == "uncertain"
    rig[2].fail = False
    assert (await rig[0].run(args))["status"] == "uncertain"
    assert len(rig[2].calls) == 2


async def test_later_same_task_has_an_app_minted_distinct_request(rig):
    for _ in range(2):
        resolved = await rig[0].run({"action": "resolve"})
        await rig[0].run(
            {
                "action": "send",
                **resolved["target"],
                "request_id": resolved["request_id"],
                "prompt": "Run tests",
            }
        )
    assert len(rig[2].calls) == 2


def test_confirmation_identifies_target_and_task(rig):
    tool = WorkspaceOrchestrationTool(rig[0])
    impact = tool.describe_args(
        {
            "action": "send",
            "project_id": "project-1",
            "workspace_id": "workspace-2",
            "terminal_id": "pane:3",
            "prompt": "Fix Linux installer",
        }
    )
    assert impact == {
        "level": "modify",
        "project": "project-1",
        "workspace": "workspace-2",
        "agent": "pane:3",
        "task": "Fix Linux installer",
    }


async def test_a_mistyped_request_id_still_delivers_exactly_once(rig):
    # Live 2026-10-01: the voice model dropped one "0" from the 32-character id.
    resolved = await rig[0].run({"action": "resolve"})
    rid = resolved["request_id"]
    garbled = rid[:20] + rid[21:]
    ids = {k: resolved["target"][k] for k in ("project_id", "workspace_id", "terminal_id")}
    first = await rig[0].run({"action": "send", **ids, "request_id": garbled, "prompt": "Task"})
    assert first["status"] == "accepted"
    retry = rid[:5] + rid[6:]
    again = await rig[0].run({"action": "send", **ids, "request_id": retry, "prompt": "Task"})
    assert again == first
    assert len(rig[2].calls) == 1


async def test_send_without_request_id_uses_the_latest_resolve(rig):
    resolved = await rig[0].run({"action": "resolve"})
    ids = {k: resolved["target"][k] for k in ("project_id", "workspace_id", "terminal_id")}
    result = await rig[0].run({"action": "send", **ids, "prompt": "Task"})
    assert result["status"] == "accepted"
    assert (await rig[0].run({"action": "send", **ids, "prompt": "Task"}))["status"] == "accepted"
    assert len(rig[2].calls) == 1
    other = await rig[0].run({"action": "send", **ids, "prompt": "Another task"})
    assert other["status"] == "accepted"
    assert len(rig[2].calls) == 2


async def test_garbled_target_ids_are_repaired_from_the_resolve(rig):
    resolved = await rig[0].run({"action": "resolve"})
    target = resolved["target"]
    result = await rig[0].run(
        {
            "action": "send",
            "project_id": target["project_id"][:-1],
            "workspace_id": target["workspace_id"][1:],
            "terminal_id": target["terminal_id"],
            "request_id": resolved["request_id"],
            "prompt": "Task",
        }
    )
    assert result["status"] == "accepted"
    assert rig[2].calls[0]["workspace_id"] == target["workspace_id"]


async def test_context_ignores_a_broken_request_id(rig):
    resolved = await target(rig)
    result = await rig[0].run({"action": "context", **resolved, "request_id": "not-an-id"})
    assert result["status"] == "observed" or result.get("delivery") == "accepted"


async def test_spoken_workspace_name_with_filler_words_resolves(rig):
    resolved = await target(rig, project="Jarvis-Works", workspace="Personal-Jarvis-Workspace")
    assert resolved["workspace"] == "Personal Jarvis"


async def test_an_unmatched_reference_lists_every_open_workspace(rig):
    result = await rig[0].run({"action": "resolve", "workspace": "Something else entirely"})
    assert result["status"] == "needs_clarification"
    names = {c["workspace"] for c in result["candidates"]}
    assert names == {"Personal Jarvis", "Other project"}
    assert "Something else entirely" in result["reason"]


@pytest.fixture
def runnable(monkeypatch):
    from dodaios.agentic_ide import session as session_mod

    monkeypatch.setattr(session_mod, "agent_argv", lambda name: (f"/usr/bin/{name}",))


async def test_new_agents_open_in_the_named_background_workspace(rig, runnable):
    # Live 2026-10-01: "spawn a new Claude Code agent in the VMs workspace"
    # became an invisible mission worker; no pane ever appeared there.
    orchestrator, registry, sessions = rig
    owner = registry.sessions[0]
    owner.name = "VM`s"
    before_active = registry.active_id
    existing = [t.history_id for t in owner.terminals]
    published = []

    async def publish(event):
        published.append(event)

    orchestrator.publish = publish
    result = await orchestrator.run(
        {"action": "create", "workspace": "VMs Workspace", "cli": "Claude Cotec", "count": 2}
    )
    assert result["status"] == "created", result
    assert result["workspace_id"] == owner.id
    assert [a["cli"] for a in result["agents"]] == ["claude", "claude"]
    assert len(owner.terminals) == len(existing) + 2
    assert [t.history_id for t in owner.terminals[: len(existing)]] == existing
    assert registry.active_id == before_active
    assert not sessions.calls
    assert published and published[0].session_id == owner.id
    assert len(published[0].names) == 2


async def test_a_new_agent_with_a_task_is_briefed_through_a_receipted_send(rig, runnable):
    orchestrator, registry, sessions = rig
    result = await orchestrator.run(
        {
            "action": "create",
            "workspace": "Personal Jarvis",
            "cli": "Claude Code",
            "prompt": "Deep-dive the update path",
        }
    )
    assert result["status"] == "created", result
    new_pane = result["agents"][0]["terminal_id"]
    assert [d["status"] for d in result["deliveries"]] == ["accepted"]
    assert sessions.calls[0]["terminal_id"] == new_pane
    assert sessions.calls[0]["prompt"] == "Deep-dive the update path"


async def test_an_unknown_cli_asks_instead_of_opening_a_substitute(rig, runnable):
    owner = rig[1].sessions[0]
    count = len(owner.terminals)
    result = await rig[0].run(
        {"action": "create", "workspace": "Personal Jarvis", "cli": "Banana"}
    )
    assert result["status"] == "needs_clarification" and result["kind"] == "cli"
    assert len(owner.terminals) == count


async def test_no_idle_agent_points_to_create(rig):
    for term in rig[1].session.terminals:
        term.activity = "working"
    result = await rig[0].run({"action": "resolve"})
    assert result["status"] == "unavailable"
    assert "create" in result["reason"]


def test_create_is_a_logged_action_with_a_valid_live_schema(rig):
    import jsonschema

    tool = WorkspaceOrchestrationTool(rig[0])
    args = {"action": "create", "workspace": "VMs", "cli": "Codex", "count": 3, "prompt": "x"}
    jsonschema.validate(args, tool.schema)
    assert tool.risk_tier_for_args(args) == "monitor"
    assert tool.describe_args(args)["agent"] == "3 new Codex"


async def test_mixed_clis_open_in_one_call(rig, runnable):
    # The maintainer's benchmark: "five Claude Code and three Codex" at once.
    orchestrator, registry, _ = rig
    owner = registry.sessions[0]
    before = len(owner.terminals)
    result = await orchestrator.run(
        {
            "action": "create",
            "workspace": "Personal Jarvis",
            "agents": [{"cli": "Claude Code", "count": 5}, {"cli": "Codex", "count": 3}],
        }
    )
    assert result["status"] == "created", result
    assert [a["cli"] for a in result["agents"]] == ["claude"] * 5 + ["codex"] * 3
    assert len(owner.terminals) == before + 8


async def test_open_workspace_creates_a_new_workspace_with_mixed_agents(rig, runnable, tmp_path):
    orchestrator, registry, _ = rig
    folder = tmp_path / "Fresh"
    folder.mkdir()
    published = []

    async def publish(event):
        published.append(event)

    orchestrator.publish = publish
    result = await orchestrator.run(
        {
            "action": "open_workspace",
            "folder": str(folder),
            "agents": [{"cli": "claude", "count": 2}, {"cli": "codex", "count": 1}],
        }
    )
    assert result["status"] == "opened", result
    assert [a["cli"] for a in result["agents"]] == ["claude", "claude", "codex"]
    assert registry.get(result["workspace_id"]) is not None
    assert published


async def test_open_workspace_without_a_folder_lists_known_projects(rig):
    result = await rig[0].run({"action": "open_workspace"})
    assert result["status"] == "needs_clarification" and result["kind"] == "folder"
    assert {c["project"] for c in result["candidates"]} == {"Personal Jarvis", "Other project"}


async def test_respond_answers_the_question_a_pane_shows(rig):
    orchestrator, registry, sessions = rig
    name = registry.sessions[0].terminals[0].name
    result = await orchestrator.run(
        {"action": "respond", "workspace": "Personal Jarvis", "agent": name, "prompt": "1"}
    )
    assert result["status"] == "accepted", result
    respond = sessions.calls[-1]
    assert respond["action"] == "respond" and respond["prompt"] == "1"
    assert respond["input_token"] == "token-1" and respond["response_mode"] == "dialog"  # noqa: S105 - a fake input token


async def test_keys_and_interrupt_press_only_whitelisted_keys(rig, monkeypatch):
    orchestrator, registry, _ = rig
    pressed = []
    monkeypatch.setattr(
        registry, "write", lambda key, data, workspace_id=None: pressed.append(data) or True
    )
    owner = registry.sessions[0]
    args = {"workspace": "Personal Jarvis", "agent": owner.terminals[0].name}
    assert (await orchestrator.run({"action": "keys", **args, "keys": ["down", "enter"]}))[
        "status"
    ] == "pressed"
    assert (await orchestrator.run({"action": "interrupt", **args}))["status"] == "pressed"
    assert pressed == ["\x1b[B", "\r", "\x1b"]
    refused = await orchestrator.run({"action": "keys", **args, "keys": ["rm -rf /"]})
    assert refused["status"] == "not_accepted"
    assert len(pressed) == 3


async def test_close_removes_one_named_pane(rig):
    orchestrator, registry, _ = rig
    owner = registry.sessions[0]
    owner.terminals.append(Terminal("t2", "Nova", "codex", "Codex", 1, status="live"))
    result = await orchestrator.run(
        {"action": "close", "workspace": "Personal Jarvis", "agent": "Nova"}
    )
    assert result["status"] == "closed", result
    assert [t.name for t in owner.terminals] == ["Alex"]


async def test_show_brings_a_background_workspace_on_screen(rig):
    orchestrator, registry, _ = rig
    background = next(s for s in registry.sessions if s.id != registry.active_id)
    result = await orchestrator.run({"action": "show", "workspace": background.name})
    assert result["status"] == "shown", result
    assert registry.active_id == background.id


async def test_the_same_words_later_are_a_new_instruction(rig):
    from dodaios.agentic_ide import orchestration

    resolved = await target(rig)
    args = {"action": "send", **resolved, "prompt": "continue"}
    assert (await rig[0].run(args))["status"] == "accepted"
    assert (await rig[0].run(args))["status"] == "accepted"
    assert len(rig[2].calls) == 1  # an immediate repeat is a retry
    issued = rig[0]._issued
    for request_id, (pane, at, sent) in list(issued.items()):
        issued[request_id] = (pane, at - orchestration._RETRY_WINDOW_S - 1, sent)
    assert (await rig[0].run(args))["status"] == "accepted"
    assert len(rig[2].calls) == 2


def test_pane_reads_are_safe_and_every_new_action_validates(rig):
    import jsonschema

    tool = WorkspaceOrchestrationTool(rig[0])
    assert tool.risk_tier_for_args({"action": "observe"}) == "safe"
    for action in ("respond", "keys", "interrupt", "close", "open_workspace", "restore", "show"):
        jsonschema.validate({"action": action}, tool.schema)
        assert tool.risk_tier_for_args({"action": action}) == "monitor"


# --- Reaching an agent that is in a turn ---------------------------------------
#
# Live 2026-10-07: a scope correction sent to a working Claude pane came back
# not_accepted ("The selected coding agent is busy; nothing was sent."), with
# no way to deliver it. A busy refusal now says how the USER's correction can
# reach the turn, and a resend of the same request delivers it exactly once.


@pytest.fixture
def fast_queue(monkeypatch):
    monkeypatch.setattr(orchestration, "_QUEUE_POLL_S", 0.01)
    monkeypatch.setattr(orchestration.random, "uniform", lambda *_: 0.0)


async def until(predicate, timeout_s: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate():
        assert time.monotonic() < deadline, "condition never became true"
        await asyncio.sleep(0.01)


async def busy_send(rig, **extra):
    resolved = await target(rig)
    rig[2].refused = True
    args = {"action": "send", **resolved, "request_id": uuid4().hex,
            "prompt": "Narrow the review to the save flow", **extra}
    return args, await rig[0].run(args)


async def test_ordinary_send_to_a_busy_agent_types_nothing_and_says_how(rig):
    args, refused = await busy_send(rig)
    assert refused["status"] == "not_accepted" and refused["busy"] is True
    assert refused["input_written"] is False
    assert refused["while_busy_options"] == {"steer": True, "interrupt": True, "queue": True}
    assert "while_busy='steer'" in refused["next"]
    assert rig[2].calls[-1]["when_busy"] == "refuse"
    assert rig[2].typed == []


async def test_busy_refusal_then_steer_delivers_the_correction_exactly_once(rig):
    args, refused = await busy_send(rig)
    assert refused["status"] == "not_accepted"
    steered = await rig[0].run({**args, "while_busy": "steer"})
    assert steered["status"] == "accepted" and steered["mid_turn"] is True
    assert steered["request_id"] == refused["request_id"]
    assert rig[2].typed == [args["prompt"]]
    # Any retry of the request reads its receipt, whatever mode it names.
    for mode in ("steer", "interrupt", "queue", "refuse"):
        again = await rig[0].run({**args, "while_busy": mode})
        assert again["status"] == "accepted"
    assert rig[2].typed == [args["prompt"]]


async def test_steer_on_a_cli_without_mid_turn_input_is_refused_with_options(rig):
    rig[2].steerable = False
    args, refused = await busy_send(rig, while_busy="steer")
    assert refused["status"] == "not_accepted" and refused["busy"] is True
    assert rig[2].typed == []


async def test_interrupt_stops_the_turn_and_delivers_once(rig):
    args, delivered = await busy_send(rig, while_busy="interrupt")
    assert delivered["status"] == "accepted"
    assert rig[2].calls[-1]["when_busy"] == "interrupt"
    assert rig[2].typed == [args["prompt"]]
    assert (await rig[0].run(args))["status"] == "accepted"
    assert rig[2].typed == [args["prompt"]]


async def test_interrupt_that_does_not_settle_is_queued_then_delivered_once(rig, fast_queue):
    rig[2].settles = False
    args, held = await busy_send(rig, while_busy="interrupt")
    assert held["status"] == "queued" and held["interrupted"] is True
    assert held["input_written"] is False and rig[2].typed == []
    # The turn ends on its own; the queue types the correction at the prompt.
    rig[2].refused = False
    await until(lambda: rig[2].typed)
    await until(lambda: not rig[0]._queued)
    receipt = await rig[0].run(args)
    assert receipt["status"] == "accepted" and receipt["queued"] is True
    assert rig[2].typed == [args["prompt"]]
    # The queue never presses Stop again: only the first attempt interrupted.
    assert [c.get("when_busy") for c in rig[2].calls].count("interrupt") == 1


async def test_queue_holds_the_message_until_the_turn_ends(rig, fast_queue):
    args, held = await busy_send(rig, while_busy="queue")
    assert held["status"] == "queued" and "interrupted" not in held
    assert all(c["when_busy"] == "refuse" for c in rig[2].calls)
    # While it waits, a retry reads the queued receipt and sends nothing.
    await asyncio.sleep(0.05)
    assert (await rig[0].run(args))["status"] == "queued"
    assert rig[2].typed == []
    rig[2].refused = False
    await until(lambda: not rig[0]._queued)
    assert rig[2].typed == [args["prompt"]]
    assert (await rig[0].run(args))["status"] == "accepted"
    assert rig[2].typed == [args["prompt"]]


async def test_queue_that_never_frees_expires_unsent_and_can_be_retried(
    rig, fast_queue, monkeypatch,
):
    monkeypatch.setattr(orchestration, "_QUEUE_TTL_S", 0.05)
    args, held = await busy_send(rig, while_busy="queue")
    assert held["status"] == "queued"
    await until(lambda: not rig[0]._queued)
    retried = await rig[0].run({**args, "while_busy": "refuse"})
    # The expired receipt proved nothing was typed, so this retry was a fresh
    # attempt, refused again because the pane is still busy.
    assert retried["status"] == "not_accepted" and retried["busy"] is True
    rig[2].refused = False
    assert (await rig[0].run(args))["status"] == "accepted"
    assert rig[2].typed == [args["prompt"]]


async def test_a_queue_left_by_an_earlier_app_run_is_expired_not_trusted(rig, fast_queue):
    args, held = await busy_send(rig, while_busy="queue")
    assert held["status"] == "queued"
    # The app stops: its queue task ends without typing. A new orchestrator over
    # the same receipt store has no task holding that message.
    for task in list(rig[0]._queued.values()):
        task.cancel()
    await until(lambda: not rig[0]._queued)
    restarted = WorkspaceOrchestrator(rig[1], rig[2], rig[0].ledger)
    rig[2].refused = False
    assert (await restarted.run(args))["status"] == "accepted"
    assert (await restarted.run(args))["status"] == "accepted"
    assert rig[2].typed == [args["prompt"]]


async def test_a_receipt_still_marked_queued_without_its_task_is_not_trusted(rig, fast_queue):
    args, held = await busy_send(rig, while_busy="queue")
    receipt_id = next(iter(rig[0]._queued))
    # A hard stop: the task vanished without filing its final receipt.
    rig[0]._queued.pop(receipt_id).cancel()
    await asyncio.sleep(0.05)
    rig[0].ledger.finish("workspace-orchestration", receipt_id, held)
    rig[2].refused = False
    assert (await rig[0].run(args))["status"] == "accepted"
    assert rig[2].typed == [args["prompt"]]


async def test_unknown_or_misplaced_while_busy_is_rejected(rig):
    resolved = await target(rig)
    with pytest.raises(ValueError, match="while_busy must be one of"):
        await rig[0].run({"action": "send", **resolved, "prompt": "x", "while_busy": "kill"})
    with pytest.raises(ValueError, match="belongs to send"):
        await rig[0].run({"action": "context", **resolved, "while_busy": "steer"})
    assert rig[2].calls == []


def test_tool_schema_offers_while_busy_and_shows_it_for_approval():
    tool = WorkspaceOrchestrationTool(gateway=None)
    assert tool.schema["properties"]["while_busy"]["enum"] == [
        "refuse", "steer", "interrupt", "queue",
    ]
    described = tool.describe_args({"action": "send", "prompt": "x", "while_busy": "interrupt"})
    assert described["while_busy"] == "interrupt"
    assert "while_busy" not in tool.describe_args({"action": "send", "prompt": "x"})


async def test_a_stop_while_the_queue_is_typing_is_uncertain_never_retyped(rig, fast_queue):
    args, held = await busy_send(rig, while_busy="queue")
    typing = asyncio.Event()
    finish = asyncio.Event()
    plain_run = rig[2].run

    async def slow_run(call):
        if call["action"] == "send" and not rig[2].refused:
            typing.set()
            await finish.wait()  # the app stops while this write is in flight
        return await plain_run(call)

    rig[2].run = slow_run
    rig[2].refused = False
    await asyncio.wait_for(typing.wait(), 2)
    for task in list(rig[0]._queued.values()):
        task.cancel()
    await until(lambda: not rig[0]._queued)
    again = await rig[0].run(args)
    assert again["status"] == "uncertain"
    assert rig[2].typed == []  # the cancelled write never completed, and no retry typed


async def test_a_failed_look_at_the_pane_is_retried_not_dropped(rig, fast_queue, monkeypatch):
    args, held = await busy_send(rig, while_busy="queue")
    looks = []

    async def flaky(term):
        looks.append(term)
        if len(looks) == 1:
            raise OSError("transcript locked")
        return ""

    monkeypatch.setattr(rig[1], "turn_in_progress", flaky)
    rig[2].refused = False
    await until(lambda: not rig[0]._queued)
    assert len(looks) >= 2
    assert (await rig[0].run(args))["status"] == "accepted"
    assert rig[2].typed == [args["prompt"]]


async def test_messages_queued_for_one_pane_arrive_in_order(rig, fast_queue):
    first, held = await busy_send(rig, while_busy="queue")
    second = {**first, "request_id": uuid4().hex, "prompt": "And keep the tests green"}
    assert (await rig[0].run(second))["status"] == "queued"
    rig[2].refused = False
    await until(lambda: not rig[0]._queued)
    assert rig[2].typed == [first["prompt"], second["prompt"]]


# --- One board for "what is running, what is done, who needs me" ----------------


async def test_status_lists_every_open_agent_and_who_needs_the_user_in_one_call(rig):
    orchestrator, registry, sessions = rig
    visible = registry.session
    other = next(s for s in registry.sessions if s.id != visible.id)
    visible.terminals[0].activity = "working"
    other.terminals[0].activity = "asking"
    board = await orchestrator.run({"action": "status"})
    assert board["status"] == "ok"
    rows = {row["workspace"]: row for row in board["workspaces"]}
    assert set(rows) == {"Personal Jarvis", "Other project"}
    assert rows[visible.name]["agents"][0]["state"] == "busy"
    assert rows[visible.name]["visible"] is True
    assert rows[other.name]["agents"][0]["state"] == "needs_input"
    assert board["counts"] == {"busy": 1, "needs_input": 1}
    assert board["needs_you"] == [f"Alex ({other.name})"]
    assert "folder" not in rows[visible.name]
    assert not sessions.calls  # no pane is read or touched for the overview


async def test_status_narrows_to_a_named_workspace(rig):
    board = await rig[0].run({"action": "status", "workspace": "Other project"})
    assert [row["workspace"] for row in board["workspaces"]] == ["Other project"]
    missing = await rig[0].run({"action": "status", "workspace": "No such workspace"})
    assert "workspaces" not in missing and missing["status"] != "ok"


@pytest.fixture
def visible_repo(rig):
    """The visible workspace's folder as a fresh repository with one new file."""
    import subprocess
    from pathlib import Path

    from dodaios.agentic_ide import git_ops
    from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS

    if not git_ops.git_available():
        pytest.skip("git is not installed")
    visible = rig[1].session
    subprocess.run(  # noqa: S603 - a fixed git command in a temporary folder
        ["git", "init", "-q"], cwd=visible.folder, check=True,  # noqa: S607
        creationflags=NO_WINDOW_CREATIONFLAGS,
    )
    Path(visible.folder, "notes.txt").write_text("draft", encoding="utf-8")
    return visible


async def test_status_reports_the_git_state_of_a_workspace_folder(rig, visible_repo):
    board = await rig[0].run({"action": "status"})
    rows = {row["workspace"]: row for row in board["workspaces"]}
    git = rows[visible_repo.name]["git"]
    assert git["branch"] and git["changed_files"] == 1
    assert git["worktree"] is False and git["conflicted"] == 0
    plain = next(name for name in rows if name != visible_repo.name)
    assert "git" not in rows[plain]  # a folder outside any repository has no git row


class _Origin:
    """The conversation a tool call came from, as the workspace tool records it."""

    def __init__(self, surface: str) -> None:
        self.origin = {"reply_surface": surface, "reply_session_id": "", "lang": "en"}

    def __enter__(self):
        from dodaios.core.delegation import current_delegation_origin

        self._var = current_delegation_origin
        self._token = self._var.set(self.origin)

    def __exit__(self, *_exc):
        self._var.reset(self._token)


@pytest.fixture
def reportable(monkeypatch):
    from dodaios.agentic_ide import followthrough

    monkeypatch.setattr(followthrough, "can_report", lambda _term: True)
    monkeypatch.setattr(followthrough, "_events", lambda _term: [])


async def test_watch_follows_a_hand_started_job_and_shows_on_the_board(rig, reportable):
    orchestrator, registry, sessions = rig
    term = registry.session.terminals[0]
    term.activity, term.last_prompt = "working", "Refactor the importer"
    watch = {"action": "watch", "workspace": registry.session.name, "agent": term.name}
    with _Origin("voice"):
        first = await orchestrator.run(watch)
        again = await orchestrator.run(watch)
    assert first["status"] == "watching" and "already" not in first
    assert again["status"] == "watching" and again["already"] is True
    assert term.delegation_result.watched
    assert "Refactor the importer" in term.delegation_result.request
    board = await orchestrator.run({"action": "status", "workspace": registry.session.name})
    assert board["workspaces"][0]["agents"][0]["watched"] is True
    assert not sessions.calls  # watching types nothing into the pane


async def test_watch_refuses_honestly_when_there_is_nothing_to_report(rig, monkeypatch):
    orchestrator, registry, _sessions = rig
    term = registry.session.terminals[0]
    watch = {"action": "watch", "workspace": registry.session.name, "agent": term.name}
    with _Origin("voice"):
        idle = await orchestrator.run(watch)
    assert idle["status"] == "not_running" and term.delegation_result is None
    term.activity = "working"
    with _Origin("voice"):
        unreadable = await orchestrator.run(watch)  # this CLI session has no record yet
    assert unreadable["status"] == "unavailable" and term.delegation_result is None
    from dodaios.agentic_ide import followthrough

    monkeypatch.setattr(followthrough, "can_report", lambda _term: True)
    with _Origin("none"):
        nowhere = await orchestrator.run(watch)
    assert nowhere["status"] == "unavailable" and term.delegation_result is None


async def test_watch_without_a_name_follows_the_one_agent_at_work(rig, reportable):
    # "Tell me when the coding agent is done" with one agent working was asked
    # back for a call-sign in a live call (2026-10-14).
    orchestrator, registry, sessions = rig
    panes = [term for session in registry.sessions for term in session.terminals]
    with _Origin("voice"):
        nobody = await orchestrator.run({"action": "watch"})
    assert nobody["status"] == "needs_clarification" and nobody["working"] == []
    term = panes[0]
    term.activity, term.last_prompt = "working", "Run the migration"
    with _Origin("voice"):
        watched = await orchestrator.run({"action": "watch"})
    assert watched["status"] == "watching" and watched["agent"] == term.name
    assert watched["target"]["terminal_id"] == "pane:" + term.history_id
    assert term.delegation_result.watched and not sessions.calls


async def test_watch_without_a_name_asks_when_several_agents_work(rig, reportable):
    orchestrator, registry, _sessions = rig
    panes = [term for session in registry.sessions for term in session.terminals]
    assert len(panes) >= 2
    for term in panes[:2]:
        term.activity = "working"
    with _Origin("voice"):
        asked = await orchestrator.run({"action": "watch"})
    assert asked["status"] == "needs_clarification"
    assert set(asked["working"]) >= {panes[0].name, panes[1].name}
    assert all(term.delegation_result is None for term in panes)


def test_status_is_a_read_and_watch_is_a_logged_action(rig):
    import jsonschema

    tool = WorkspaceOrchestrationTool(rig[0])
    jsonschema.validate({"action": "status", "workspace": "Other project"}, tool.schema)
    jsonschema.validate({"action": "watch", "agent": "Alex"}, tool.schema)
    assert tool.risk_tier_for_args({"action": "status"}) == "safe"
    assert tool.describe_args({"action": "status"})["level"] == "read"
    assert tool.risk_tier_for_args({"action": "watch"}) == "monitor"


# --- A copy of an agent's conversation, optionally in its own worktree ----------------


async def test_fork_opens_a_copy_of_the_named_agent_and_addresses_it(rig, monkeypatch):
    orchestrator, registry, sessions = rig
    owner = registry.session
    asked = []

    async def fork(wanted, *, workspace_id=None, worktree=False, name=None, direction="right"):
        asked.append((wanted, workspace_id, worktree, name))
        copy = Terminal("t9", "Alex 2", "codex", "Codex", 1, status="live")
        if worktree:
            copy.folder, copy.branch = "/repo/.worktrees/try-b", "try-b"
        owner.terminals.append(copy)
        return copy

    monkeypatch.setattr(registry, "fork_terminal", fork)
    plain = await orchestrator.run(
        {"action": "fork", "workspace": owner.name, "agent": "Alex"}
    )
    assert plain["status"] == "forked" and plain["agent"] == "Alex"
    assert plain["copy"]["name"] == "Alex 2" and plain["copy"]["terminal_id"].startswith("pane:")
    assert "folder" not in plain["copy"]
    apart = await orchestrator.run(
        {"action": "fork", "workspace": owner.name, "agent": "Alex", "worktree": True,
         "name": " try-b "}
    )
    assert apart["copy"]["branch"] == "try-b" and "own worktree" in apart["reason"]
    assert asked == [("Alex", owner.id, False, None), ("Alex", owner.id, True, "try-b")]
    assert not sessions.calls  # nothing is typed into either pane


async def test_a_fork_the_app_refuses_is_passed_on_with_its_reason(rig, monkeypatch):
    from dodaios.agentic_ide.session import SessionError

    orchestrator, registry, _sessions = rig

    async def refuse(wanted, **_kwargs):
        raise SessionError("Alex is a plain terminal — it has no chat to fork.")

    monkeypatch.setattr(registry, "fork_terminal", refuse)
    result = await orchestrator.run(
        {"action": "fork", "workspace": registry.session.name, "agent": "Alex"}
    )
    assert result["status"] == "not_accepted" and "no chat to fork" in result["reason"]


def test_fork_is_a_logged_action_with_a_valid_schema(rig):
    import jsonschema

    tool = WorkspaceOrchestrationTool(rig[0])
    jsonschema.validate({"action": "fork", "agent": "Alex", "worktree": True}, tool.schema)
    assert tool.risk_tier_for_args({"action": "fork"}) == "monitor"


async def test_a_job_that_ends_while_the_watch_is_set_up_is_not_watched_forever(
    rig, reportable, monkeypatch
):
    from dodaios.agentic_ide import followthrough

    orchestrator, registry, _sessions = rig
    term = registry.session.terminals[0]
    term.activity = "working"
    real = followthrough.watch

    async def finishes_meanwhile(pane, origin):
        armed = await real(pane, origin)
        pane.activity = "idle"  # its end is now part of the watch's starting point
        return armed

    monkeypatch.setattr(followthrough, "watch", finishes_meanwhile)
    with _Origin("voice"):
        result = await orchestrator.run(
            {"action": "watch", "workspace": registry.session.name, "agent": term.name}
        )
    assert result["status"] == "not_running" and "just finished" in result["reason"]
    assert term.delegation_result is None
