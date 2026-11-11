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
    ],
    ids=[
        "success",
        "stdin-eof",
        "nonzero",
        "partial-exit",
        "partial-stuck",
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
                timeout_s=5.0,
            ),
            timeout=20.0,
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


async def _drive_fake_claude(
    tmp_path: Path,
    source: str,
    *,
    reap: bool = True,
    runner: str = "claude-cli",
    events: list | None = None,
    keep_stdin: bool = False,
) -> tuple[object, object]:
    store = AgentChatStore(":memory:")
    session = store.create_session(
        provider="claude-api", model="fake", effort="", cwd=str(tmp_path)
    )

    async def emit(event):
        if events is not None:
            events.append(event)

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
                    keep_stdin=keep_stdin,
                ),
                runner,
                cwd=tmp_path,
                started_at=time.time(),
                placement=None,
                tree=None,
                bridge=None,
            ),
            timeout=30.0,
        )
    finally:
        if reap:
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
    source = f"import time\ntime.sleep(1.5)\nprint({_RESULT_LINE!r}, flush=True)\n"
    outcome, _proc = await _drive_fake_claude(tmp_path, source)
    assert outcome.status == "done", outcome.error


async def _settle_lingering() -> None:
    for tasks in list(runner_cli._LINGERING.values()):
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize(
    "ending",
    ["time.sleep(60)", "os.close(1); os.close(2); time.sleep(60)"],
    ids=["lingers", "pipes-closed-lingers"],
)
async def test_a_cli_lingering_after_its_answer_ends_the_turn_promptly(
    tmp_path: Path, monkeypatch, ending
):
    """The answer is in: the turn ends within about a second, as done, and the
    lingering process is killed in the background after a short grace."""
    monkeypatch.setattr(runner_cli, "_REAP_GRACE_S", 0.3)
    source = f"import os, time\nprint({_RESULT_LINE!r}, flush=True)\n{ending}\n"
    t0 = time.monotonic()
    outcome, proc = await _drive_fake_claude(tmp_path, source, reap=False)
    assert outcome.status == "done", outcome.error
    assert outcome.error is None
    assert outcome.usage["output_tokens"] == 1
    # Far below the 60 s the process would linger (generous for a loaded box).
    assert time.monotonic() - t0 < 20.0
    await _settle_lingering()
    assert proc.returncode is not None


async def test_the_next_turn_waits_for_a_lingering_cli(monkeypatch):
    gate = asyncio.Event()
    order: list[str] = []
    hurried: list[bool] = []

    async def shutting_down(hurry: asyncio.Event) -> None:
        await gate.wait()
        hurried.append(hurry.is_set())
        order.append("reaped")

    runner_cli._linger("s-linger", shutting_down)
    waiter = asyncio.create_task(runner_cli._await_lingering("s-linger", asyncio.Event()))
    await asyncio.sleep(0.05)
    assert not waiter.done()
    gate.set()
    assert await waiter is True
    order.append("next turn")
    assert order == ["reaped", "next turn"]
    assert hurried == [True]  # the lingering CLI was told a turn waits for it
    assert "s-linger" not in runner_cli._LINGERING


async def test_stop_while_waiting_for_a_lingering_cli_starts_nothing():
    gate = asyncio.Event()

    async def shutting_down(_hurry: asyncio.Event) -> None:
        await gate.wait()

    runner_cli._linger("s-stop", shutting_down)
    cancel = asyncio.Event()
    waiter = asyncio.create_task(runner_cli._await_lingering("s-stop", cancel))
    await asyncio.sleep(0.05)
    cancel.set()
    assert await asyncio.wait_for(waiter, 2) is False
    gate.set()
    await _settle_lingering()


