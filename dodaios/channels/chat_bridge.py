"""Bridge ChannelAdapter inboxes into the normal Jarvis chat event path."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from dodaios.channels.base import ChannelMessage
from dodaios.channels.manager import ChannelManager
from dodaios.core.bus import EventBus
from dodaios.core.events import MessageSent
from dodaios.core.protocols import ChannelAdapter

log = logging.getLogger(__name__)


class ChannelChatBridge:
    """Consumes channel inboxes and publishes ``MessageSent(role="user")``.

    The web UI already enters the chat path through ``WebServer._route_incoming``.
    External channels such as Telegram only expose an async ``messages()``
    iterator, so they need this small runtime bridge. The original
    ``ChannelMessage.trace_id`` is preserved; response channels use that id to
    route the assistant reply back to the originating chat.
    """

    def __init__(
        self,
        *,
        bus: EventBus,
        manager: ChannelManager,
        get_chat_service: Callable[[], Any | None] | None = None,
    ) -> None:
        self._bus = bus
        self._manager = manager
        self._get_chat_service = get_chat_service
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._replies: set[asyncio.Task[None]] = set()

    def start(self) -> None:
        for name in self._manager.started():
            if name in self._tasks:
                continue
            try:
                channel = self._manager.get(name)
            except Exception as exc:  # noqa: BLE001
                log.warning("ChannelChatBridge could not get '%s': %s", name, exc)
                continue
            self._tasks[name] = asyncio.create_task(
                self._consume(name, channel),
                name=f"channel-chat-bridge:{name}",
            )
        log.info("ChannelChatBridge started for channels: %s", sorted(self._tasks))

    async def stop(self) -> None:
        if not self._tasks:
            return
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        log.info("ChannelChatBridge gestoppt")

    async def refresh(self, name: str) -> None:
        """Rebind the consumer for ``name`` to the manager's current instance.

        A live reload (marketplace connect) drops the old channel instance and
        builds a new one. The old consumer task is still iterating the old,
        now-detached ``messages()`` iterator, so inbound messages on the new
        instance would never reach the bus. This cancels the stale consumer and
        spawns a fresh one bound to ``manager.get(name)``. Idempotent and
        no-op-safe if the channel is unknown.
        """
        task = self._tasks.pop(name, None)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        try:
            channel = self._manager.get(name)
        except Exception as exc:  # noqa: BLE001
            log.warning("ChannelChatBridge.refresh could not get '%s': %s", name, exc)
            return
        self._tasks[name] = asyncio.create_task(
            self._consume(name, channel),
            name=f"channel-chat-bridge:{name}",
        )
        log.info("ChannelChatBridge consumer rebound for '%s'", name)

    async def _consume(self, name: str, channel: ChannelAdapter) -> None:
        try:
            async for msg in channel.messages():
                await self._handle_message(name, msg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("ChannelChatBridge consumer for '%s' stopped: %s", name, exc)

    async def _handle_message(self, name: str, msg: ChannelMessage) -> None:
        if msg.kind not in {"text", "voice"}:
            return
        text = (msg.content or "").strip()
        if not text:
            return
        svc = self._lead_service(name, msg)
        if svc is not None:
            # The owner's own private chat continues the assistant's one
            # conversation; the reply goes back to the same chat.
            task = asyncio.create_task(
                self._answer_in_lead(svc, name, msg, text), name=f"channel-lead:{name}"
            )
            self._replies.add(task)
            task.add_done_callback(self._replies.discard)
            return
        await self._bus.publish(
            MessageSent(
                trace_id=msg.trace_id,
                thread_id=_thread_id_for(name, msg),
                role="user",
                text=text,
                source_layer=f"channel.{name}",
            )
        )

    def _lead_service(self, name: str, msg: ChannelMessage) -> Any | None:
        """The chat service when this message belongs in the lead conversation.

        Only the owner's private chats qualify: a Telegram private chat, a
        Discord direct message or the owner's own WhatsApp chat (the channel
        admits nobody else). A friend (``friend_id``), a group chat or a
        server channel never reaches the owner's personal conversation, and
        other channels keep their own threads.
        """
        if self._get_chat_service is None or name not in ("telegram", "discord", "whatsapp"):
            return None
        if _metadata_value(msg.metadata, "friend_id"):
            return None
        if name == "telegram":
            try:
                if int(_metadata_value(msg.metadata, "telegram_chat_id") or "0") <= 0:
                    return None
            except ValueError:  # an unreadable chat id is not the owner's private chat
                return None
        elif name == "whatsapp":
            if msg.metadata.get("whatsapp_private") is not True:
                return None
        elif msg.metadata.get("discord_dm") is not True:
            return None
        try:
            return self._get_chat_service()
        except Exception:  # noqa: BLE001 — fall back to the classic chat path
            return None

    async def _answer_in_lead(self, svc: Any, name: str, msg: ChannelMessage, text: str) -> None:
        from dodaios.agent_chat.lead import answer_in_lead

        try:
            answer = await answer_in_lead(svc, text, source=name)
        except Exception as exc:  # noqa: BLE001
            log.warning("ChannelChatBridge: lead turn for '%s' failed: %s", name, exc)
            answer = ""
        if not answer:
            return
        try:
            channel = self._manager.get(name)
            await channel.send_message(
                ChannelMessage(
                    session_id=msg.session_id,
                    kind="text",
                    content=answer,
                    trace_id=msg.trace_id,
                    metadata=dict(msg.metadata),
                )
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("ChannelChatBridge: reply to '%s' failed: %s", name, exc)


def _thread_id_for(name: str, msg: ChannelMessage) -> str:
    chat_id = _metadata_value(msg.metadata, "telegram_chat_id")
    if chat_id:
        return f"telegram:{chat_id}"
    jid = _metadata_value(msg.metadata, "whatsapp_jid")
    if jid:
        return f"whatsapp:{jid}"
    channel_session = _metadata_value(msg.metadata, "channel_session_id")
    if channel_session:
        return f"{name}:{channel_session}"
    return f"{name}:{msg.session_id}"


def _metadata_value(metadata: dict[str, Any], key: str) -> str:
    value = metadata.get(key)
    if value is None:
        return ""
    text = str(value).strip()
    return text
