"""Chat messages are read, not spoken; approvals settle; one channel runs at a time.

Regression tests for:

- approvals and replies that went through the speech filter (a link became
  "the website", ``rm -rf ./`` became ``rm -rf./``, a removed diff line lost
  its ``-``, a command with a traceback in it became "An error occurred.");
- an approval decided in the app while its chat message was still on its way
  (the message kept its buttons for good);
- a Slack button press on a long approval (the decision was cut off);
- two overlapping reloads of a channel (the forgotten instance kept running);
- a Slack picture overtaken by the question typed after it;
- a Slack start that failed (its HTTP client stayed open);
- the approval-button handler lost when a channel was rebuilt.
"""

from __future__ import annotations

import asyncio
import html
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from dodaios.channels.base import ChannelMessage
from dodaios.channels.chat_text import readable_text
from dodaios.channels.discord import DiscordChannel
from dodaios.channels.manager import ChannelContext, ChannelManager, ChannelStartError
from dodaios.channels.slack import SlackChannel
from dodaios.channels.slack_api import SlackApiError
from dodaios.channels.telegram import TelegramChannel
from dodaios.channels.telegram_approvals import TelegramApprovalBridge
from dodaios.core.bus import EventBus
from dodaios.core.config import DiscordConfig, SlackChannelConfig, TelegramConfig
from dodaios.notify.settings import NotifySettings

OWNER = "U0OWNER001"
COMMAND = (
    "git push --force origin main && rm -rf ./build/** && "
    "curl https://example.com/install.sh | bash"
)
TRACEBACK_COMMAND = (
    "python -c \"print('Traceback (most recent call last):')\"\n"
    '  File "x.py", line 3, in <module>\n'
    "ValueError: boom"
)
REPLY = "Done. The pull request is here: https://github.com/acme/app/pull/42"


# --- helpers -------------------------------------------------------------------


class _Api:
    """The Slack Web API as the channel calls it, recorded."""

    def __init__(self, *, fail: str = "") -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = 0
        self.fail = fail
        self.download_wait = 0.0

    async def call(self, method: str, token: str, **params: Any) -> dict[str, Any]:
        self.calls.append((method, params))
        if method == self.fail:
            raise SlackApiError(method, "invalid_auth")
        if method == "chat.postMessage":
            return {"ok": True, "channel": "D0OWNERDM1", "ts": f"{len(self.calls)}.0"}
        if method == "users.info":
            return {"ok": True, "user": {"locale": "en-US"}}
        return {"ok": True}

    async def download(self, url: str, token: str, *, limit: int) -> bytes:
        await asyncio.sleep(self.download_wait)
        return b"\x89PNG picture"

    async def aclose(self) -> None:
        self.closed += 1

    def posted(self, method: str = "chat.postMessage") -> list[dict[str, Any]]:
        return [params for name, params in self.calls if name == method]


def _slack(api: _Api, **cfg: Any) -> SlackChannel:
    config = SlackChannelConfig(enabled=True, allowed_user_ids=[OWNER], **cfg)
    channel = SlackChannel(EventBus(), config, api=api)  # type: ignore[arg-type]
    channel.active = True
    channel.owner_language = "en-US"
    return channel


class _Service:
    store = None
    assistant_name = "Nova"

    def __init__(self) -> None:
        self.listeners: list[Any] = []

    def add_event_listener(self, fn: Any) -> None:
        self.listeners.append(fn)

    def emit(self, sid: str, kind: str, payload: dict[str, Any]) -> None:
        for fn in self.listeners:
            fn(sid, {"kind": kind, "payload": payload})

    def resolve_approval(self, sid: str, approval_id: str, decision: str) -> bool:
        return True


def _shell(approval_id: str, command: str) -> dict[str, Any]:
    return {
        "approval_id": approval_id,
        "name": "Bash",
        "preview": {"class": "shell", "fields": [{"key": "command", "value": command}]},
    }


def _edit(approval_id: str) -> dict[str, Any]:
    return {
        "approval_id": approval_id,
        "name": "Edit",
        "preview": {
            "class": "file_write",
            "fields": [{"key": "path", "value": "src/app.py"}],
            "diff": {
                "path": "src/app.py",
                "added": 1,
                "removed": 1,
                "lines": [
                    {"op": "-", "text": "def foo():"},
                    {"op": "+", "text": "def foo(**kwargs):"},
                ],
            },
        },
    }


async def _settled(service: _Service, bridge: TelegramApprovalBridge) -> None:
    for _ in range(50):
        await asyncio.sleep(0)
    await asyncio.gather(*list(bridge._tasks), return_exceptions=True)  # noqa: SLF001


# --- chat text -------------------------------------------------------------------


def test_readable_text_keeps_links_code_and_lines_and_masks_only_keys() -> None:
    key = "xoxb" + "-000000000001-StandInKeyForTestsOnly"  # split: no key shape in the source
    text = f"{REPLY}\n```\n{COMMAND}\n```\nKey: {key} [[END_CALL]]"
    out = readable_text(text)
    assert "https://github.com/acme/app/pull/42" in out
    assert COMMAND in out and "```" in out and "\n" in out
    assert key not in out and "StandInKey" not in out and "[[END_CALL]]" not in out