async def test_a_late_answer_after_a_background_task_is_part_of_the_turn(
    tmp_path: Path, monkeypatch
):
    """Claude Code answers, its background task ends, and seconds later it
    wakes and answers again: that answer belongs to the turn and is not cut."""
    started = json.dumps(
        {"type": "system", "subtype": "task_started", "task_id": "b1", "description": "pytest"}
    )
    ended = json.dumps(
        {"type": "system", "subtype": "task_notification", "task_id": "b1", "status": "completed"}
    )
    wake = json.dumps(
        {"type": "stream_event", "event": {"type": "message_start", "message": {"id": "m2"}}}
    )
    late = json.dumps(
        {
            "type": "assistant",
            "message": {"id": "m2", "content": [{"type": "text", "text": "Late: tests pass."}]},
        }
    )
    source = (
        "import time\n"
        f"print({started!r}, flush=True)\n"
        f"print({_RESULT_LINE!r}, flush=True)\n"
        "time.sleep(0.5)\n"
        f"print({ended!r}, flush=True)\n"
        "time.sleep(3.0)\n"
        f"print({wake!r}, flush=True)\n"
        f"print({late!r}, flush=True)\n"
        f"print({_RESULT_LINE!r}, flush=True)\n"
    )
    events: list = []
    outcome, proc = await _drive_fake_claude(tmp_path, source, events=events)
    assert outcome.status == "done", outcome.error
    texts = [e["payload"]["text"] for e in events if e["kind"] == "assistant_text"]
    assert "Late: tests pass." in texts
    assert proc.returncode == 0  # it ended by itself, never killed


async def test_a_cli_still_writing_after_its_answer_is_not_killed(tmp_path: Path, monkeypatch):
    """Post-answer work (a SessionEnd hook, a flush) that still prints is no
    stall: the silence limit restarts with every line, there is no clock."""
    monkeypatch.setattr(runner_cli, "_REAP_GRACE_S", 0.5)
    source = (
        "import sys, time\n"
        f"print({_RESULT_LINE!r}, flush=True)\n"
        "for i in range(10):\n"
        "    time.sleep(0.25)\n"
        "    print('hook output', i, file=sys.stderr, flush=True)\n"
    )
    outcome, proc = await _drive_fake_claude(tmp_path, source, reap=False)
    assert outcome.status == "done", outcome.error
    await _settle_lingering()
    assert proc.returncode == 0


async def test_a_handed_over_cli_is_never_reaped():
    class _Handed:
        returncode = None
        handed_over = True
        detached = True
        stdout = None
        stderr = None
        killed = released = False

        def kill(self) -> None:
            self.killed = True

        def release(self) -> None:
            self.released = True

    proc = _Handed()
    cleaned: list[bool] = []
    await asyncio.wait_for(
        runner_cli._reap_after_answer(
            asyncio.Event(), proc, "t", "claude-cli", True, lambda: cleaned.append(True)
        ),
        2,
    )
    assert not proc.killed and not proc.released and not cleaned


async def test_the_drain_never_cuts_a_line_still_being_handled(monkeypatch):
    """A pump busy with a line (a slow emit, a stalled loop) is not cut off by
    the drain window, and a line still buffered is read first."""
    monkeypatch.setattr(runner_cli, "_PIPE_DRAIN_S", 0.05)
    stdout = asyncio.StreamReader()
    for line in (b"one\n", b"result\n"):
        stdout.feed_data(line)
    stdout.feed_eof()

    class _Exited:
        returncode = 0
        stderr = None

    proc = _Exited()
    proc.stdout = stdout
    reads, busy, handled = [0], [False], []

    async def pump() -> None:
        while True:
            busy[0] = False
            raw = await stdout.readline()
            reads[0] += 1
            busy[0] = True
            if not raw:
                return
            await asyncio.sleep(0.3)  # far longer than the drain window
            handled.append(raw)

    pump_task = asyncio.create_task(pump())
    idle = asyncio.create_task(asyncio.sleep(0))
    await asyncio.wait_for(
        runner_cli._natural_end(proc, pump_task, idle, idle, lambda: reads[0], lambda: busy[0]),
        5,
    )
    assert handled == [b"one\n", b"result\n"]


