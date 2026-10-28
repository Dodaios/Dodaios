"""OpenClaw agents: native tool approvals, the plain-named ask tool, stream
repair, Gateway restarts and retired agents.

Live 2026-10-28 (a local Ollama agent on OpenClaw 2026.10.8):

- with Permissions = Ask, OpenClaw's own ``write`` ran without a card: only
  exec approvals reach the ACP client;
- the model called ``society_ask_user`` and got "Tool society_ask_user not
  found" (the MCP catalog has ``dodaios__society_ask_user`` behind tool
  search), then OpenClaw's own ``ask_user`` rejected the id ``color-pref``;
- after OpenClaw's "isolated finalization" pass the chat lost the first N
  characters of the reply (N = the previous bubble's length);
- a run OpenClaw itself ended as ``cancelled`` poisoned the Gateway, whose
  restart then could not resume the run (``delegated_authority_unavailable``);
- archiving the agent left its Gateway (about 1.3 GB) running.
"""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import Future
from pathlib import Path
from typing import Any

import pytest

from dodaios.agent_runtimes import base, gateway, native_gate, openclaw_gate
from dodaios.agent_runtimes.acp import AcpTurn
from dodaios.agent_runtimes.base import RuntimeTurn
from dodaios.agent_runtimes.model_map import ModelRoute
from dodaios.agent_runtimes.openclaw import OpenClawRuntime

_MCP = "http://127.0.0.1:47821/api/control/mcp/"


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.setattr(base, "runtimes_root", lambda: tmp_path / "rt")
    monkeypatch.setattr(base, "legacy_runtimes_root", lambda: tmp_path / "legacy")
    native_gate.reset()
    gateway.reset()
    yield
    native_gate.reset()
    gateway.reset()


def _turn(tmp_path: Path, **overrides: Any) -> RuntimeTurn:
    values: dict[str, Any] = {
        "agent_id": "ada",
        "agent_name": "Ada",
        "session_id": "society:ada",
        "workspace": tmp_path,
        "route": ModelRoute(
            provider="ollama",
            model="qwen3.5:9b",
            base_url="http://127.0.0.1:47821/api/runtime-gateway/v1",
            transport="chat_completions",
            api_key="gw-token",
            context_window=65536,
        ),
        "resume": None,
        "auto_approve": False,
        "mcp_url": _MCP,
        "control_key": "control-key",
    }
    values.update(overrides)
    return RuntimeTurn(**values)


