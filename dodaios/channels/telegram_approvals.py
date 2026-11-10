"""Approvals in the owner's Telegram chat: Allow / Deny buttons.

When a tool call waits for the person's approval (an ``approval_required``
event in a chat) and the owner's Telegram is connected, the request also goes
to their private chat with two inline buttons. A button answers the very same
approval the app's card is waiting on (``AgentChatService.resolve_approval``);
a decision taken in the app settles the Telegram message instead. Only the
owner (the first allowed private user, or the configured chat) can press.

The bridge listens on the chat service's event listener, so it sees every
runner the chat has. It never awaits inside the listener: it schedules.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from dodaios.notify.reminders import notification_language, phrase
from dodaios.notify.settings import NotifySettings, load_settings

log = logging.getLogger(__name__)

#: Callback-data prefix of the buttons (Telegram allows 64 bytes).
CALLBACK_PREFIX: Final[str] = "apr:"
DECISIONS: Final[dict[str, str]] = {"a": "allow", "d": "deny"}


@dataclass(slots=True)
class Sent:
    session_id: str
    chat_id: int
    message_id: int | None
    text: str


def owner_chat_id(cfg: Any) -> int | None:
    """The owner's private chat: the first allowed user, else the configured chat id."""
    telegram = getattr(getattr(cfg, "integrations", None), "telegram", None)
    if telegram is None:
        return None
    users = list(getattr(telegram, "allowed_user_ids", None) or [])
    if users:
        try:
            return int(users[0])
        except (TypeError, ValueError):  # an unreadable id means no owner is known
            return None
    chat = str(getattr(telegram, "chat_id", "") or "").strip()
    try:
        return int(chat) if chat else None
    except ValueError:  # an unreadable id means no owner is known
        return None


def callback_data(decision: str, approval_id: str) -> str:
    short = "a" if decision == "allow" else "d"
    return f"{CALLBACK_PREFIX}{short}:{approval_id}"


def parse_callback(data: str) -> tuple[str, str] | None:
    """``(decision, approval_id)`` for a button press, ``None`` for anything else."""
    if not data or not data.startswith(CALLBACK_PREFIX):
        return None
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[1] not in DECISIONS or not parts[2]:
        return None
    return DECISIONS[parts[1]], parts[2]


class TelegramApprovalBridge:
    def __init__(
        self,
        service: Any,
        *,
        channel: Callable[[], Any | None],
        config: Callable[[], Any],
        settings: Callable[[], NotifySettings] = load_settings,
    ) -> None:
        self._service = service
        self._channel = channel
        self._config = config
        self._settings = settings
        self._sent: dict[str, Sent] = {}
        self._from_telegram: set[str] = set()
        self._tasks: set[asyncio.Task[Any]] = set()

    def install(self) -> None:
        self._service.add_event_listener(self.listener)

    # ------------------------------------------------------------ listening

    def listener(self, session_id: str, event: dict[str, Any]) -> None:
        kind = event.get("kind")
        if kind not in ("approval_required", "approval_resolved"):
            return
        payload = dict(event.get("payload") or {})
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # emitted off the loop: nothing to send from here
            return
        if kind == "approval_required":
            coro = self._send(session_id, payload)
        else:
            coro = self._settle(str(payload.get("approval_id") or ""), payload)
        task = loop.create_task(coro, name="telegram-approval")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _send(self, session_id: str, payload: dict[str, Any]) -> None:
        try:
            if not self._settings().telegram_approvals:
                return
            if _unattended(session_id):
                return
            approval_id = str(payload.get("approval_id") or "")
            if not approval_id or approval_id in self._sent:
                return
            channel = self._channel()
            if channel is None:
                return
            chat_id = owner_chat_id(self._config())
            if chat_id is None:
                return
            send = getattr(channel, "send_approval", None)
            if not callable(send):
                return
            channel.on_approval_callback = self.on_callback
            text = self._text(payload)
            lang = notification_language(text)
            message_id = await send(
                chat_id,
                text,
                approval_id,
                allow=phrase("telegram_allow", lang),
                deny=phrase("telegram_deny", lang),
            )
            self._sent[approval_id] = Sent(session_id, chat_id, message_id, text)
        except Exception:  # noqa: BLE001 — the app's own card still works without Telegram
            log.warning("telegram approvals: request not sent", exc_info=True)

    def _text(self, payload: dict[str, Any]) -> str:
        summary = " ".join(str(payload.get("summary") or "").split())[:300]
        tool = str(payload.get("name") or payload.get("tool") or "").strip() or "a tool"
        agent = str(payload.get("agent_name") or "").strip() or self._assistant_name()
        lang = notification_language(summary or tool)
        return phrase("telegram_approval", lang, agent=agent, tool=tool, summary=summary or "…")

    def _assistant_name(self) -> str:
        name = getattr(self._service, "assistant_name", None)
        try:
            value = name() if callable(name) else name
        except Exception:  # noqa: BLE001 — a cosmetic name; the phrase has a fallback
            value = None
        return str(value or "").strip() or phrase("an_agent", "en")

    # ------------------------------------------------------------- answering

    async def on_callback(self, approval_id: str, decision: str, from_user: int | None) -> str:
        """A button press; returns the short answer Telegram shows the presser."""
        sent = self._sent.get(approval_id)
        lang = notification_language(sent.text if sent else "")
        owner = owner_chat_id(self._config())
        if owner is not None and from_user is not None and int(from_user) != owner:
            return phrase("telegram_expired", lang)
        if sent is None:
            return phrase("telegram_expired", lang)
        try:
            ok = bool(self._service.resolve_approval(sent.session_id, approval_id, decision))
        except ValueError:  # a decision the service does not know: the card stays open
            ok = False
        if not ok:
            self._sent.pop(approval_id, None)
            return phrase("telegram_expired", lang)
        self._from_telegram.add(approval_id)
        return phrase("telegram_allowed" if decision == "allow" else "telegram_denied", lang)

    async def _settle(self, approval_id: str, payload: dict[str, Any]) -> None:
        sent = self._sent.pop(approval_id, None)
        if sent is None:
            return
        if approval_id in self._from_telegram:
            # The button's own answer already edited the message.
            self._from_telegram.discard(approval_id)
            return
        channel = self._channel()
        edit = getattr(channel, "edit_message", None)
        if channel is None or not callable(edit) or sent.message_id is None:
            return
        lang = notification_language(sent.text)
        settled = f"{sent.text}\n\n{phrase('telegram_settled', lang)}"
        try:
            await edit(sent.chat_id, sent.message_id, settled)
        except Exception:  # noqa: BLE001 — a stale Telegram message is cosmetic
            log.debug("telegram approvals: could not settle the message", exc_info=True)

    def open(self) -> list[str]:
        """Approval ids this bridge is showing right now (tests, diagnostics)."""
        return list(self._sent)


def _unattended(session_id: str) -> bool:
    try:
        from dodaios.society.routine_runner import is_routine_session

        return bool(is_routine_session(session_id))
    except Exception:  # noqa: BLE001 — without the society every chat counts as attended
        return False


__all__ = [
    "CALLBACK_PREFIX",
    "TelegramApprovalBridge",
    "callback_data",
    "owner_chat_id",
    "parse_callback",
]
