"""A thread keeps its CLI conversation when its first turn never reaches its end.

The conversation id used to reach the session only as the turn's return value.
A reboot or a crash in the first turn left the thread without it, and the next
message started a CLI that knew nothing of the work so far.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

from dodaios.agent_chat import runner_cli
from dodaios.agent_chat import service as service_module
from dodaios.agent_chat.runner_api import TurnHandle
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS


async def _until(predicate, limit_s: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + limit_s
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.01)


async def _no_approval(*_args):
    pytest.fail("No approval should be requested")


def _fake_claude(conversation: str) -> str:
    """A CLI that names its conversation, answers once and then works for ever."""
    lines = [
        {"type": "system", "subtype": "init", "session_id": conversation},
        {
            "type": "assistant",
            "session_id": conversation,
            "message": {"id": "m", "content": [{"type": "text", "text": "Working on it."}]},
        },
    ]
    return (
        "import sys, time\n"
        + "\n".join(f"print({json.dumps(line)!r}, flush=True)" for line in lines)
        + "\ntime.sleep(120)\n"
    )


async def _drive(handle: TurnHandle, source: str, tmp_path: Path, *, resume: str | None = None):
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",
        "-c",
        source,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=NO_WINDOW_CREATIONFLAGS,
    )
    task = asyncio.create_task(
        runner_cli._drive_cli(
            handle,
            proc,
            runner_cli.CliPlan(
                argv=[],
                env={},
                stdin_text="prompt\n",
                shape="claude",
                vendor_session=resume,
                keep_stdin=True,
            ),
            "claude-cli",
            cwd=tmp_path,
            started_at=time.time(),
            placement=None,
            tree=None,
            bridge=None,
            timeout_s=60.0,
        )
    )
    return proc, task


async def _hard_stop(proc, task) -> None:
    """The machine goes down: the CLI dies and the app never sees the turn end."""
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    if proc.returncode is None:
        proc.kill()
    await asyncio.wait_for(proc.wait(), 5)


async def test_a_first_turn_cut_off_by_a_hard_stop_keeps_its_conversation(tmp_path: Path):
    database = tmp_path / "agent_chat.db"
    service = AgentChatService(AgentChatStore(database))
    session = service.store.create_session(
        provider="claude-api", model="fake", effort="", cwd=str(tmp_path)
    )
    seen: list[dict] = []

    async def emit(event):
        seen.append(event)

    handle = TurnHandle(
        session,
        "turn",
        emit,
        _no_approval,
        asyncio.Event(),
        on_conversation=lambda vendor: service._keep_conversation(session.session_id, vendor),
    )
    proc, task = await _drive(handle, _fake_claude("conv-1"), tmp_path)
    try:
        await _until(lambda: any(e["kind"] == "assistant_text" for e in seen))
        # The turn is still running, and the session already knows its conversation.
        assert not task.done()
        assert service.store.get_session(session.session_id).vendor_session == "conv-1"
    finally:
        await _hard_stop(proc, task)
        service.store.close()

    # The next process reads the same file: the next message resumes "conv-1".
    restarted = AgentChatStore(database)
    try:
        assert restarted.get_session(session.session_id).vendor_session == "conv-1"
    finally:
        restarted.close()


async def test_a_resumed_conversation_is_not_written_again(tmp_path: Path):
    store = AgentChatStore(":memory:")
    session = store.create_session(
        provider="claude-api", model="fake", effort="", cwd=str(tmp_path)
    )
    session = store.update_session(session.session_id, vendor_session="conv-1")
    seen: list[dict] = []
    written: list[str] = []

    async def emit(event):
        seen.append(event)

    handle = TurnHandle(
        session, "turn", emit, _no_approval, asyncio.Event(), on_conversation=written.append
    )
    proc, task = await _drive(handle, _fake_claude("conv-1"), tmp_path, resume="conv-1")
    try:
        await _until(lambda: any(e["kind"] == "assistant_text" for e in seen))
        assert written == []
    finally:
        await _hard_stop(proc, task)
        store.close()


async def test_a_turn_without_a_writer_runs_as_before(tmp_path: Path):
    """Task turns and evals share the runner and own no session row to write."""
    store = AgentChatStore(":memory:")
    session = store.create_session(
        provider="claude-api", model="fake", effort="", cwd=str(tmp_path)
    )
    seen: list[dict] = []

    async def emit(event):
        seen.append(event)

    handle = TurnHandle(session, "turn", emit, _no_approval, asyncio.Event())
    proc, task = await _drive(handle, _fake_claude("conv-1"), tmp_path)
    try:
        await _until(lambda: any(e["kind"] == "assistant_text" for e in seen))
        assert store.get_session(session.session_id).vendor_session is None
    finally:
        await _hard_stop(proc, task)
        store.close()


async def test_the_service_hands_every_thread_turn_a_writer(tmp_path: Path, monkeypatch):
    """The thread's own turn: the id is in the session before the turn returns."""
    service = AgentChatService(AgentChatStore(":memory:"))
    session = service.store.create_session(
        provider="claude-api", model="fake", effort="", cwd=str(tmp_path), surface="agent"
    )
    named = asyncio.Event()
    release = asyncio.Event()

    async def run(handle, prompt, runner, **_kwargs):
        assert handle.on_conversation is not None
        handle.on_conversation("conv-1")
        named.set()
        await release.wait()
        await handle.emit(
            service_module.make_event(
                "turn_finished", {"turn_id": handle.turn_id, "status": "done", "usage": {}}
            )
        )
        return "conv-1"

    monkeypatch.setattr(service_module, "resolve_runner", lambda *args, **kwargs: "claude-cli")
    monkeypatch.setattr(service_module, "run_cli_turn", run)
    try:
        await service.send(session.session_id, "Please start.")
        await asyncio.wait_for(named.wait(), 10)
        assert service.is_running(session.session_id)
        assert service.store.get_session(session.session_id).vendor_session == "conv-1"
    finally:
        release.set()
        await _until(lambda: not service.is_running(session.session_id))
        service.store.close()
