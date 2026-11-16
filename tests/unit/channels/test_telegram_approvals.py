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
    assert sent["text"].startswith("An agent wants to run a command.")
    assert "\nls\n" in sent["text"]
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
    # Decided: the message shrinks to its first line and the decision.
    assert channel.edited
    assert channel.edited[0][2] == "An agent wants to run a command.\nDenied in the app."
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


# ---- the message itself: the owner's language, whole, who asks ----------------------------

_GERMAN_OWNER = "Bitte repariere den Scheduler, damit Termine wieder kommen."  # i18n-allow
_LONG_COMMAND = (
    'echo "== load / disk =="; uptime; df -h / | tail -1; echo; '
    'echo "== was the Mac awake at 09:00 on 2026-11-14? (sleep/wake between 08:30 and 09:45) =="; '
    "pmset -g log | grep -E \"^2026-11-14 0(8:[3-5]|9:[0-4])\" | awk '{print $1, $2, $4}'"
)


def _thread(tmp_path: Path, *, title: str, said: str = "") -> tuple[AgentChatService, str]:
    svc = AgentChatService(AgentChatStore(":memory:"), assistant_name=lambda: "Dodaios")
    sid = svc.store.create_session(
        provider="claude", model="m", effort="", cwd=str(tmp_path), title=title, surface="agent"
    ).session_id
    if said:
        svc.store.append_event(sid, make_event("user_message", {"text": said}))
    return svc, sid


def _bridge(svc: AgentChatService) -> TelegramApprovalBridge:
    return TelegramApprovalBridge(
        svc, channel=lambda: _Channel(), config=lambda: _cfg([42]), settings=NotifySettings
    )


def test_a_command_is_shown_whole_in_the_owners_language(tmp_path: Path) -> None:
    svc, sid = _thread(tmp_path, title="Scheduler fix", said=_GERMAN_OWNER)
    bridge = _bridge(svc)
    payload = {
        "name": "Bash",
        "why": "Check load and disk",
        "preview": {
            "class": "shell",
            "irreversible": False,
            "fields": [
                {"key": "command", "value": _LONG_COMMAND},
                {"key": "folder", "value": "Dodaios"},
            ],
        },
    }
    lang = bridge._owner_language(sid, None)  # noqa: SLF001
    assert lang == "de"
    text = bridge._text(payload, lang, sid)  # noqa: SLF001
    lines = text.split("\n")
    assert lines[0] == "Coding-Agent „Scheduler fix“ möchte einen Befehl ausführen."  # i18n-allow
    assert lines[1] == "Warum: Check load and disk"  # i18n-allow
    assert _LONG_COMMAND in text  # not cut after 140 characters
    assert "…" not in text
    assert lines[-1] == "Ordner: Dodaios"  # i18n-allow
    assert "An agent" not in text and "Bash" not in text


def test_a_file_edit_shows_the_path_and_the_changed_lines(tmp_path: Path) -> None:
    svc, sid = _thread(tmp_path, title="Scheduler fix", said=_GERMAN_OWNER)
    path = ".claude/worktrees/scheduler-due-after-sleep/dodaios/tasks/scheduler.py"
    payload = {
        "name": "Edit",
        "preview": {
            "class": "file_write",
            "irreversible": True,
            "fields": [{"key": "path", "value": path}],
            "diff": {
                "path": path, "creates": False, "added": 2, "removed": 1,
                "lines": [
                    {"op": "@", "text": "@@ -1,3 +1,4 @@"},
                    {"op": " ", "text": "import asyncio"},
                    {"op": "-", "text": "MAX_WAIT_S = 3600"},
                    {"op": "+", "text": "MAX_WAIT_S = 60"},
                    {"op": "+", "text": "# wake up often enough to notice a sleep"},
                ],
            },
        },
    }
    text = _bridge(svc)._text(payload, "de", sid)  # noqa: SLF001
    assert text.split("\n") == [
        "Coding-Agent „Scheduler fix“ möchte eine Datei ändern.",  # i18n-allow
        f"Datei: {path}",  # i18n-allow
        "2 Zeilen dazu, 1 entfernt",  # i18n-allow
        "",
        # A code block: Telegram's channel sends it as <pre> (chat_text.telegram_html).
        "```",
        "- MAX_WAIT_S = 3600",
        "+ MAX_WAIT_S = 60",
        "+ # wake up often enough to notice a sleep",
        "```",
        "",
        "Das lässt sich nicht rückgängig machen.",  # i18n-allow
    ]


def test_more_changed_lines_than_a_screenful_point_to_the_app(tmp_path: Path) -> None:
    svc, sid = _thread(tmp_path, title="Big edit")
    rows = [{"op": "+", "text": f"line {i}"} for i in range(30)]
    payload = {
        "name": "Write",
        "preview": {
            "class": "file_write",
            "fields": [{"key": "path", "value": "new.py"}],
            "diff": {"creates": True, "added": 51, "removed": 0, "lines": rows},
        },
    }
    text = _bridge(svc)._text(payload, "en", sid)  # noqa: SLF001
    assert text.startswith('Coding agent "Big edit" wants to create a file.')
    assert "+ line 19" in text and "+ line 20" not in text
    assert text.endswith("… 31 more lines in the app")


def test_the_owners_telegram_language_decides_without_typed_words(tmp_path: Path) -> None:
    svc, sid = _thread(tmp_path, title="t")
    bridge = _bridge(svc)
    assert bridge._owner_language(sid, SimpleNamespace(owner_language="de-DE")) == "de"  # noqa: SLF001


def test_an_agents_own_words_do_not_set_the_language(tmp_path: Path) -> None:
    svc, sid = _thread(tmp_path, title="t", said=_GERMAN_OWNER)
    svc.store.append_event(
        sid,
        make_event("user_message", {
            "text": "Please run the whole test suite and report back in English.",
            "author": {"agent_id": "a1", "name": "Scout"},
        }),
    )
    assert _bridge(svc)._owner_language(sid, None) == "de"  # noqa: SLF001


def test_a_plan_approval_says_so_in_plain_words(tmp_path: Path) -> None:
    svc, sid = _thread(tmp_path, title="Rituals")
    payload = {"name": "ExitPlanMode", "summary": "ExitPlanMode", "source": {"kind": "plan"}}
    text = _bridge(svc)._text(payload, "de", sid)  # noqa: SLF001
    assert text == "Coding-Agent „Rituals“ möchte mit seinem Plan anfangen."  # i18n-allow


def test_a_huge_command_is_cut_with_a_note(tmp_path: Path) -> None:
    svc, sid = _thread(tmp_path, title="t")
    payload = {
        "name": "Bash",
        "preview": {"class": "shell", "fields": [{"key": "command", "value": "x" * 6000}]},
    }
    text = _bridge(svc)._text(payload, "en", sid)  # noqa: SLF001
    assert len(text) < 4096
    assert "(shortened, the whole text is in the app)" in text


def test_the_owners_words_count_however_long_the_thread_is(tmp_path: Path) -> None:
    svc, sid = _thread(tmp_path, title="t", said=_GERMAN_OWNER)
    for i in range(400):  # a busy coding thread: tool events after the person's words
        svc.store.append_event(sid, make_event("tool_result", {"output": f"ok {i} done"}))
    assert _bridge(svc)._owner_language(sid, None) == "de"  # noqa: SLF001
