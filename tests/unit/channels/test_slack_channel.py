"""The owner's own Slack app as a conversation channel, against a stand-in for Slack.

Every test runs the real :class:`SlackChannel` over the network: ``httpx``
to the stand-in's Web API and ``websockets`` to its Socket Mode link
(``tests/fakes/slack_standin.py``). Only the Credential Manager and the
config file are replaced.
"""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

import dodaios.channels.slack as slack_mod
from dodaios.channels.base import ChannelMessage
from dodaios.channels.chat_bridge import ChannelChatBridge
from dodaios.channels.manager import ChannelContext, ChannelManager, ChannelStartError
from dodaios.channels.slack import SlackChannel, _paired_line, plain_from_slack, slack_escape
from dodaios.channels.slack_api import (
    SlackApi,
    SlackSetupError,
    check_keys,
    create_app_url,
    safe_api_base,
)
from dodaios.channels.telegram_approvals import TelegramApprovalBridge, callback_data
from dodaios.core.bus import EventBus
from dodaios.core.config import SlackChannelConfig
from dodaios.notify.settings import NotifySettings
from tests.fakes.slack_standin import FAKE_APP_TOKEN, FAKE_BOT_TOKEN, SlackStandIn

OWNER = "U0OWNER001"
STRANGER = "U0OTHER001"


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    store = {"slack_bot_token": FAKE_BOT_TOKEN, "slack_app_token": FAKE_APP_TOKEN}
    monkeypatch.setattr(slack_mod, "get_secret", lambda key, env_fallback=None: store.get(key))
    return store