def _config(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    token = "t"  # noqa: S105 — the loopback Gateway token: any value
    return OpenClawRuntime().config_for(_turn(tmp_path, **overrides), port=1, token=token)


# ------------------------------------------------------------ the config


def test_the_gate_plugin_is_loaded_and_the_config_ignores_the_stance(tmp_path):
    ask = _config(tmp_path)
    bypass = _config(tmp_path, auto_approve=True)
    # A stance change never rewrites the file, so it never restarts the Gateway.
    assert ask == bypass
    plugins = ask["plugins"]
    folder = Path(plugins["load"]["paths"][0])
    assert folder.name == openclaw_gate.PLUGIN_ID
    assert (folder / "index.mjs").is_file()
    assert (folder / "openclaw.plugin.json").is_file()
    entry = plugins["entries"][openclaw_gate.PLUGIN_ID]
    assert entry["enabled"] is True
    assert entry["hooks"]["timeouts"]["before_tool_call"] == openclaw_gate.HOOK_TIMEOUT_MS
    settings = entry["config"]
    assert settings["gateUrl"] == "http://127.0.0.1:47821/api/control/runtime/native-approval"
    assert settings["session"] == "society:ada"
    assert settings["ask"]["name"] == "society_ask_user"
    # Nothing secret in the file: the plugin reads the key from its environment.
    assert "control-key" not in json.dumps(ask)


def test_the_file_tools_stay_and_unanswerable_native_tools_go(tmp_path):
    denied = set(_config(tmp_path)["tools"]["deny"])
    assert not denied & set(openclaw_gate.GATED_TOOLS)  # they ask through the gate
    assert {"computer", "terminal", "openclaw", "ask_user"} <= denied
    # One ask tool: the plain one, never the deferred MCP copy as well.
    assert "dodaios__society_ask_user" in denied
    assert _config(tmp_path)["tools"]["exec"]["mode"] == "ask"


def test_without_dodaios_tools_file_changes_do_not_run_outside_bypass(tmp_path):
    ask = _config(tmp_path, mcp_url=None, control_key=None)
    assert "load" not in ask["plugins"]
    assert set(openclaw_gate.GATED_TOOLS) <= set(ask["tools"]["deny"])
    bypass = _config(tmp_path, mcp_url=None, control_key=None, auto_approve=True)
    assert not set(openclaw_gate.GATED_TOOLS) & set(bypass["tools"]["deny"])


def test_a_routine_gateway_gates_files_but_offers_no_question(tmp_path):
    entry = _config(tmp_path, session_id="society:ada:routine:7")["plugins"]["entries"][
        openclaw_gate.PLUGIN_ID
    ]
    assert entry["config"]["gateUrl"]
    assert "ask" not in entry["config"]
    assert "mcpUrl" not in entry["config"]


def test_the_plugin_build_is_part_of_the_config(tmp_path):
    first = openclaw_gate.install(tmp_path)
    again = openclaw_gate.install(tmp_path)
    assert first == again
    source = (first.path / "index.mjs").read_text(encoding="utf-8")
    for tool in (*openclaw_gate.GATED_TOOLS, *openclaw_gate.READ_TOOLS, "process"):
        assert f'"{tool}"' in source
    assert "JARVIS_CONTROL_API_KEY" in source
    assert 'catalogMode: "direct-only"' in source
    manifest = json.loads((first.path / "openclaw.plugin.json").read_text(encoding="utf-8"))
    assert manifest["contracts"]["tools"] == ["society_ask_user"]
    entry = _config(tmp_path)["plugins"]["entries"][openclaw_gate.PLUGIN_ID]
    assert entry["config"]["build"] == first.digest


def test_the_plain_ask_tool_only_requires_the_question():
    """OpenClaw validates a plugin tool's input before Dodaios sees it: a
    small model that leaves out ``recommendation_reason`` (or sends an id
    like ``color-pref``) still reaches the card."""
    from dodaios.agent_chat.questions import parse_questions
    from dodaios.society.ask_tool import AskUserTool

    spec = openclaw_gate.ask_spec("dodaios")
    items = spec["schema"]["properties"]["questions"]["items"]
    assert items["required"] == ["question"]
    assert AskUserTool.schema["properties"]["questions"]["items"]["required"] == [
        "question", "recommendation_reason",
    ]  # Dodaios' own schema is untouched
    asked = {"questions": [{"id": "color-pref", "header": "Colour", "question": "Which colour?",
                            "options": [{"label": "red"}, {"label": "green"}],
                            "multiSelect": False}]}
    (question,) = parse_questions(asked)
    assert question.question == "Which colour?"
    assert [o.label for o in question.options] == ["red", "green"]


# ------------------------------------------------------- the native gate


class _IO:
    def __init__(self, answer: str = "allow") -> None:
        self.answer = answer
        self.events: list[dict[str, Any]] = []
        self.asked: list[tuple[str, str]] = []

    async def write(self, frame: dict[str, Any]) -> None:
        pass

    async def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    async def ask(self, call_id: str, name: str, args: dict[str, Any], summary: str) -> str:
        self.asked.append((call_id, name))
        return self.answer


def _kinds(io: _IO) -> list[str]:
    return [event["kind"] for event in io.events]


def _gate(turn: AcpTurn, io: _IO, tool: str = "write", *, read_only: bool = False) -> str:
    return asyncio.run(
        turn.native_permission(
            io, "call_w1", tool, {"path": "a.txt", "content": "x"}, f"{tool}: a.txt",
            read_only=read_only,
        )
    )


def test_ask_shows_a_card_on_the_tool_row():
    io = _IO("allow")
    turn = AcpTurn(turn_id="t", cwd=".", prompt_text="hi")
    assert _gate(turn, io) == "allow"
    assert io.asked == [("call_w1", "write")]
    assert _kinds(io) == ["tool_call"]
    # The ACP tool_call of the same call that follows adds no second row.
    assert "call_w1" in turn.emitted_tool_ids


def test_bypass_allows_and_plan_refuses_without_a_card():
    io = _IO()
    assert _gate(AcpTurn(turn_id="t", cwd=".", prompt_text="hi", auto_allow=True), io) == "allow"
    assert _gate(AcpTurn(turn_id="t", cwd=".", prompt_text="hi", auto_deny=True), io) == "deny"
    assert io.asked == []


def test_reads_ask_in_always_ask_only():
    io = _IO()
    for turn in (
        AcpTurn(turn_id="t", cwd=".", prompt_text="hi"),
        AcpTurn(turn_id="t", cwd=".", prompt_text="hi", auto_deny=True),  # Plan reads freely
    ):
        assert _gate(turn, io, "read", read_only=True) == "allow"
    assert io.asked == []
    strict = AcpTurn(turn_id="t", cwd=".", prompt_text="hi", always_ask=True)
    assert _gate(strict, io, "read", read_only=True) == "allow"
    assert io.asked == [("call_w1", "read")]


def test_allow_always_is_remembered_except_in_always_ask():
    remembered: set[str] = set()
    io = _IO("allow_always")
    turn = AcpTurn(turn_id="t", cwd=".", prompt_text="hi", native_always=remembered)
    assert _gate(turn, io) == "allow_always"
    assert remembered == {"write"}
    later = AcpTurn(turn_id="t2", cwd=".", prompt_text="hi", native_always=remembered)
    assert _gate(later, _IO("deny")) == "allow"  # no second card
    strict_set: set[str] = set()
    strict = AcpTurn(
        turn_id="t3", cwd=".", prompt_text="hi", always_ask=True, native_always=strict_set
    )
    assert _gate(strict, _IO("allow_always")) == "allow"
    assert strict_set == set()


def test_decide_refuses_without_a_running_turn_and_follows_the_card():
    async def go() -> list[tuple[str, str]]:
        results = [await native_gate.decide("society:ada", "write", {})]
        answers = iter(["allow", "deny", "cancel"])

        async def decider(call_id, tool, args, title, read_only):
            return next(answers)

        native_gate.register("society:ada", decider)
        for _ in range(3):
            results.append(await native_gate.decide("society:ada", "write", {}))
        native_gate.unregister("society:ada", decider)
        results.append(await native_gate.decide("society:ada", "write", {}))
        return results

    assert asyncio.run(go()) == [
        ("deny", native_gate.NO_TURN),
        ("allow", ""),
        ("deny", native_gate.DECLINED),
        ("deny", native_gate.STOPPED),
        ("deny", native_gate.NO_TURN),
    ]


def test_a_card_nobody_answers_is_refused_in_time(monkeypatch):
    monkeypatch.setattr(native_gate, "DECISION_TIMEOUT_S", 0.05)

    async def never(*_args):
        await asyncio.sleep(10)
        return "allow"

    async def go() -> tuple[str, str]:
        native_gate.register("s", never)
        return await native_gate.decide("s", "edit", {})

    assert asyncio.run(go()) == ("deny", native_gate.NO_ANSWER)
    assert native_gate.DECISION_TIMEOUT_S * 1000 < openclaw_gate.HOOK_TIMEOUT_MS


def test_the_control_route_asks_the_running_turn(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from dodaios.ui.web import control_routes

    app = FastAPI()
    app.include_router(control_routes.router)
    app.dependency_overrides[control_routes.require_control_key] = lambda: None
    seen: list[tuple[str, str, bool]] = []

    async def decider(call_id, tool, args, title, read_only):
        seen.append((call_id, tool, read_only))
        return "allow"

    native_gate.register("society:ada", decider)
    client = TestClient(app)
    url = "/api/control/runtime/native-approval"
    body = {"tool": "write", "params": {"path": "a"}, "tool_call_id": "c1", "title": "write: a"}
    ok = client.post(url, json=body, headers={"x-jarvis-chat-session": "society:ada"})
    assert ok.json() == {"decision": "allow", "reason": ""}
    read = client.post(
        url, json={**body, "tool": "read"}, headers={"x-jarvis-chat-session": "society:ada"}
    )
    assert read.json()["decision"] == "allow"
    assert seen == [("c1", "write", False), ("c1", "read", True)]
    other = client.post(url, json=body, headers={"x-jarvis-chat-session": "society:bob"})
    assert other.json() == {"decision": "deny", "reason": native_gate.NO_TURN}
    nobody = client.post(url, json=body)
    assert nobody.json()["decision"] == "deny"


def test_typing_into_a_running_process_asks_and_watching_it_does_not():
    # An allowed interactive shell would otherwise run every later command
    # typed into it without a card.
    assert openclaw_gate.kind("process", {"action": "submit", "data": "rm -rf x"}) == "change"
    assert openclaw_gate.kind("process", {"action": "send-keys"}) == "change"
    for action in ("list", "poll", "log", "kill"):
        assert openclaw_gate.kind("process", {"action": action}) == "free"
    assert openclaw_gate.kind("grep", {"pattern": "x"}) == "read"
    assert openclaw_gate.kind("write", {"path": "a"}) == "change"

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from dodaios.ui.web import control_routes

    app = FastAPI()
    app.include_router(control_routes.router)
    app.dependency_overrides[control_routes.require_control_key] = lambda: None
    seen: list[tuple[str, bool]] = []

    async def decider(call_id, tool, args, title, read_only):
        seen.append((tool, read_only))
        return "deny"

    native_gate.register("society:ada", decider)
    client = TestClient(app)
    url = "/api/control/runtime/native-approval"
    headers = {"x-jarvis-chat-session": "society:ada"}
    poll = client.post(url, json={"tool": "process", "params": {"action": "poll"}}, headers=headers)
    assert poll.json()["decision"] == "allow"
    typed = client.post(
        url, json={"tool": "process", "params": {"action": "submit"}}, headers=headers
    )
    assert typed.json()["decision"] == "deny"
    assert seen == [("process", False)]


# ------------------------------------------------------ stream repair


def _update(kind: str, **fields: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {"sessionId": "s", "update": {"sessionUpdate": kind, **fields}},
    }


def _chunk(text: str) -> dict[str, Any]:
    return _update("agent_message_chunk", content={"type": "text", "text": text})


def _tool(call_id: str) -> dict[str, Any]:
    return _update("tool_call", toolCallId=call_id, title="write: a.txt", status="in_progress")


def _done(call_id: str) -> dict[str, Any]:
    return _update("tool_call_update", toolCallId=call_id, status="completed")


def _result(stop: str = "end_turn") -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 3, "result": {"stopReason": stop}}


def _texts(io: _IO) -> list[str]:
    return [e["payload"]["text"] for e in io.events if e["kind"] == "assistant_text"]


def _run(frames: list[dict[str, Any]], replies: list[tuple[str, int]], **kw: Any):
    turn = AcpTurn(
        turn_id="t", cwd=".", prompt_text="hi", reply_texts=lambda: list(replies), **kw
    )
    turn._acp_session = "s"
    io = _IO()

    async def go() -> None:
        for frame in frames:
            await turn.on_message(frame, io)

    asyncio.run(go())
    return turn, io


def test_a_reply_cut_by_the_previous_bubble_is_shown_whole():
    first = "I create the file qa_local.txt."
    final = "Done! The file qa_local.txt now holds: hello from QA (13 bytes)."
    # OpenClaw's bridge sends the final message from offset len(first) on.
    cut = final[len(first):]
    turn, io = _run(
        [_chunk(first), _tool("w"), _done("w"), _chunk(cut), _result()],
        [(first, 1), ("", 0), (final, 0)],
    )
    assert _texts(io) == [first, final]
    assert turn.result_text == final and turn.status == "done"


def test_a_final_reply_shorter_than_the_last_bubble_is_not_lost():
    first = "Let me look at the whole repository before I answer the question."
    final = "Red or green?"
    turn, io = _run(
        [_chunk(first), _tool("w"), _done("w"), _result()],
        [(first, 1), (final, 0)],
    )
    assert _texts(io) == [first, final]
    assert turn.result_text == final


def test_intact_streams_and_silent_replies_stay_as_they_are():
    _, io = _run([_chunk("Hello there."), _result()], [("Hello there.", 0)])
    assert _texts(io) == ["Hello there."]
    _, io = _run([_tool("w"), _done("w"), _result()], [("", 1), ("NO_REPLY", 0)])
    assert _texts(io) == []
    # The last model call asked for a tool: no answer was dropped.
    _, io = _run([_chunk("Working."), _tool("w"), _result()], [("Working.", 1)])
    assert _texts(io) == ["Working."]


def test_the_gateway_keeps_each_turns_answers():
    signal: Future[str] = Future()
    other: Future[str] = Future()
    gateway._record_reply(signal, "first", 1)
    gateway._record_reply(signal, "second", 0)
    gateway._record_reply(None, "nobody", 0)
    assert gateway.turn_replies(signal) == [("first", 1), ("second", 0)]
    assert gateway.turn_replies(other) == []
    for i in range(100):
        gateway._record_reply(signal, str(i), 0)
    assert len(gateway.turn_replies(signal)) == gateway._MAX_REPLIES
    assert gateway.turn_replies(signal)[-1] == ("99", 0)


# ----------------------------------------- runtime-ended runs and restarts


def test_a_run_the_runtime_cancelled_itself_says_so():
    turn, _ = _run([_chunk("Red or green?"), _result("cancelled")], [])
    assert turn.prompt_answered
    assert turn.error and turn.error.startswith("The runtime ended the run")
    stopped = AcpTurn(turn_id="t", cwd=".", prompt_text="hi")
    stopped._acp_session = "s"
    assert stopped.cancel_frame() is not None
    io = _IO()
    asyncio.run(stopped.on_message(_result("cancelled"), io))
    assert stopped.error == "The turn was cancelled before it finished."


def test_an_answered_prompt_never_restarts_the_gateway():
    from dodaios.agent_chat.runner_acp import poisons_runtime

    ended, _ = _run([_chunk("x"), _result("cancelled")], [])
    for cancelled in (False, True):
        assert not poisons_runtime(ended, cancelled=cancelled, provider_failed=False)
    # A failure the model gateway saw still starts the runtime afresh.
    assert poisons_runtime(ended, cancelled=False, provider_failed=True)
    silent = AcpTurn(turn_id="t", cwd=".", prompt_text="hi")
    assert poisons_runtime(silent, cancelled=False, provider_failed=False)
    assert poisons_runtime(None, cancelled=False, provider_failed=False)
    starting = AcpTurn(turn_id="t", cwd=".", prompt_text="hi")
    starting._fail("Agent main has not completed startup inspection and preparation.")
    assert not poisons_runtime(starting, cancelled=False, provider_failed=False)


# ------------------------------------------------------ retired agents


async def test_archiving_a_runtime_agent_stops_its_processes(tmp_path, monkeypatch):
    from dodaios import agent_runtimes
    from dodaios.society import roster as roster_mod
    from dodaios.society import runtime as runtime_mod
    from dodaios.society.runtime import SocietyRuntime

    stopped: list[tuple[str, str]] = []

    class Fake:
        def __init__(self, name: str) -> None:
            self.name = name

        async def stop(self, agent_id=None):
            stopped.append((self.name, agent_id))

    drivers = [Fake("hermes"), Fake("openclaw")]
    monkeypatch.setattr(agent_runtimes, "started_drivers", lambda: drivers)
    rt = SocietyRuntime(tmp_path / "society", seed_starter_team=False)
    await rt.ensure_started()
    try:
        claw, _ = await rt.roster.create(name="Claw", runtime="openclaw")
        plain, _ = await rt.roster.create(name="Plain")
        await rt.roster.archive(plain.agent_id)
        await rt.roster.archive(claw.agent_id)
        await asyncio.gather(*list(roster_mod._STOPPING))
        assert stopped == [("openclaw", claw.agent_id)]
        hermit, _ = await rt.roster.create(name="Hermit", runtime="hermes")
        await rt.roster.update(hermit.agent_id, {"title": "Researcher"})
        await asyncio.gather(*list(roster_mod._STOPPING))
        assert len(stopped) == 1  # an ordinary edit stops nothing
        await rt.roster.archive(hermit.agent_id)
        await asyncio.gather(*list(roster_mod._STOPPING))
        assert stopped[-1] == ("hermes", hermit.agent_id)
    finally:
        runtime_mod.set_current_runtime(None)
        await rt.close()


def test_openclaw_offers_always_ask_and_hermes_does_not():
    from dodaios.agent_chat.permissions import society_mode_supported

    assert society_mode_supported("openclaw-cli", "always_ask")
    assert society_mode_supported("openclaw-cli", "ask")
    assert not society_mode_supported("hermes-cli", "always_ask")


def test_the_plugins_ask_call_passes_dodaios_mcp_endpoint(monkeypatch):
    """The plugin calls Dodaios' MCP tool with one stateless ``tools/call``;
    the endpoint checks the call against the listed schema, which requires
    ``recommendation_reason`` (the plugin fills an empty one in)."""
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from dodaios.core import runtime_refs
    from dodaios.core.protocols import ToolResult
    from dodaios.society.ask_tool import AskUserTool
    from dodaios.ui.web import mcp_server_routes

    seen: list[dict[str, Any]] = []

    class Gateway:
        def catalog(self):
            return [SimpleNamespace(
                name="society_ask_user", description="ask", input_schema=AskUserTool.schema,
                read_only=False,
            )]

        async def execute(self, name, args, request):
            seen.append(args)
            return ToolResult(success=True, output={"answers": [{"answer": "red"}]})

    monkeypatch.setattr(runtime_refs, "get_supervisor_tool_gateway", lambda: Gateway())
    monkeypatch.setattr(mcp_server_routes, "_authorized", lambda scope, surface: True)
    app = FastAPI()
    app.mount("/api/control/mcp", mcp_server_routes.build_mcp_asgi_app())
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        "x-jarvis-chat-session": "society:ada",
    }

    def call(method: str, params: dict[str, Any]) -> dict[str, Any]:
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        return client.post("/api/control/mcp/", headers=headers, json=body).json()

    question = {"id": "color_pref", "header": "Colour", "question": "Which colour?",
                "options": [{"label": "red"}, {"label": "green"}]}
    with TestClient(app) as client:
        assert call("tools/list", {})["result"]["tools"][0]["name"] == "society_ask_user"
        filled = call("tools/call", {"name": "society_ask_user", "arguments": {
            "questions": [{**question, "recommendation_reason": ""}]}})
        assert filled["result"]["isError"] is False, filled
        assert seen and seen[0]["questions"][0]["question"] == "Which colour?"
        bare = call("tools/call", {"name": "society_ask_user",
                                   "arguments": {"questions": [question]}})
        assert bare["result"]["isError"] is True  # why the plugin fills the reason in
    source = openclaw_gate.source()
    assert 'next.recommendation_reason = ""' in source
