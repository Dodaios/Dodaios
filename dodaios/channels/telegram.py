# === F-FRIENDS [F1] · feature/friends-section · ruben-2026-04-30 ===
"""TelegramChannel: bidirectional ChannelAdapter via the Telegram Bot API.

Architecture (Phase F1):

- **Long-polling** — no public HTTPS endpoint required.
- **Token via Credential Manager** (``get_secret("telegram_bot_token", ...)``).
- **getMe validation on ``start()``**: raises ``ChannelStartError`` on InvalidToken.
- **Allowlist default**: empty ``allowed_user_ids`` = bot replies to nothing.
- **Outbound routing via InflightMap**: ``trace_id -> chat_id`` with TTL.
- **Readable text**: an outbound message is sent as written, links, code and
  lines kept; only keys and the call's hang-up marker are taken out
  (``channels.chat_text``). The speech filter is for a voice, not a chat.
- **FriendRegistry integration**: inbound reverse-lookup, optional auto-register.
- **Pictures and voice notes**: a photo (or an image sent as a file) and a voice
  message are downloaded and travel as :class:`ChannelMedia`; the chat bridge
  transcribes the voice and hands the pictures to the turn. A picture sent
  without words waits briefly for the question that usually follows it.

Jarvis-Agent pattern adopted: token hierarchy, ``group_policy``, ``require_mention``.
"""
from __future__ import annotations

import asyncio
import dataclasses
import html
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from dodaios.channels.base import (
    FIRST_CONTACT_PAIRING_WINDOW_S,
    ChannelMedia,
    ChannelMessage,
    ChannelSession,
)
from dodaios.channels.chat_text import readable_text, telegram_html, without_fences
from dodaios.channels.manager import (
    ChannelContext,
    ChannelStartError,
    is_transient_start_error,
)
from dodaios.core.bus import EventBus
from dodaios.core.config import TelegramConfig, get_secret, set_secret
from dodaios.core.events import Event, ResponseGenerated
from dodaios.friends.models import Friend, FriendChannel

# === F-FRIENDS [F1] · feature/friends-section · ruben-2026-04-30 ===
if TYPE_CHECKING:  # pragma: no cover
    from dodaios.friends.registry import FriendRegistry
    from dodaios.friends.schemas import StatusUpdate

log = logging.getLogger(__name__)


__all__ = ["TelegramChannel", "InflightMap"]

#: Longest error text kept from a Telegram/httpx exception.
_ERROR_TEXT_MAX = 300

#: The Bot API serves files up to this size to a bot.
_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024

#: A picture sent without words waits this long for the question that follows
#: it (people send the photo first and then type or dictate what they want).
PICTURE_WAIT_S = 25.0
#: The pictures of one album arrive as separate messages within a moment.
ALBUM_WAIT_S = 2.0


@dataclasses.dataclass(slots=True)
class _Held:
    """Pictures of one chat waiting for the words that belong to them."""

    message: ChannelMessage
    album: str
    timer: asyncio.Task[None] | None = None


def _safe_error(exc: BaseException, token: str | None = None) -> str:
    """``Type: message`` with the bot token removed.

    The token is part of every Bot API URL, and python-telegram-bot itself
    puts it into ``InvalidToken`` ("The token `…` was rejected by the
    server."). Every error text this channel logs, stores or raises goes
    through here: the exact token first, then the generic secret shapes.
    """
    from dodaios.core.redact import redact_secrets

    message = str(exc)
    if token:
        message = message.replace(token, "[redacted]")
    message = redact_secrets(message)[:_ERROR_TEXT_MAX]
    name = type(exc).__name__
    return f"{name}: {message}" if message else name


class InflightMap:
    """Mapping ``trace_id -> chat_id`` with TTL-based GC."""

    def __init__(self, ttl_s: float = 1800.0) -> None:
        self._ttl_ns = int(ttl_s * 1_000_000_000)
        self._map: dict[UUID, tuple[int, int]] = {}

    def set(self, trace_id: UUID, chat_id: int) -> None:
        expiry_ns = time.time_ns() + self._ttl_ns
        self._map[trace_id] = (chat_id, expiry_ns)
        self._gc()

    def get(self, trace_id: UUID) -> int | None:
        item = self._map.get(trace_id)
        if item is None:
            return None
        chat_id, expiry_ns = item
        if time.time_ns() > expiry_ns:
            self._map.pop(trace_id, None)
            return None
        return chat_id

    def _gc(self) -> None:
        now_ns = time.time_ns()
        expired = [t for t, (_, e) in self._map.items() if e < now_ns]
        for t in expired:
            self._map.pop(t, None)

    def __len__(self) -> int:
        return len(self._map)