@pytest.fixture
def saved_owners(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    saved: list[str] = []
    import dodaios.core.config_writer as writer

    monkeypatch.setattr(writer, "add_slack_allowed_user_id", lambda uid, **_: saved.append(uid))
    return saved


@pytest.fixture
async def slack():
    async with SlackStandIn() as standin:
        yield standin


def _channel(standin: SlackStandIn, **cfg: Any) -> SlackChannel:
    config = SlackChannelConfig(enabled=True, api_base_url=standin.api_base, **cfg)
    channel = SlackChannel(EventBus(), config)
    channel.picture_wait_s = 0.3
    channel.reconnect_delays = (0.05, 0.1)
    return channel


async def _next(channel: SlackChannel, timeout: float = 5.0) -> ChannelMessage:
    agen = channel.messages()
    try:
        return await asyncio.wait_for(agen.__anext__(), timeout)
    finally:
        await agen.aclose()


async def _until(check, timeout: float) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not check():
        assert asyncio.get_running_loop().time() < deadline, "not in time"
        await asyncio.sleep(0.02)


async def _nothing(channel: SlackChannel, wait: float = 0.4) -> bool:
    try:
        await _next(channel, wait)
    except TimeoutError:
        return True
    return False


# --- setup ---------------------------------------------------------------------


def test_the_manifest_link_creates_a_socket_mode_app_people_can_message() -> None:
    url = create_app_url("Nova")
    parts = urlsplit(url)
    assert parts.netloc == "api.slack.com" and parts.path == "/apps"
    query = parse_qs(parts.query)
    assert query["new_app"] == ["1"]
    manifest = json.loads(query["manifest_json"][0])
    assert manifest["display_information"]["name"] == "Nova"
    assert manifest["settings"]["socket_mode_enabled"] is True
    assert manifest["settings"]["interactivity"]["is_enabled"] is True
    assert set(manifest["settings"]["event_subscriptions"]["bot_events"]) == {
        "message.im",
        "app_mention",
    }
    home = manifest["features"]["app_home"]
    assert home["messages_tab_enabled"] is True and home["messages_tab_read_only_enabled"] is False
    scopes = set(manifest["oauth_config"]["scopes"]["bot"])
    assert {"im:history", "app_mentions:read", "chat:write", "files:read"} <= scopes


def test_the_bot_key_goes_only_to_slack_or_this_computer() -> None:
    assert safe_api_base("") == "https://slack.com/api"
    assert safe_api_base("http://127.0.0.1:9/api") == "http://127.0.0.1:9/api"
    assert safe_api_base("https://evil.example/api") == "https://slack.com/api"
    api = SlackApi()
    assert api.may_receive_key("https://files.slack.com/files-pri/T1-F1/x.png")
    assert not api.may_receive_key("https://files.slack.com.evil.example/x.png")
    assert not api.may_receive_key("http://files.slack.com/x.png")


async def test_check_keys_names_what_is_wrong(slack: SlackStandIn) -> None:
    api = SlackApi(slack.api_base)
    try:
        keys = await check_keys(FAKE_BOT_TOKEN, FAKE_APP_TOKEN, api=api)
        assert (keys.team_id, keys.app_id, keys.bot_name) == (slack.team_id, slack.app_id, "nova")
        for bot, app, code in (
            ("xoxp-nope", FAKE_APP_TOKEN, "bot_token_shape"),
            (FAKE_BOT_TOKEN, "xoxb-nope", "app_token_shape"),
            ("xoxb-wrongkey", FAKE_APP_TOKEN, "bot_token_rejected"),
            (FAKE_BOT_TOKEN, "xapp-1-wrong-key", "app_token_rejected"),
        ):
            with pytest.raises(SlackSetupError) as err:
                await check_keys(bot, app, api=api)
            assert err.value.code == code
        slack.socket_mode_enabled = False
        with pytest.raises(SlackSetupError) as err:
            await check_keys(FAKE_BOT_TOKEN, FAKE_APP_TOKEN, api=api)
        assert err.value.code == "socket_mode_off"
        slack.socket_mode_enabled = True
        slack.link_app_id = "A0OTHERAPP"  # the link names another app than the bot's
        with pytest.raises(SlackSetupError) as err:
            await check_keys(FAKE_BOT_TOKEN, FAKE_APP_TOKEN, api=api)
        assert err.value.code == "different_apps"
    finally:
        await api.aclose()


def test_slack_text_is_read_as_written_and_replies_are_escaped() -> None:
    raw = (
        "<@U0NOVABOT1> look at <https://x.dev/a|the page> in <#C1|general> &amp; tell <@U0OTHER001>"
    )
    assert plain_from_slack(raw, bot_user_id="U0NOVABOT1") == (
        "look at the page (https://x.dev/a) in #general & tell @U0OTHER001"
    )
    assert slack_escape("a < b && c > d") == "a &lt; b &amp;&amp; c &gt; d"


# --- pairing and the owner ---------------------------------------------------------


async def test_the_first_direct_message_pairs_the_owner_and_strangers_get_nothing(
    slack: SlackStandIn, keys: dict[str, str], saved_owners: list[str]
) -> None:
    channel = _channel(slack)
    await channel.start()
    try:
        assert channel.active and channel.connected and channel.pairing_open
        await slack.dm(OWNER, "Hello, are you there?")
        msg = await _next(channel)
        assert msg.content == "Hello, are you there?"
        assert msg.metadata["slack_owner"] is True and msg.metadata["slack_dm"] is True
        assert msg.metadata["slack_channel"] == "D0OWNERDM1"
        assert msg.metadata["slack_language"] == "de-DE"
        assert channel.owner_ids == [OWNER] and saved_owners == [OWNER]
        assert not channel.pairing_open
        # One line tells the owner it worked, in their Slack's language.
        posts = await slack.wait_posts(1)
        assert posts[0]["channel"] == "D0OWNERDM1"
        assert posts[0]["text"] == slack_escape(_paired_line("de-DE"))
        assert posts[0]["text"] != slack_escape(_paired_line("en"))

        await slack.dm(STRANGER, "Me too!")
        assert await _nothing(channel)
        await asyncio.sleep(0.2)
        assert len(slack.posts) == 1  # no refusal, nothing at all
        assert saved_owners == [OWNER]
    finally:
        await channel.stop()


async def test_after_the_pairing_window_nobody_can_claim_the_app(
    slack: SlackStandIn, keys: dict[str, str], saved_owners: list[str], caplog
) -> None:
    channel = _channel(slack)
    channel._pairing_closes_at = 0.0  # the window closed long ago
    await channel.start()
    try:
        with caplog.at_level(logging.WARNING, logger="dodaios.channels.slack"):
            await slack.dm(STRANGER, "Mine now")
            assert await _nothing(channel)
        assert channel.owner_ids == [] and saved_owners == []
        assert "pairing refused" in caplog.text
        assert slack.posts == []
    finally:
        await channel.stop()


async def test_a_paired_owner_needs_no_pairing_and_a_mention_is_answered_in_its_thread(
    slack: SlackStandIn, keys: dict[str, str], saved_owners: list[str]
) -> None:
    channel = _channel(
        slack, allowed_user_ids=[OWNER], pair_on_first_dm=False, answer_mentions=True
    )
    await channel.start()
    try:
        ts = await slack.mention(OWNER, "sum up this channel")
        msg = await _next(channel)
        assert msg.content == "sum up this channel"
        assert msg.metadata["slack_dm"] is False and msg.metadata["slack_thread_ts"] == ts
        await channel.send_message(
            ChannelMessage(
                session_id=msg.session_id,
                kind="text",
                content="Done <3 & more",
                metadata=dict(msg.metadata),
            )
        )
        post = (await slack.wait_posts(1))[0]
        assert post["channel"] == "C0GENERAL1" and post["thread_ts"] == ts
        assert post["text"] == "Done &lt;3 &amp; more"

        await slack.mention(STRANGER, "me too")
        assert await _nothing(channel)
        assert saved_owners == []
    finally:
        await channel.stop()


async def test_a_mention_in_a_channel_is_not_answered_unless_the_owner_turned_it_on(
    slack: SlackStandIn, keys: dict[str, str]
) -> None:
    # The answer would come from the owner's private conversation, readable
    # by everyone in the channel: off until the owner chooses it.
    assert SlackChannelConfig().answer_mentions is False
    channel = _channel(slack, allowed_user_ids=[OWNER], pair_on_first_dm=False)
    await channel.start()
    try:
        await slack.mention(OWNER, "what did my doctor say?")
        assert await _nothing(channel)
        await slack.dm(OWNER, "hello")
        assert (await _next(channel)).content == "hello"
    finally:
        await channel.stop()


async def test_every_envelope_is_acknowledged_and_a_resent_event_is_handled_once(
    slack: SlackStandIn, keys: dict[str, str]
) -> None:
    channel = _channel(slack, allowed_user_ids=[OWNER], pair_on_first_dm=False)
    await channel.start()
    try:
        event = {
            "type": "message",
            "channel": "D0OWNERDM1",
            "channel_type": "im",
            "user": OWNER,
            "text": "once",
            "ts": slack.next_ts(),
        }
        await slack.send_event(event)
        await slack.send_event(dict(event))  # Slack's retry after a late ack
        await slack.send_event({**event, "bot_id": "B0NOVABOT1", "ts": slack.next_ts()})
        await slack.send_event({**event, "subtype": "message_changed", "ts": slack.next_ts()})
        await slack.wait_acks(4)
        assert (await _next(channel)).content == "once"
        assert await _nothing(channel)
    finally:
        await channel.stop()


async def test_the_owner_message_continues_the_lead_conversation(
    slack: SlackStandIn, keys: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Through the real chat bridge: the owner's DM is a lead turn, the answer goes back."""
    from dodaios.agent_chat import lead

    asked: list[tuple[str, str]] = []

    async def fake_answer(svc, text, *, source, report, on_card, pictures):
        asked.append((source, text))
        return "All 42 tests pass."

    monkeypatch.setattr(lead, "answer_in_lead", fake_answer)
    channel = _channel(slack, allowed_user_ids=[OWNER], pair_on_first_dm=False)
    await channel.start()
    manager = SimpleNamespace(
        started=lambda: ["slack"],
        get=lambda name: channel,
        add_late_start_listener=lambda fn: None,
        remove_late_start_listener=lambda fn: None,
    )
    bridge = ChannelChatBridge(
        bus=EventBus(),
        manager=manager,
        get_chat_service=lambda: object(),
        phone_allows=lambda kind: True,
    )
    monkeypatch.setattr(ChannelChatBridge, "_answers_open_card", _no_card)
    bridge.start()
    try:
        await slack.dm(OWNER, "Do the tests in trailhead pass?")
        post = (await slack.wait_posts(1))[0]
        assert asked == [("slack", "Do the tests in trailhead pass?")]
        assert post["channel"] == "D0OWNERDM1" and "42 tests" in post["text"]
    finally:
        await bridge.stop()
        await channel.stop()


async def _no_card(self, svc, text) -> bool:
    return False


def test_only_messages_marked_as_the_owner_reach_the_lead() -> None:
    bridge = ChannelChatBridge(
        bus=EventBus(), manager=SimpleNamespace(), get_chat_service=lambda: "svc"
    )
    from uuid import uuid4

    def msg(**meta: Any) -> ChannelMessage:
        return ChannelMessage(session_id=uuid4(), kind="text", content="hi", metadata=meta)

    assert bridge._lead_service("slack", msg(slack_owner=True)) == "svc"
    assert bridge._lead_service("slack", msg(slack_owner="yes")) is None
    assert bridge._lead_service("slack", msg()) is None


# --- pictures ------------------------------------------------------------------------


async def test_a_picture_waits_for_the_words_and_is_fetched_with_the_bot_key(
    slack: SlackStandIn, keys: dict[str, str]
) -> None:
    channel = _channel(slack, allowed_user_ids=[OWNER], pair_on_first_dm=False)
    channel.picture_wait_s = 5.0
    await channel.start()
    try:
        picture = slack.add_file(b"\x89PNG fake", "image/png", "steak.png")
        await slack.dm(OWNER, "", files=[picture])
        assert await _nothing(channel, 0.3)  # held for the words that follow
        await slack.dm(OWNER, "Is this done?")
        msg = await _next(channel)
        assert msg.content == "Is this done?"
        assert [(m.kind, m.name, m.data) for m in msg.media] == [
            ("image", "steak.png", b"\x89PNG fake")
        ]
        assert slack.downloads  # fetched from the file host, with the bot key
    finally:
        await channel.stop()


# --- the link: restart and reconnect -------------------------------------------------


async def test_the_link_comes_back_after_a_refresh_and_after_it_drops(
    slack: SlackStandIn, keys: dict[str, str]
) -> None:
    channel = _channel(slack, allowed_user_ids=[OWNER], pair_on_first_dm=False)
    await channel.start()
    try:
        await slack.disconnect("refresh_requested")
        await slack.wait_link(count=2)
        await slack.dm(OWNER, "after refresh")
        assert (await _next(channel)).content == "after refresh"

        await slack.drop()
        await slack.wait_link(count=3)
        await slack.dm(OWNER, "after drop")
        assert (await _next(channel)).content == "after drop"
        assert channel.connected and channel.last_error == ""
    finally:
        await channel.stop()


async def test_while_slack_is_unreachable_the_link_keeps_trying(
    slack: SlackStandIn, keys: dict[str, str]
) -> None:
    channel = _channel(slack, allowed_user_ids=[OWNER], pair_on_first_dm=False)
    await channel.start()
    try:
        slack.go_offline()
        await slack.drop()
        # A refused connect takes about two seconds on Windows: wait for it,
        # never for a fixed moment.
        await _until(lambda: not channel.connected and bool(channel.last_error), 15.0)
        slack.go_online()
        await slack.wait_link(count=2)
        await slack.dm(OWNER, "back")
        assert (await _next(channel)).content == "back"
    finally:
        await channel.stop()


async def test_socket_mode_turned_off_ends_the_link_for_good(
    slack: SlackStandIn, keys: dict[str, str]
) -> None:
    channel = _channel(slack, allowed_user_ids=[OWNER], pair_on_first_dm=False)
    await channel.start()
    try:
        await slack.disconnect("link_disabled")
        await _until(lambda: bool(channel.last_error), 15.0)
        assert "Socket Mode" in channel.last_error and not channel.connected
        assert slack.links_opened == 1
    finally:
        await channel.stop()


async def test_a_start_without_network_is_tried_again_and_binds_late(
    slack: SlackStandIn, keys: dict[str, str]
) -> None:
    """The fix of PR #1732 holds for Slack: no network at login, up on a retry."""
    slack.go_offline()
    waits: list[float] = []
    gate = asyncio.Event()

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        await gate.wait()

    config = SlackChannelConfig(enabled=True, api_base_url=slack.api_base, allowed_user_ids=[OWNER])
    manager = ChannelManager(
        ChannelContext(bus=EventBus(), config={"slack_config": config}), sleep=sleep
    )
    manager._classes = {"slack": SlackChannel}
    manager._loaded = True
    late: list[str] = []

    async def on_late(name: str) -> None:
        late.append(name)

    manager.add_late_start_listener(on_late)
    with pytest.raises(ChannelStartError) as err:
        await manager.start("slack")
    assert err.value.transient is True
    assert manager.retrying() == ["slack"]
    slack.go_online()
    gate.set()
    await _until(lambda: bool(late), 20.0)
    try:
        assert late == ["slack"] and manager.started() == ["slack"]
        assert manager.get("slack").connected
    finally:
        await manager.stop_all()


async def test_a_revoked_key_or_missing_keys_are_not_tried_again(
    slack: SlackStandIn, keys: dict[str, str]
) -> None:
    slack.bot_revoked = True
    with pytest.raises(ChannelStartError) as err:
        await _channel(slack).start()
    assert err.value.transient is False and "invalid_auth" in str(err.value)
    slack.bot_revoked = False
    slack.app_revoked = True
    with pytest.raises(ChannelStartError) as err:
        await _channel(slack).start()
    assert err.value.transient is False
    keys.clear()
    with pytest.raises(ChannelStartError) as err:
        await _channel(slack).start()
    assert err.value.transient is False and "missing" in str(err.value)


async def test_a_switched_off_channel_starts_idle() -> None:
    channel = SlackChannel(EventBus(), SlackChannelConfig(enabled=False))
    await channel.start()
    assert not channel.active and not channel.pairing_open
    await channel.stop()


async def test_no_key_ever_reaches_the_log(
    slack: SlackStandIn, keys: dict[str, str], saved_owners: list[str], caplog
) -> None:
    caplog.set_level(logging.DEBUG)
    channel = _channel(slack)
    await channel.start()
    try:
        await slack.dm(OWNER, "hi")
        await _next(channel)
        await slack.drop()
        await slack.wait_link(count=2)
    finally:
        await channel.stop()
    slack.bot_revoked = True
    with pytest.raises(ChannelStartError):
        await _channel(slack).start()
    text = caplog.text + " ".join(str(r.args) for r in caplog.records)
    for secret in (FAKE_BOT_TOKEN, FAKE_APP_TOKEN, "ticket="):
        assert secret not in text.replace("ticket=<redacted", "")


# --- approvals -------------------------------------------------------------------------


class _Service:
    def __init__(self) -> None:
        self.listeners: list[Any] = []
        self.resolved: list[tuple[str, str, str]] = []
        self.store = None

    def add_event_listener(self, fn: Any) -> None:
        self.listeners.append(fn)

    def resolve_approval(self, sid: str, approval_id: str, decision: str) -> bool:
        self.resolved.append((sid, approval_id, decision))
        return True

    def emit(self, sid: str, kind: str, payload: dict[str, Any]) -> None:
        for fn in self.listeners:
            fn(sid, {"kind": kind, "payload": payload})


async def test_an_approval_gets_buttons_only_the_owner_can_press(
    slack: SlackStandIn, keys: dict[str, str]
) -> None:
    channel = _channel(slack, allowed_user_ids=[OWNER], pair_on_first_dm=False)
    await channel.start()
    service = _Service()
    bridge = TelegramApprovalBridge(
        service,
        channel=lambda: channel,
        config=lambda: None,
        settings=lambda: NotifySettings(),
        source="slack",
    )
    bridge.install()
    try:
        service.emit(
            "s1",
            "approval_required",
            {
                "approval_id": "ap1",
                "name": "Bash",
                "preview": {
                    "class": "shell",
                    "fields": [{"key": "command", "value": "rm -rf build"}],
                },
            },
        )
        post = (await slack.wait_posts(1))[0]
        assert post["channel"] == "D0OWNERDM1"
        actions = [b for b in post["blocks"] if b["type"] == "actions"][0]["elements"]
        assert [a["action_id"] for a in actions] == [
            callback_data("allow", "ap1"),
            callback_data("deny", "ap1"),
        ]
        assert "rm -rf build" in post["blocks"][0]["text"]["text"]

        await slack.press(STRANGER, callback_data("allow", "ap1"), post)
        await asyncio.sleep(0.3)
        assert service.resolved == [] and slack.updates == []

        await slack.press(OWNER, callback_data("deny", "ap1"), post)
        update = (await slack.wait_updates(1))[0]
        assert service.resolved == [("s1", "ap1", "deny")]
        assert update["ts"] == post["ts"] and "Slack" in update["text"]
        assert all(b["type"] != "actions" for b in update["blocks"])
    finally:
        await channel.stop()


async def test_an_approval_decided_in_the_app_settles_the_slack_message(
    slack: SlackStandIn, keys: dict[str, str]
) -> None:
    channel = _channel(slack, allowed_user_ids=[OWNER], pair_on_first_dm=False)
    await channel.start()
    service = _Service()
    TelegramApprovalBridge(
        service,
        channel=lambda: channel,
        config=lambda: None,
        settings=lambda: NotifySettings(),
        source="slack",
    ).install()
    try:
        service.emit("s1", "approval_required", {"approval_id": "ap2", "name": "Write"})
        post = (await slack.wait_posts(1))[0]
        service.emit("s1", "approval_resolved", {"approval_id": "ap2", "decision": "allow"})
        update = (await slack.wait_updates(1))[0]
        assert update["ts"] == post["ts"] and update["channel"] == "D0OWNERDM1"
    finally:
        await channel.stop()


async def test_slack_approvals_follow_their_own_switch(
    slack: SlackStandIn, keys: dict[str, str]
) -> None:
    channel = _channel(slack, allowed_user_ids=[OWNER], pair_on_first_dm=False)
    await channel.start()
    service = _Service()
    TelegramApprovalBridge(
        service,
        channel=lambda: channel,
        config=lambda: None,
        settings=lambda: NotifySettings(slack_approvals=False),
        source="slack",
    ).install()
    try:
        service.emit("s1", "approval_required", {"approval_id": "ap3", "name": "Bash"})
        await asyncio.sleep(0.3)
        assert slack.posts == []
    finally:
        await channel.stop()


async def test_a_message_in_a_thread_of_the_direct_message_is_answered_there(
    slack: SlackStandIn, keys: dict[str, str]
) -> None:
    channel = _channel(slack, allowed_user_ids=[OWNER], pair_on_first_dm=False)
    await channel.start()
    try:
        await slack.send_event(
            {
                "type": "message",
                "channel": "D0OWNERDM1",
                "channel_type": "im",
                "user": OWNER,
                "text": "and the other one?",
                "ts": slack.next_ts(),
                "thread_ts": "1700000000.000100",
            }
        )
        msg = await _next(channel)
        assert msg.metadata["slack_thread_ts"] == "1700000000.000100"
        assert msg.metadata["slack_dm"] is True
    finally:
        await channel.stop()
