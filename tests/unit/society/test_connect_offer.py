"""A plugin tool that is not connected shows its Connect card in the chat by itself."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat.approval_bridge import approval_ref
from dodaios.agent_chat.credential_requests import PLUGIN
from dodaios.agent_chat.service import AgentChatService, _Running
from dodaios.agent_chat.store import AgentChatStore
from dodaios.core.bus import EventBus
from dodaios.core.config import SafetyConfig
from dodaios.core.protocols import ToolResult
from dodaios.safety.approval import ApprovalWorkflow
from dodaios.safety.risk_tier import RiskTierEvaluator
from dodaios.safety.tool_executor import ToolExecutor
from dodaios.society import connect_offer, connect_tool
from dodaios.society import runtime as runtime_mod
from dodaios.society.connect_offer import CARD_STATUS, names_missing_connection, offer_connect
from dodaios.society.connect_tool import Target

LEAD_CHAT = "3ba569d6bc824153b9a994e6a896a78f"
GMAIL_ERROR = "Gmail is not connected — connect it in the Plugins view."


def _failed(error: str = GMAIL_ERROR) -> ToolResult:
    return ToolResult(success=False, output=None, error=error)


def _chat(session_id: str = LEAD_CHAT) -> dict[str, Any]:
    return {"approval_surface": "interactive", "approval_ref": approval_ref(session_id)}


@pytest.fixture
async def chat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The lead's chat with a running turn, and Gmail without a connection."""
    svc = AgentChatService(AgentChatStore(":memory:"), assistant_name=lambda: "Testo")
    svc.store.create_session(
        provider="fakeprov", model="m", effort="high", cwd=str(tmp_path),
        session_id=LEAD_CHAT, surface="jarvis",
    )
    run = _Running("turn-1", asyncio.Event())
    run.task = asyncio.create_task(asyncio.sleep(3600))
    svc._running[LEAD_CHAT] = run  # noqa: SLF001 — a running turn without a runner
    state = {"connected": False}

    def resolve(kind: str, raw: str) -> Target | None:
        if kind != PLUGIN or raw != "gmail":
            return None
        return Target(kind, "gmail", "Gmail", state["connected"])

    monkeypatch.setattr(connect_tool, "resolve_target", resolve)
    runtime = SimpleNamespace(
        chat_service=lambda: svc,
        cached_agent=lambda agent_id: SimpleNamespace(name=agent_id.title()),
    )
    monkeypatch.setattr(runtime_mod, "current_runtime", lambda: runtime)
    try:
        yield SimpleNamespace(svc=svc, state=state, run=run)
    finally:
        run.task.cancel()


def _cards(svc: AgentChatService, session_id: str = LEAD_CHAT) -> list[dict[str, Any]]:
    return [
        event["payload"]
        for event in svc.store.list_events(session_id)
        if event["kind"] == "credential_required"
    ]


def test_every_plugin_tool_words_a_missing_connection_the_way_the_offer_reads_it() -> None:
    from dodaios.plugins.tool import (
        drive_rest,
        gmail_rest,
        google_calendar_rest,
        home_assistant_rest,
        slack_rest,
        spotify_rest,
        youtube_music_rest,
    )

    modules = (
        drive_rest, gmail_rest, google_calendar_rest, home_assistant_rest,
        slack_rest, spotify_rest, youtube_music_rest,
    )
    for module in modules:
        assert names_missing_connection(module._NOT_CONNECTED), module.__name__  # noqa: SLF001
        reconnect = getattr(module, "_NEEDS_RECONNECT", None)
        if reconnect is not None:
            assert names_missing_connection(reconnect), module.__name__
    assert names_missing_connection("Vercel is not connected — connect it in the Plugins view.")
    assert not names_missing_connection("message_id missing")
    assert not names_missing_connection(None)


async def test_a_plugin_tool_without_a_connection_shows_the_card_in_the_chat(chat) -> None:
    result = await offer_connect("gmail", _failed(), _chat())
    cards = _cards(chat.svc)
    assert len(cards) == 1
    card = cards[0]
    assert card["kind"] == PLUGIN and card["env"] == "gmail" and card["label"] == "Gmail"
    # In its own chat the card carries the assistant's name.
    assert card["turn_id"] == "turn-1" and card["asker"] == "Testo"
    # The model is told what the person sees, and not to walk them anywhere.
    assert not result.success
    assert result.output == {
        "status": CARD_STATUS, "kind": PLUGIN, "id": "gmail", "request_id": card["request_id"],
    }
    assert "Connect card for Gmail is now shown" in (result.error or "")
    assert "Do not open or name the Plugins page" in (result.error or "")
    assert "continues the request by itself" in (result.error or "")


