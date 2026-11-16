"""SlackChannel: the owner messages their own Slack app, the assistant answers.

Architecture, the same as the Telegram channel's:

- **Socket Mode**: the channel opens a WebSocket to Slack (with the app-level
  key, ``xapp-``) and Slack sends the app's events through it. No public
  address. Every envelope is acknowledged at once, before it is handled.
- **Keys in the Credential Manager**: ``slack_bot_token`` (``xoxb-``) for the
  Web API, ``slack_app_token`` (``xapp-``) for the link. Neither is logged:
  every error text goes through :func:`_safe_error`.
- **Owner only**: an empty ``allowed_user_ids`` answers nobody. The first
  direct message within :data:`FIRST_CONTACT_PAIRING_WINDOW_S` of the start
  claims it (``pair_on_first_dm``) and is answered with one line that says so.
  Anyone else gets nothing back, not even a refusal.
- **One conversation**: the owner's direct message carries ``slack_owner`` and
  goes to the lead conversation through the chat bridge, the one that
  continues on the desktop and the phone. A mention of the app in a channel
  is answered only when ``answer_mentions`` is on (off by default): the answer
  comes from that private conversation and every member of the channel reads
  it in the thread.
- **In order**: the events of one conversation are handled one after the
  other, so a picture still downloading is not overtaken by the question
  typed after it.
- **Readable text**: replies and approvals are sent as written, links, code
  and lines kept; only keys are taken out (``channels.chat_text``).
- **Pictures and voice clips** sent to the app travel as :class:`ChannelMedia`;
  a picture without words waits briefly for the words that follow.
- **Approvals**: :meth:`send_approval` posts Allow / Deny buttons
  (``channels/telegram_approvals.py`` drives it, as for Telegram).
- **Restart and reconnect**: a start that fails for a passing reason (no
  network at login) raises a transient :class:`ChannelStartError`, and the
  channel manager tries again. Once up, a dropped link, Slack's
  ``refresh_requested`` and ``warning`` disconnects, and a dead link found by
  the WebSocket ping open a fresh link by themselves, after growing waits
  while Slack is unreachable. A revoked key or Socket Mode switched off ends
  the link for good and says so in :attr:`last_error`.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import html
import json
import logging
import re
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from dodaios.channels.base import (
    FIRST_CONTACT_PAIRING_WINDOW_S,
    ChannelMedia,
    ChannelMessage,
    ChannelSession,
)
from dodaios.channels.chat_text import readable_text
from dodaios.channels.manager import (
    ChannelContext,
    ChannelStartError,
    is_transient_start_error,
)
from dodaios.channels.slack_api import SlackApi, SlackApiError
from dodaios.core.bus import EventBus
from dodaios.core.config import SlackChannelConfig, get_secret
from dodaios.core.events import Event, ResponseGenerated

if TYPE_CHECKING:  # pragma: no cover
    from dodaios.friends.registry import FriendRegistry

log = logging.getLogger(__name__)

__all__ = ["SlackChannel"]

#: Longest error text kept from a Slack/httpx/websockets exception.
_ERROR_TEXT_MAX = 300
#: Files larger than this are left out (the words of the message still go).
_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
#: A picture sent without words waits this long for the words that follow it.
PICTURE_WAIT_S = 25.0
#: How long the first ``hello`` of a fresh link may take.
HELLO_TIMEOUT_S = 15.0
#: Waits between attempts to open a new link while Slack is unreachable.
RECONNECT_DELAYS_S: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
#: Slack sends an event again when the acknowledgement was late; these
#: messages were handled already.
_SEEN_MAX = 500
#: Slack's limit for the text of one section block is 3000 characters.
_SECTION_MAX = 2900
#: Message subtypes that are the person writing (others are edits, joins, ...).
_PERSON_SUBTYPES = frozenset({"", "file_share", "thread_broadcast"})
#: Files Slack does not host itself, or no longer shows: no key goes to them.
_SKIPPED_FILE_MODES = frozenset({"external", "tombstone", "hidden_by_limit"})

_MENTION = re.compile(r"<@([UW][A-Z0-9]+)(?:\|[^>]*)?>")
_CHANNEL_REF = re.compile(r"<#[CG][A-Z0-9]+\|([^>]*)>")
_LINK = re.compile(r"<((?:https?|mailto):[^|>]+)(?:\|([^>]*))?>")
_SPECIAL = re.compile(r"<!(here|channel|everyone)(?:\|[^>]*)?>")


def slack_escape(text: str) -> str:
    """Escape the three characters Slack's message format reserves."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def plain_from_slack(text: str, *, bot_user_id: str = "") -> str:
    """A Slack message's text as the person wrote it.

    The mention of the app itself is dropped, other mentions keep their id,
    a channel reference keeps its name, a link its address (and its label),
    and Slack's escapes are undone.
    """
    if bot_user_id:
        text = re.sub(rf"<@{re.escape(bot_user_id)}(?:\|[^>]*)?>", "", text)
    text = _MENTION.sub(lambda m: f"@{m.group(1)}", text)
    text = _CHANNEL_REF.sub(lambda m: f"#{m.group(1)}", text)
    text = _LINK.sub(
        lambda m: (
            m.group(1)
            if not m.group(2) or m.group(2) == m.group(1)
            else f"{m.group(2)} ({m.group(1)})"
        ),
        text,
    )
    text = _SPECIAL.sub(lambda m: f"@{m.group(1)}", text)
    return html.unescape(text).strip()