class TelegramChannel:
    """Bidirectional Telegram bot channel."""

    name = "telegram"

    def __init__(
        self,
        bus: EventBus,
        config: TelegramConfig | None = None,
        friend_registry: FriendRegistry | None = None,
    ) -> None:
        self._bus = bus
        self._cfg = config if config is not None else TelegramConfig()
        self._friends = friend_registry
        self._app: Any = None
        self._inbox: asyncio.Queue[ChannelMessage] = asyncio.Queue()
        self._inflight = InflightMap(ttl_s=1800.0)
        self._sessions_by_chat: dict[int, ChannelSession] = {}
        self._event_handler_ref: Any = None
        self._bot_username: str = ""
        self._started = False
        # First-contact pairing is open only for a short window after this
        # instance is built (see FIRST_CONTACT_PAIRING_WINDOW_S).
        self._pairing_closes_at = time.monotonic() + FIRST_CONTACT_PAIRING_WINDOW_S
        self._pairing_closed_logged = False
        #: The language the owner's Telegram app is set to (``language_code``).
        self.owner_language = ""
        #: Per chat: pictures waiting for the message that belongs to them.
        self._held: dict[int, _Held] = {}
        self.picture_wait_s = PICTURE_WAIT_S
        self.album_wait_s = ALBUM_WAIT_S
        #: ``(approval_id, decision, from_user_id) -> answer text`` for the
        #: Allow / Deny buttons; set by ``channels.telegram_approvals``.
        self.on_approval_callback: Callable[[str, str, int | None], Awaitable[str]] | None = None

    @classmethod
    def from_context(cls, ctx: ChannelContext) -> TelegramChannel:
        cfg = ctx.config.get("telegram_config")
        if not isinstance(cfg, TelegramConfig):
            cfg = TelegramConfig()
        return cls(bus=ctx.bus, config=cfg, friend_registry=ctx.friend_registry)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._started:
            return
        if not self._cfg.enabled:
            self._event_handler_ref = self._on_bus_event
            self._bus.subscribe_all(self._event_handler_ref)
            self._started = True
            log.info("TelegramChannel disabled (config.enabled=False) — skipping")
            return

        token = get_secret("telegram_bot_token", env_fallback="TELEGRAM_BOT_TOKEN")
        if not token:
            token = self._token_from_marketplace_store()
        if not token:
            raise ChannelStartError(
                "Telegram token missing. Setup: run 'python -m dodaios --wizard' and "
                "enter the token from @BotFather (https://t.me/BotFather)."
            )

        # Import python-telegram-bot off the event loop. It is a heavy import
        # (~0.8 s isolated, more under the boot import-lock storm), and this
        # start() runs as a boot-time channel-bootstrap task that shares the
        # loop with the voice warm-up. Importing inline blocked the loop and
        # delayed VoiceBootStatus(ready=True) by ~the import time; moving it to
        # a thread keeps the loop free so the "VOICE STARTING…" spinner clears
        # sooner. The module lands in sys.modules either way.
        def _import_telegram_ext() -> tuple[Any, Any, Any, Any]:
            import telegram.ext as telegram_ext  # noqa: WPS433
            from telegram.ext import (  # noqa: WPS433
                ApplicationBuilder,
                MessageHandler,
                filters,
            )
            # The approval buttons need callback queries; a build of the
            # library without them still carries messages.
            callback_handler = getattr(telegram_ext, "CallbackQueryHandler", None)
            return ApplicationBuilder, callback_handler, MessageHandler, filters

        try:
            ApplicationBuilder, CallbackQueryHandler, MessageHandler, filters = (
                await asyncio.to_thread(_import_telegram_ext)
            )
        except ImportError as exc:
            raise ChannelStartError(
                "python-telegram-bot not installed. "
                "Install via: pip install 'python-telegram-bot>=22,<23'"
            ) from exc

        # python-telegram-bot polls through httpx, which logs every request URL
        # at INFO — and every Bot API URL carries the token.
        from dodaios.core.redact import redact_logger

        redact_logger("httpx")
        await self._validate_token(token)

        failure: str | None = None
        transient = False
        try:
            self._app = ApplicationBuilder().token(token).build()
            # Approval buttons (telegram_approvals.py) answer through callback
            # queries; everything else is a message.
            if CallbackQueryHandler is not None:
                self._app.add_handler(
                    CallbackQueryHandler(self._on_callback_query, pattern=r"^apr:")
                )
            self._app.add_handler(MessageHandler(filters.ALL, self._on_telegram_msg))

            await self._app.initialize()
            await self._app.start()
            await self._app.updater.start_polling(
                poll_interval=self._cfg.polling_interval_s
            )
        except Exception as exc:  # noqa: BLE001 — reported below without the token
            # ``initialize()`` re-checks the token and raises InvalidToken with
            # the token in its message.
            failure = _safe_error(exc, token)
            # The error is dropped below, so its type is read here: the
            # channel manager tries a passing failure again later.
            transient = is_transient_start_error(exc)
        except BaseException:
            # Cancelled mid-start (a stop or the shutdown ended a background
            # retry): no half-started poller may stay behind.
            await self._discard_app(token)
            raise
        if failure is not None:
            # A failed start leaves nothing running, or every retry would add
            # an Application that still waits for updates.
            await self._discard_app(token)
            # Raised outside the handler: the original error is then not even
            # reachable from this one (no ``__context__``), whatever prints it.
            raise ChannelStartError(f"Telegram start failed: {failure}", transient=transient)

        self._event_handler_ref = self._on_bus_event
        self._bus.subscribe_all(self._event_handler_ref)

        self._started = True
        log.info("TelegramChannel started (bot=@%s)", self._bot_username)

    async def stop(self) -> None:
        if not self._started:
            return

        if self._event_handler_ref is not None:
            wildcards = getattr(self._bus, "_wildcard_subscribers", None)
            if wildcards is not None and self._event_handler_ref in wildcards:
                wildcards.remove(self._event_handler_ref)
            self._event_handler_ref = None

        for held in self._held.values():
            if held.timer is not None:
                held.timer.cancel()
        self._held.clear()

        if self._app is not None:
            try:
                await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()
            except Exception as exc:  # noqa: BLE001
                log.warning("Telegram stop raised: %s", _safe_error(exc))
            self._app = None

        self._started = False
        log.info("TelegramChannel stopped")

    async def _discard_app(self, token: str) -> None:
        """Stop and shut down the Application of a start that failed or was cancelled."""
        app, self._app = self._app, None
        if app is None:
            return
        try:
            updater = getattr(app, "updater", None)
            if getattr(updater, "running", False):
                await updater.stop()
            if getattr(app, "running", False):
                await app.stop()
            shutdown = getattr(app, "shutdown", None)
            if callable(shutdown):
                await shutdown()
        except Exception as exc:  # noqa: BLE001 — the start already failed; this is cleanup
            log.debug("Telegram cleanup after a failed start raised: %s", _safe_error(exc, token))

    def _token_from_marketplace_store(self) -> str | None:
        """Migration fallback for tokens saved before the channel mirror existed."""
        try:
            from dodaios.marketplace.token_store import TokenStore

            tokens = TokenStore().load("telegram")
        except Exception as exc:  # noqa: BLE001
            log.debug("Telegram marketplace token fallback failed: %s", _safe_error(exc))
            return None
        if tokens is None or not tokens.access:
            return None
        set_secret("telegram_bot_token", tokens.access)
        log.info(
            "Telegram token read from Marketplace TokenStore; "
            "telegram_bot_token was mirrored best-effort."
        )
        return tokens.access

    @property
    def bot_username(self) -> str:
        """The bot's own username without the ``@``; empty until Telegram has said it."""
        return "" if self._bot_username == "<unknown>" else self._bot_username

    async def _validate_token(self, token: str) -> None:
        from telegram import Bot  # noqa: WPS433
        from telegram.error import InvalidToken  # noqa: WPS433

        bot = Bot(token=token)
        failure: str | None = None
        transient = False
        try:
            me = await bot.get_me()
            self._bot_username = (me.username or "").lower() or "<unknown>"
        except InvalidToken:  # reported below; its own message carries the token
            failure = (
                "Telegram token invalid (InvalidToken). "
                "Check the token in @BotFather or renew it via the wizard."
            )
        except Exception as exc:  # noqa: BLE001 — reported below without the token
            failure = f"Telegram getMe failed: {_safe_error(exc, token)}"
            # A timeout or no network yet (the app starts at login): the
            # manager tries again. Read from the type, as the error is dropped.
            transient = is_transient_start_error(exc)
        if failure is not None:
            # Outside the handler, so the original error is not its context.
            raise ChannelStartError(failure, transient=transient)

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    async def _on_telegram_msg(self, update: Any, _ctx: Any) -> None:
        try:
            msg_obj = getattr(update, "message", None)
            if msg_obj is None:
                return
            if not self._is_allowed(update) and not self._pair_first_private_user(
                update
            ):
                log.debug(
                    "Telegram message dropped (not allowed): chat=%s",
                    getattr(getattr(msg_obj, "chat", None), "id", "?"),
                )
                return

            # A photo's words are its caption.
            text = getattr(msg_obj, "text", None) or getattr(msg_obj, "caption", None) or ""
            chat_id = msg_obj.chat.id
            user = getattr(msg_obj, "from_user", None)
            user_id = user.id if user is not None else None

            command = text.strip().lower().split(maxsplit=1)[0] if text.strip() else ""
            if command in {"/start", "/help"}:
                await self._send_text(
                    chat_id,
                    "Telegram is connected. Send a message here and I will "
                    "forward it directly to Dodaios.",
                    language="en",
                )
                return

            media = await self._media_of(msg_obj)
            if not text.strip() and not media:
                log.debug("Telegram message without text or readable media dropped")
                return

            told = str(getattr(user, "language_code", "") or "")
            if told and getattr(getattr(msg_obj, "chat", None), "type", "") == "private":
                # The owner's Telegram language words their approval requests.
                self.owner_language = told
            friend = await self._resolve_friend(chat_id, user)
            session = self._session_for_chat(chat_id, user)

            channel_msg = ChannelMessage(
                session_id=session.session_id,
                kind="voice" if any(m.kind == "voice" for m in media) else "text",
                content=text,
                metadata={
                    "telegram_chat_id": chat_id,
                    "telegram_user_id": user_id,
                    "telegram_username": getattr(user, "username", None),
                    "telegram_language": getattr(user, "language_code", None),
                    "friend_id": str(friend.id) if friend else None,
                    "friend_display_name": friend.display_name if friend else None,
                },
                media=media,
            )
            await self._deliver(
                chat_id, channel_msg, album=str(getattr(msg_obj, "media_group_id", None) or "")
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("TelegramChannel._on_telegram_msg failed: %s", exc)

    async def _deliver(self, chat_id: int, msg: ChannelMessage, *, album: str = "") -> None:
        """Put ``msg`` in the inbox, or hold pictures for the words that follow.

        A picture without words waits :data:`PICTURE_WAIT_S` for the next
        message of the same chat and then travels with it, so "photo, then the
        question" is one message with the picture attached. The pictures of an
        album (one ``media_group_id``) are gathered into one message.
        """
        held = self._held.pop(chat_id, None)
        if held is not None:
            if held.timer is not None:
                held.timer.cancel()
            words = "\n\n".join(
                part for part in (held.message.content.strip(), msg.content.strip()) if part
            )
            msg = dataclasses.replace(
                msg,
                content=words,
                kind="voice" if "voice" in (msg.kind, held.message.kind) else "text",
                media=held.message.media + msg.media,
            )
            album = album if album and album == held.album else ""
        pictures_only = bool(msg.media) and all(m.kind == "image" for m in msg.media)
        if album or (pictures_only and not msg.content.strip()):
            wait = self.album_wait_s if album and msg.content.strip() else self.picture_wait_s
            waiting = _Held(message=msg, album=album)
            waiting.timer = asyncio.create_task(
                self._release_after(chat_id, waiting, wait), name=f"telegram-hold:{chat_id}"
            )
            self._held[chat_id] = waiting
            return
        await self._enqueue(chat_id, msg)

    async def _release_after(self, chat_id: int, held: _Held, wait_s: float) -> None:
        """Send held pictures on their own when no words followed in time."""
        await asyncio.sleep(wait_s)
        if self._held.get(chat_id) is not held:
            return
        del self._held[chat_id]
        await self._enqueue(chat_id, held.message)

    async def _enqueue(self, chat_id: int, msg: ChannelMessage) -> None:
        self._inflight.set(msg.trace_id, chat_id)
        await self._inbox.put(msg)

    async def _media_of(self, msg_obj: Any) -> tuple[ChannelMedia, ...]:
        """The pictures and voice note of one Telegram message, downloaded.

        A photo comes in several sizes; the largest is taken. An image sent as
        a file (no compression) counts as a picture. A voice message, or an
        audio file, is a voice note. A file the Bot API will not serve (over
        20 MB) or one that fails to download is left out; the words still go.
        """
        message_id = getattr(msg_obj, "message_id", None) or int(time.time())
        wanted: list[tuple[str, str, str, Any]] = []
        photos = getattr(msg_obj, "photo", None) or ()
        if photos:
            wanted.append(("image", f"telegram-photo-{message_id}.jpg", "image/jpeg", photos[-1]))
        document = getattr(msg_obj, "document", None)
        doc_mime = str(getattr(document, "mime_type", "") or "")
        if document is not None and doc_mime.startswith("image/") and doc_mime != "image/svg+xml":
            name = str(getattr(document, "file_name", "") or f"telegram-image-{message_id}")
            wanted.append(("image", name, doc_mime, document))
        for attr, default_name in (("voice", "voice.ogg"), ("audio", "audio")):
            note = getattr(msg_obj, attr, None)
            if note is None:
                continue
            mime = str(getattr(note, "mime_type", "") or "audio/ogg")
            name = str(getattr(note, "file_name", "") or f"telegram-{default_name}")
            wanted.append(("voice", name, mime, note))

        out: list[ChannelMedia] = []
        for kind, name, mime, item in wanted:
            size = getattr(item, "file_size", None)
            if isinstance(size, int) and size > _MAX_DOWNLOAD_BYTES:
                log.info("Telegram %s left out: %d bytes is over the download limit", kind, size)
                continue
            try:
                handle = await item.get_file()
                data = bytes(await handle.download_as_bytearray())
            except Exception as exc:  # noqa: BLE001 - the words of the message still go
                log.warning("Telegram %s download failed: %s", kind, _safe_error(exc))
                continue
            if data:
                out.append(ChannelMedia(kind=kind, name=name, data=data, mime=mime))  # type: ignore[arg-type]
        return tuple(out)

    def _is_allowed(self, update: Any) -> bool:
        msg = update.message
        if msg is None or msg.from_user is None:
            return False
        user_id = msg.from_user.id
        chat = msg.chat
        chat_type = getattr(chat, "type", "private")
        text = getattr(msg, "text", None) or getattr(msg, "caption", None) or ""

        if chat_type == "private":
            return user_id in self._cfg.allowed_user_ids

        if self._cfg.group_policy == "disabled":
            return False
        if (
            self._cfg.group_policy == "allowlist"
            and chat.id not in self._cfg.allowed_chat_ids
        ):
            return False

        if self._cfg.require_mention and self._bot_username:
            mention = f"@{self._bot_username}"
            if mention not in text.lower():
                return False

        return True

    def _pair_first_private_user(self, update: Any) -> bool:
        """Claim an empty private allowlist for the first sender.

        The Marketplace can validate a bot token but cannot know which Telegram
        user should be allowed. Without this pairing step the common setup
        ("paste token, send /start") looks broken because every message is
        silently dropped by the empty allowlist.
        """
        if not self._cfg.pair_on_first_private_message:
            return False
        if self._cfg.allowed_user_ids or self._cfg.allowed_chat_ids:
            return False

        msg = getattr(update, "message", None)
        if msg is None:
            return False
        chat = getattr(msg, "chat", None)
        user = getattr(msg, "from_user", None)
        if chat is None or user is None:
            return False
        if getattr(chat, "type", "private") != "private":
            return False

        try:
            user_id = int(user.id)
        except (TypeError, ValueError):
            return False

        if time.monotonic() > self._pairing_closes_at:
            if not self._pairing_closed_logged:
                self._pairing_closed_logged = True
                log.warning(
                    "Telegram first-user pairing refused: the pairing window closed "
                    "%.0f s after the channel started. Message the bot right after "
                    "connecting it, or add your user id to allowed_user_ids.",
                    FIRST_CONTACT_PAIRING_WINDOW_S,
                )
            return False

        self._cfg.allowed_user_ids.append(user_id)
        try:
            from dodaios.core.config_writer import add_telegram_allowed_user_id

            add_telegram_allowed_user_id(user_id)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Telegram first-user pairing could not be persisted "
                "(user=%s): %s",
                user_id,
                exc,
            )
        log.info("Telegram first-user pairing: user_id=%s allowed", user_id)
        return True

    async def _resolve_friend(self, chat_id: int, user: Any) -> Friend | None:
        if self._friends is None:
            return None
        existing = await self._friends.find_friend_by_channel("telegram", str(chat_id))
        if existing is not None:
            return existing
        if not self._cfg.auto_register_friends:
            return None
        display = (
            getattr(user, "full_name", None)
            or getattr(user, "username", None)
            or f"telegram:{chat_id}"
        )
        friend = Friend(display_name=display)
        await self._friends.add_friend(friend)
        await self._friends.link_channel(
            FriendChannel(
                friend_id=friend.id,
                channel="telegram",
                handle=str(chat_id),
                is_primary=True,
            )
        )
        log.info("Telegram-Friend auto-registered: %s (chat=%s)", display, chat_id)
        return friend

    def _session_for_chat(self, chat_id: int, user: Any) -> ChannelSession:
        existing = self._sessions_by_chat.get(chat_id)
        if existing is not None:
            return existing
        handle = (
            getattr(user, "username", None)
            or getattr(user, "full_name", None)
            or str(chat_id)
        )
        session = ChannelSession(
            session_id=uuid4(),
            channel_name=self.name,
            user_handle=handle,
            locale="de",
        )
        self._sessions_by_chat[chat_id] = session
        return session

    async def messages(self) -> AsyncIterator[ChannelMessage]:
        while True:
            msg = await self._inbox.get()
            yield msg

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    async def _on_bus_event(self, event: Event) -> None:
        if not isinstance(event, ResponseGenerated):
            return
        trace_id = getattr(event, "trace_id", None)
        if trace_id is None:
            return
        chat_id = self._inflight.get(trace_id)
        if chat_id is None:
            return
        text = event.text or ""
        await self._send_text(chat_id, text, language=event.language or "en")

    async def send_message(self, msg: ChannelMessage) -> None:
        chat_id_raw = msg.metadata.get("telegram_chat_id")
        if chat_id_raw is None:
            log.warning(
                "TelegramChannel.send_message without telegram_chat_id (session=%s); drop",
                msg.session_id,
            )
            return
        try:
            chat_id = int(chat_id_raw)
        except (TypeError, ValueError):
            log.warning("Invalid telegram_chat_id: %r — drop", chat_id_raw)
            return
        await self._send_text(chat_id, msg.content, language="en")

    async def broadcast_event(self, event: Event) -> None:
        """No-op: Telegram routing goes through InflightMap, not broadcast."""

    # ------------------------------------------------------------------
    # Approvals (channels/telegram_approvals.py)
    # ------------------------------------------------------------------

    async def send_approval(
        self, chat_id: int, text: str, approval_id: str, *, allow: str, deny: str
    ) -> int | None:
        """A waiting approval with Allow / Deny buttons; returns the message id."""
        if self._app is None:
            log.debug("TelegramChannel send_approval aborted: not started")
            return None
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup  # noqa: WPS433

        from dodaios.channels.telegram_approvals import callback_data

        # The whole command or diff, as it will run: read, not spoken, and in
        # a code block, escaped for Telegram's HTML and nothing else.
        cleaned = readable_text(text)
        if not cleaned:
            return None
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(allow, callback_data=callback_data("allow", approval_id)),
                    InlineKeyboardButton(deny, callback_data=callback_data("deny", approval_id)),
                ]
            ]
        )
        try:
            message = await self._app.bot.send_message(
                chat_id=chat_id,
                text=telegram_html(cleaned),
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        except Exception as exc:  # noqa: BLE001
            # Telegram refused the markup: the same words as plain text.
            log.warning("Telegram send_approval as HTML failed: %s", _safe_error(exc))
            try:
                message = await self._app.bot.send_message(
                    chat_id=chat_id, text=without_fences(cleaned), reply_markup=keyboard
                )
            except Exception as again:  # noqa: BLE001
                log.warning("Telegram send_approval failed: %s", _safe_error(again))
                return None
        return getattr(message, "message_id", None)

    async def edit_message(self, chat_id: int, message_id: int, text: str) -> None:
        """Replace a sent message's text and drop its buttons."""
        if self._app is None:
            return
        try:
            await self._app.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, text=text, reply_markup=None
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Telegram edit_message failed: %s", _safe_error(exc))

    async def _on_callback_query(self, update: Any, _ctx: Any) -> None:
        """An Allow / Deny button: answer the approval, then settle the message."""
        query = getattr(update, "callback_query", None)
        if query is None:
            return
        from dodaios.channels.telegram_approvals import parse_callback

        parsed = parse_callback(str(getattr(query, "data", "") or ""))
        user = getattr(query, "from_user", None)
        user_id = getattr(user, "id", None)
        answer = ""
        try:
            if parsed is None or self.on_approval_callback is None:
                answer = ""
            else:
                decision, approval_id = parsed
                answer = await self.on_approval_callback(approval_id, decision, user_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("Telegram approval callback failed: %s", _safe_error(exc))
        try:
            await query.answer(answer or None)
        except Exception as exc:  # noqa: BLE001
            log.debug("Telegram callback answer failed: %s", _safe_error(exc))
        if not answer:
            return
        message = getattr(query, "message", None)
        original = str(getattr(message, "text", "") or "")
        # The approval went out as HTML: keep its code block where the message
        # says how it looked.
        marked = getattr(message, "text_html", None)
        try:
            if isinstance(marked, str) and marked:
                await query.edit_message_text(
                    text=f"{marked}\n\n{html.escape(answer, quote=False)}",
                    parse_mode="HTML",
                    reply_markup=None,
                )
            else:
                await query.edit_message_text(text=f"{original}\n\n{answer}", reply_markup=None)
        except Exception as exc:  # noqa: BLE001
            log.debug("Telegram callback edit failed: %s", _safe_error(exc))

    async def _send_text(self, chat_id: int, text: str, *, language: str) -> None:
        if self._app is None:
            log.debug("TelegramChannel send aborted: not started")
            return
        cleaned = readable_text(text)
        if not cleaned:
            log.debug("TelegramChannel send aborted: nothing to send")
            return
        try:
            await self._app.bot.send_message(chat_id=chat_id, text=cleaned)
        except Exception as exc:  # noqa: BLE001
            log.warning("Telegram send_message failed: %s", _safe_error(exc))

    # === F-FRIENDS [F4] · feature/friends-section · ruben-2026-05-01 ===
    async def send_status_card(
        self, chat_id: int, update: StatusUpdate
    ) -> None:
        """Sends a formatted status card as a Telegram Markdown message.

        Layout:

            *[Status] <event_type>*
            - <field>: <value>
            ...

        ``timestamp_ns`` is omitted (implied by the header). On error the
        failure is logged but not propagated — a blocked friend must not
        stop the bus dispatch.
        """
        if self._app is None:
            log.debug("send_status_card aborted: not started")
            return
        text_lines = [f"*[Status] {update.event_type}*"]
        for key, value in update.fields.items():
            if key == "timestamp_ns":
                continue
            text_lines.append(f"- {key}: {value}")
        text = "\n".join(text_lines)
        try:
            await self._app.bot.send_message(
                chat_id=chat_id, text=text, parse_mode="Markdown"
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Telegram send_status_card failed: %s", _safe_error(exc))

    async def sessions(self) -> list[ChannelSession]:
        return list(self._sessions_by_chat.values())