async def test_open_background_tasks_keep_the_turn_open_without_a_clock(
    tmp_path: Path, monkeypatch
):
    """A result with an open task is not the end: the CLI wakes and answers again."""
    monkeypatch.setattr(runner_cli, "_RESULT_EXIT_GRACE_S", 0.1)
    started = json.dumps(
        {"type": "system", "subtype": "task_started", "task_id": "b1", "description": "pytest"}
    )
    ended = json.dumps(
        {"type": "system", "subtype": "task_notification", "task_id": "b1", "status": "completed"}
    )
    late = json.dumps(
        {
            "type": "assistant",
            "message": {"id": "m2", "content": [{"type": "text", "text": "Tests pass."}]},
        }
    )
    source = (
        "import time\n"
        f"print({started!r}, flush=True)\n"
        f"print({_RESULT_LINE!r}, flush=True)\n"
        "time.sleep(1.5)\n"
        f"print({ended!r}, flush=True)\n"
        f"print({late!r}, flush=True)\n"
        f"print({_RESULT_LINE!r}, flush=True)\n"
    )
    t0 = time.monotonic()
    outcome, _proc = await _drive_fake_claude(tmp_path, source)
    assert outcome.status == "done", outcome.error
    assert time.monotonic() - t0 >= 1.4


_GRANDCHILD = (
    "import subprocess, sys, time\n"
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],"
    " stdout=sys.stdout, stderr=sys.stderr)\n"
    "open({pidfile!r}, 'w').write(str(child.pid))\n"
)


def _kill_pid_from(pidfile: Path) -> None:
    import os
    import signal

    try:
        os.kill(int(pidfile.read_text()), signal.SIGTERM)
    except (OSError, ValueError):
        pass


async def test_a_grandchild_holding_the_pipes_does_not_hold_the_turn(tmp_path: Path):
    """The CLI exited; a process it left behind keeps stdout open. The turn ends."""
    pidfile = tmp_path / "grandchild.pid"
    source = _GRANDCHILD.format(pidfile=str(pidfile)) + "print('All done.', flush=True)\n"
    try:
        t0 = time.monotonic()
        outcome, events = await _drive_plain(tmp_path, source)
        assert outcome.status == "done", outcome.error
        # Far below the 30 s the grandchild holds the pipes.
        assert time.monotonic() - t0 < 15.0
        assert any(
            e["kind"] == "assistant_text" and "All done." in e["payload"]["text"] for e in events
        )
    finally:
        _kill_pid_from(pidfile)


async def test_stop_ends_the_turn_promptly_with_a_grandchild_holding_the_pipes(tmp_path: Path):
    pidfile = tmp_path / "grandchild.pid"
    source = (
        _GRANDCHILD.format(pidfile=str(pidfile)) + "print('working', flush=True)\ntime.sleep(60)\n"
    )
    try:
        t0 = time.monotonic()
        outcome, _events = await _drive_plain(tmp_path, source, stop_after=0.8)
        assert outcome.status == "cancelled"
        assert time.monotonic() - t0 < 15.0
    finally:
        _kill_pid_from(pidfile)


async def _drive_plain(
    tmp_path: Path, source: str, *, stop_after: float | None = None
) -> tuple[object, list[dict]]:
    store = AgentChatStore(":memory:")
    session = store.create_session(
        provider="claude-api", model="fake", effort="", cwd=str(tmp_path)
    )
    events: list[dict] = []

    async def emit(event):
        events.append(event)

    async def approve(*_args):
        pytest.fail("No approval should be requested")

    cancel = asyncio.Event()
    handle = TurnHandle(session, "turn", emit, approve, cancel)
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",
        "-c",
        source,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=NO_WINDOW_CREATIONFLAGS,
    )
    if stop_after is not None:
        asyncio.get_running_loop().call_later(stop_after, cancel.set)
    try:
        outcome = await asyncio.wait_for(
            runner_cli._drive_cli(
                handle,
                proc,
                runner_cli.CliPlan(
                    argv=[], env={}, stdin_text=None, shape="text", vendor_session=None
                ),
                "text-cli",
                cwd=tmp_path,
                started_at=time.time(),
                placement=None,
                tree=None,
                bridge=None,
            ),
            timeout=25.0,
        )
    finally:
        if proc.returncode is None:
            proc.kill()
        store.close()
    return outcome, events


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