async def test_a_second_failed_call_keeps_the_one_card(chat) -> None:
    first = await offer_connect("gmail", _failed(), _chat())
    second = await offer_connect("gmail", _failed(), _chat())
    assert len(_cards(chat.svc)) == 1
    assert first.output["request_id"] == second.output["request_id"]


async def test_asked_again_in_a_later_turn_the_card_stands_under_that_turn(chat) -> None:
    """The person finds the card under the newest message, not further up."""
    first = await offer_connect("gmail", _failed(), _chat())
    chat.run.task.cancel()
    await asyncio.sleep(0)
    later = _Running("turn-2", asyncio.Event())
    later.task = asyncio.create_task(asyncio.sleep(3600))
    chat.svc._running[LEAD_CHAT] = later  # noqa: SLF001 — the next turn
    try:
        second = await offer_connect("gmail", _failed(), _chat())
        cards = _cards(chat.svc)
        assert [card["turn_id"] for card in cards] == ["turn-1", "turn-2"]
        assert second.output["request_id"] == cards[1]["request_id"] != first.output["request_id"]
        closed = [
            event["payload"]
            for event in chat.svc.store.list_events(LEAD_CHAT)
            if event["kind"] == "credential_resolved"
        ]
        assert closed == [
            {
                "turn_id": "turn-1", "request_id": first.output["request_id"],
                "env": "gmail", "status": "superseded",
            }
        ]
        assert chat.svc.pending_credential_requests(LEAD_CHAT) == [second.output["request_id"]]
    finally:
        later.task.cancel()


async def test_the_card_closes_once_gmail_is_really_connected(chat) -> None:
    result = await offer_connect("gmail", _failed(), _chat())
    request_id = result.output["request_id"]
    chat.state["connected"] = True
    chat.svc._continue_after_connect = lambda *_a: None  # noqa: SLF001 — not this test's subject
    assert await chat.svc.submit_credential(LEAD_CHAT, request_id, "connected")
    assert await chat.svc.wait_credential_request(LEAD_CHAT, request_id, 1) == "saved"


@pytest.mark.parametrize(
    "tool_name,result,config",
    [
        # The call worked.
        ("gmail", ToolResult(success=True, output={"messages": []}), _chat()),
        # It failed for another reason.
        ("gmail", _failed("message_id missing"), _chat()),
        # A spoken call has no chat to show a card in.
        ("gmail", _failed(), {"approval_surface": "conversational"}),
        # A routine and a task agent run with nobody there to press Connect.
        ("gmail", _failed(), {**_chat(), "approval_surface": "unattended"}),
        ("gmail", _failed(), _chat("society:ada:routine:t1:r1")),
        # Not a marketplace plugin.
        ("run_shell", _failed("the host is not connected"), _chat()),
        # No config at all.
        ("gmail", _failed(), None),
    ],
)
async def test_everything_else_keeps_the_tools_own_result(
    chat, tool_name: str, result: ToolResult, config: dict[str, Any] | None
) -> None:
    assert await offer_connect(tool_name, result, config) is result
    assert _cards(chat.svc) == []


@pytest.mark.parametrize("connected", [True, None])
async def test_a_connected_or_unreadable_state_asks_for_no_sign_in(chat, connected) -> None:
    chat.state["connected"] = connected
    result = _failed()
    assert await offer_connect("gmail", result, _chat()) is result
    assert _cards(chat.svc) == []


async def test_a_turn_that_is_over_keeps_the_tools_own_error(chat) -> None:
    chat.run.task.cancel()
    await asyncio.sleep(0)
    result = _failed()
    assert await offer_connect("gmail", result, _chat()) is result