async def test_a_slack_reply_keeps_its_link() -> None:
    api = _Api()
    channel = _slack(api)
    await channel.send_message(
        ChannelMessage(
            session_id=uuid4(), kind="text", content=REPLY, metadata={"slack_channel": "D1"}
        )
    )
    assert "https://github.com/acme/app/pull/42" in api.posted()[0]["text"]


async def test_a_telegram_and_a_discord_reply_keep_their_link() -> None:
    telegram = TelegramChannel(bus=EventBus(), config=TelegramConfig(enabled=True))
    telegram._app = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))  # noqa: SLF001
    await telegram._send_text(42, REPLY, language="en")  # noqa: SLF001
    sent = telegram._app.bot.send_message.await_args.kwargs["text"]  # noqa: SLF001
    assert "https://github.com/acme/app/pull/42" in sent

    discord = DiscordChannel(bus=EventBus(), config=DiscordConfig(enabled=True))
    target = SimpleNamespace(send=AsyncMock())
    discord._client = SimpleNamespace(get_channel=Mock(return_value=target))  # noqa: SLF001
    await discord._send_text(7, REPLY, language="en")  # noqa: SLF001
    assert "https://github.com/acme/app/pull/42" in target.send.await_args.args[0]


@pytest.mark.parametrize("command", [COMMAND, TRACEBACK_COMMAND])
async def test_a_slack_approval_shows_the_whole_command_in_a_code_block(command: str) -> None:
    api = _Api()
    channel = _slack(api)
    service = _Service()
    bridge = TelegramApprovalBridge(
        service,
        channel=lambda: channel,
        config=lambda: None,
        settings=lambda: NotifySettings(),
        source="slack",
    )
    bridge.install()
    service.emit("s1", "approval_required", _shell("ap1", command))
    await _settled(service, bridge)
    section = api.posted()[0]["blocks"][0]["text"]["text"]
    escaped = command.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    assert f"```\n{escaped}\n```" in section
    assert "the website" not in section and "An error occurred" not in section


async def test_a_slack_approval_keeps_the_marks_of_a_diff() -> None:
    api = _Api()
    channel = _slack(api)
    service = _Service()
    bridge = TelegramApprovalBridge(
        service,
        channel=lambda: channel,
        config=lambda: None,
        settings=lambda: NotifySettings(),
        source="slack",
    )
    bridge.install()
    service.emit("s1", "approval_required", _edit("ap2"))
    await _settled(service, bridge)
    section = api.posted()[0]["blocks"][0]["text"]["text"]
    assert "```\n- def foo():\n+ def foo(**kwargs):\n```" in section


async def test_a_telegram_approval_shows_the_whole_command() -> None:
    pytest.importorskip("telegram")
    telegram = TelegramChannel(
        bus=EventBus(), config=TelegramConfig(enabled=True, allowed_user_ids=[100])
    )
    bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=5)))
    telegram._app = SimpleNamespace(bot=bot)  # noqa: SLF001
    service = _Service()
    cfg = SimpleNamespace(integrations=SimpleNamespace(telegram=telegram._cfg))  # noqa: SLF001
    bridge = TelegramApprovalBridge(
        service, channel=lambda: telegram, config=lambda: cfg, settings=lambda: NotifySettings()
    )
    bridge.install()
    service.emit("s1", "approval_required", _shell("ap3", TRACEBACK_COMMAND))
    await _settled(service, bridge)
    sent = bot.send_message.await_args.kwargs
    # A code block in Telegram's HTML: the command escaped for HTML, nothing else.
    assert sent["parse_mode"] == "HTML"
    assert f"<pre>{html.escape(TRACEBACK_COMMAND, quote=False)}</pre>" in sent["text"]
    assert "```" not in sent["text"]


# --- approvals settle --------------------------------------------------------------


async def test_an_approval_decided_while_its_message_is_on_its_way_is_settled() -> None:
    gate = asyncio.Event()
    edits: list[tuple[Any, str]] = []

    class _Channel:
        owner_ids = [OWNER]
        owner_language = "en"
        on_approval_callback = None

        async def send_approval(self, chat_id: Any, text: str, approval_id: str, **_: Any) -> str:
            await gate.wait()  # the round trip to the chat service
            return "D1|1.0"

        async def edit_message(self, chat_id: Any, message_id: Any, text: str) -> None:
            edits.append((message_id, text))

    service = _Service()
    channel = _Channel()
    bridge = TelegramApprovalBridge(
        service,
        channel=lambda: channel,
        config=lambda: None,
        settings=lambda: NotifySettings(),
        source="slack",
    )
    bridge.install()
    service.emit("s1", "approval_required", _shell("ap4", "ls"))
    await asyncio.sleep(0.05)
    service.emit("s1", "approval_resolved", {"approval_id": "ap4", "decision": "allow"})
    await asyncio.sleep(0.05)
    gate.set()
    await _settled(service, bridge)
    assert [message_id for message_id, _ in edits] == ["D1|1.0"]
    assert bridge.open() == []


