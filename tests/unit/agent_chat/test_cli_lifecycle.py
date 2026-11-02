"""Completion requires a terminal result and a reaped process, not final-sounding text."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

from dodaios.agent_chat import runner_cli
from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.runner_api import TurnHandle
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS


@pytest.mark.parametrize(
    ("result", "ending", "expected", "error"),
    [
        (True, "pass", "done", None),
        (True, "sys.stdin.read()", "done", None),
        (True, "sys.exit(7)", "error", "exited with code 7"),
        (False, "pass", "error", "without a terminal result"),
        (False, "time.sleep(60)", "error", "did not finish within"),
        (True, "time.sleep(60)", "error", "did not finish within"),
        (True, "os.close(1); os.close(2); time.sleep(60)", "error", "did not finish within"),
    ],
    ids=[
        "success",
        "stdin-eof",
        "nonzero",
        "partial-exit",
        "partial-stuck",
        "result-stuck",
        "pipes-closed-stuck",
    ],
)
async def test_claude_process_completion(tmp_path: Path, result, ending, expected, error):
    store = AgentChatStore(":memory:")
    session = store.create_session(
        provider="claude-api", model="fake", effort="", cwd=str(tmp_path)
    )
    events = []

    async def emit(event):
        events.append(event)

    async def approve(*_args):
        pytest.fail("No approval should be requested")

    handle = TurnHandle(session, "turn", emit, approve, asyncio.Event())
    answer = {
        "type": "assistant",
        "message": {"id": "m", "content": [{"type": "text", "text": "Fix committed locally."}]},
    }
    lines = [answer]
    if result:
        lines.append(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "usage": {"output_tokens": 12},
            }
        )
    source = (
        "import sys, time, os\n"
        + "\n".join(f"print({json.dumps(line)!r}, flush=True)" for line in lines)
        + "\n"
        + ending
    )
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
    try:
        outcome = await asyncio.wait_for(
            runner_cli._drive_cli(
                handle,
                proc,
                runner_cli.CliPlan(
                    argv=[],
                    env={},
                    stdin_text="prompt\n",
                    shape="claude",
                    vendor_session=None,
                    keep_stdin=True,
                ),
                "claude-cli",
                cwd=tmp_path,
                started_at=time.time(),
                placement=None,
                tree=None,
                bridge=None,
                timeout_s=1.0,
            ),
            timeout=4.0,
        )
        assert outcome.status == expected
        assert (error in outcome.error) if error else outcome.error is None
        assert proc.returncode is not None
        assert [e["payload"]["text"] for e in events if e["kind"] == "assistant_text"] == [
            "Fix committed locally."
        ]
        if result:
            assert outcome.usage["output_tokens"] == 12
    finally:
        if proc.returncode is None:
            proc.kill()
        await asyncio.wait_for(proc.wait(), 3)
        store.close()


def test_a_coding_agent_turn_has_no_wall_clock_limit():
    """Sessions may run for days, for every coding CLI (no 3600 s cut-off)."""
    import inspect

    assert runner_cli._TURN_TIMEOUT_S is None
    default = inspect.signature(runner_cli._drive_cli).parameters["timeout_s"].default
    assert default is None


async def _drive_fake_claude(tmp_path: Path, source: str) -> tuple[object, object]:
    store = AgentChatStore(":memory:")
    session = store.create_session(
        provider="claude-api", model="fake", effort="", cwd=str(tmp_path)
    )

    async def emit(_event):
        return None

    async def approve(*_args):
        pytest.fail("No approval should be requested")

    handle = TurnHandle(session, "turn", emit, approve, asyncio.Event())
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
    try:
        outcome = await asyncio.wait_for(
            runner_cli._drive_cli(
                handle,
                proc,
                runner_cli.CliPlan(
                    argv=[],
                    env={},
                    stdin_text="prompt\n",
                    shape="claude",
                    vendor_session=None,
                    keep_stdin=False,
                ),
                "claude-cli",
                cwd=tmp_path,
                started_at=time.time(),
                placement=None,
                tree=None,
                bridge=None,
            ),
            timeout=8.0,
        )
    finally:
        if proc.returncode is None:
            proc.kill()
        await asyncio.wait_for(proc.wait(), 3)
        store.close()
    return outcome, proc


_RESULT_LINE = json.dumps(
    {"type": "result", "subtype": "success", "is_error": False, "usage": {"output_tokens": 1}}
)


async def test_a_long_silent_turn_is_not_cut_off(tmp_path: Path, monkeypatch):
    """Silent work before the final answer is never stopped by a clock."""
    monkeypatch.setattr(runner_cli, "_ACP_WATCH_TICK_S", 0.05)
    monkeypatch.setattr(runner_cli, "_EXIT_AFTER_RESULT_S", 0.3)
    source = f"import time\ntime.sleep(1.5)\nprint({_RESULT_LINE!r}, flush=True)\n"
    outcome, _proc = await _drive_fake_claude(tmp_path, source)
    assert outcome.status == "done", outcome.error


async def test_a_cli_lingering_silently_after_its_answer_is_stopped(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(runner_cli, "_ACP_WATCH_TICK_S", 0.05)
    monkeypatch.setattr(runner_cli, "_EXIT_AFTER_RESULT_S", 0.3)
    source = f"import time\nprint({_RESULT_LINE!r}, flush=True)\ntime.sleep(60)\n"
    outcome, proc = await _drive_fake_claude(tmp_path, source)
    assert outcome.status == "error"
    assert "of its final answer" in outcome.error
    assert proc.returncode is not None


@pytest.mark.parametrize("status", ["done", "error", "cancelled"])
async def test_a_turn_publishes_its_terminal_status_only_once(tmp_path, status):
    store = AgentChatStore(":memory:")
    service = AgentChatService(store)
    session = store.create_session(provider="openai", model="fake", effort="", cwd=str(tmp_path))
    seen = []
    service._event_listeners.append(lambda _sid, event: seen.append(event))
    try:
        first = make_event(
            "turn_finished", {"turn_id": "t", "status": status, "usage": {"output_tokens": 12}}
        )
        late = make_event(
            "turn_finished",
            {
                "turn_id": "t",
                "status": "error",
                "error": "claude-cli did not finish within 3600 s.",
            },
        )
        await service._emit(session.session_id, first)
        await service._emit(session.session_id, late)
        assert len(seen) == 1
        assert len(store.list_events(session.session_id)) == 1
        # Old logs already contain duplicates. Reading their canonical outcome
        # must agree with replay in the UI, without rewriting the audit trail.
        store.append_event(session.session_id, late)
        terminal = store.turn_terminal(session.session_id, "t")
        assert terminal["payload"] == first["payload"]
    finally:
        store.close()