async def test_a_turn_that_used_its_cards_keeps_the_tools_own_error(
    chat, monkeypatch: pytest.MonkeyPatch
) -> None:
    labels = {"gmail": "Gmail", "slack": "Slack", "spotify": "Spotify", "vercel": "Vercel"}
    monkeypatch.setattr(
        connect_tool, "resolve_target",
        lambda kind, raw: Target(kind, raw, labels[raw], False) if raw in labels else None,
    )
    for name in ("gmail", "slack", "spotify"):
        shown = await offer_connect(name, _failed(f"{labels[name]} is not connected"), _chat())
        assert shown.output["status"] == CARD_STATUS
    fourth = _failed("Vercel is not connected — connect it in the Plugins view.")
    assert await offer_connect("vercel", fourth, _chat()) is fourth
    assert len(_cards(chat.svc)) == 3


async def test_an_agents_chat_shows_the_card_under_the_agents_name(
    chat, tmp_path: Path
) -> None:
    svc = chat.svc
    svc.store.create_session(
        provider="fakeprov", model="m", effort="high", cwd=str(tmp_path),
        session_id="society:ada", surface="society",
    )
    run = _Running("turn-9", asyncio.Event())
    run.task = asyncio.create_task(asyncio.sleep(3600))
    svc._running["society:ada"] = run  # noqa: SLF001 — a running turn without a runner
    try:
        await offer_connect("gmail", _failed(), _chat("society:ada"))
        assert _cards(svc, "society:ada")[0]["asker"] == "Ada"
    finally:
        run.task.cancel()


async def test_a_coding_thread_shows_the_card_without_a_name(chat, tmp_path: Path) -> None:
    svc = chat.svc
    svc.store.create_session(
        provider="fakeprov", model="m", effort="high", cwd=str(tmp_path),
        session_id="thread-7", surface="agent",
    )
    run = _Running("turn-3", asyncio.Event())
    run.task = asyncio.create_task(asyncio.sleep(3600))
    svc._running["thread-7"] = run  # noqa: SLF001 — a running turn without a runner
    try:
        shown = await offer_connect("gmail", _failed(), _chat("thread-7"))
        assert shown.output["status"] == CARD_STATUS
        assert _cards(svc, "thread-7")[0]["asker"] == ""
    finally:
        run.task.cancel()


async def test_the_card_is_the_persons_step_not_a_failure_to_work_around(chat) -> None:
    """With the card on screen the turn ends on one sentence: no automatic
    continuation looks for another route to the service, and none sends the
    agent back to "act now"."""
    from dodaios.agent_chat.task_recovery import ToolRecovery, blocks_automatic_recovery

    shown = await offer_connect("gmail", _failed(), _chat())
    text = f"Tool failed: {shown.error}"
    assert blocks_automatic_recovery(text)
    assert not blocks_automatic_recovery(f"Tool failed: {GMAIL_ERROR}")
    recovery = ToolRecovery()
    recovery.observe({"kind": "tool_call", "payload": {"call_id": "c1", "name": "gmail"}})
    recovery.observe(
        {"kind": "tool_result", "payload": {"call_id": "c1", "output": text, "is_error": True}}
    )
    assert recovery.blocked and recovery.hint() is None


async def test_the_tool_executor_offers_the_card_for_a_chats_call(chat) -> None:
    """The one place every tool call of a chat passes: no model has to ask for the card."""

    class Gmail:
        name = "gmail"
        description = "Read mail."
        risk_tier = "safe"
        schema: dict[str, Any] = {"type": "object", "properties": {}}

        async def execute(self, _args: dict[str, Any], _ctx: Any) -> ToolResult:
            return _failed()

    bus = EventBus()
    executor = ToolExecutor(bus, RiskTierEvaluator(SafetyConfig()), ApprovalWorkflow(bus))
    shown = await executor.execute(Gmail(), {"action": "list_messages"}, config_snapshot=_chat())
    assert not shown.success and shown.output["status"] == CARD_STATUS
    assert len(_cards(chat.svc)) == 1
    # The same call outside a chat reads the tool's own sentence.
    plain = await executor.execute(Gmail(), {"action": "list_messages"}, config_snapshot={})
    assert plain.error == GMAIL_ERROR and plain.output is None


async def test_a_broken_offer_never_costs_the_tools_result(
    chat, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dodaios.safety import tool_executor

    async def broken(*_args: Any) -> ToolResult:
        raise RuntimeError("catalog gone")

    monkeypatch.setattr(connect_offer, "offer_connect", broken)
    result = _failed()
    tool = SimpleNamespace(name="gmail")
    assert await tool_executor._offer_connect(tool, result, _chat()) is result  # noqa: SLF001