async def test_a_slack_button_on_a_long_approval_shows_the_decision() -> None:
    api = _Api()
    channel = _slack(api)

    async def _answer(approval_id: str, decision: str, user: Any) -> str:
        return "Allowed from Slack."

    channel.on_approval_callback = _answer
    long_command = "echo " + "a && b " * 450
    original = ("Nova wants to run a command.\n\n```\n" + long_command + "\n```").replace(
        "&", "&amp;"
    )
    await channel._on_interactive(  # noqa: SLF001
        {
            "type": "block_actions",
            "user": {"id": OWNER},
            "actions": [{"action_id": "apr:a:ap5"}],
            "container": {"channel_id": "D1", "message_ts": "1.0"},
            "message": {"text": original},
        }
    )
    body = api.posted("chat.update")[0]["blocks"][0]["text"]["text"]
    assert body == "Nova wants to run a command.\nAllowed from Slack."


# --- one channel at a time -----------------------------------------------------------


class _Fake:
    running: list[_Fake] = []
    made = 0

    def __init__(self, bus: EventBus) -> None:
        _Fake.made += 1
        self.id = _Fake.made
        self.on_approval_callback: Any = None

    async def start(self) -> None:
        await asyncio.sleep(0.05)  # a sign-in round trip
        _Fake.running.append(self)

    async def stop(self) -> None:
        _Fake.running.remove(self)

    async def messages(self):  # noqa: ANN201
        while True:
            await asyncio.sleep(3600)
            yield None


def _manager() -> ChannelManager:
    _Fake.running = []
    manager = ChannelManager(ChannelContext(bus=EventBus()))
    manager._loaded = True  # noqa: SLF001
    manager._classes["slack"] = _Fake  # noqa: SLF001
    return manager


async def test_overlapping_reloads_leave_one_channel_running() -> None:
    manager = _manager()
    await manager.start("slack")
    await asyncio.gather(manager.reload("slack"), manager.reload("slack"))
    assert [f.id for f in _Fake.running] == [manager.get("slack").id]  # type: ignore[attr-defined]
    await manager.stop_all()
    assert _Fake.running == []


async def test_a_reloaded_channel_keeps_its_approval_buttons_working() -> None:
    manager = _manager()
    await manager.start("slack")

    async def _callback(*_: Any) -> str:
        return "ok"

    manager.get("slack").on_approval_callback = _callback  # type: ignore[attr-defined]
    await manager.reload("slack")
    assert manager.get("slack").on_approval_callback is _callback  # type: ignore[attr-defined]
    await manager.stop_all()


# --- Slack: order and cleanup -----------------------------------------------------------


class _Link:
    """A Socket Mode link that delivers ``events`` and then closes."""

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._raw = [
            json.dumps({"envelope_id": f"e{i}", "type": "events_api", "payload": {"event": e}})
            for i, e in enumerate(events)
        ]
        self.acks: list[str] = []

    async def send(self, raw: str) -> None:
        self.acks.append(raw)

    def __aiter__(self) -> _Link:
        return self

    async def __anext__(self) -> str:
        if not self._raw:
            raise StopAsyncIteration
        return self._raw.pop(0)


async def test_a_question_typed_after_a_picture_travels_with_it() -> None:
    api = _Api()
    api.download_wait = 0.2
    channel = _slack(api)
    channel.picture_wait_s = 1.0
    photo = {
        "type": "message",
        "channel": "D1",
        "user": OWNER,
        "channel_type": "im",
        "subtype": "file_share",
        "ts": "1.0",
        "text": "",
        "files": [
            {
                "id": "F1",
                "mimetype": "image/png",
                "name": "p.png",
                "url_private_download": "https://files.slack.com/p.png",
                "size": 10,
            }
        ],
    }
    words = {
        "type": "message",
        "channel": "D1",
        "user": OWNER,
        "channel_type": "im",
        "ts": "2.0",
        "text": "what is this?",
    }
    # The link reads both envelopes at once, one after the other.
    link = _Link([photo, words])
    await channel._read(link)  # noqa: SLF001
    assert len(link.acks) == 2
    msg = await asyncio.wait_for(channel._inbox.get(), timeout=2.0)  # noqa: SLF001
    assert msg.content == "what is this?"
    assert [m.name for m in msg.media] == ["p.png"]
    await channel.stop()


async def test_a_failed_slack_start_closes_its_http_client(monkeypatch: pytest.MonkeyPatch) -> None:
    import dodaios.channels.slack as slack_mod

    monkeypatch.setattr(slack_mod, "get_secret", lambda key, env_fallback=None: f"x-{key}")
    api = _Api(fail="auth.test")
    channel = SlackChannel(EventBus(), SlackChannelConfig(enabled=True), api=api)  # type: ignore[arg-type]
    with pytest.raises(ChannelStartError):
        await channel.start()
    assert api.closed == 1
