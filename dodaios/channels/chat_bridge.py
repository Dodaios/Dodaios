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
            if await self._answers_open_card(svc, text):
                return  # the waiting turn goes on and answers this chat itself
            # The owner's own private chat continues the assistant's one
            # conversation; the reply goes back to the same chat.
            task = asyncio.create_task(
                self._answer_in_lead(svc, name, msg, text), name=f"channel-lead:{name}"
            )
            self._replies.add(task)
            task.add_done_callback(self._replies.discard)
            return
        # Not the owner's private chat: a trigger candidate for the lead's event
        # intake (a no-op unless the owner turned the channel source on).
        from dodaios.lead_triggers.wiring import on_channel_message

        await on_channel_message(
            name,
            _thread_id_for(name, msg),
            _metadata_value(msg.metadata, "friend_id") or _metadata_value(msg.metadata, "sender"),
            text,
        )
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
        from dodaios.agent_chat.lead import LeadCard, LeadReport, answer_in_lead

        language = _language_of(text)
        report = LeadReport()

        async def on_card(card: LeadCard) -> None:
            await self._reply(name, msg, _card_line(card, language))

        try:
            answer = await answer_in_lead(svc, text, source=name, report=report, on_card=on_card)
        except Exception as exc:  # noqa: BLE001
            log.warning("ChannelChatBridge: lead turn for '%s' failed: %s", name, exc)
            answer = ""
            report.status = "error"
        # The owner always gets an answer: the reply, or one honest line.
        await self._reply(name, msg, answer or _failure_line(report.status, language))

    async def _reply(self, name: str, msg: ChannelMessage, content: str) -> None:
        try:
            channel = self._manager.get(name)
            await channel.send_message(
                ChannelMessage(
                    session_id=msg.session_id,
                    kind="text",
                    content=content,
                    trace_id=msg.trace_id,
                    metadata=dict(msg.metadata),
                )
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("ChannelChatBridge: reply to '%s' failed: %s", name, exc)

    async def _answers_open_card(self, svc: Any, text: str) -> bool:
        """Whether this message answered a card the lead's turn waits on.

        A plain yes / no settles the oldest open approval; any other message
        answers an open question card. Anything else is a new message.
        """
        try:
            from dodaios.agent_chat.lead import lead_session, open_approval_ids

            session = lead_session(svc)
            if session is None:
                return False
            sid = session.session_id
            decision = _decision_of(text)
            approvals = open_approval_ids(svc, sid) if decision else []
            if approvals:
                return bool(svc.resolve_approval(sid, approvals[0], decision))
            if svc.pending_questions(sid):
                outcome = await svc.answer_by_message(sid, text)
                return bool(outcome.get("consumed"))
        except Exception as exc:  # noqa: BLE001 — a card not answerable here is answered in the app
            log.debug("ChannelChatBridge: card answer not applied: %s", exc)
        return False


# Input vocabulary (closed lists, like the screen-reference words): a message
# that is only one of these answers an open approval card.
_YES: frozenset[str] = frozenset(
    {"yes", "y", "ok", "okay", "allow", "approve", "approved", "sure", "go",  # i18n-allow
     "ja", "j", "klar", "erlaubt", "genehmigt", "freigeben",  # i18n-allow
     "si", "sí", "sim", "claro", "permitir"}  # i18n-allow
)
_NO: frozenset[str] = frozenset(
    {"no", "n", "nope", "deny", "denied", "stop", "cancel",  # i18n-allow
     "nein", "ablehnen", "abbrechen",  # i18n-allow
     "nao", "não", "cancelar", "negar"}  # i18n-allow
)

_LANGS: tuple[str, ...] = ("en", "de", "es", "pt")

# Short lines for the owner's phone. The reason is generic on purpose: a
# provider's own text never reaches a chat.
_FAILURES: dict[str, dict[str, str]] = {
    "en": {
        "error": "I couldn't finish that: the turn hit an error. It's in the app.",
        "cancelled": "I couldn't finish that: the turn was stopped. It's in the app.",
        "timeout": "I couldn't finish that: it is taking too long. It continues in the app.",
        "empty": "I couldn't finish that: the turn ended without an answer. It's in the app.",
        "not_sent": "I couldn't start that: the message did not go through. It's in the app.",
        "no_session": "I couldn't reach the conversation. Please try again in the app.",
    },
    "de": {  # i18n-allow: localized phone lines
        "error": "Das habe ich nicht geschafft: Es gab einen Fehler. Es steht in der App.",  # i18n-allow  # noqa: E501
        "cancelled": "Das habe ich nicht geschafft: Ich wurde gestoppt. Es steht in der App.",  # i18n-allow  # noqa: E501
        "timeout": "Das habe ich nicht geschafft: Es dauert zu lange. Es läuft in der App weiter.",  # i18n-allow  # noqa: E501
        "empty": "Das habe ich nicht geschafft: Es kam keine Antwort. Es steht in der App.",  # i18n-allow  # noqa: E501
        "not_sent": "Das konnte ich nicht starten: Nachricht nicht angekommen. Es steht in der App.",  # i18n-allow  # noqa: E501
        "no_session": "Ich komme gerade nicht an die Unterhaltung. Bitte versuch es in der App.",  # i18n-allow  # noqa: E501
    },
    "es": {  # i18n-allow: localized phone lines
        "error": "No pude terminarlo: hubo un error. Está en la app.",
        "cancelled": "No pude terminarlo: se detuvo. Está en la app.",
        "timeout": "No pude terminarlo: tarda demasiado. Sigue en la app.",
        "empty": "No pude terminarlo: terminó sin respuesta. Está en la app.",
        "not_sent": "No pude empezarlo: el mensaje no se envió. Está en la app.",
        "no_session": "No llego a la conversación. Inténtalo en la app.",
    },
    "pt": {  # i18n-allow: localized phone lines
        "error": "Não consegui terminar: houve um erro. Está na app.",
        "cancelled": "Não consegui terminar: foi parado. Está na app.",
        "timeout": "Não consegui terminar: demora demais. Continua na app.",
        "empty": "Não consegui terminar: acabou sem resposta. Está na app.",
        "not_sent": "Não consegui começar: a mensagem não seguiu. Está na app.",
        "no_session": "Não consigo chegar à conversa. Tenta na app.",
    },
}
_CARD_APPROVAL: dict[str, str] = {
    "en": "Needs your OK: {summary}\nReply yes or no.",
    "de": "Ich brauche dein OK: {summary}\nAntworte mit ja oder nein.",  # i18n-allow
    "es": "Necesito tu visto bueno: {summary}\nResponde sí o no.",  # i18n-allow
    "pt": "Preciso da tua autorização: {summary}\nResponde sim ou não.",  # i18n-allow
}
_CARD_QUESTION: dict[str, str] = {
    "en": "A question for you: {summary}{options}\nReply with your answer.",
    "de": "Eine Frage an dich: {summary}{options}\nAntworte einfach hier.",  # i18n-allow
    "es": "Una pregunta para ti: {summary}{options}\nResponde aquí.",  # i18n-allow
    "pt": "Uma pergunta para ti: {summary}{options}\nResponde aqui.",  # i18n-allow
}
_OPTIONS: dict[str, str] = {"en": "Options", "de": "Optionen", "es": "Opciones", "pt": "Opções"}


def _language_of(text: str) -> str:
    """The language of the owner's message, English when it cannot be told."""
    try:
        from dodaios.core.turn_language import resolve_turn_language

        code = resolve_turn_language(None, text)
    except Exception:  # noqa: BLE001
        log.debug("ChannelChatBridge: reply language not detected", exc_info=True)
        return "en"
    return code if code in _LANGS else "en"


def _failure_line(status: str, language: str) -> str:
    lines = _FAILURES.get(language) or _FAILURES["en"]
    return lines.get(status) or lines["empty"]


def _card_line(card: Any, language: str) -> str:
    summary = card.summary or ""
    if card.kind == "approval":
        return _CARD_APPROVAL.get(language, _CARD_APPROVAL["en"]).format(summary=summary)
    options = ""
    if card.options:
        options = f"\n{_OPTIONS.get(language, 'Options')}: " + ", ".join(card.options)
    return _CARD_QUESTION.get(language, _CARD_QUESTION["en"]).format(
        summary=summary, options=options
    )


def _decision_of(text: str) -> str:
    """``allow`` / ``deny`` for a message that is only a yes or a no, else ""."""
    word = "".join(ch for ch in text.lower() if ch.isalpha() or ch.isspace()).strip()
    if word in _YES:
        return "allow"
    if word in _NO:
        return "deny"
    return ""


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
