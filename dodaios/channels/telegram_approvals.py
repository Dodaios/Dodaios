"""Approvals in the owner's Telegram chat: Allow / Deny buttons.

When a tool call waits for the person's approval (an ``approval_required``
event in a chat) and the owner's Telegram is connected, the request also goes
to their private chat with two inline buttons. A button answers the very same
approval the app's card is waiting on (``AgentChatService.resolve_approval``);
a decision taken in the app settles the Telegram message instead. Only the
owner (the first allowed private user, or the configured chat) can press.

The bridge listens on the chat service's event listener, so it sees every
runner the chat has. It never awaits inside the listener: it schedules.

The same bridge serves the owner's Slack app (``channels/slack.py``): one
instance per channel, built with ``source="slack"``, which asks the live
channel for its owner and reads the ``slack_approvals`` switch.

The message is written for a phone, in the owner's language: who asks (a
coding thread by its title), what it wants in plain words, and the whole of
it, the full command or the changed lines, not a line cut off after 140
characters. Once decided, the message shrinks to its first line and the
decision, so a busy coding session does not fill the chat.
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


#: Telegram's message limit is 4096 characters; the body stays well below.
_MAX_MESSAGE: Final[int] = 3500
#: The longest command shown in full; a longer one is cut with a note.
_MAX_COMMAND: Final[int] = 2500
#: Changed lines of a file edit shown on the phone.
_MAX_DIFF_LINES: Final[int] = 20
#: A thread title is shown up to this length.
_MAX_TITLE: Final[int] = 48
#: The owner's own messages read to tell their language.
_LANGUAGE_SAMPLE: Final[int] = 600
_LANGS: Final[tuple[str, ...]] = ("en", "de", "es", "pt")


@dataclass(slots=True)
class Sent:
    session_id: str
    #: Telegram: the chat id (an int); Slack: the owner's member id.
    chat_id: Any
    #: Telegram: the message id; Slack: ``"<channel>|<ts>"``.
    message_id: Any
    text: str
    lang: str = "en"


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


def slack_owner(channel: Any) -> str | None:
    """The owner of the Slack app: the first paired member id of the live channel."""
    owners = list(getattr(channel, "owner_ids", None) or [])
    return str(owners[0]) if owners else None


class TelegramApprovalBridge:
    def __init__(
        self,
        service: Any,
        *,
        channel: Callable[[], Any | None],
        config: Callable[[], Any],
        settings: Callable[[], NotifySettings] = load_settings,
        source: str = "telegram",
    ) -> None:
        self._service = service
        self._channel = channel
        self._config = config
        self._settings = settings
        #: ``telegram`` or ``slack``: whose switch, owner and words apply.
        self._source = source if source in ("telegram", "slack") else "telegram"
        self._sent: dict[str, Sent] = {}
        #: Approvals whose message is on its way (the send has not returned).
        self._sending: set[str] = set()
        #: Decisions taken in the app while their message was on its way.
        self._settled_early: dict[str, dict[str, Any]] = {}
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
        task = loop.create_task(coro, name=f"{self._source}-approval")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _send(self, session_id: str, payload: dict[str, Any]) -> None:
        try:
            if not getattr(self._settings(), f"{self._source}_approvals", True):
                return
            if _unattended(session_id):
                return
            approval_id = str(payload.get("approval_id") or "")
            if not approval_id or approval_id in self._sent or approval_id in self._sending:
                return
            channel = self._channel()
            if channel is None:
                return
            chat_id = self._owner(channel)
            if chat_id is None:
                return
            send = getattr(channel, "send_approval", None)
            if not callable(send):
                return
            channel.on_approval_callback = self.on_callback
            lang = self._owner_language(session_id, channel)
            text = self._text(payload, lang, session_id)
            # A decision in the app can come while the message is on its way;
            # it is kept and applied once the message exists (see _settle).
            self._sending.add(approval_id)
            try:
                message_id = await send(
                    chat_id,
                    text,
                    approval_id,
                    allow=phrase("telegram_allow", lang),
                    deny=phrase("telegram_deny", lang),
                )
            except BaseException:
                self._settled_early.pop(approval_id, None)
                raise
            finally:
                self._sending.discard(approval_id)
            self._sent[approval_id] = Sent(session_id, chat_id, message_id, text, lang)
            early = self._settled_early.pop(approval_id, None)
            if early is not None:
                await self._settle(approval_id, early)
        except Exception:  # noqa: BLE001 — the app's own card still works without Telegram
            log.warning("%s approvals: request not sent", self._source, exc_info=True)

    def _owner(self, channel: Any | None) -> Any | None:
        """Who may decide: the Telegram owner chat from the config, the Slack app's owner."""
        if self._source == "slack":
            return slack_owner(channel) if channel is not None else None
        return owner_chat_id(self._config())

    def _text(self, payload: dict[str, Any], lang: str = "en", session_id: str = "") -> str:
        """The request in plain words, whole, in ``lang``."""
        preview = payload.get("preview") if isinstance(payload.get("preview"), dict) else {}
        klass = str(preview.get("class") or "")
        fields = {
            str(f.get("key")): f for f in preview.get("fields", []) if isinstance(f, dict)
        }
        tool = str(payload.get("name") or payload.get("tool") or "").strip() or "a tool"
        agent = self._agent_label(payload, session_id, lang)
        why = " ".join(str(payload.get("why") or "").split())
        lines: list[str] = []
        if klass == "shell":
            lines.append(phrase("telegram_wants_command", lang, agent=agent))
            if why:
                lines.append(phrase("telegram_why", lang, why=why))
            command = str(fields.get("command", {}).get("value") or "").strip()
            if command:
                cut = len(command) > _MAX_COMMAND
                if cut:
                    command = command[:_MAX_COMMAND].rstrip()
                lines += ["", *self._code(command.split("\n")), ""]
                if cut:
                    lines += [phrase("telegram_cut", lang), ""]
            folder = str(fields.get("folder", {}).get("value") or "").strip()
            if folder:
                lines.append(phrase("telegram_folder", lang, folder=folder))
        elif klass in ("file_write", "file_delete"):
            diff = preview.get("diff") if isinstance(preview.get("diff"), dict) else {}
            key = (
                "telegram_wants_delete" if klass == "file_delete"
                else "telegram_wants_create" if diff.get("creates")
                else "telegram_wants_edit"
            )
            lines.append(phrase(key, lang, agent=agent))
            if why:
                lines.append(phrase("telegram_why", lang, why=why))
            path = str(fields.get("path", {}).get("value") or diff.get("path") or "").strip()
            if path:
                lines.append(phrase("telegram_file", lang, path=path))
            if diff:
                lines.append(phrase(
                    "telegram_lines", lang,
                    added=int(diff.get("added") or 0), removed=int(diff.get("removed") or 0),
                ))
                shown, more = _diff_lines(diff, lang)
                if shown:
                    lines += ["", *self._code(shown)]
                    if more:
                        lines.append(more)
        else:
            source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
            if source.get("kind") == "plan":
                lines.append(phrase("telegram_wants_plan", lang, agent=agent))
            else:
                lines.append(phrase("telegram_wants_tool", lang, agent=agent, tool=tool))
            if why:
                lines.append(phrase("telegram_why", lang, why=why))
            if preview:
                from dodaios.agent_chat.approval_preview import compact_line

                said = compact_line(preview, lang)
            else:
                said = str(payload.get("summary") or "")
            said = said.strip()
            if said and said != tool and said != why:
                lines += ["", said]
        if preview.get("irreversible"):
            lines += ["", phrase("telegram_irreversible", lang)]
        text = "\n".join(lines).strip()
        if len(text) > _MAX_MESSAGE:
            text = text[:_MAX_MESSAGE].rstrip()
            if text.count("```") % 2:
                text += "\n```"  # a code block cut open would swallow the note
            text += "\n" + phrase("telegram_cut", lang)
        return text

    def _code(self, lines: list[str]) -> list[str]:
        """Command or diff lines as they run, in a code block.

        A fenced block in the text: Slack shows it as one, Telegram's channel
        turns it into ``<pre>`` (``chat_text.telegram_html``).
        """
        # A fence inside the command would end the block early.
        return ["```", *(line.replace("```", "`\u200b`\u200b`") for line in lines), "```"]

    def _agent_label(self, payload: dict[str, Any], session_id: str, lang: str) -> str:
        """Who asks: the named agent, a coding thread by its title, else the assistant."""
        named = str(payload.get("agent_name") or "").strip()
        if named:
            return named
        session = self._session(session_id)
        if session is not None and str(getattr(session, "surface", "")) == "agent":
            title = " ".join(str(getattr(session, "title", "") or "").split())
            if title:
                if len(title) > _MAX_TITLE:
                    title = title[: _MAX_TITLE - 1].rstrip() + "…"
                return phrase("telegram_coding_agent", lang, title=title)
            return phrase("an_agent", lang)
        return self._assistant_name()

    def _session(self, session_id: str) -> Any | None:
        store = getattr(self._service, "store", None)
        if not session_id or store is None:
            return None
        try:
            return store.get_session(session_id)
        except Exception:  # noqa: BLE001 — a cosmetic label; the phrase has a fallback
            log.debug("telegram approvals: session not readable", exc_info=True)
            return None

    def _owner_language(self, session_id: str, channel: Any) -> str:
        """The language the owner writes in: their own words in this chat first.

        An agent's command or file path says nothing about the person who has
        to decide, so the request is not worded in the language of its
        content. Order: what the owner typed in this conversation, the
        language their Telegram app is set to, then the app's setting.
        """
        from dodaios.core.turn_language import detect_text_language

        typed = self._owner_words(session_id)
        if typed:
            code = detect_text_language(typed)
            if code in _LANGS:
                return code
        told = str(getattr(channel, "owner_language", "") or "").lower().split("-")[0]
        if told in _LANGS:
            return told
        code = notification_language("")
        return code if code in _LANGS else "en"

    def _owner_words(self, session_id: str) -> str:
        store = getattr(self._service, "store", None)
        if not session_id or store is None:
            return ""
        try:
            events = store.recent_user_messages(session_id)
        except Exception:  # noqa: BLE001 — without the history the next signal decides
            log.debug("telegram approvals: history not readable", exc_info=True)
            return ""
        words: list[str] = []
        for event in events:
            payload = event.get("payload") or {}
            if payload.get("author") or payload.get("origin") in ("control", "background"):
                continue  # written by an agent or the app, not by the owner
            typed = payload.get("typed")
            said = str(typed if isinstance(typed, str) else payload.get("text") or "").strip()
            if said:
                words.append(said)
            if sum(len(w) for w in words) >= _LANGUAGE_SAMPLE:
                break
        return " ".join(words)[:_LANGUAGE_SAMPLE]

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
        lang = sent.lang if sent else notification_language("")
        owner = self._owner(self._channel())
        if owner is not None and from_user is not None and str(from_user) != str(owner):
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
        said = "allowed" if decision == "allow" else "denied"
        return phrase(f"{self._source}_{said}", lang)

    async def _settle(self, approval_id: str, payload: dict[str, Any]) -> None:
        sent = self._sent.pop(approval_id, None)
        if sent is None:
            if approval_id in self._sending:
                # Decided before the message arrived: settle it once it has.
                self._settled_early[approval_id] = payload
            return
        if approval_id in self._from_telegram:
            # The button's own answer already edited the message.
            self._from_telegram.discard(approval_id)
            return
        channel = self._channel()
        edit = getattr(channel, "edit_message", None)
        if channel is None or not callable(edit) or sent.message_id is None:
            return
        decision = str(payload.get("decision") or "")
        key = (
            "telegram_settled_allowed" if decision.startswith("allow")
            else "telegram_settled_denied" if decision == "deny"
            else "telegram_settled"
        )
        # Decided: only the first line stays, so the chat is not filled with
        # commands nobody has to read any more.
        head = sent.text.split("\n", 1)[0]
        settled = f"{head}\n{phrase(key, sent.lang)}"
        try:
            await edit(sent.chat_id, sent.message_id, settled)
        except Exception:  # noqa: BLE001 — a stale Telegram message is cosmetic
            log.debug("telegram approvals: could not settle the message", exc_info=True)

    def open(self) -> list[str]:
        """Approval ids this bridge is showing right now (tests, diagnostics)."""
        return list(self._sent)


def _diff_lines(diff: dict[str, Any], lang: str) -> tuple[list[str], str]:
    """The changed lines of a file edit (at most a screenful), and the "more" line."""
    changed = [
        r for r in diff.get("lines") or []
        if isinstance(r, dict) and r.get("op") in ("+", "-")
    ]
    out = [f"{r['op']} {str(r.get('text') or '').rstrip()}" for r in changed[:_MAX_DIFF_LINES]]
    hidden = max(0, int(diff.get("added") or 0) + int(diff.get("removed") or 0) - len(out))
    if not out:
        return [], ""
    return out, phrase("telegram_more_lines", lang, count=hidden) if hidden else ""


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
    "slack_owner",
]
