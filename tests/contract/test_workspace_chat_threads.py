"""A coding agent Dodaios starts opens as a chat thread, not a grid pane.

The chat service is the real one with a real store; only the coding CLI is
replaced by a scripted runner, so no binary runs and nothing is billed.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import uuid4

import pytest

from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.agentic_ide import chat_threads, library, resume_store, task_state
from dodaios.agentic_ide.chat_threads import ChatThreads, spawn_mode
from dodaios.agentic_ide.folders import probe_project
from dodaios.agentic_ide.orchestration import WorkspaceOrchestrator
from dodaios.agentic_ide.session import Registry, Session, Terminal
from dodaios.brain.workspace_tool import WorkspaceOrchestrationTool
from dodaios.core.delegation import current_delegation_origin
from dodaios.core.events import AnnouncementRequested, DelegationResultReady, NavigateSidebar
from dodaios.live.state import LiveLedger
from dodaios.orchestrator import jobs
from tests.fakes.fake_pty_manager import FakePtyManager

VOICE = {"reply_surface": "voice", "reply_session_id": "", "lang": "en"}


class ScriptedService(AgentChatService):
    """The real service; every turn runs the next scripted step instead of a CLI."""

    def __init__(self, store: AgentChatStore) -> None:
        super().__init__(store)
        self.prompts: list[tuple[str, str]] = []
        self.authors: list[dict[str, str] | None] = []
        self.steps: dict[str, list[Any]] = {}
        self.hold: asyncio.Event | None = None

    async def send(self, session_id: str, text: str, *args: Any, **kwargs: Any) -> str:
        self.authors.append(kwargs.get("author"))

        async def runner(handle: Any, prompt: str) -> None:
            self.prompts.append((session_id, prompt))
            if self.hold is not None:
                await self.hold.wait()
            queue = self.steps.get(session_id) or []
            step = queue.pop(0) if queue else "done"
            status = "done"
            for event in step if isinstance(step, list) else [step]:
                if event == "error":
                    status = "error"
                    continue
                if isinstance(event, str):
                    event = make_event("assistant_text", {"text": event})
                event["payload"].setdefault("turn_id", handle.turn_id)
                await handle.emit(event)
            await handle.emit(
                make_event(
                    "turn_finished",
                    {"turn_id": handle.turn_id, "status": status,
                     **({"error": "the CLI crashed"} if status == "error" else {})},
                )
            )

        kwargs.setdefault("control_runner", runner)
        return await super().send(session_id, text, *args, **kwargs)


class Rig:
    def __init__(self, orchestrator, registry, service, workspace, published) -> None:
        self.orchestrator = orchestrator
        self.registry = registry
        self.service = service
        self.workspace = workspace
        self.published = published

    def threads(self) -> list[Any]:
        return self.service.store.list_sessions(surface="agent")

    def results(self) -> list[Any]:
        return [
            e for e in self.published
            if isinstance(e, (AnnouncementRequested, DelegationResultReady))
        ]

    async def settle(self) -> None:
        for _ in range(400):
            await asyncio.sleep(0.01)
            busy = self.service.running_session_ids() or self.orchestrator.threads._tasks
            if not busy:
                return
        raise AssertionError("the threads did not settle")


@pytest.fixture
async def rig(tmp_path, monkeypatch):
    from dodaios.agentic_ide import activity
    from dodaios.agentic_ide import session as session_mod
    from dodaios.society import coding_threads

    task_state.reset()
    monkeypatch.setattr(activity, "STAMP_FRESH_S", 3600.0)
    monkeypatch.setattr(library, "_root", lambda: tmp_path / "library")
    monkeypatch.setattr(resume_store, "_store_path", lambda: tmp_path / "snapshot.json")
    monkeypatch.setattr(session_mod, "agent_argv", lambda name: (f"/usr/bin/{name}",))
    monkeypatch.setattr(chat_threads, "SETTLE_S", 0.01)

    async def installed() -> dict[str, bool]:
        return {}

    monkeypatch.setattr(coding_threads, "_installed_clis", installed)
    jobs.set_ledger(jobs.JobLedger(tmp_path / "jobs.db"))
    registry = Registry(pty_manager=FakePtyManager())
    folder = tmp_path / "Personal Jarvis"
    folder.mkdir()
    project = library.ensure_project(folder)
    (tmp_path / "Website").mkdir()
    library.ensure_project(tmp_path / "Website")
    workspace = Session(
        id=uuid4().hex,
        folder=str(folder),
        name="Personal Jarvis",
        profile=probe_project(folder),
        terminals=[
            Terminal("t1", "Alex", "codex", "Codex", 0, status="live", activity="idle",
                     activity_at=time.time())
        ],
        created_at=1,
        project_id=project.id,
    )
    registry._sessions[workspace.id] = workspace
    registry._active = workspace.id
    ledger = LiveLedger(tmp_path / "receipts.db")
    service = ScriptedService(AgentChatStore(":memory:"))
    published: list[Any] = []

    async def publish(event: Any) -> None:
        published.append(event)

    orchestrator = WorkspaceOrchestrator(
        registry, None, ledger, threads=ChatThreads(lambda: service)
    )
    orchestrator.publish = publish
    token = current_delegation_origin.set(dict(VOICE))
    try:
        yield Rig(orchestrator, registry, service, workspace, published)
    finally:
        current_delegation_origin.reset(token)
        ledger.close()
        jobs.set_ledger(None)
        task_state.reset()


async def create(rig: Rig, **args: Any) -> dict[str, Any]:
    return await rig.orchestrator.run(
        {"action": "create", "cli": "Codex", "prompt": "Fix the failing tests", **args}
    )


def test_the_mode_is_chat_unless_the_grid_is_named():
    assert spawn_mode(None) == "chat"
    assert spawn_mode("") == "chat"
    assert spawn_mode("chat") == "chat"
    assert spawn_mode("Grid") == "grid"
    assert spawn_mode("terminal") == "grid"
    # One creation per request: an unreadable mode still opens the agent.
    assert spawn_mode("sideways") == "chat"


def test_the_tool_offers_the_mode_and_names_chat_the_default():
    mode = WorkspaceOrchestrationTool.schema["properties"]["mode"]
    assert mode["enum"] == ["chat", "grid"]
    assert "default" in mode["description"]
    assert "chat threads" in WorkspaceOrchestrationTool.description


async def test_a_new_agent_opens_as_a_chat_thread_not_a_pane(rig: Rig):
    panes = len(rig.workspace.terminals)

    result = await create(rig)

    assert result["status"] == "created" and result["mode"] == "chat", result
    assert len(rig.workspace.terminals) == panes
    [agent] = result["agents"]
    assert agent["terminal_id"].startswith("thread:") and agent["cli"] == "codex"
    [thread] = rig.threads()
    assert agent["terminal_id"] == "thread:" + thread.session_id
    assert thread.surface == "agent" and thread.cwd == rig.workspace.folder
    assert [d["status"] for d in result["deliveries"]] == ["accepted"]
    assert result["success"] is True
    await rig.settle()
    assert rig.service.prompts == [(thread.session_id, "Fix the failing tests")]
    # The thread shows who wrote the task.
    assert rig.service.authors[0]["agent_id"] == "jarvis"


async def test_a_thread_opens_in_the_pane_stance_not_with_full_access(rig: Rig):
    from dodaios.agent_chat.permissions import default_permission
    from dodaios.agent_chat.service import resolve_runner

    await create(rig)

    [thread] = rig.threads()
    runner = resolve_runner(thread.provider, surface="agent")
    assert thread.permission_mode == default_permission(runner)


async def test_the_grid_is_used_when_the_request_names_it(rig: Rig):
    panes = len(rig.workspace.terminals)

    result = await rig.orchestrator.run(
        {"action": "create", "cli": "Codex", "mode": "grid", "count": 2}
    )

    assert result["status"] == "created" and result["mode"] == "grid", result
    assert len(rig.workspace.terminals) == panes + 2
    assert all(a["terminal_id"].startswith("pane:") for a in result["agents"])
    assert rig.threads() == []


async def test_several_agents_are_several_threads_with_names_to_tell_apart(rig: Rig):
    result = await create(rig, cli=None, agents=[{"cli": "Codex", "count": 2}])

    assert [a["name"] for a in result["agents"]] == ["Codex 1", "Codex 2"]
    assert len(rig.threads()) == 2
    assert result["requested"] == 2 and result["capped"] is False
    await rig.settle()
    assert sorted(prompt for _sid, prompt in rig.service.prompts) == [
        "Fix the failing tests", "Fix the failing tests",
    ]


async def test_a_named_project_needs_no_open_workspace(rig: Rig, tmp_path):
    result = await create(rig, project="Website")

    assert result["status"] == "created", result
    [thread] = rig.threads()
    assert thread.cwd == str(tmp_path / "Website")
    assert result["workspace_id"] == "" and result["project"] == "Website"


async def test_a_folder_names_the_place_and_becomes_a_project(rig: Rig, tmp_path):
    fresh = tmp_path / "Brand new"
    fresh.mkdir()

    result = await create(rig, folder=str(fresh))

    assert result["status"] == "created", result
    assert rig.threads()[0].cwd == str(fresh.resolve())
    assert any(p.path == str(fresh.resolve()) for p in library.list_projects())


async def test_an_unknown_project_asks_and_opens_nothing(rig: Rig):
    result = await create(rig, project="Nowhere")

    assert result["status"] == "needs_clarification" and result["kind"] == "project"
    assert {c["project"] for c in result["candidates"]} == {"Personal Jarvis", "Website"}
    assert rig.threads() == []


async def test_a_cli_without_a_chat_mode_opens_in_the_grid(rig: Rig, monkeypatch):
    from dodaios.agentic_ide import orchestration

    monkeypatch.setattr(orchestration, "chat_provider", lambda cli: None)
    panes = len(rig.workspace.terminals)

    result = await rig.orchestrator.run({"action": "create", "cli": "Codex"})

    assert result["status"] == "created" and result["mode"] == "grid", result
    assert "terminal pane" in result["mode_note"]
    assert len(rig.workspace.terminals) == panes + 1
    assert rig.threads() == []


async def test_a_retried_creation_reads_its_receipt_and_opens_no_second_thread(rig: Rig):
    first = await create(rig, _dispatch_scope="turn-1")
    again = await create(rig, _dispatch_scope="turn-1")

    assert again["agents"] == first["agents"]
    assert len(rig.threads()) == 1


async def test_a_finished_thread_reports_to_the_spoken_conversation(rig: Rig):
    rig.service.hold = asyncio.Event()
    result = await create(rig)
    sid = result["agents"][0]["terminal_id"].removeprefix("thread:")
    rig.service.steps[sid] = ["All 12 tests pass now."]
    rig.service.hold.set()
    await rig.settle()

    [report] = rig.results()
    assert isinstance(report, AnnouncementRequested)
    assert report.source_layer == "agentic_ide.readback"
    assert "has finished" in report.text and "All 12 tests pass now." in report.report
    assert "Fix the failing tests" in report.report
    # Reported once; the thread is no longer followed.
    assert sid not in rig.orchestrator.threads._tracked


async def test_a_typed_conversation_gets_a_card_and_the_result_in_its_chat(rig: Rig):
    lead = rig.service.create_session(provider="claude-api", surface="jarvis")
    current_delegation_origin.set(
        {"reply_surface": "chat", "reply_session_id": lead.session_id, "lang": "en"}
    )

    result = await create(rig)
    await rig.settle()

    sid = result["agents"][0]["terminal_id"].removeprefix("thread:")
    notices = [e for e in rig.service.store.list_events(lead.session_id) if e["kind"] == "notice"]
    assert notices[0]["payload"]["kind"] == "coding_thread"
    assert notices[0]["payload"]["thread_id"] == sid
    [report] = rig.results()
    assert isinstance(report, DelegationResultReady)
    assert report.session_id == lead.session_id and report.status == "completed"
    # Nothing moves on screen while the person types in their chat.
    assert not [e for e in rig.published if isinstance(e, NavigateSidebar)]


async def test_a_spoken_request_brings_the_thread_forward_in_chat(rig: Rig):
    result = await create(rig)
    await rig.settle()

    [shown] = [e for e in rig.published if isinstance(e, NavigateSidebar)]
    assert shown.section == "agentic-ide" and shown.target == "thread"
    assert "thread:" + shown.target_id == result["agents"][0]["terminal_id"]


async def test_a_failed_turn_is_reported_as_failed(rig: Rig):
    rig.service.hold = asyncio.Event()
    result = await create(rig)
    sid = result["agents"][0]["terminal_id"].removeprefix("thread:")
    rig.service.steps[sid] = [["error"]]
    rig.service.hold.set()
    await rig.settle()

    [report] = rig.results()
    assert "failed" in report.text and "the CLI crashed" in report.report


async def test_a_question_is_reported_and_a_turn_the_person_takes_over_is_theirs(rig: Rig):
    rig.service.hold = asyncio.Event()
    result = await create(rig)
    sid = result["agents"][0]["terminal_id"].removeprefix("thread:")
    rig.service.steps[sid] = [[
        "I need one decision first.",
        make_event("question_required", {
            "question_id": "q1", "deferred": True,
            "questions": [{"question": "Which database?", "options": [{"label": "SQLite"}]}],
        }),
    ]]
    rig.service.hold.set()
    await rig.settle()

    [asked] = rig.results()
    assert "needs your input" in asked.text and "Which database?" in asked.report
    # Still followed: the answer may come from this conversation.
    assert sid in rig.orchestrator.threads._tracked
    board = await rig.orchestrator.run({"action": "status"})
    assert board["threads"][0]["state"] == "needs_input"
    assert any("chat thread" in name for name in board["needs_you"])

    rig.published.clear()
    # The person answers in the thread themselves: that turn is theirs.
    await rig.service.send(sid, "Use SQLite and carry on")
    await rig.settle()

    assert rig.results() == []
    assert sid not in rig.orchestrator.threads._tracked


async def test_a_follow_up_goes_to_the_thread_by_its_id(rig: Rig):
    result = await create(rig)
    target = result["agents"][0]["terminal_id"]
    await rig.settle()

    receipt = await rig.orchestrator.run(
        {"action": "send", "terminal_id": target, "prompt": "Also update the docs"}
    )

    assert receipt["status"] == "accepted" and receipt["target"]["terminal_id"] == target
    await rig.settle()
    assert [prompt for _sid, prompt in rig.service.prompts] == [
        "Fix the failing tests", "Also update the docs",
    ]
    assert len(rig.threads()) == 1
    # The same instruction again is the same request, not a second delivery.
    again = await rig.orchestrator.run(
        {"action": "send", "terminal_id": target, "prompt": "Also update the docs"}
    )
    assert again["status"] == "accepted"
    await rig.settle()
    assert len(rig.service.prompts) == 2


async def test_a_thread_in_a_turn_takes_nothing_until_it_is_interrupted(rig: Rig):
    rig.service.hold = asyncio.Event()
    result = await create(rig)
    target = result["agents"][0]["terminal_id"]
    await asyncio.sleep(0.05)

    busy = await rig.orchestrator.run(
        {"action": "send", "terminal_id": target, "prompt": "Stop, use pytest instead"}
    )
    assert busy["status"] == "not_accepted" and busy["busy"] is True
    assert busy["input_written"] is False

    stopped = await rig.orchestrator.run({"action": "interrupt", "terminal_id": target})
    assert stopped["status"] == "interrupted"
    rig.service.hold.set()
    await rig.settle()

    # Nothing was written, so the same request is free to go again.
    retry = await rig.orchestrator.run(
        {"action": "send", "terminal_id": target, "prompt": "Stop, use pytest instead"}
    )
    assert retry["status"] == "accepted", retry
    await rig.settle()


async def test_the_status_board_lists_threads_beside_the_panes(rig: Rig):
    result = await create(rig)
    await rig.settle()

    board = await rig.orchestrator.run({"action": "status"})

    [thread] = board["threads"]
    assert thread["terminal_id"] == result["agents"][0]["terminal_id"]
    assert thread["state"] == "idle" and thread["mode"] == "chat"
    assert thread["job"] == "Fix the failing tests"
    assert board["counts"]["idle"] >= 1
    # A board narrowed to another project leaves this thread out.
    other = await rig.orchestrator.run({"action": "status", "project": "Website"})
    assert "threads" not in other


async def test_observe_reads_the_thread_and_pane_actions_are_refused(rig: Rig):
    rig.service.hold = asyncio.Event()
    result = await create(rig)
    target = result["agents"][0]["terminal_id"]
    sid = target.removeprefix("thread:")
    rig.service.steps[sid] = ["Done: 3 files changed."]
    rig.service.hold.set()
    await rig.settle()

    seen = await rig.orchestrator.run({"action": "observe", "terminal_id": target})
    assert seen["status"] == "observed"
    assert [e["text"] for e in seen["events"] if e["from"] == "coding agent"] == [
        "Done: 3 files changed."
    ]

    resolved = await rig.orchestrator.run({"action": "resolve", "terminal_id": target})
    assert resolved["status"] == "resolved" and resolved["target"]["terminal_id"] == target

    refused = await rig.orchestrator.run({"action": "keys", "terminal_id": target, "keys": ["y"]})
    assert refused["status"] == "not_accepted" and "terminal panes" in refused["reason"]


async def test_a_thread_that_is_gone_is_a_stale_target(rig: Rig):
    receipt = await rig.orchestrator.run(
        {"action": "send", "terminal_id": "thread:missing", "prompt": "Hello"}
    )

    assert receipt["status"] == "stale_target" and receipt["input_written"] is False


async def test_without_a_chat_service_new_agents_still_open_as_panes(rig: Rig):
    def unavailable() -> Any:
        raise RuntimeError("no web server")

    rig.orchestrator.threads = ChatThreads(unavailable)
    panes = len(rig.workspace.terminals)

    result = await rig.orchestrator.run({"action": "create", "cli": "Codex"})

    assert result["status"] == "created" and result["mode"] == "grid", result
    assert len(rig.workspace.terminals) == panes + 1