async def test_an_idle_grok_turn_says_it_waits_on_background_work(
    tmp_path: Path, monkeypatch
):
    """Grok holds its result while background work runs; its stream may never
    say what. A turn that went quiet after its message says it waits."""
    monkeypatch.setattr(runner_cli, "_GROK_IDLE_HINT_S", 0.2)
    end_turn = json.dumps(
        {
            "type": "stream_event",
            "event": {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
        }
    )
    source = (
        "import time\n"
        f"print({end_turn!r}, flush=True)\n"
        "time.sleep(1.0)\n"
        f"print({_RESULT_LINE!r}, flush=True)\n"
    )
    events: list = []
    outcome, _proc = await _drive_fake_claude(
        tmp_path, source, runner="grok-cli", events=events
    )
    assert outcome.status == "done", outcome.error
    waits = [e["payload"]["tasks"] for e in events if e["kind"] == "background_wait"]
    assert waits == [[runner_cli.GROK_BACKGROUND_WORK], []]


async def test_the_empty_result_for_a_resumed_task_notice_does_not_end_the_turn(
    tmp_path: Path,
):
    """Resumed after a background agent was stopped, Claude Code first answers
    that task's notice with an empty result (no model turn), then runs the
    prompt. That first result closed stdin and ended the turn: the thread read
    "Finished without an answer" and the agent's question card failed with
    "Stream closed". The prompt's own answer must stay in the turn."""
    notice = json.dumps(
        {"type": "system", "subtype": "task_notification", "task_id": "a1", "status": "stopped"}
    )
    phantom = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "num_turns": 0,
            "duration_api_ms": 0,
            "stop_reason": None,
            "result": "",
            "usage": {"output_tokens": 0},
        }
    )
    answer = json.dumps(
        {
            "type": "assistant",
            "message": {"id": "m1", "content": [{"type": "text", "text": "The questions."}]},
        }
    )
    source = (
        "import sys, time\n"
        "sys.stdin.readline()\n"
        f"print({notice!r}, flush=True)\n"
        f"print({phantom!r}, flush=True)\n"
        "time.sleep(1.5)\n"
        f"print({answer!r}, flush=True)\n"
        f"print({_RESULT_LINE!r}, flush=True)\n"
        # Waits for stdin to close: only the real result may close it.
        "sys.stdin.read()\n"
    )
    events: list = []
    outcome, proc = await _drive_fake_claude(tmp_path, source, events=events, keep_stdin=True)
    assert outcome.status == "done", outcome.error
    texts = [e["payload"]["text"] for e in events if e["kind"] == "assistant_text"]
    assert texts == ["The questions."]
    assert outcome.usage["output_tokens"] == 1


def test_only_a_notice_answer_without_a_model_turn_is_skipped():
    st = runner_cli._ClaudeState(turn_id="t")
    empty = {"type": "result", "is_error": False, "num_turns": 0, "result": ""}
    # No notice before it: a result with no model turn (a local command) ends the turn.
    runner_cli.translate_claude_line(empty, st)
    assert st.saw_result
    st = runner_cli._ClaudeState(turn_id="t")
    runner_cli.translate_claude_line(
        {"type": "system", "subtype": "task_notification", "task_id": "a", "status": "stopped"}, st
    )
    # An error after a notice still ends the turn.
    runner_cli.translate_claude_line({**empty, "is_error": True}, st)
    assert st.saw_result and st.status == "error"
