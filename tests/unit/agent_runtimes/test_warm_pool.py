"""Warm runtime processes: one ACP process serves an agent's turns one after another."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from dodaios.agent_chat import runner_acp
from dodaios.agent_chat import runner_cli as rc
from dodaios.agent_chat.runner_api import TurnHandle
from dodaios.agent_chat.store import AgentChatSession
from dodaios.agent_runtimes.acp import AcpTurn, session_params
from dodaios.agent_runtimes.warm import SessionWant, WarmPool, WarmSpec, signature

_AGENT = Path(__file__).resolve().parents[2] / "fakes" / "fake_acp_agent.py"


def _session(tmp_path: Path, vendor: str | None) -> AgentChatSession:
    return AgentChatSession(
        session_id="society:hermit",
        title="Hermit",
        provider="local-openai",
        model="fake-model",
        effort="",
        cwd=str(tmp_path),
        permission_mode="bypass",
        vendor_session=vendor,
        created_ms=0,
        updated_ms=0,
        message_count=0,
        preview="",
        surface="society",
        runtime="hermes",
    )


class _Rig:
    """Turns through the CLI runner on a pool, the way the runtime drivers plan them."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.pool = WarmPool("hermes")
        self.log = tmp_path / "frames.log"
        self.config = "v1"
        self.env = dict(os.environ)
        self.env["FAKE_ACP_STORE"] = str(tmp_path / "store.json")
        self.env["FAKE_ACP_LOG"] = str(self.log)
        self.pids: list[int] = []
        self.released = 0
        monkeypatch.setattr(runner_acp, "plan_runtime_turn", self._plan)

    def spec(self) -> WarmSpec:
        argv = [sys.executable, str(_AGENT)]
        return WarmSpec(
            argv=argv,
            env=self.env,
            cwd=self.tmp_path,
            signature=signature(argv, self.env, self.config),
        )

    def want(self, resume: str | None) -> SessionWant:
        return SessionWant(resume=resume, params=session_params(str(self.tmp_path), []))

    async def _plan(self, handle: Any, runner: str, *, prompt: str, cwd: Path, resume, identity):
        lease = await self.pool.lease("hermit", self.spec(), self.want(resume))
        assert lease is not None
        self.pids.append(lease.pid)
        acp = AcpTurn(
            turn_id=handle.turn_id,
            cwd=str(cwd),
            prompt_text=prompt,
            resume=resume,
            auto_allow=True,
        )
        acp.initialized = lease.initialized
        acp.open_session = lease.open_session
        lease.turn = acp

        def release() -> None:
            if not lease.finished:
                lease.finish()
            self.released += 1

        return rc.CliPlan(
            argv=self.spec().argv,
            env=self.env,
            stdin_text=None,
            shape="acp",
            vendor_session=None,
            keep_stdin=True,
            acp=acp,
            after_turn=release,
            proc=lease,
        )

    async def turn(
        self, text: str, vendor: str | None, *, cancel_after: float | None = None
    ) -> tuple[str | None, list[dict[str, Any]]]:
        events: list[dict[str, Any]] = []

        async def emit(event: dict[str, Any]) -> None:
            events.append(event)

        async def ask(*_args: Any) -> str:
            return "allow"

        cancel = asyncio.Event()
        handle = TurnHandle(
            session=_session(self.tmp_path, vendor),
            turn_id=f"t{len(self.pids) + 1}",
            emit=emit,
            request_approval=ask,
            cancel=cancel,
        )
        if cancel_after is not None:
            asyncio.get_running_loop().call_later(cancel_after, cancel.set)
        vendor_out = await rc.run_cli_turn(handle, text, "hermes-cli")
        return vendor_out, events

    def methods(self) -> list[str]:
        if not self.log.is_file():
            return []
        return [
            json.loads(line).get("method", "")
            for line in self.log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


def _texts(events: list[dict[str, Any]]) -> list[str]:
    return [e["payload"]["text"] for e in events if e["kind"] == "assistant_text"]


def _finished(events: list[dict[str, Any]]) -> dict[str, Any]:
    return next(e["payload"] for e in events if e["kind"] == "turn_finished")


def test_the_second_turn_only_sends_its_prompt(monkeypatch, tmp_path):
    rig = _Rig(monkeypatch, tmp_path)

    async def scenario() -> None:
        vendor, events = await rig.turn("hello", None)
        assert vendor and _texts(events) == ["echo: hello"]
        vendor2, events2 = await rig.turn("again", vendor)
        assert vendor2 == vendor
        assert _texts(events2) == ["echo: again"]
        await rig.pool.stop()

    asyncio.run(scenario())
    assert rig.pids[0] == rig.pids[1]  # one process for both turns
    assert rig.methods() == [
        "initialize",
        "session/new",
        "session/prompt",
        "session/prompt",  # no handshake, no reload: the session stayed open
    ]
    assert rig.released == 2


def test_a_warm_up_opens_the_conversation_before_the_message(monkeypatch, tmp_path):
    rig = _Rig(monkeypatch, tmp_path)

    async def scenario() -> None:
        vendor, _ = await rig.turn("first", None)
        await rig.pool.stop()  # the app restarted: no process left
        assert await rig.pool.warm("hermit", rig.spec(), rig.want(vendor))
        before = len(rig.methods())
        vendor2, events = await rig.turn("second", vendor)
        assert vendor2 == vendor and _texts(events) == ["echo: second"]
        assert rig.methods()[before:] == ["session/prompt"]
        await rig.pool.stop()

    asyncio.run(scenario())
    assert rig.methods().count("session/load") == 1  # done by the warm-up


def test_a_changed_launch_starts_a_fresh_process(monkeypatch, tmp_path):
    rig = _Rig(monkeypatch, tmp_path)

    async def scenario() -> None:
        vendor, _ = await rig.turn("hello", None)
        rig.config = "v2"  # the agent's model or tools changed
        vendor2, events = await rig.turn("again", vendor)
        assert vendor2 == vendor and _texts(events) == ["echo: again"]
        await rig.pool.stop()

    asyncio.run(scenario())
    assert rig.pids[0] != rig.pids[1]
    assert rig.methods().count("initialize") == 2
    assert rig.methods().count("session/load") == 1  # the new process reopened it


def test_a_fresh_conversation_never_reuses_the_open_one(monkeypatch, tmp_path):
    rig = _Rig(monkeypatch, tmp_path)

    async def scenario() -> None:
        vendor, _ = await rig.turn("hello", None)
        vendor2, _ = await rig.turn("rollover", None)  # resume=None: a new conversation
        assert vendor2 and vendor2 != vendor
        await rig.pool.stop()

    asyncio.run(scenario())
    assert rig.pids[0] == rig.pids[1]
    assert rig.methods().count("session/new") == 2


def test_stop_ends_the_process_and_the_next_turn_starts_a_new_one(monkeypatch, tmp_path):
    rig = _Rig(monkeypatch, tmp_path)

    async def scenario() -> None:
        vendor, _ = await rig.turn("hello", None)
        _, events = await rig.turn("SLOW", vendor, cancel_after=0.5)
        assert _finished(events)["status"] == "cancelled"
        vendor3, events3 = await rig.turn("after", vendor)
        assert _texts(events3) == ["echo: after"]
        await rig.pool.stop()

    asyncio.run(scenario())
    # The stopped turn ran on the warm process; Stop ended that process (no
    # frame of a stopped turn is trusted), so the next turn reopened the
    # conversation on a fresh one.
    assert rig.pids[0] == rig.pids[1] != rig.pids[2]
    assert rig.methods().count("session/load") == 1


def test_a_process_that_died_is_replaced(monkeypatch, tmp_path):
    rig = _Rig(monkeypatch, tmp_path)

    async def scenario() -> None:
        vendor, _ = await rig.turn("hello", None)
        _, events = await rig.turn("EXIT", vendor)
        assert _finished(events)["status"] == "error"
        _, events3 = await rig.turn("back", vendor)
        assert _texts(events3) == ["echo: back"]
        await rig.pool.stop()

    asyncio.run(scenario())
    assert rig.pids[1] != rig.pids[2]


def test_a_cancelled_start_leaves_no_half_started_process(tmp_path):
    """Stop during a warm process' handshake: nothing half-started stays for
    the next turn to pick up."""
    pool = WarmPool("hermes")
    argv = [sys.executable, "-c", "import time; time.sleep(60)"]  # never answers
    spec = WarmSpec(argv=argv, env=dict(os.environ), cwd=tmp_path, signature="s")
    want = SessionWant(resume=None, params=session_params(str(tmp_path), []))

    async def scenario() -> None:
        task = asyncio.create_task(pool.lease("hermit", spec, want))
        await asyncio.sleep(0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not pool.has("hermit")
        await pool.stop()

    asyncio.run(scenario())


def test_a_reset_turns_session_serves_the_turns_after_it(monkeypatch, tmp_path):
    """OpenClaw: the conversation is the runtime's own key; the session a
    fresh (reset) turn opened keeps serving the turns that follow."""
    rig = _Rig(monkeypatch, tmp_path)
    reset = {"sessionKey": "agent:main:main", "resetSession": True}
    keep = {"sessionKey": "agent:main:main", "resetSession": False}
    match = session_params(str(tmp_path), [], {"sessionKey": "agent:main:main"})

    def want(meta: dict[str, Any]) -> SessionWant:
        return SessionWant(
            resume=None, params=session_params(str(tmp_path), [], meta),
            bound=not meta["resetSession"], match=match,
        )

    async def scenario() -> None:
        first = await rig.pool.lease("hermit", rig.spec(), want(reset))
        assert first is not None and first.open_session == ""
        first.finish()  # a turn that never prompted: nothing to keep
        assert await rig.pool.warm("hermit", rig.spec(), want(keep))
        second = await rig.pool.lease("hermit", rig.spec(), want(keep))
        assert second is not None and second.open_session  # opened ahead, bound
        second.finish()
        again = await rig.pool.lease("hermit", rig.spec(), want(reset))
        assert again is not None and again.open_session == ""  # a reset never reuses
        again.finish()
        await rig.pool.stop()

    asyncio.run(scenario())