def _safe_error(exc: BaseException, *secrets: str) -> str:
    """``Type: message`` with the keys and the link's ticket removed."""
    from dodaios.core.redact import redact_secrets

    message = str(exc)
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[redacted]")
    message = redact_secrets(message)[:_ERROR_TEXT_MAX]
    name = type(exc).__name__
    return f"{name}: {message}" if message else name


class _Lasting(Exception):
    """The link cannot come back by trying again (key revoked, Socket Mode off)."""


class _Inflight:
    """``trace_id -> (channel, thread_ts)`` for replies on the classic chat path."""

    def __init__(self, ttl_s: float = 1800.0) -> None:
        self._ttl = ttl_s
        self._map: dict[UUID, tuple[str, str, float]] = {}

    def set(self, trace_id: UUID, channel: str, thread_ts: str) -> None:
        now = time.monotonic()
        self._map = {k: v for k, v in self._map.items() if v[2] > now}
        self._map[trace_id] = (channel, thread_ts, now + self._ttl)

    def get(self, trace_id: UUID) -> tuple[str, str] | None:
        item = self._map.get(trace_id)
        if item is None or item[2] < time.monotonic():
            return None
        return item[0], item[1]


@dataclasses.dataclass(slots=True)
class _Held:
    message: ChannelMessage
    timer: asyncio.Task[None] | None = None


def _ws_connect(url: str) -> Awaitable[Any]:
    from websockets.asyncio.client import connect

    # Slack pings too; the client's own ping finds a link that died silently
    # (a Mac waking from sleep) within about forty seconds.
    return connect(url, ping_interval=20, ping_timeout=20, max_size=8 * 1024 * 1024)


