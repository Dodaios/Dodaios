"""The approval action card: one card for every approval source, rules from the card.

Every source of an approval (the ToolExecutor bridge behind the brain runner
and the MCP gateway, the API loop, Claude Code's stdin protocol, ACP
``session/request_permission`` from Hermes/OpenClaw) ends in
``AgentChatService._ask``. These tests drive each source with fakes and check
the same card fields arrive and the same decisions resolve it; then the rules a
card saves, and that ``society.approvals.decide`` keeps its order.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agent_chat.approval_bridge import ChatApprovalBridge, ChatGrant, approval_ref
from dodaios.agent_chat.approval_card import describe_call, request_detail, rule_offer
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.core.bus import EventBus
from dodaios.core.events import ActionApprovalRequired, ActionApproved, ActionProposed
from dodaios.society import approvals as society_approvals
from dodaios.society.approvals import Verdict, apply_rule, card_rule, decide, rule_text
from dodaios.society.capabilities import CapabilityKind, CapabilityRow
from dodaios.ui.web.agent_chat_routes import router

SECRETS = (
    "hunter2-correct-horse-battery",
    # Built at runtime so no credential-shaped literal sits in the source.
    "sk" + "-proj-" + "q7" * 18,
    "gh" + "p_" + "Z9" * 20,
    "xa" + "i-" + "k3" * 16,
)


async def _next(q: asyncio.Queue, kind: str, budget_s: float = 5.0) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget_s
    while True:
        ev = await asyncio.wait_for(q.get(), timeout=max(0.01, deadline - loop.time()))
        if ev["kind"] == kind:
            return ev


def _service(tmp_path: Path, *, surface: str = "jarvis", session_id: str | None = None):
    svc = AgentChatService(AgentChatStore(":memory:"))
    session = svc.store.create_session(
        provider="claude-api",
        model="m",
        effort="medium",
        cwd=str(tmp_path),
        permission_mode="ask",
        surface=surface,
        session_id=session_id,
    )
    return svc, session


# ------------------------------------------------------------------ display


@pytest.mark.parametrize(
    ("name", "args", "kind", "app", "caution"),
    [
        # Brain runner / ToolExecutor bridge: the registry's bare tool name.
        ("gmail", {"action": "send", "to": "a@b.c"}, "connector", "Gmail", "data_leaves"),
        # The MCP gateway: this app's own server, under either name.
        (
            "mcp__dodaios__google_calendar",
            {"action": "delete"},
            "connector",
            "Google Calendar",
            "irreversible",
        ),
        ("mcp__jarvis__github", {"action": "list"}, "connector", "GitHub", ""),
        # Another MCP server's tool: that server is the source.
        ("mcp__notion__create_page", {"title": "x"}, "connector", "Notion", ""),
        # The API loop's folder tools.
        ("RunCommand", {"command": "rm -rf build"}, "terminal", "", "irreversible"),
        ("Write", {"file_path": "a.txt", "content": "x"}, "files", "", ""),
        # Claude Code over stdin.
        (
            "Bash",
            {"command": "git push --force", "description": "Publish"},
            "terminal",
            "",
            "irreversible",
        ),
        ("Bash", {"command": "sudo chmod 777 /etc"}, "terminal", "", "security"),
        ("Bash", {"command": "git push origin main"}, "terminal", "", "data_leaves"),
        ("ExitPlanMode", {"plan": "1. x"}, "plan", "", ""),
        # ACP request_permission (Hermes / OpenClaw): a title-like name.
        ("execute", {"command": "ls"}, "terminal", "", ""),
        ("society_browser", {"url": "https://example.com/a"}, "browser", "", ""),
        ("click", {"x": 1}, "computer", "", ""),
    ],
)
def test_every_source_maps_onto_the_same_card_fields(name, args, kind, app, caution):
    card = describe_call(name, args, "summary", cwd="C:/work")
    assert card["source"]["kind"] == kind
    assert card["source"].get("app", "") == app or kind not in ("connector",)
    assert card["caution"] == caution
    if kind in ("terminal", "files"):
        # The chat's own folder reads as its name; the full path stays in where_full.
        assert card["where"] == "work"
        assert card["where_full"] == "C:/work"
    if kind == "plan":
        assert card["detail"] == "" and card["rule"] is None


def test_the_card_carries_the_agents_reason_and_the_site():
    assert describe_call("Bash", {"command": "npm i", "description": "Install deps"})["why"] == (
        "Install deps"
    )
    assert describe_call("society_browser", {"url": "https://mail.example.com/x"})["where"] == (
        "mail.example.com"
    )
    connector = describe_call("gmail", {"action": "send"})
    assert connector["source"] == {"kind": "connector", "app": "Gmail", "verb": "send"}
    # A shell command is never a verb a rule could name.
    assert "verb" not in describe_call("society_shell", {"command": "rm -rf x"})["source"]


def test_secrets_never_reach_the_disclosure():
    args = {
        "user": "ada",
        "password": SECRETS[0],
        "api_key": SECRETS[1],
        "nested": {"auth_token": SECRETS[2], "headers": {"Authorization": f"Bearer {SECRETS[3]}"}},
        "note": f"use {SECRETS[1]} please",
        "max_tokens": 400,
    }
    card = describe_call("mcp__acme__login", args, "Sign in")
    for secret in SECRETS:
        assert secret not in json.dumps(card)
    assert "ada" in card["detail"] and "400" in card["detail"]
    command = request_detail({}, f"curl -H 'Authorization: Bearer {SECRETS[3]}' https://x")
    assert SECRETS[3] not in command
    why = describe_call("Bash", {"command": "x", "description": f"api_key={SECRETS[1]}"})["why"]
    assert SECRETS[1] not in why


def test_describe_never_raises(monkeypatch: pytest.MonkeyPatch):
    from dodaios.agent_chat import approval_card

    assert describe_call("x", None, "")["source"]["kind"] == "connector"  # type: ignore[arg-type]
    weird = describe_call("tool", {"command": object()})
    assert weird["source"]["kind"] in ("tool", "connector", "terminal")

    def broken(*_a: Any) -> dict[str, Any]:
        raise RuntimeError("boom")

    monkeypatch.setattr(approval_card, "_describe", broken)
    assert describe_call("Bash", {"command": "ls"}) == {}


def test_rule_offers_per_surface():
    assert rule_offer("jarvis", "gmail", {}, None) == {
        "scopes": ["chat"],
        "chat": "tool",
        "app": "Gmail",
    }
    assert rule_offer("agent", "Bash", {}, None) == {"scopes": ["chat"], "chat": "all"}
    assert rule_offer("society", "Bash", {}, None) == {"scopes": [], "chat": "runtime"}
    own = {
        "capability": "plugin:gmail",
        "app": "Gmail",
        "verb": "send",
        "pattern": "plugin:gmail:send",
        "broad": "plugin:gmail",
    }
    assert rule_offer("society", "gmail", {}, own)["scopes"] == ["agent", "chat"]


# ------------------------------------------------------------ every source


def test_the_api_loop_and_stdin_shapes_ask_on_the_same_card(tmp_path: Path):
    async def scenario() -> None:
        svc, session = _service(tmp_path)
        q = svc.subscribe(session.session_id)
        for name, args, answer in (
            ("RunCommand", {"command": "echo hi"}, "allow"),
            ("Bash", {"command": "rm -rf build", "description": "Clean"}, "deny"),
            ("mcp__dodaios__gmail", {"action": "send", "password": SECRETS[0]}, "allow"),
        ):
            asking = asyncio.create_task(svc._ask(session.session_id, "t1", "c1", name, args, name))  # noqa: SLF001
            payload = (await _next(q, "approval_required"))["payload"]
            assert {"source", "where", "why", "caution", "detail", "rule"} <= payload.keys()
            assert SECRETS[0] not in payload["detail"]
            assert svc.resolve_approval(session.session_id, payload["approval_id"], answer)
            assert await asyncio.wait_for(asking, 2) == answer
            resolved = (await _next(q, "approval_resolved"))["payload"]
            assert resolved["decision"] == answer

    asyncio.run(scenario())


def test_the_bridge_and_the_mcp_gateway_ask_on_the_same_card(tmp_path: Path):
    async def scenario() -> None:
        svc, session = _service(tmp_path)
        q = svc.subscribe(session.session_id)
        bus = EventBus()
        bridge = ChatApprovalBridge(bus)
        approved: list[ActionApproved] = []

        async def seen(event: ActionApproved) -> None:
            approved.append(event)

        bus.subscribe(ActionApproved, seen)
        ref = approval_ref(session.session_id)
        bridge.arm(
            ref,
            ChatGrant(
                session_id=session.session_id,
                turn_id="t1",
                stance="ask",
                always_allowed=svc.always_allowed(session.session_id),
                ask=lambda call_id, name, args, summary: svc._ask(  # noqa: SLF001
                    session.session_id, "t1", call_id, name, args, summary
                ),
            ),
        )
        proposed = ActionProposed(tool_name="gmail", args={"action": "send", "to": "a@b.c"})
        await bus.publish(proposed)
        await bus.publish(
            ActionApprovalRequired(trace_id=proposed.trace_id, tool_name="gmail", approval_ref=ref)
        )
        payload = (await _next(q, "approval_required"))["payload"]
        assert payload["source"] == {"kind": "connector", "app": "Gmail", "verb": "send"}
        assert payload["caution"] == "data_leaves"
        svc.resolve_approval(
            session.session_id, payload["approval_id"], "allow_always", scope="chat"
        )
        notice = (await _next(q, "notice"))["payload"]
        assert notice["kind"] == "approval_rule" and notice["scope"] == "chat"
        await asyncio.sleep(0.05)
        assert approved and approved[-1].approved_by == "user"
        # The chat-scoped "always" now answers the bridge without a card.
        assert "gmail" in svc.always_allowed(session.session_id)
        again = ActionProposed(tool_name="gmail", args={"action": "send"})
        await bus.publish(again)
        await bus.publish(
            ActionApprovalRequired(trace_id=again.trace_id, tool_name="gmail", approval_ref=ref)
        )
        await asyncio.sleep(0.05)
        assert approved[-1].trace_id == again.trace_id
        assert svc.pending_approvals(session.session_id) == []

    asyncio.run(scenario())


def test_acp_request_permission_asks_on_the_same_card(tmp_path: Path):
    from dodaios.agent_runtimes.acp import AcpTurn

    async def scenario() -> None:
        svc, session = _service(tmp_path, surface="society", session_id="society:ada")
        q = svc.subscribe(session.session_id)

        class _Io:
            async def write(self, frame: dict[str, Any]) -> None:
                pass

            async def emit(self, event: dict[str, Any]) -> None:
                pass

            async def ask(self, call_id: str, name: str, args: dict[str, Any], summary: str) -> str:
                return await svc._ask(session.session_id, "t1", call_id, name, args, summary)  # noqa: SLF001

        turn = AcpTurn(turn_id="t1", cwd=str(tmp_path), prompt_text="x")
        params = {
            "toolCall": {
                "toolCallId": "tc1",
                "title": "rm -rf build",
                "kind": "execute",
                "rawInput": {"command": "rm -rf build"},
            },
            "options": [
                {"kind": "allow_once", "optionId": "o1"},
                {"kind": "allow_always", "optionId": "o2"},
                {"kind": "reject_once", "optionId": "o3"},
            ],
        }
        answering = asyncio.create_task(turn._permission(params, _Io()))  # noqa: SLF001
        payload = (await _next(q, "approval_required"))["payload"]
        assert payload["source"]["kind"] == "terminal"
        assert payload["caution"] == "irreversible"
        # A runtime's own tool: its "always" stays the runtime's to remember.
        offer = payload["rule"]
        assert (offer["scopes"], offer["chat"]) == ([], "runtime")
        # ...and the card may still narrow it to this one command for this chat.
        assert payload["rule"]["narrow"][0]["kind"] == "command"
        svc.resolve_approval(session.session_id, payload["approval_id"], "allow_always")
        assert await asyncio.wait_for(answering, 2) == {"outcome": "selected", "optionId": "o2"}

    asyncio.run(scenario())


def test_a_card_without_extras_still_asks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from dodaios.agent_chat import approval_card

    def broken(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise RuntimeError("boom")

    monkeypatch.setattr(approval_card, "rule_offer", broken)

    async def scenario() -> None:
        svc, session = _service(tmp_path)
        q = svc.subscribe(session.session_id)
        asking = asyncio.create_task(svc._ask(session.session_id, "t1", "c1", "Bash", {}, "ls"))  # noqa: SLF001
        payload = (await _next(q, "approval_required"))["payload"]
        assert payload["name"] == "Bash" and "source" not in payload
        svc.resolve_approval(session.session_id, payload["approval_id"], "deny")
        assert await asyncio.wait_for(asking, 2) == "deny"

    asyncio.run(scenario())


# ------------------------------------------------------------ rules


class _Roster:
    def __init__(self, agent: Any) -> None:
        self.agent = agent

    async def get(self, agent_id: str) -> Any:
        return self.agent if agent_id == self.agent.agent_id else None

    async def update(self, agent_id: str, fields: dict[str, Any]) -> Any:
        self.agent = SimpleNamespace(**{**vars(self.agent), **fields})
        return self.agent


class _Runtime:
    def __init__(self, agent: Any) -> None:
        self.roster = _Roster(agent)
        self.cached: Any = None

    def catalog(self) -> list[CapabilityRow]:
        return [
            CapabilityRow(
                id="plugin:gmail",
                kind=CapabilityKind.PLUGIN,
                label="Gmail",
                one_liner="",
                risk_tier="ask",
                connected=True,
                tool_name="gmail",
            )
        ]

    def cache_agent(self, agent: Any) -> None:
        self.cached = agent


def _agent(**rules: list[str]) -> Any:
    return SimpleNamespace(
        agent_id="ada",
        approval_rules={
            "require_approval": rules.get("require", []),
            "always_allow": rules.get("always", []),
        },
        approval_mode=None,
        permission_ceiling="monitor",
    )


@pytest.fixture
def society_runtime(monkeypatch: pytest.MonkeyPatch):
    from dodaios.society import runtime as runtime_mod

    rt = _Runtime(_agent())
    monkeypatch.setattr(runtime_mod, "current_runtime", lambda: rt)
    return rt


def test_card_rule_only_for_the_agents_own_tools(society_runtime):
    assert card_rule("gmail", {"action": "send"}) == {
        "capability": "plugin:gmail",
        "app": "Gmail",
        "verb": "send",
        "pattern": "plugin:gmail:send",
        "broad": "plugin:gmail",
    }
    assert card_rule("mcp__dodaios__gmail", {})["pattern"] == "plugin:gmail"  # type: ignore[index]
    assert card_rule("Bash", {"command": "ls"}) is None
    assert card_rule("mcp__notion__create_page", {}) is None


def test_rule_text_and_apply_rule():
    assert rule_text("always_allow", "Gmail", "send") == "Always allow send with Gmail"
    assert rule_text("require_approval", "Gmail") == "Ask first before Gmail"
    rules = apply_rule(
        {"require_approval": ["plugin:gmail:send"], "always_allow": []},
        "always_allow",
        "plugin:gmail:send",
    )
    assert rules == {"require_approval": [], "always_allow": ["plugin:gmail:send"]}
    back = apply_rule(rules, "require_approval", "plugin:gmail:send")
    assert back == {"require_approval": ["plugin:gmail:send"], "always_allow": []}
    with pytest.raises(ValueError):
        apply_rule(rules, "never", "x")


def test_an_always_saved_on_the_agent_auto_allows_the_next_call(tmp_path: Path, society_runtime):
    async def scenario() -> None:
        svc, session = _service(tmp_path, surface="society", session_id="society:ada")
        q = svc.subscribe(session.session_id)
        asking = asyncio.create_task(
            svc._ask(session.session_id, "t1", "c1", "gmail", {"action": "send"}, "Send")  # noqa: SLF001
        )
        payload = (await _next(q, "approval_required"))["payload"]
        assert payload["rule"]["scopes"] == ["agent", "chat"]
        assert payload["rule"]["pattern"] == "plugin:gmail:send"
        svc.resolve_approval(
            session.session_id,
            payload["approval_id"],
            "allow_always",
            scope="agent",
            breadth="action",
        )
        assert await asyncio.wait_for(asking, 2) == "allow_always"
        resolved = (await _next(q, "approval_resolved"))["payload"]
        assert resolved["scope"] == "agent"
        notice = (await _next(q, "notice"))["payload"]
        assert notice["kind"] == "approval_rule" and notice["pattern"] == "plugin:gmail:send"
        agent = society_runtime.roster.agent
        assert agent.approval_rules["always_allow"] == ["plugin:gmail:send"]
        assert society_runtime.cached is agent
        # The session's own stance is untouched: the rule lives on the agent.
        assert svc.store.get_session(session.session_id).permission_mode == "ask"  # type: ignore[union-attr]
        # The next matching call runs without a card; another verb still asks.
        assert decide(agent, "plugin:gmail", "ask", verb="send") is Verdict.RUN
        assert decide(agent, "plugin:gmail", "ask", verb="delete") is Verdict.QUEUE

    asyncio.run(scenario())


def test_an_agent_rule_for_one_action_is_not_widened_by_the_bridge(
    tmp_path: Path, society_runtime
):
    """"Only send with Gmail" saved on the agent: the chat must not then wave
    every Gmail action through (the bridge's own chat-wide "always")."""

    async def scenario() -> None:
        svc, session = _service(tmp_path, surface="society", session_id="society:ada")
        sid = session.session_id
        q = svc.subscribe(sid)
        bus = EventBus()
        bridge = svc._bridge_for(bus)  # noqa: SLF001 — wires the service's hook
        assert bridge is not None
        approved: list[ActionApproved] = []

        async def seen(event: ActionApproved) -> None:
            approved.append(event)

        bus.subscribe(ActionApproved, seen)
        ref = approval_ref(sid)
        bridge.arm(
            ref,
            ChatGrant(
                session_id=sid,
                turn_id="t1",
                stance="ask",
                always_allowed=svc.always_allowed(sid),
                ask=lambda call_id, name, args, summary: svc._ask(  # noqa: SLF001
                    sid, "t1", call_id, name, args, summary
                ),
            ),
        )
        send = ActionProposed(tool_name="gmail", args={"action": "send"})
        await bus.publish(send)
        await bus.publish(
            ActionApprovalRequired(trace_id=send.trace_id, tool_name="gmail", approval_ref=ref)
        )
        payload = (await _next(q, "approval_required"))["payload"]
        svc.resolve_approval(
            sid, payload["approval_id"], "allow_always", scope="agent", breadth="action"
        )
        await _next(q, "notice")
        await asyncio.sleep(0.05)
        assert approved and approved[-1].trace_id == send.trace_id
        assert society_runtime.roster.agent.approval_rules["always_allow"] == ["plugin:gmail:send"]
        assert "gmail" not in svc.always_allowed(sid)
        # Another Gmail action still reaches the card.
        delete = ActionProposed(tool_name="gmail", args={"action": "delete"})
        await bus.publish(delete)
        await bus.publish(
            ActionApprovalRequired(trace_id=delete.trace_id, tool_name="gmail", approval_ref=ref)
        )
        again = (await _next(q, "approval_required"))["payload"]
        assert again["source"]["verb"] == "delete"
        svc.resolve_approval(sid, again["approval_id"], "deny")
        await asyncio.sleep(0.05)

    asyncio.run(scenario())


def test_a_chat_always_still_covers_the_tool(tmp_path: Path):
    """Without an agent rule the bridge keeps remembering the tool for the chat."""
    svc, session = _service(tmp_path)
    bridge = svc._bridge_for(EventBus())  # noqa: SLF001
    assert bridge is not None
    assert bridge.chat_keeps_always(session.session_id, "gmail") is True


def test_breadth_is_validated(tmp_path: Path):
    svc, session = _service(tmp_path)
    with pytest.raises(ValueError):
        svc.resolve_approval(session.session_id, "a1", "allow_always", scope="agent", breadth="all")


def test_a_rule_saved_after_the_fact(tmp_path: Path, society_runtime):
    async def scenario() -> None:
        svc, session = _service(tmp_path, surface="society", session_id="society:ada")
        sid = session.session_id
        svc.store.append_event(
            sid, {"kind": "turn_started", "ts_ms": 1, "payload": {"turn_id": "t1"}}
        )
        svc.store.append_event(
            sid,
            {
                "kind": "approval_required",
                "ts_ms": 2,
                "payload": {
                    "turn_id": "t1",
                    "approval_id": "old",
                    "call_id": "c1",
                    "name": "gmail",
                    "input": {"action": "send"},
                    "summary": "Send",
                },
            },
        )
        svc.store.append_event(
            sid,
            {
                "kind": "approval_resolved",
                "ts_ms": 3,
                "payload": {
                    "turn_id": "t1",
                    "approval_id": "old",
                    "decision": "expired",
                },
            },
        )
        rule = await svc.save_approval_rule(
            sid, "old", kind="always_allow", scope="agent", breadth="app"
        )
        assert rule["pattern"] == "plugin:gmail"
        assert society_runtime.roster.agent.approval_rules["always_allow"] == ["plugin:gmail"]
        undo = await svc.save_approval_rule(
            sid, "old", kind="require_approval", scope="agent", breadth="app"
        )
        assert undo["pattern"] == "plugin:gmail"
        assert society_runtime.roster.agent.approval_rules == {
            "require_approval": ["plugin:gmail"],
            "always_allow": [],
        }
        last = svc.store.list_events(sid)[-1]
        assert last["kind"] == "notice" and last["payload"]["rule_kind"] == "require_approval"
        with pytest.raises(KeyError):
            await svc.save_approval_rule(sid, "never-shown", kind="always_allow", scope="agent")

    asyncio.run(scenario())


def test_decide_keeps_its_order_after_card_rules():
    """Regression: the card writes patterns; it never changes how they are read."""
    allowed = _agent(always=["plugin:gmail:send"])
    assert decide(allowed, "plugin:gmail", "ask", verb="send") is Verdict.RUN
    # An explicit "ask first" still wins over a standing yes.
    both = _agent(require=["plugin:gmail:*"], always=["plugin:gmail:send"])
    assert decide(both, "plugin:gmail", "ask", verb="send") is Verdict.QUEUE
    # Always ask ignores a standing yes.
    assert decide(allowed, "plugin:gmail", "ask", verb="send", approval_mode="always_ask") is (
        Verdict.QUEUE
    )
    # A standing yes never lifts a blocked tool class.
    assert decide(allowed, "plugin:gmail", "block", verb="send") is Verdict.BLOCK


def test_still_asks_reports_a_broader_ask_first(tmp_path: Path, society_runtime):
    society_runtime.roster.agent = _agent(require=["plugin:gmail:*"])

    async def scenario() -> None:
        rule = await society_approvals.save_card_rule(
            "society:ada", "gmail", {"action": "send"}, kind="always_allow"
        )
        assert rule is not None and rule["still_asks"] is True

    asyncio.run(scenario())


# ------------------------------------------------------------ routes


def _app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.agent_chat = AgentChatService(AgentChatStore(":memory:"))
    return app


def test_the_rule_route(tmp_path: Path):
    app = _app(tmp_path)
    svc: AgentChatService = app.state.agent_chat
    with TestClient(app) as client:
        jarvis = svc.store.create_session(
            provider="claude-api", model="m", effort="medium", cwd=str(tmp_path), surface="jarvis"
        ).session_id
        coding = svc.store.create_session(
            provider="claude-api", model="m", effort="medium", cwd=str(tmp_path), surface="agent"
        ).session_id
        for sid in (jarvis, coding):
            svc.store.append_event(
                sid,
                {
                    "kind": "approval_required",
                    "ts_ms": 2,
                    "payload": {
                        "turn_id": "t1",
                        "approval_id": "a1",
                        "call_id": "c1",
                        "name": "gmail",
                        "input": {},
                        "summary": "s",
                    },
                },
            )
        url = "/api/agent-chat/sessions/{}/approvals/{}/rule"
        ok = client.post(url.format(jarvis, "a1"), json={"kind": "always_allow", "scope": "chat"})
        assert ok.status_code == 200 and ok.json()["rule"]["pattern"] == "gmail"
        assert "gmail" in svc.always_allowed(jarvis)
        # A coding chat's "always" would silence the whole chat: never after the fact.
        refused = client.post(
            url.format(coding, "a1"), json={"kind": "always_allow", "scope": "chat"}
        )
        assert refused.status_code == 409
        assert (
            client.post(
                url.format(jarvis, "zz"), json={"kind": "always_allow", "scope": "chat"}
            ).status_code
            == 404
        )
        assert (
            client.post(
                url.format(jarvis, "a1"), json={"kind": "never", "scope": "chat"}
            ).status_code
            == 400
        )
        assert (
            client.post(
                url.format(jarvis, "a1"), json={"kind": "always_allow", "scope": "x"}
            ).status_code
            == 400
        )
        bad_scope = client.post(
            f"/api/agent-chat/sessions/{jarvis}/approvals/a1",
            json={"decision": "allow_always", "scope": "planet"},
        )
        assert bad_scope.status_code == 400
        bad_breadth = client.post(
            f"/api/agent-chat/sessions/{jarvis}/approvals/a1",
            json={"decision": "allow_always", "scope": "agent", "breadth": "planet"},
        )
        assert bad_breadth.status_code == 400


# ------------------------------------------------------------ narrow rules, short paths

WIN_HOME = "C:\\Users\\Ada"
WIN_CWD = "C:\\Users\\Ada\\Desktop\\proj"


def test_display_paths_shortens_the_workspace_and_the_home_folder():
    from dodaios.agent_chat.approval_card import display_paths

    text = f"Edit {WIN_CWD}\\src\\a.py and C:/Users/ada/Downloads/x.txt"
    assert display_paths(text, WIN_CWD, WIN_HOME) == "Edit src\\a.py and ~/Downloads/x.txt"
    # The workspace itself reads as its own name, not the long path to it.
    assert display_paths(WIN_CWD, WIN_CWD, WIN_HOME) == "proj"
    assert display_paths(f"In {WIN_CWD}", WIN_CWD, WIN_HOME) == "In proj"
    assert display_paths("echo hi", WIN_CWD, WIN_HOME) == "echo hi"
    assert display_paths("/home/bob/code/x.py", "/home/bob/code", "/home/bob") == "x.py"
    assert display_paths("cat /home/bob/notes.md", "", "/home/bob") == "cat ~/notes.md"
    # A folder that only starts like the home folder is left alone.
    assert display_paths("C:\\Users\\Adam\\x", "", WIN_HOME) == "C:\\Users\\Adam\\x"


def test_narrow_options_and_matches():
    from dodaios.agent_chat.approval_card import narrow_matches, narrow_options

    folder = narrow_options("files", {"file_path": f"{WIN_CWD}\\src\\a.py"}, WIN_CWD)
    assert folder == [{"kind": "folder", "value": f"{WIN_CWD}\\src", "label": "src"}] or (
        # POSIX normpath keeps backslashes as part of the name; the label still shortens.
        folder and folder[0]["kind"] == "folder"
    )
    command = narrow_options("terminal", {"command": "npm   test"}, WIN_CWD)
    assert command == [{"kind": "command", "value": "npm test", "label": "npm test"}]
    assert narrow_options("connector", {"action": "send"}, WIN_CWD) == []
    assert narrow_options("terminal", {"command": "x" * 500}, WIN_CWD) == []

    rule = {"tool": "Bash", "kind": "command", "value": "npm test"}
    assert narrow_matches(rule, "Bash", {"command": "npm  test"})
    assert not narrow_matches(rule, "Bash", {"command": "npm test && rm -rf /"})
    assert not narrow_matches(rule, "RunCommand", {"command": "npm test"})


def test_a_folder_rule_covers_only_that_folder(tmp_path: Path):
    from dodaios.agent_chat.approval_card import narrow_matches

    root = tmp_path / "src"
    rule = {"tool": "Edit", "kind": "folder", "value": str(root)}
    assert narrow_matches(rule, "Edit", {"file_path": str(root / "a" / "b.py")})
    assert narrow_matches(rule, "Edit", {"file_path": "src/c.py"}, str(tmp_path))
    assert not narrow_matches(rule, "Edit", {"file_path": str(tmp_path / "other.py")})
    assert not narrow_matches(rule, "Edit", {"file_path": str(root / ".." / "escape.py")})
    assert not narrow_matches(rule, "Write", {"file_path": str(root / "a.py")})
    assert not narrow_matches(rule, "Edit", {})


def test_the_card_shows_short_paths_and_offers_narrow_rules(tmp_path: Path):
    target = tmp_path / "src" / "app.py"
    fields = describe_call(
        "Edit",
        {"file_path": str(target), "old_string": "a", "new_string": "b"},
        f"Edit {target}",
        cwd=str(tmp_path),
        rule={"scopes": ["chat"], "chat": "tool", "app": "Edit"},
    )
    assert str(tmp_path) not in fields["brief"]
    assert fields["brief"].replace("\\", "/") == "Edit src/app.py"
    # The full path stays in the disclosure.
    assert str(target).replace("\\", "\\\\") in fields["detail"] or str(target) in fields["detail"]
    narrow = fields["rule"]["narrow"]
    assert narrow[0]["kind"] == "folder" and narrow[0]["value"] == str(target.parent)
    assert narrow[0]["label"] == "src"
    # A plan offers nothing; a connector offers no narrow rule.
    assert describe_call("ExitPlanMode", {"plan": "x"}, rule={"scopes": []})["rule"] is None
    gmail = describe_call("gmail", {"action": "send"}, rule={"scopes": ["chat"]})
    assert "narrow" not in gmail["rule"]


def test_a_narrow_command_rule_allows_only_that_command(tmp_path: Path):
    async def scenario() -> None:
        svc, session = _service(tmp_path)
        sid = session.session_id
        q = svc.subscribe(sid)
        asking = asyncio.create_task(
            svc._ask(sid, "t1", "c1", "Bash", {"command": "npm test"}, "npm test")  # noqa: SLF001
        )
        payload = (await _next(q, "approval_required"))["payload"]
        assert payload["rule"]["narrow"] == [
            {"kind": "command", "value": "npm test", "label": "npm test"}
        ]
        assert svc.resolve_approval(
            sid, payload["approval_id"], "allow_always", scope="chat", narrow="command"
        )
        # The runtime hears a plain yes: it must not widen the rule to the tool.
        assert await asyncio.wait_for(asking, 2) == "allow"
        resolved = (await _next(q, "approval_resolved"))["payload"]
        assert resolved["decision"] == "allow_always" and resolved["scope"] == "chat"
        notice = (await _next(q, "notice"))["payload"]
        assert notice["narrow"] == "command" and notice["target"] == "npm test"
        assert "Bash" not in svc.always_allowed(sid)
        assert svc.store.get_session(sid).permission_mode == "ask"  # type: ignore[union-attr]
        # The same command runs without a card; another one still asks.
        assert await svc._ask(sid, "t1", "c2", "Bash", {"command": "npm test"}, "") == "allow"  # noqa: SLF001
        other = asyncio.create_task(
            svc._ask(sid, "t1", "c3", "Bash", {"command": "rm -rf dist"}, "")  # noqa: SLF001
        )
        again = (await _next(q, "approval_required"))["payload"]
        assert again["input"] == {"command": "rm -rf dist"}
        svc.resolve_approval(sid, again["approval_id"], "deny")
        assert await asyncio.wait_for(other, 2) == "deny"

    asyncio.run(scenario())


def test_a_narrow_folder_rule_allows_only_that_folder(tmp_path: Path):
    async def scenario() -> None:
        svc, session = _service(tmp_path, surface="society", session_id="society:ada")
        sid = session.session_id
        q = svc.subscribe(sid)
        inside = str(tmp_path / "docs" / "a.md")
        asking = asyncio.create_task(
            svc._ask(sid, "t1", "c1", "Edit", {"file_path": inside}, "")  # noqa: SLF001
        )
        payload = (await _next(q, "approval_required"))["payload"]
        svc.resolve_approval(
            sid, payload["approval_id"], "allow_always", scope="chat", narrow="folder"
        )
        assert await asyncio.wait_for(asking, 2) == "allow"
        later = str(tmp_path / "docs" / "deep" / "b.md")
        assert await svc._ask(sid, "t1", "c2", "Edit", {"file_path": later}, "") == "allow"  # noqa: SLF001
        outside = asyncio.create_task(
            svc._ask(sid, "t1", "c3", "Edit", {"file_path": str(tmp_path / "x.md")}, "")  # noqa: SLF001
        )
        again = (await _next(q, "approval_required"))["payload"]
        svc.resolve_approval(sid, again["approval_id"], "deny")
        assert await asyncio.wait_for(outside, 2) == "deny"

    asyncio.run(scenario())


def test_narrow_is_validated(tmp_path: Path):
    svc, session = _service(tmp_path)
    with pytest.raises(ValueError):
        svc.resolve_approval(session.session_id, "a1", "allow_always", scope="chat", narrow="disk")
    with pytest.raises(ValueError):
        svc.resolve_approval(
            session.session_id, "a1", "allow_always", scope="agent", narrow="folder"
        )


def test_an_always_without_a_choice_never_writes_a_rule_for_a_runtime_tool(
    tmp_path: Path, society_runtime
):
    """An older client's bare "Always allow" on Claude's own Edit: no
    ``plugin:edit`` on the agent, no chat-wide auto, only that tool in this chat."""

    async def scenario() -> None:
        from dodaios.society.surface import remember_always_allow

        svc, session = _service(tmp_path, surface="society", session_id="society:ada")
        sid = session.session_id
        q = svc.subscribe(sid)
        assert await remember_always_allow(session, "Edit", {"file_path": "a.py"}) is False
        asking = asyncio.create_task(
            svc._ask(sid, "t1", "c1", "Edit", {"file_path": "a.py"}, "")  # noqa: SLF001
        )
        payload = (await _next(q, "approval_required"))["payload"]
        svc.resolve_approval(sid, payload["approval_id"], "allow_always")
        assert await asyncio.wait_for(asking, 2) == "allow_always"
        assert society_runtime.roster.agent.approval_rules["always_allow"] == []
        assert "Edit" in svc.always_allowed(sid)
        assert svc.store.get_session(sid).permission_mode == "ask"  # type: ignore[union-attr]

    asyncio.run(scenario())


def test_the_route_takes_a_narrow_rule(tmp_path: Path):
    app = _app(tmp_path)
    svc: AgentChatService = app.state.agent_chat
    session = svc.store.create_session(
        provider="claude-api", model="m", effort="medium", cwd=str(tmp_path), surface="jarvis"
    )
    with TestClient(app) as client:
        url = f"/api/agent-chat/sessions/{session.session_id}/approvals/a1"
        bad = client.post(url, json={"decision": "allow_always", "scope": "chat", "narrow": "x"})
        assert bad.status_code == 400
        wrong_scope = client.post(
            url, json={"decision": "allow_always", "scope": "agent", "narrow": "folder"}
        )
        assert wrong_scope.status_code == 400


def test_a_narrow_rule_that_cannot_be_saved_never_widens(tmp_path: Path):
    """"Only this folder" on a call that has no folder: this call runs once,
    the tool and the chat keep asking."""

    async def scenario() -> None:
        svc, session = _service(tmp_path)
        sid = session.session_id
        q = svc.subscribe(sid)
        asking = asyncio.create_task(
            svc._ask(sid, "t1", "c1", "Bash", {"command": "npm test"}, "npm test")  # noqa: SLF001
        )
        payload = (await _next(q, "approval_required"))["payload"]
        svc.resolve_approval(
            sid, payload["approval_id"], "allow_always", scope="chat", narrow="folder"
        )
        assert await asyncio.wait_for(asking, 2) == "allow"
        assert "Bash" not in svc.always_allowed(sid)
        assert svc.store.get_session(sid).permission_mode == "ask"  # type: ignore[union-attr]
        again = asyncio.create_task(
            svc._ask(sid, "t1", "c2", "Bash", {"command": "npm test"}, "")  # noqa: SLF001
        )
        card = (await _next(q, "approval_required"))["payload"]
        svc.resolve_approval(sid, card["approval_id"], "deny")
        assert await asyncio.wait_for(again, 2) == "deny"

    asyncio.run(scenario())


def test_a_narrow_rule_on_an_own_server_tool_matches_its_later_calls():
    from dodaios.agent_chat.approval_card import narrow_matches, narrow_tool

    rule = {"tool": narrow_tool("mcp__dodaios__shell"), "kind": "command", "value": "ls"}
    assert narrow_matches(rule, "mcp__jarvis__shell", {"command": "ls"})
    other = {"tool": narrow_tool("mcp__fs__shell"), "kind": "command", "value": "ls"}
    assert narrow_matches(other, "mcp__fs__shell", {"command": "ls"})
    assert not narrow_matches(other, "mcp__evil__shell", {"command": "ls"})


def test_the_home_folder_is_never_offered_as_only_this_folder(tmp_path: Path):
    from dodaios.agent_chat.approval_card import narrow_options

    home = str(tmp_path / "home")
    at_home = narrow_options("files", {"file_path": str(tmp_path / "home" / "x.txt")}, "", home)
    assert at_home == []
    above = narrow_options("files", {"file_path": str(tmp_path / "y.txt")}, "", home)
    assert above == []
    deeper = narrow_options(
        "files", {"file_path": str(tmp_path / "home" / "proj" / "z.txt")}, "", home
    )
    assert deeper and deeper[0]["value"] == str(tmp_path / "home" / "proj")
    assert deeper[0]["label"].replace("\\", "/") == "~/proj"


def test_a_runtime_file_request_reads_inside_the_agents_workspace():
    """Hermes asks with the tool's own arguments nested; the card stays short."""
    workspace = "C:/Users/Ada/data/society/agent-1/workspace"
    args = {"tool": "write_file", "arguments": {"path": "qa_note.txt", "content": "hello"}}
    card = describe_call("edit", args, "Approve edit: qa_note.txt", cwd=workspace)
    assert card["where"] == "workspace"
    assert card["where_full"] == workspace
    assert card["brief"] == "Approve edit: qa_note.txt"
    narrow = narrow_options_for(args, workspace)
    assert narrow and narrow[0]["label"] == "workspace"


def narrow_options_for(args, cwd):
    from dodaios.agent_chat.approval_card import narrow_options

    return narrow_options("files", args, cwd, "C:/Users/Ada")


def test_a_file_call_on_a_missing_file_asks_to_create_it(tmp_path):
    """"Create this file?" for a new file, "Change this file?" for one already there."""
    (tmp_path / "notes.md").write_text("x", encoding="utf-8")
    new = describe_call("Write", {"file_path": "draft.md", "content": "hi"}, cwd=str(tmp_path))
    assert new.get("creates") is True
    existing = describe_call("Write", {"file_path": "notes.md", "content": "hi"}, cwd=str(tmp_path))
    assert "creates" not in existing
    assert "creates" not in describe_call("Bash", {"command": "ls"}, cwd=str(tmp_path))
