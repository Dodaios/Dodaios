"""A slow tool does not hold the lead: the next message is answered, then the result arrives."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from dodaios.agent_chat import delegation_wait, parked_work, send_queue
from dodaios.agent_chat import service as service_mod
from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.parked_work import BACKGROUND_ORIGIN
from dodaios.agent_chat.send_queue import send_or_queue
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.core.protocols import ToolResult
from dodaios.orchestrator import async_tools, jobs

_FIRST = "Build the project and tell me when it is done."
_SECOND = "What is two plus two?"


async def _until(predicate, limit_s: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + limit_s
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.005)


class Build:
    """A shell command that ends when the test says so."""

    name = "run_shell"

    def __init__(self) -> None:
        self.done = asyncio.Event()

    async def execute(self, args, ctx):
        await self.done.wait()
        return ToolResult(True, {"stdout": "build ok", "exit_code": 0})


class Chat:
    def __init__(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(delegation_wait, "POLL_SECONDS", 0.005)
        monkeypatch.setattr(parked_work, "_POLL_S", 0.005)
        monkeypatch.setattr(send_queue, "_POLL_S", 0.005)
        monkeypatch.setenv("DODAIOS_ASYNC_TOOL_BUDGET_S", "0.05")
        self.ledger = jobs.JobLedger(tmp_path / "jobs.db")
        jobs.set_ledger(self.ledger)
        self.store = AgentChatStore(tmp_path / "chat.db")
        self.svc = AgentChatService(self.store)
        self.sid = self.store.create_session(
            provider="openai", model="", effort="", surface="jarvis", cwd=str(tmp_path)
        ).session_id
        self.prompts: list[tuple[str, str]] = []
        self.build = Build()
        self.tool_output: dict | None = None
        monkeypatch.setattr(service_mod, "run_brain_turn", self._model)
        monkeypatch.setattr(service_mod, "resolve_runner", lambda *a, **kw: "brain")

    async def _model(self, handle, prompt, *args, **kwargs) -> None:
        index = len(self.prompts)
        self.prompts.append((handle.turn_id, prompt))
        if index == 0:
            ctx = SimpleNamespace(
                trace_id=uuid4(), user_utterance=prompt, memory_read=None,
                config={"approval_ref": f"agent-chat:{self.sid}", "tool_origin": "agent-chat"},
            )
            result = await async_tools.run_tool(self.build, {"command": "npm run build"}, ctx)
            self.tool_output = result.output
            text = "The build is running; I will report when it ends."
        elif index == 1:
            text = "Four."
        else:
            text = "The build finished."
        await handle.emit(make_event("assistant_text", {"turn_id": handle.turn_id, "text": text}))
        await handle.emit(make_event(
            "turn_finished", {"turn_id": handle.turn_id, "status": "done", "usage": {}},
        ))

    def events(self, kind: str) -> list[dict]:
        return [e for e in self.store.list_events(self.sid) if e["kind"] == kind]

    async def idle(self) -> None:
        await _until(lambda: not self.svc.is_running(self.sid))


@pytest.fixture
def chat(tmp_path, monkeypatch):
    built = Chat(tmp_path, monkeypatch)
    yield built
    built.svc.parked_work.stop(built.sid)
    jobs.set_ledger(None)
    built.ledger.close()
    built.store.close()


async def test_the_lead_answers_a_new_message_while_a_slow_tool_runs_then_gets_its_result(chat):
    first_turn, _ = await send_or_queue(chat.svc, chat.sid, _FIRST)
    await _until(lambda: chat.tool_output is not None)
    job_id = chat.tool_output["job_id"]
    assert chat.tool_output["started"] is True
    await _until(lambda: any("Waiting for agents" in e["payload"].get("text", "")
                             for e in chat.events("reasoning")))

    # The person writes again while the build runs: answered at once, no wait.
    second_turn, queue_id = await send_or_queue(chat.svc, chat.sid, _SECOND)
    assert second_turn and queue_id == ""
    await chat.idle()
    assert jobs.get_ledger().get(job_id).state == "running"  # the build is still going
    assert chat.prompts[1][1] == _SECOND
    assert [e["payload"]["text"] for e in chat.events("assistant_text")][1] == "Four."
    assert len(chat.prompts) == 2  # no model call for the build while it runs

    # The build ends: its result reaches the conversation as an event of its own.
    chat.build.done.set()
    await _until(lambda: len(chat.prompts) == 3)
    await chat.idle()
    result_turn, result_prompt = chat.prompts[2]
    assert result_turn not in (first_turn, second_turn)
    assert "build ok" in result_prompt and _FIRST in result_prompt
    marker = chat.events("user_message")[2]["payload"]
    assert marker["origin"] == BACKGROUND_ORIGIN
    assert jobs.get_ledger().get(job_id).state == "done"
    assert not chat.events("error")


async def test_an_undisturbed_turn_is_continued_with_the_result(chat):
    await send_or_queue(chat.svc, chat.sid, _FIRST)
    await _until(lambda: chat.tool_output is not None)
    chat.build.done.set()
    await _until(lambda: len(chat.prompts) == 2)
    await chat.idle()
    assert "build ok" in chat.prompts[1][1]


async def test_a_stopped_job_reports_cancelled_into_the_conversation(chat):
    await send_or_queue(chat.svc, chat.sid, _FIRST)
    await _until(lambda: chat.tool_output is not None)
    assert async_tools.stop(chat.tool_output["job_id"]) == "stopped"
    await _until(lambda: len(chat.prompts) == 2)
    await chat.idle()
    assert "cancelled" in chat.prompts[1][1]