class SlackChannel:
    """Bidirectional Slack channel over Socket Mode."""

    name = "slack"

    def __init__(
        self,
        bus: EventBus,
        config: SlackChannelConfig | None = None,
        friend_registry: FriendRegistry | None = None,
        *,
        api: SlackApi | None = None,
        connect: Callable[[str], Awaitable[Any]] | None = None,
        sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
    ) -> None:
        self._bus = bus
        self._cfg = config if config is not None else SlackChannelConfig()
        self._friends = friend_registry
        self._api = api if api is not None else SlackApi(self._cfg.api_base_url)
        self._connect = connect or _ws_connect
        self._sleep = sleep
        self._inbox: asyncio.Queue[ChannelMessage] = asyncio.Queue()
        self._inflight = _Inflight()
        self._sessions: dict[str, ChannelSession] = {}
        self._held: dict[str, _Held] = {}
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._tasks: set[asyncio.Future[Any]] = set()
        #: The newest event task of each conversation (see _spawn_in_order).
        self._lanes: dict[str, asyncio.Future[Any]] = {}
        self._runner: asyncio.Task[None] | None = None
        self._ws: Any = None
        self._event_handler_ref: Any = None
        self._bot_token = ""
        self._app_token = ""
        self._started = False
        self._stopping = False
        self.picture_wait_s = PICTURE_WAIT_S
        self.reconnect_delays = RECONNECT_DELAYS_S
        # First-contact pairing is open only for a short window after this
        # instance is built (see FIRST_CONTACT_PAIRING_WINDOW_S).
        self._pairing_closes_at = time.monotonic() + FIRST_CONTACT_PAIRING_WINDOW_S
        self._pairing_closed_logged = False
        #: Whether the channel runs (``enabled`` and both keys accepted).
        self.active = False
        #: Whether the Socket Mode link is up right now.
        self.connected = False
        self.team_id = ""
        self.team_name = ""
        self.team_url = ""
        self.bot_user_id = ""
        self.bot_name = ""
        self.app_id = ""
        #: Why the link is down, without any key; "" while it is fine.
        self.last_error = ""
        #: The language the owner's Slack is set to, e.g. ``de-DE``.
        self.owner_language = ""
        #: ``(approval_id, decision, from_user_id) -> answer text`` for the
        #: Allow / Deny buttons; set by ``channels.telegram_approvals``.
        self.on_approval_callback: Callable[[str, str, Any], Awaitable[str]] | None = None

    @classmethod
    def from_context(cls, ctx: ChannelContext) -> SlackChannel:
        cfg = ctx.config.get("slack_config")
        if not isinstance(cfg, SlackChannelConfig):
            cfg = SlackChannelConfig()
        return cls(bus=ctx.bus, config=cfg, friend_registry=ctx.friend_registry)

    # ------------------------------------------------------------------
    # State for the settings page
    # ------------------------------------------------------------------

    @property
    def owner_ids(self) -> list[str]:
        return [str(v) for v in self._cfg.allowed_user_ids]

    @property
    def pairing_open(self) -> bool:
        """Whether the next direct message would make its sender the owner."""
        return (
            self.active
            and not self._cfg.allowed_user_ids
            and self._cfg.pair_on_first_dm
            and time.monotonic() <= self._pairing_closes_at
        )

    @property
    def pairing_seconds_left(self) -> int:
        return max(0, int(self._pairing_closes_at - time.monotonic())) if self.pairing_open else 0

    @property
    def dm_url(self) -> str:
        """The web address of the direct message with the app, once Slack has named it."""
        if not (self.team_id and self.app_id):
            return ""
        return f"https://slack.com/app_redirect?app={self.app_id}&team={self.team_id}"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._started:
            return
        if not self._cfg.enabled:
            # Like every channel, a switched-off one still listens on the bus
            # (the channel contract); it has nothing to route, so it stays idle.
            self._event_handler_ref = self._on_bus_event
            self._bus.subscribe_all(self._event_handler_ref)
            self._started = True
            log.info("SlackChannel disabled (config.enabled=False) — skipping")
            return
        bot = get_secret("slack_bot_token", env_fallback="SLACK_BOT_TOKEN") or ""
        app = get_secret("slack_app_token", env_fallback="SLACK_APP_TOKEN") or ""
        if not bot or not app:
            missing = " and ".join(
                n for n, v in (("bot token", bot), ("app-level token", app)) if not v
            )
            raise ChannelStartError(
                f"Slack {missing} missing. Connect Slack under Plugins → Slack → "
                "Chat with the assistant in Slack.",
                transient=False,
            )
        self._bot_token, self._app_token = bot.strip(), app.strip()
        from dodaios.core.redact import redact_logger

        # httpx logs every request at INFO; the URLs carry no key, but a
        # Socket Mode link carries its ticket.
        redact_logger("httpx")
        # A logger's filter does not see its children's records: the
        # handshake line ("> GET /link/?ticket=...") comes from the client's.
        redact_logger("websockets")
        redact_logger("websockets.client")
        self._stopping = False
        try:
            ws = await self._first_link()
        except BaseException:
            # A failed or cancelled start leaves no HTTP client open: stop()
            # does nothing for a channel that never started, and a reload
            # builds a new channel with a client of its own. A retry of this
            # one opens a fresh client on its first call.
            with contextlib.suppress(Exception):
                await self._api.aclose()
            raise
        self.active = True
        self.last_error = ""
        self._event_handler_ref = self._on_bus_event
        self._bus.subscribe_all(self._event_handler_ref)
        self._runner = asyncio.create_task(self._run(ws), name="slack-socket")
        self._started = True
        log.info("SlackChannel started (workspace=%s, app=%s)", self.team_name or "?", self.app_id)

    async def _first_link(self) -> Any:
        """Who the bot is, then the first link; a failure as a :class:`ChannelStartError`."""
        await self._who_am_i()
        try:
            return await self._open_link()
        except _Lasting as exc:
            raise ChannelStartError(f"Slack start failed: {exc}", transient=False) from None
        except Exception as exc:  # noqa: BLE001 — reported below without any key
            failure = _safe_error(exc, self._bot_token, self._app_token)
            # A refused handshake or an overloaded Slack (websockets' own
            # errors, Slack's 5xx and rate limits) may work later too.
            transient = (
                is_transient_start_error(exc)
                or isinstance(exc, SlackApiError)
                or type(exc).__module__.partition(".")[0] == "websockets"
            )
            if isinstance(exc, SlackApiError) and exc.lasting:
                transient = False
        # Outside the handler, so the original error (and any key) is not its context.
        raise ChannelStartError(f"Slack start failed: {failure}", transient=transient)

    async def _who_am_i(self) -> None:
        """Ask Slack who the bot is; a refused key is lasting, no network passing."""
        failure: str | None = None
        transient = False
        try:
            me = await self._api.call("auth.test", self._bot_token)
        except SlackApiError as exc:  # reported below as a ChannelStartError, without the key
            failure = f"Slack refused the bot token ({exc.code})"
            transient = not exc.lasting
        except Exception as exc:  # noqa: BLE001 — reported below without the key
            failure = f"Slack auth.test failed: {_safe_error(exc, self._bot_token)}"
            transient = is_transient_start_error(exc)
        if failure is not None:
            # Outside the handler, so the original error is not its context.
            raise ChannelStartError(failure, transient=transient)
        self.team_id = str(me.get("team_id") or "")
        self.team_name = str(me.get("team") or "")
        self.team_url = str(me.get("url") or "")
        self.bot_user_id = str(me.get("user_id") or "")
        self.bot_name = str(me.get("user") or "")
        bot_id = str(me.get("bot_id") or "")
        if bot_id and not self.app_id:
            with contextlib.suppress(Exception):
                info = await self._api.call("bots.info", self._bot_token, bot=bot_id)
                self.app_id = str((info.get("bot") or {}).get("app_id") or "")

    async def stop(self) -> None:
        if not self._started:
            return
        self._stopping = True
        if self._event_handler_ref is not None:
            wildcards = getattr(self._bus, "_wildcard_subscribers", None)
            if wildcards is not None and self._event_handler_ref in wildcards:
                wildcards.remove(self._event_handler_ref)
            self._event_handler_ref = None
        for held in self._held.values():
            if held.timer is not None:
                held.timer.cancel()
        self._held.clear()
        self._lanes.clear()
        runner, self._runner = self._runner, None
        if runner is not None:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)
        await self._close_ws()
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        with contextlib.suppress(Exception):
            await self._api.aclose()
        self.active = False
        self.connected = False
        self._started = False
        log.info("SlackChannel stopped")

    async def _close_ws(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()

    # ------------------------------------------------------------------
    # The Socket Mode link
    # ------------------------------------------------------------------

    async def _open_link(self) -> Any:
        """A fresh link, after Slack's ``hello``; raises :class:`_Lasting` for good failures."""
        try:
            opened = await self._api.call("apps.connections.open", self._app_token)
        except SlackApiError as exc:
            if exc.lasting or exc.code in ("socket_mode_not_enabled",):
                raise _Lasting(f"Slack refused the app-level token ({exc.code})") from None
            raise
        url = str(opened.get("url") or "")
        if not url.startswith(("wss://", "ws://")):
            raise SlackApiError("apps.connections.open", "no_link")
        ws = await self._connect(url)
        try:
            first = json.loads(await asyncio.wait_for(ws.recv(), timeout=HELLO_TIMEOUT_S))
        except BaseException:
            with contextlib.suppress(Exception):
                await ws.close()
            raise
        if not isinstance(first, dict) or first.get("type") != "hello":
            with contextlib.suppress(Exception):
                await ws.close()
            if isinstance(first, dict) and first.get("type") == "disconnect":
                if first.get("reason") == "link_disabled":
                    raise _Lasting("Socket Mode is turned off for the Slack app")
            raise SlackApiError("socket", "no_hello")
        info = first.get("connection_info") or {}
        if isinstance(info, dict) and info.get("app_id") and not self.app_id:
            self.app_id = str(info["app_id"])
        self._ws = ws
        self.connected = True
        return ws

    async def _run(self, ws: Any) -> None:
        """Read the link; open a new one whenever it ends, until the channel stops."""
        attempt = 0
        try:
            while not self._stopping:
                if ws is not None:
                    reason = await self._read(ws)
                    self.connected = False
                    await self._close_ws()
                    if reason == "link_disabled":
                        self.last_error = "Socket Mode was turned off for the Slack app."
                        log.warning("Slack link ended for good: Socket Mode was turned off")
                        return
                    if self._stopping:
                        return
                    log.info("Slack link ended (%s); opening a new one", reason)
                    ws = None
                try:
                    ws = await self._open_link()
                except _Lasting as exc:
                    self.last_error = str(exc)
                    log.warning("Slack link cannot come back: %s", exc)
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 — tried again after a wait
                    wait = self.reconnect_delays[min(attempt, len(self.reconnect_delays) - 1)]
                    if isinstance(exc, SlackApiError) and exc.retry_after:
                        wait = max(wait, exc.retry_after)
                    attempt += 1
                    self.last_error = _safe_error(exc, self._bot_token, self._app_token)
                    log.info(
                        "Slack link could not open (%s); next try in %g s", self.last_error, wait
                    )
                    await self._sleep(wait)
                    continue
                attempt = 0
                self.last_error = ""
                log.info("Slack link open again")
        finally:
            self.connected = False

    async def _read(self, ws: Any) -> str:
        """Handle envelopes until the link ends; returns why it ended."""
        try:
            async for raw in ws:
                try:
                    envelope = json.loads(raw)
                except (TypeError, ValueError):  # not JSON: Slack sends only JSON, skip noise
                    continue
                if not isinstance(envelope, dict):
                    continue
                envelope_id = envelope.get("envelope_id")
                if envelope_id:
                    # Acknowledged first: Slack sends it again after 3 s otherwise.
                    await ws.send(json.dumps({"envelope_id": envelope_id}))
                kind = envelope.get("type")
                if kind == "disconnect":
                    return str(envelope.get("reason") or "disconnect")
                payload = envelope.get("payload")
                if not isinstance(payload, dict):
                    continue
                if kind == "events_api":
                    event = payload.get("event")
                    if isinstance(event, dict):
                        self._spawn_in_order(str(event.get("channel") or ""), event)
                elif kind == "interactive":
                    self._spawn(self._on_interactive(payload), "slack-action")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — a closed or broken link: open a new one
            return _safe_error(exc, self._app_token).split(":", 1)[0]
        return "closed"

    def _spawn(self, coro: Awaitable[Any], name: str) -> asyncio.Future[Any]:
        task = asyncio.ensure_future(coro)
        task.set_name(name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _spawn_in_order(self, conversation: str, event: dict[str, Any]) -> None:
        """Handle ``event`` after the earlier events of the same conversation.

        Each event still gets its own task (the link reads on at once), but a
        picture that is downloading is not overtaken by the question typed
        after it: the question waits, then joins the held picture.
        """
        previous = self._lanes.get(conversation)

        async def run() -> None:
            if previous is not None and not previous.done():
                await asyncio.wait({previous})
            await self._on_event(event)

        task = self._spawn(run(), "slack-event")
        self._lanes[conversation] = task

        def _done(finished: asyncio.Future[Any]) -> None:
            if self._lanes.get(conversation) is finished:
                del self._lanes[conversation]

        task.add_done_callback(_done)

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    async def _on_event(self, event: dict[str, Any]) -> None:
        try:
            await self._handle_event(event)
        except Exception as exc:  # noqa: BLE001
            log.warning("SlackChannel event failed: %s", _safe_error(exc, self._bot_token))

    async def _handle_event(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        channel = str(event.get("channel") or "")
        user = str(event.get("user") or "")
        if not channel or not user or event.get("bot_id") or user == self.bot_user_id:
            return
        if kind == "message":
            if str(event.get("subtype") or "") not in _PERSON_SUBTYPES:
                return
            if event.get("channel_type") != "im":
                return
            # A message in a thread of the direct message is answered in that thread.
            is_dm, thread_ts = True, str(event.get("thread_ts") or "")
        elif kind == "app_mention":
            if not self._cfg.answer_mentions or channel.startswith("D"):
                return  # a direct message comes as message.im
            is_dm, thread_ts = False, str(event.get("thread_ts") or event.get("ts") or "")
        else:
            return
        key = f"{channel}:{event.get('ts') or event.get('event_ts') or ''}"
        if key in self._seen:
            return
        self._seen[key] = None
        while len(self._seen) > _SEEN_MAX:
            self._seen.popitem(last=False)

        paired_now = False
        if user not in self.owner_ids:
            if not (is_dm and self._pair_first_dm(user)):
                log.debug("Slack message dropped (not the owner, %s)", "dm" if is_dm else "mention")
                return
            paired_now = True

        await self._learn_owner_language(user)
        if paired_now:
            await self._post(channel, _paired_line(self.owner_language), thread_ts="")

        text = plain_from_slack(str(event.get("text") or ""), bot_user_id=self.bot_user_id)
        media = await self._media_of(event)
        if not text and not media:
            return
        session = self._session_for(channel, user)
        msg = ChannelMessage(
            session_id=session.session_id,
            kind="voice" if any(m.kind == "voice" for m in media) else "text",
            content=text,
            metadata={
                "slack_channel": channel,
                "slack_user_id": user,
                "slack_thread_ts": thread_ts,
                "slack_dm": is_dm,
                # Only the paired owner gets here: the bridge takes this
                # message into the lead conversation.
                "slack_owner": True,
                "slack_language": self.owner_language,
                "channel_session_id": channel,
            },
            media=media,
        )
        await self._deliver(channel, msg)

    def _pair_first_dm(self, user: str) -> bool:
        """Claim an empty allowlist for the first direct message after the start."""
        if not self._cfg.pair_on_first_dm or self._cfg.allowed_user_ids:
            return False
        if not re.fullmatch(r"[UW][A-Z0-9]{2,32}", user):
            return False
        if time.monotonic() > self._pairing_closes_at:
            if not self._pairing_closed_logged:
                self._pairing_closed_logged = True
                log.warning(
                    "Slack first-DM pairing refused: the pairing window closed %.0f s after "
                    "the channel started. Use 'Pair again' in the app, then message the app.",
                    FIRST_CONTACT_PAIRING_WINDOW_S,
                )
            return False
        self._cfg.allowed_user_ids.append(user)
        try:
            from dodaios.core.config_writer import add_slack_allowed_user_id

            add_slack_allowed_user_id(user)
        except Exception as exc:  # noqa: BLE001
            log.warning("Slack first-DM pairing could not be saved: %s", exc)
        log.info("Slack first-DM pairing: the owner is paired")
        return True

    async def _learn_owner_language(self, user: str) -> None:
        if self.owner_language:
            return
        try:
            info = await self._api.call(
                "users.info", self._bot_token, user=user, include_locale=True
            )
        except Exception as exc:  # noqa: BLE001 — the language has other signals
            log.debug("Slack users.info failed: %s", _safe_error(exc, self._bot_token))
            return
        self.owner_language = str((info.get("user") or {}).get("locale") or "")

    async def _deliver(self, channel: str, msg: ChannelMessage) -> None:
        """Put ``msg`` in the inbox, or hold a picture for the words that follow it."""
        held = self._held.pop(channel, None)
        if held is not None:
            if held.timer is not None:
                held.timer.cancel()
            words = "\n\n".join(p for p in (held.message.content.strip(), msg.content.strip()) if p)
            msg = dataclasses.replace(
                msg,
                content=words,
                kind="voice" if "voice" in (msg.kind, held.message.kind) else "text",
                media=held.message.media + msg.media,
            )
        pictures_only = bool(msg.media) and all(m.kind == "image" for m in msg.media)
        if pictures_only and not msg.content.strip():
            waiting = _Held(message=msg)
            waiting.timer = asyncio.create_task(
                self._release_after(channel, waiting), name=f"slack-hold:{channel}"
            )
            self._held[channel] = waiting
            return
        await self._enqueue(msg)

    async def _release_after(self, channel: str, held: _Held) -> None:
        await self._sleep(self.picture_wait_s)
        if self._held.get(channel) is not held:
            return
        del self._held[channel]
        await self._enqueue(held.message)

    async def _enqueue(self, msg: ChannelMessage) -> None:
        self._inflight.set(
            msg.trace_id,
            str(msg.metadata.get("slack_channel") or ""),
            str(msg.metadata.get("slack_thread_ts") or ""),
        )
        await self._inbox.put(msg)

    async def _media_of(self, event: dict[str, Any]) -> tuple[ChannelMedia, ...]:
        """The pictures and voice clips of one message, downloaded with the bot key."""
        out: list[ChannelMedia] = []
        for item in event.get("files") or ():
            if not isinstance(item, dict):
                continue
            if item.get("is_external") or item.get("mode") in _SKIPPED_FILE_MODES:
                continue
            mime = str(item.get("mimetype") or "")
            if mime.startswith("image/") and mime != "image/svg+xml":
                kind = "image"
            elif mime.startswith("audio/") or item.get("subtype") == "slack_audio":
                kind = "voice"
            else:
                continue
            size = item.get("size")
            if isinstance(size, int) and size > _MAX_DOWNLOAD_BYTES:
                log.info("Slack %s left out: %d bytes is over the download limit", kind, size)
                continue
            url = str(item.get("url_private_download") or item.get("url_private") or "")
            if not url:
                continue
            try:
                data = await self._api.download(url, self._bot_token, limit=_MAX_DOWNLOAD_BYTES)
            except Exception as exc:  # noqa: BLE001 — the words of the message still go
                log.warning("Slack %s download failed: %s", kind, _safe_error(exc, self._bot_token))
                continue
            if data:
                name = str(item.get("name") or f"slack-{kind}-{item.get('id') or ''}")
                out.append(ChannelMedia(kind=kind, name=name, data=data, mime=mime))  # type: ignore[arg-type]
        return tuple(out)

    def _session_for(self, channel: str, user: str) -> ChannelSession:
        existing = self._sessions.get(channel)
        if existing is not None:
            return existing
        session = ChannelSession(
            session_id=uuid4(), channel_name=self.name, user_handle=user, locale="en"
        )
        self._sessions[channel] = session
        return session

    async def messages(self) -> AsyncIterator[ChannelMessage]:
        while True:
            yield await self._inbox.get()

    async def sessions(self) -> list[ChannelSession]:
        return list(self._sessions.values())

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    async def _on_bus_event(self, event: Event) -> None:
        if not isinstance(event, ResponseGenerated):
            return
        trace_id = getattr(event, "trace_id", None)
        target = self._inflight.get(trace_id) if trace_id is not None else None
        if target is None:
            return
        channel, thread_ts = target
        await self._post(channel, readable_text(event.text or ""), thread_ts=thread_ts)

    async def send_message(self, msg: ChannelMessage) -> None:
        channel = str(msg.metadata.get("slack_channel") or "")
        if not channel:
            log.warning("SlackChannel.send_message without slack_channel; dropped")
            return
        await self._post(
            channel,
            readable_text(msg.content),
            thread_ts=str(msg.metadata.get("slack_thread_ts") or ""),
        )

    async def broadcast_event(self, event: Event) -> None:
        """No-op: replies are routed by channel, not broadcast."""

    async def _post(
        self, channel: str, text: str, *, thread_ts: str = "", blocks: list[Any] | None = None
    ) -> dict[str, Any] | None:
        if not self.active or not text.strip():
            return None
        try:
            return await self._api.call(
                "chat.postMessage",
                self._bot_token,
                channel=channel,
                text=slack_escape(text),
                thread_ts=thread_ts or None,
                blocks=blocks,
                unfurl_links=False,
                unfurl_media=False,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Slack chat.postMessage failed: %s", _safe_error(exc, self._bot_token))
            return None

    # ------------------------------------------------------------------
    # Approvals (channels/telegram_approvals.py)
    # ------------------------------------------------------------------

    async def send_approval(
        self, chat_id: Any, text: str, approval_id: str, *, allow: str, deny: str
    ) -> str | None:
        """A waiting approval with Allow / Deny buttons in the owner's DM; returns its reference."""
        from dodaios.channels.telegram_approvals import callback_data

        # The whole command or diff, as it will run: read, not spoken.
        cleaned = readable_text(text)
        if not cleaned or not self.active:
            return None
        body = _section_text(slack_escape(cleaned))
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": body, "verbatim": True}},
            {
                "type": "actions",
                "block_id": "approval",
                "elements": [
                    {
                        "type": "button",
                        "action_id": callback_data("allow", approval_id),
                        "text": {"type": "plain_text", "text": allow[:70]},
                        "style": "primary",
                        "value": "allow",
                    },
                    {
                        "type": "button",
                        "action_id": callback_data("deny", approval_id),
                        "text": {"type": "plain_text", "text": deny[:70]},
                        "style": "danger",
                        "value": "deny",
                    },
                ],
            },
        ]
        # Posting to the member id lands in the app's direct message with them.
        sent = await self._post(str(chat_id), cleaned, blocks=blocks)
        if not sent:
            return None
        return f"{sent.get('channel') or chat_id}|{sent.get('ts') or ''}"

    async def edit_message(self, chat_id: Any, message_id: Any, text: str) -> None:
        """Replace a sent approval's text and drop its buttons."""
        channel, _, ts = str(message_id or "").partition("|")
        if not channel or not ts or not self.active:
            return
        body = _section_text(slack_escape(text))
        section = {"type": "section", "text": {"type": "mrkdwn", "text": body, "verbatim": True}}
        try:
            await self._api.call(
                "chat.update",
                self._bot_token,
                channel=channel,
                ts=ts,
                text=body,
                blocks=[section],
            )
        except Exception as exc:  # noqa: BLE001 — a stale message is cosmetic
            log.warning("Slack chat.update failed: %s", _safe_error(exc, self._bot_token))

    async def _on_interactive(self, payload: dict[str, Any]) -> None:
        """An Allow / Deny button: answer the approval, then settle the message."""
        if payload.get("type") != "block_actions":
            return
        from dodaios.channels.telegram_approvals import parse_callback

        actions = payload.get("actions") or []
        action = actions[0] if actions and isinstance(actions[0], dict) else {}
        parsed = parse_callback(str(action.get("action_id") or ""))
        user = str((payload.get("user") or {}).get("id") or "")
        if parsed is None or self.on_approval_callback is None:
            return
        if user not in self.owner_ids:
            log.debug("Slack approval button pressed by someone who is not the owner; ignored")
            return
        decision, approval_id = parsed
        try:
            answer = await self.on_approval_callback(approval_id, decision, user)
        except Exception as exc:  # noqa: BLE001
            log.warning("Slack approval callback failed: %s", _safe_error(exc))
            return
        if not answer:
            return
        container = payload.get("container") or {}
        channel = str(container.get("channel_id") or (payload.get("channel") or {}).get("id") or "")
        ts = str(container.get("message_ts") or (payload.get("message") or {}).get("ts") or "")
        original = plain_from_slack(str((payload.get("message") or {}).get("text") or ""))
        # Decided: the first line stays and the answer follows it, as for a
        # decision in the app, so a long command never pushes the answer out.
        head = original.split("\n", 1)[0].strip()
        if channel and ts:
            await self.edit_message(channel, f"{channel}|{ts}", f"{head}\n{answer}".strip())


# Closed list of the one line the owner reads when the pairing happened.
_PAIRED: dict[str, str] = {
    "en": "Connected. From now on I answer only you here.",
    "de": "Verbunden. Ab jetzt antworte ich hier nur dir.",  # i18n-allow
    "es": "Conectado. A partir de ahora aquí solo te respondo a ti.",  # i18n-allow
    "pt": "Ligado. A partir de agora respondo aqui só a ti.",  # i18n-allow
}


def _paired_line(locale: str) -> str:
    code = (locale or "en").lower().split("-")[0]
    return _PAIRED.get(code, _PAIRED["en"])


def _section_text(body: str) -> str:
    """``body`` cut to what one Slack section holds, never inside an escape or a code block."""
    if len(body) <= _SECTION_MAX:
        return body
    cut = body[:_SECTION_MAX]
    amp = cut.rfind("&")
    if amp != -1 and ";" not in cut[amp:]:
        cut = cut[:amp]  # a cut "&am" would show as text
    cut = cut.rstrip() + " …"
    if cut.count("```") % 2:
        cut += "\n```"
    return cut
