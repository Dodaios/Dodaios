"""Allow / Deny buttons in the owner's Telegram answer the app's approval."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.service import AgentChatService, _Running
from dodaios.agent_chat.store import AgentChatStore
from dodaios.channels.telegram import TelegramChannel
from dodaios.channels.telegram_approvals import (
    TelegramApprovalBridge,
    callback_data,
    owner_chat_id,
    parse_callback,
)
from dodaios.core.bus import EventBus
from dodaios.core.config import TelegramConfig
from dodaios.notify.settings import NotifySettings


def _cfg(users: list[int] | None = None, chat_id: str = "") -> Any:
    telegram = TelegramConfig(allowed_user_ids=list(users or []), chat_id=chat_id)
    return SimpleNamespace(integrations=SimpleNamespace(telegram=telegram))


def test_owner_chat_id_prefers_the_first_allowed_user() -> None:
    assert owner_chat_id(_cfg([42, 7])) == 42
    assert owner_chat_id(_cfg([], "99")) == 99
    assert owner_chat_id(_cfg()) is None
    assert owner_chat_id(SimpleNamespace()) is None


def test_callback_data_round_trips_within_telegram_limits() -> None:
    data = callback_data("allow", "a" * 32)
    assert len(data.encode()) <= 64
    assert parse_callback(data) == ("allow", "a" * 32)
    assert parse_callback(callback_data("deny", "x1")) == ("deny", "x1")
    assert parse_callback("apr:z:x1") is None
    assert parse_callback("other") is None
    assert parse_callback("") is None


class _Channel:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.edited: list[tuple[int, int, str]] = []
        self.on_approval_callback: Any = None

    async def send_approval(
        self, chat_id: int, text: str, approval_id: str, *, allow: str, deny: str
    ) -> int:
        self.sent.append(
            {
                "chat_id": chat_id,
                "text": text,
                "approval_id": approval_id,
                "allow": allow,
                "deny": deny,
            }
        )
        return len(self.sent)

    async def edit_message(self, chat_id: int, message_id: int, text: str) -> None:
        self.edited.append((chat_id, message_id, text))


def _service(tmp_path: Path) -> tuple[AgentChatService, str]:
    svc = AgentChatService(AgentChatStore(":memory:"), assistant_name=lambda: "Dodaios")
    sid = svc.store.create_session(provider="p", model="m", effort="", cwd=str(tmp_path)).session_id
    return svc, sid


async def _open_card(svc: AgentChatService, sid: str) -> tuple[asyncio.Task[str], str]:
    run = _Running("t1", asyncio.Event())
    run.task = asyncio.ensure_future(asyncio.sleep(3600))
    svc._running[sid] = run
    task = asyncio.ensure_future(svc._ask(sid, "t1", "c1", "RunCommand", {"command": "ls"}, "ls"))
    for _ in range(50):
        await asyncio.sleep(0)
        if svc.pending_approvals(sid):
            break
    return task, svc.pending_approvals(sid)[0]


def _close(svc: AgentChatService, sid: str) -> None:
    """Stop the fake turn so no sleeping task outlives the test's loop."""
    run = svc._running.pop(sid, None)
    if run is not None and run.task is not None:
        run.task.cancel()


async def test_a_button_answers_the_card_the_app_is_waiting_on(tmp_path: Path) -> None:
    svc, sid = _service(tmp_path)
    channel = _Channel()
    bridge = TelegramApprovalBridge(
        svc, channel=lambda: channel, config=lambda: _cfg([42]), settings=NotifySettings
    )
    bridge.install()
    waiting, approval_id = await _open_card(svc, sid)
    await asyncio.sleep(0.05)
    assert len(channel.sent) == 1
    sent = channel.sent[0]
    assert sent["chat_id"] == 42 and sent["approval_id"] == approval_id
    assert "RunCommand" in sent["text"] and "ls" in sent["text"]
    assert (sent["allow"], sent["deny"]) == ("Allow", "Deny")
    assert channel.on_approval_callback == bridge.on_callback
    # A stranger's press changes nothing.
    assert await bridge.on_callback(approval_id, "allow", 7) == "This request is no longer open."
    assert not waiting.done()
    assert await bridge.on_callback(approval_id, "allow", 42) == "Allowed from Telegram."
    assert await waiting == "allow"
    # The card's resolution does not edit the message a second time.
    svc._approvals.pop(approval_id, None)
    await asyncio.sleep(0.05)
    assert channel.edited == []
    assert await bridge.on_callback(approval_id, "deny", 42) == "This request is no longer open."
    _close(svc, sid)


