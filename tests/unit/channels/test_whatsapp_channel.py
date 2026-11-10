"""The WhatsApp channel is off by default, answers only its owner, and needs a bridge."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from dodaios.channels.base import ChannelMessage
from dodaios.channels.chat_bridge import ChannelChatBridge, _thread_id_for
from dodaios.channels.manager import ChannelContext, ChannelStartError
from dodaios.channels.whatsapp import (
    BridgeTransport,
    WhatsAppChannel,
    WhatsAppConfig,
    load_whatsapp_config,
    save_whatsapp_config,
    whatsapp_status,
)
from dodaios.core.bus import EventBus
from dodaios.core.http_pool import HttpClientPool


class _FakeTransport:
    def __init__(self) -> None:
        self.on_message = None
        self.sent: list[tuple[str, str]] = []
        self.stopped = False

    async def start(self, on_message) -> None:
        self.on_message = on_message

    async def stop(self) -> None:
        self.stopped = True

    async def send_text(self, jid: str, text: str) -> None:
        self.sent.append((jid, text))

    def status(self) -> dict[str, Any]:
        return {"linked": True, "me": "me@s.whatsapp.net"}


async def _next(channel: WhatsAppChannel) -> ChannelMessage:
    iterator = channel.messages()
    return await asyncio.wait_for(iterator.__anext__(), timeout=1.0)


@pytest.mark.asyncio
async def test_disabled_channel_starts_silently_without_a_transport() -> None:
    channel = WhatsAppChannel(EventBus(), WhatsAppConfig(enabled=False))
    await channel.start()
    assert channel.status()["enabled"] is False and channel.status()["running"] is False
    await channel.stop()


@pytest.mark.asyncio
async def test_first_private_sender_becomes_the_owner_and_others_are_dropped(tmp_path) -> None:
    transport = _FakeTransport()
    channel = WhatsAppChannel(
        EventBus(),
        WhatsAppConfig(enabled=True),
        transport,
        config_path=tmp_path / "whatsapp.json",
    )
    await channel.start()
    assert transport.on_message is not None
    owner = "4915@s.whatsapp.net"
    await transport.on_message({"id": "1", "from": owner, "text": "Hi", "private": True})
    first = await _next(channel)
    assert first.content == "Hi" and first.metadata["whatsapp_private"] is True
    assert channel.config.owner_jid == "4915@s.whatsapp.net"
    assert load_whatsapp_config(tmp_path / "whatsapp.json").owner_jid == "4915@s.whatsapp.net"
    # A stranger, a group and an empty message never reach the inbox.
    stranger = "4999@s.whatsapp.net"
    await transport.on_message({"id": "2", "from": stranger, "text": "Yo", "private": True})
    await transport.on_message({"id": "3", "from": owner, "text": "grp", "private": False})
    await transport.on_message({"id": "4", "from": owner, "text": "  ", "private": True})
    assert channel._inbox.empty()
    assert channel.status()["dropped"] == 3
    # Replies go only to the owner's chat.
    await channel.send_message(
        ChannelMessage(session_id=first.session_id, kind="text", content="Reply",
                       metadata=dict(first.metadata))
    )
    await channel.send_message(
        ChannelMessage(session_id=first.session_id, kind="text", content="Leak",
                       metadata={"whatsapp_jid": "4999@s.whatsapp.net"})
    )
    assert transport.sent == [("4915@s.whatsapp.net", "Reply")]
    await channel.stop()
    assert transport.stopped


@pytest.mark.asyncio
async def test_owner_claim_closes_after_the_pairing_window(tmp_path) -> None:
    transport = _FakeTransport()
    channel = WhatsAppChannel(
        EventBus(), WhatsAppConfig(enabled=True), transport, config_path=tmp_path / "w.json"
    )
    await channel.start()
    channel._pairing_closes_at = 0.0
    await transport.on_message({"from": "4915@s.whatsapp.net", "text": "Hi", "private": True})
    assert channel._inbox.empty() and channel.config.owner_jid == ""


@pytest.mark.asyncio
async def test_bridge_transport_reports_a_missing_bridge_honestly() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    pool = HttpClientPool(transport=httpx.MockTransport(handler))
    transport = BridgeTransport("http://127.0.0.1:3737", pool=pool)
    with pytest.raises(ChannelStartError) as refused:
        await transport.start(lambda _m: asyncio.sleep(0))
    assert "bridge not reachable" in str(refused.value)
    assert "ConnectError" in str(refused.value)
    await pool.aclose()


@pytest.mark.asyncio
async def test_bridge_transport_polls_and_sends() -> None:
    calls: list[str] = []
    delivered: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/status":
            return httpx.Response(200, json={"linked": True, "me": "me@s.whatsapp.net"})
        if request.url.path == "/messages":
            if len(calls) > 3:
                raise httpx.ReadTimeout("quiet", request=request)
            inbound = [{"from": "a", "text": "b", "private": True}]
            return httpx.Response(200, json={"messages": inbound})
        return httpx.Response(200, json={"ok": True})

    pool = HttpClientPool(transport=httpx.MockTransport(handler))
    transport = BridgeTransport("http://127.0.0.1:3737", pool=pool)

    async def on_message(item: dict[str, Any]) -> None:
        delivered.append(item)

    await transport.start(on_message)
    await asyncio.sleep(0.05)
    await transport.send_text("a", "hello")
    await transport.stop()
    assert transport.status()["linked"] is True
    assert delivered and delivered[0]["text"] == "b"
    assert "POST /send" in calls
    await pool.aclose()


def test_config_round_trip_and_env_switch(tmp_path, monkeypatch) -> None:
    path = tmp_path / "whatsapp.json"
    assert load_whatsapp_config(path).enabled is False
    save_whatsapp_config(WhatsAppConfig(enabled=True, owner_jid="x@s.whatsapp.net"), path)
    assert load_whatsapp_config(path).owner_jid == "x@s.whatsapp.net"
    monkeypatch.setenv("DODAIOS_WHATSAPP_ENABLED", "0")
    assert load_whatsapp_config(path).enabled is False
    monkeypatch.setenv("DODAIOS_WHATSAPP_ENABLED", "1")
    assert load_whatsapp_config(tmp_path / "missing.json").enabled is True
    path.write_text("{broken", encoding="utf-8")
    monkeypatch.delenv("DODAIOS_WHATSAPP_ENABLED")
    assert load_whatsapp_config(path) == WhatsAppConfig()


def test_status_without_a_manager_and_with_one() -> None:
    config = WhatsAppConfig(enabled=True)
    plain = whatsapp_status(config, None)
    assert plain["enabled"] is True and plain["running"] is False and plain["missing"] == "bridge"

    class _Manager:
        def start_errors(self):
            return {"whatsapp": "ChannelStartError: WhatsApp bridge not reachable"}

        def started(self):
            return []

    class _State:
        channel_manager = _Manager()

    with_manager = whatsapp_status(config, _State())
    assert "bridge not reachable" in with_manager["start_error"]


def test_from_context_reads_the_config_slot() -> None:
    ctx = ChannelContext(bus=EventBus(), config={"whatsapp_config": WhatsAppConfig(enabled=True)})
    channel = WhatsAppChannel.from_context(ctx)
    assert channel.config.enabled is True
    assert channel.name == "whatsapp"


def test_chat_bridge_routes_only_the_owners_private_chat_into_the_lead() -> None:
    bridge = ChannelChatBridge(bus=EventBus(), manager=None, get_chat_service=lambda: "svc")  # type: ignore[arg-type]
    private = ChannelMessage(
        session_id=__import__("uuid").uuid4(), kind="text", content="hi",
        metadata={"whatsapp_jid": "4915@s.whatsapp.net", "whatsapp_private": True},
    )
    assert bridge._lead_service("whatsapp", private) == "svc"
    group = ChannelMessage(
        session_id=private.session_id, kind="text", content="hi",
        metadata={"whatsapp_jid": "grp", "whatsapp_private": False},
    )
    assert bridge._lead_service("whatsapp", group) is None
    assert _thread_id_for("whatsapp", private) == "whatsapp:4915@s.whatsapp.net"