async def test_a_decision_in_the_app_settles_the_telegram_message(tmp_path: Path) -> None:
    svc, sid = _service(tmp_path)
    channel = _Channel()
    bridge = TelegramApprovalBridge(
        svc, channel=lambda: channel, config=lambda: _cfg([42]), settings=NotifySettings
    )
    bridge.install()
    waiting, approval_id = await _open_card(svc, sid)
    await asyncio.sleep(0.05)
    assert svc.resolve_approval(sid, approval_id, "deny") is True
    assert await waiting == "deny"
    await asyncio.sleep(0.05)
    assert channel.edited and channel.edited[0][2].endswith("Decided in the app.")
    assert bridge.open() == []
    _close(svc, sid)


async def test_off_switch_and_missing_pieces_send_nothing(tmp_path: Path) -> None:
    svc, sid = _service(tmp_path)
    channel = _Channel()
    off = TelegramApprovalBridge(
        svc,
        channel=lambda: channel,
        config=lambda: _cfg([42]),
        settings=lambda: NotifySettings(telegram_approvals=False),
    )
    off.listener(sid, make_event("approval_required", {"approval_id": "a1", "name": "x"}))
    await asyncio.sleep(0.02)
    no_owner = TelegramApprovalBridge(
        svc, channel=lambda: channel, config=lambda: _cfg([]), settings=NotifySettings
    )
    no_owner.listener(sid, make_event("approval_required", {"approval_id": "a2", "name": "x"}))
    no_channel = TelegramApprovalBridge(
        svc, channel=lambda: None, config=lambda: _cfg([42]), settings=NotifySettings
    )
    no_channel.listener(sid, make_event("approval_required", {"approval_id": "a3", "name": "x"}))
    await asyncio.sleep(0.02)
    assert channel.sent == []


# ---------------------------------------------------- the channel's own half


def _channel_with_bot() -> tuple[TelegramChannel, Any]:
    ch = TelegramChannel(bus=EventBus(), config=TelegramConfig())
    message = SimpleNamespace(message_id=77)
    bot = SimpleNamespace(
        send_message=AsyncMock(return_value=message), edit_message_text=AsyncMock()
    )
    ch._app = SimpleNamespace(bot=bot)  # noqa: SLF001
    return ch, bot


async def test_send_approval_carries_two_inline_buttons() -> None:
    pytest.importorskip("telegram")
    ch, bot = _channel_with_bot()
    message_id = await ch.send_approval(
        42, "Scout asks to run ls", "abc", allow="Allow", deny="Deny"
    )
    assert message_id == 77
    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == 42
    buttons = kwargs["reply_markup"].inline_keyboard[0]
    assert [b.text for b in buttons] == ["Allow", "Deny"]
    assert [b.callback_data for b in buttons] == ["apr:a:abc", "apr:d:abc"]
    await ch.edit_message(42, 77, "done")
    assert bot.edit_message_text.await_args.kwargs["message_id"] == 77


async def test_a_callback_query_reaches_the_bridge_and_edits_the_message() -> None:
    ch, _bot = _channel_with_bot()
    seen: list[tuple[str, str, int | None]] = []

    async def _answer(approval_id: str, decision: str, user: int | None) -> str:
        seen.append((approval_id, decision, user))
        return "Allowed from Telegram."

    ch.on_approval_callback = _answer
    query = SimpleNamespace(
        data="apr:a:abc",
        from_user=SimpleNamespace(id=42),
        message=SimpleNamespace(text="Scout asks to run ls"),
        answer=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    await ch._on_callback_query(SimpleNamespace(callback_query=query), None)  # noqa: SLF001
    assert seen == [("abc", "allow", 42)]
    query.answer.assert_awaited_once_with("Allowed from Telegram.")
    edited = query.edit_message_text.await_args.kwargs
    assert edited["text"] == "Scout asks to run ls\n\nAllowed from Telegram."
    assert edited["reply_markup"] is None
    # Unknown data is answered quietly and leaves the message alone.
    other = SimpleNamespace(
        data="nope", from_user=None, message=None, answer=AsyncMock(), edit_message_text=AsyncMock()
    )
    await ch._on_callback_query(SimpleNamespace(callback_query=other), None)  # noqa: SLF001
    other.edit_message_text.assert_not_awaited()
