"""The bridge server: the one WebSocket ``Verse.exe`` talks to (BW1, contract 1-3).

Transport-independent: :class:`BridgeHub` serves any :class:`Transport`
(the Starlette adapter lives in ``dodaios/ui/web/verse_routes.py``; tests
use an in-memory pair). One hub per app, at most one live session.

Rules implemented here, each from ``contracts/bridge-protocol.md``:

* loopback peers only (``4403``), ``hello`` within 5 s (``4400``), token in
  constant time (``4401``), protocol list (``4426``), a second authenticated
  client replaces the first (``4409``), frames over 1 MiB (``1009``);
* ``ping`` / ``pong``; 5 s without any Verse frame is reported as hung;
* one ``seq`` counter per connection, strictly increasing; deltas carry
  ``base`` = the ``seq`` of the last frame of their topic; no replay on
  reconnect, a fresh snapshot per resubscribed topic;
* one bounded queue per topic: ``screens`` keeps the newest frame per pane,
  ``roster``, ``groups``, ``chat_tails``, ``meetings`` coalesce into a fresh
  snapshot on overflow, events and replies are never dropped;
* exactly one ``reply`` per command; unknown types are ignored and logged
  once per type; command rate limits.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import ipaddress
import itertools
import logging
import os
import secrets
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from . import protocol as P
from .cells_codec import encode as encode_cells

log = logging.getLogger(__name__)

#: Pending feed frames per coalescing topic before they fold into a snapshot.
COALESCE_LIMIT = 32
SEND_TIMEOUT_S = 5.0


class TransportClosed(Exception):
    """The peer went away."""


class Transport(Protocol):
    async def receive(self) -> str | bytes: ...
    async def send_text(self, text: str) -> None: ...
    async def send_bytes(self, data: bytes) -> None: ...
    async def close(self, code: int, reason: str = "") -> None: ...


Handler = Callable[["BridgeSession", P.Inbound], Awaitable[dict[str, Any] | None]]
NoticeHandler = Callable[["BridgeSession", P.Inbound], Awaitable[None]]


def is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        addr = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    if addr.is_loopback:
        return True
    mapped = getattr(addr, "ipv4_mapped", None)
    return bool(mapped is not None and mapped.is_loopback)


def mint_token() -> str:
    """256 bits, URL-safe base64 without padding (43 characters)."""
    return secrets.token_urlsafe(32)


@dataclass
class RateLimit:
    """At most ``count`` calls per ``window_s`` seconds."""

    count: int
    window_s: float
    _calls: deque[float] = field(default_factory=deque)

    def allow(self, now: float) -> bool:
        while self._calls and now - self._calls[0] >= self.window_s:
            self._calls.popleft()
        if len(self._calls) >= self.count:
            return False
        self._calls.append(now)
        return True


OPEN_COMMANDS = (
    "pane.open",
    "agent.open",
    "ide.focus_terminal",
    "agents.open_list",
    "group.open",
    "simulator.open",
    "ide.open",
)


def default_rate_limits() -> dict[str, RateLimit]:
    shared_open = RateLimit(4, 1.0)
    limits = {name: shared_open for name in OPEN_COMMANDS}
    limits["agent.create"] = RateLimit(1, 5.0)
    limits["launcher.start"] = RateLimit(1, 10.0)
    return limits


# ---------------------------------------------------------------------- outbound


@dataclass
class _Out:
    """One queued server frame. ``data`` may be a callable evaluated at write time."""

    type: str
    data: Any
    topic: str | None = None
    delta: bool = False
    re: str | None = None
    key: str | None = None  # screens: one slot per pane
    ref: int | None = None  # screens: binary when set
    feed: bool = False


class Outbox:
    """Ordered frames with per-topic back pressure (contract 1, Back pressure)."""

    COALESCING = ("roster", "groups", "chat_tails", "meetings", "companion")

    def __init__(self, limit: int = COALESCE_LIMIT) -> None:
        self._items: deque[_Out] = deque()
        self._slots: dict[str, _Out] = {}
        self._pending: dict[str, int] = {}
        self._limit = limit
        self._ready = asyncio.Event()
        self.snapshot_of: dict[str, Callable[[], Any]] = {}
        self.dropped = 0
        self.coalesced = 0

    def __len__(self) -> int:
        return len(self._items)

    def put(self, item: _Out) -> None:
        if item.key is not None:
            existing = self._slots.get(item.key)
            if existing is not None:
                # Newest frame per pane wins; a snapshot is never downgraded to a delta.
                if existing.delta or not item.delta:
                    existing.data, existing.delta, existing.type = item.data, item.delta, item.type
                    self.dropped += 1
                    return
                self._merge_rows(existing, item)
                self.dropped += 1
                return
            self._slots[item.key] = item
        if item.feed and item.topic in self.COALESCING:
            count = self._pending.get(item.topic, 0) + 1
            self._pending[item.topic] = count
            if count > self._limit and item.topic in self.snapshot_of:
                self._fold(item.topic)
                return
        self._items.append(item)
        self._ready.set()

    @staticmethod
    def _merge_rows(snapshot: _Out, delta: _Out) -> None:
        """A delta queued behind an unsent snapshot of the same pane: fold its rows in."""
        if not isinstance(snapshot.data, dict) or not isinstance(delta.data, dict):
            return
        rows = {r["row"]: r for r in snapshot.data.get("rows_changed", [])}
        for record in delta.data.get("rows_changed", []):
            rows[record["row"]] = record
        merged = dict(snapshot.data)
        merged["rows_changed"] = [rows[k] for k in sorted(rows) if rows[k]["runs"]]
        merged["cursor"] = delta.data.get("cursor", snapshot.data.get("cursor"))
        snapshot.data = merged

    def _fold(self, topic: str) -> None:
        """Too many pending deltas: drop them and send one fresh snapshot instead."""
        kept = deque(i for i in self._items if not (i.feed and i.topic == topic))
        self.coalesced += len(self._items) - len(kept)
        self._items = kept
        self._pending[topic] = 1
        snap_type = f"{topic}.snapshot" if topic != "chat_tails" else "chat_tails.update"
        self._items.append(_Out(snap_type, self.snapshot_of[topic], topic=topic, feed=True))
        self._ready.set()

    async def get(self) -> _Out:
        while not self._items:
            self._ready.clear()
            await self._ready.wait()
        item = self._items.popleft()
        if item.key is not None:
            self._slots.pop(item.key, None)
        if item.feed and item.topic in self._pending:
            self._pending[item.topic] = max(0, self._pending[item.topic] - 1)
        return item

    def clear_topic(self, topic: str) -> None:
        self._items = deque(i for i in self._items if i.topic != topic)
        self._slots = {k: v for k, v in self._slots.items() if v.topic != topic}
        self._pending.pop(topic, None)


# ---------------------------------------------------------------------- session


class Relay(Protocol):
    """A topic producer bound to one session (``relays/*.py``)."""

    topics: tuple[str, ...]

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def subscribe(self, topic: str) -> None: ...
    async def unsubscribe(self, topic: str) -> None: ...
    async def resync(self, topic: str, data: dict[str, Any]) -> None: ...


class BridgeSession:
    """One authenticated connection."""

    def __init__(
        self,
        hub: BridgeHub,
        transport: Transport,
        hello: P.Inbound,
        *,
        session_id: str,
    ) -> None:
        self.hub = hub
        self.transport = transport
        self.hello = hello
        self.id = session_id
        self.pid = hello.data.get("pid") if isinstance(hello.data.get("pid"), int) else None
        encodings = hello.data.get("encodings") or {}
        screens = encodings.get("screens") if isinstance(encodings, dict) else None
        self.screens_encoding = (
            "cells.bin/1"
            if not isinstance(screens, list) or "cells.bin/1" in screens or not screens
            else ("cells.json/1" if "cells.json/1" in screens else "cells.bin/1")
        )
        self.seq = 0
        self.last_seq_of: dict[str, int] = {}
        self.outbox = Outbox()
        self.subscribed: set[str] = set()
        self.relays: list[Relay] = []
        self.closed = asyncio.Event()
        self.close_code: int | None = None
        self.last_frame_at = hub.clock()
        self.hung_reported = False
        self.bytes_sent = 0
        self.screen_bytes = 0
        self.frames_sent = 0
        self._warned_types: set[str] = set()
        self._ids_seen: set[str] = set()
        self._log_budget = RateLimit(10, 1.0)
        self.rates = default_rate_limits()
        self._command_tasks: set[asyncio.Task[None]] = set()
        self.lifecycle: dict[str, Any] = {"state": "booting"}
        self.ready_ms: int | None = None
        self.panel_stream: dict[str, Any] = {"state": "stopped"}

    # ------------------------------------------------------------------ sending
    def send(
        self,
        type_: str,
        data: Any,
        *,
        topic: str | None = None,
        delta: bool = False,
        key: str | None = None,
        ref: int | None = None,
        feed: bool = False,
    ) -> None:
        """Queue one server frame; ``seq`` and ``base`` are assigned at write time."""
        if self.closed.is_set():
            return
        self.outbox.put(_Out(type_, data, topic=topic, delta=delta, key=key, ref=ref, feed=feed))

    def reply(self, rid: str, body: dict[str, Any]) -> None:
        if self.closed.is_set():
            return
        self.outbox.put(_Out("reply", body, re=rid))

    async def _write(self, item: _Out) -> None:
        data = item.data() if callable(item.data) else item.data
        if data is None:
            return
        if asyncio.iscoroutine(data):
            data = await data
            if data is None:
                return
        self.seq += 1
        seq = self.seq
        base: int | None = None
        slot = item.key or item.topic
        if item.delta and slot is not None:
            base = self.last_seq_of.get(slot)
            if base is None:
                # Never send a delta without the frame it applies to.
                self.seq -= 1
                return
        if item.ref is not None and self.screens_encoding == "cells.bin/1":
            if data.get("kind") == "snapshot":
                # The companion text frame goes right before each binary snapshot.
                meta = {
                    k: data[k] for k in ("pane_id", "ref", "cols", "rows", "style", "cut", "at")
                }
                meta_seq, seq = seq, seq + 1
                self.seq = seq
                text = P.encode(P.frame("screens.meta", meta_seq, meta))
                await asyncio.wait_for(self.transport.send_text(text), SEND_TIMEOUT_S)
                self.bytes_sent += len(text.encode("utf-8"))
                self.frames_sent += 1
            blob = encode_cells(data, ref=item.ref, seq=seq, base=base)
            await asyncio.wait_for(self.transport.send_bytes(blob), SEND_TIMEOUT_S)
            self.bytes_sent += len(blob)
            self.screen_bytes += len(blob)
        else:
            text = P.encode(P.frame(item.type, seq, data, base=base, re=item.re))
            await asyncio.wait_for(self.transport.send_text(text), SEND_TIMEOUT_S)
            size = len(text.encode("utf-8"))
            self.bytes_sent += size
            if item.ref is not None:
                self.screen_bytes += size
        self.frames_sent += 1
        if slot is not None and item.re is None:
            self.last_seq_of[slot] = seq
        if self.hub.on_frame_sent is not None:
            self.hub.on_frame_sent(self, item.type, data)

    async def writer(self) -> None:
        try:
            while not self.closed.is_set():
                item = await self.outbox.get()
                await self._write(item)
        except (TransportClosed, TimeoutError, ConnectionError):
            await self.close(1011, "send failed")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("verse bridge: writer failed")
            await self.close(1011, "internal error")

    async def close(self, code: int, reason: str = "") -> None:
        if self.closed.is_set():
            return
        self.close_code = code
        self.closed.set()
        for task in list(self._command_tasks):
            task.cancel()
        with contextlib.suppress(Exception):
            await self.transport.close(code, reason)

    # ------------------------------------------------------------------ receiving
    def warn_once(self, type_: str, message: str) -> None:
        if type_ not in self._warned_types:
            self._warned_types.add(type_)
            log.info("verse bridge: %s (%s)", message, type_)

    async def handle(self, inbound: P.Inbound) -> None:
        hub = self.hub
        entry_cmd = hub.commands.get(inbound.type)
        if entry_cmd is not None:
            if inbound.id is None:
                self.warn_once(inbound.type, "command without id ignored")
                return
            if inbound.id in self._ids_seen:
                self.reply(inbound.id, P.error("bad_request", "Request id reused."))
                return
            self._ids_seen.add(inbound.id)
            limit = self.rates.get(inbound.type)
            if limit is not None and not limit.allow(hub.clock()):
                self.reply(inbound.id, P.error("rate_limited", f"{inbound.type} rate limit."))
                return
            # Commands run beside the reader, so a long one (a launch batch)
            # never stalls ping handling; replies are matched by ``re``.
            task = asyncio.ensure_future(self._run_command(entry_cmd, inbound))
            self._command_tasks.add(task)
            task.add_done_callback(self._command_tasks.discard)
            return
        notice = hub.notices.get(inbound.type)
        if notice is not None:
            try:
                await notice(self, inbound)
            except Exception:  # noqa: BLE001
                log.exception("verse bridge: notice %s failed", inbound.type)
            return
        self.warn_once(inbound.type, "unknown message type ignored")

    async def _run_command(self, handler: Handler, inbound: P.Inbound) -> None:
        assert inbound.id is not None
        try:
            result = await handler(self, inbound)
        except P.BridgeError as exc:
            self.reply(inbound.id, P.error(exc.code, exc.message))
            return
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("verse bridge: %s failed", inbound.type)
            self.reply(inbound.id, P.error("internal", f"{inbound.type} failed."))
            return
        self.reply(inbound.id, P.ok(result))

    async def drain_commands(self) -> None:
        """Wait for every running command (tests and orderly shutdown)."""
        while self._command_tasks:
            await asyncio.gather(*list(self._command_tasks), return_exceptions=True)

    async def reader(self) -> None:
        while not self.closed.is_set():
            try:
                raw = await self.transport.receive()
            except TransportClosed:
                break
            self.last_frame_at = self.hub.clock()
            self.hung_reported = False
            size = len(raw) if isinstance(raw, bytes) else len(raw.encode("utf-8"))
            if size > P.MAX_FRAME_BYTES:
                await self.close(P.CLOSE_TOO_BIG, "frame too large")
                break
            if isinstance(raw, bytes):
                self.warn_once("binary", "binary frame from Verse ignored")
                continue
            try:
                inbound = P.parse(raw)
            except P.MalformedFrame as exc:
                self.warn_once("malformed", f"malformed frame ignored: {exc}")
                continue
            await self.handle(inbound)
        await self.close(1000, "")

    async def watchdog(self) -> None:
        """5 s without any Verse frame: report the link as hung (once per silence)."""
        while not self.closed.is_set():
            await asyncio.sleep(self.hub.watchdog_tick_s)
            idle = self.hub.clock() - self.last_frame_at
            if idle >= P.DEAD_LINK_S and not self.hung_reported:
                self.hung_reported = True
                log.warning("verse bridge: no frame for %.1f s, reporting hung", idle)
                if self.hub.on_hung is not None:
                    with contextlib.suppress(Exception):
                        await self.hub.on_hung(self)

    def allow_log(self) -> bool:
        return self._log_budget.allow(self.hub.clock())


# ---------------------------------------------------------------------- hub

TokenCheck = Callable[[str], bool]
RelayFactory = Callable[[BridgeSession], Relay]
WelcomeBuilder = Callable[[BridgeSession], dict[str, Any]]


class BridgeHub:
    """Serves ``/api/verse/bridge``: handshake, the one live session, dispatch."""

    def __init__(
        self,
        *,
        check_token: TokenCheck,
        welcome: WelcomeBuilder,
        features: Iterable[str] = P.BASE_FEATURES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.check_token = check_token
        self.build_welcome = welcome
        self.features = list(features)
        self.clock = clock
        self.current: BridgeSession | None = None
        self.commands: dict[str, Handler] = {}
        self.notices: dict[str, NoticeHandler] = {}
        self.relay_factories: list[RelayFactory] = []
        self.on_hung: Callable[[BridgeSession], Awaitable[None]] | None = None
        self.on_session: Callable[[BridgeSession | None], Awaitable[None]] | None = None
        self.on_frame_sent: Callable[[BridgeSession, str, Any], None] | None = None
        self.watchdog_tick_s = 0.1
        self._ids = itertools.count(1)
        self._register_core()

    # ------------------------------------------------------------------ registry
    def command(self, type_: str, handler: Handler) -> None:
        self.commands[type_] = handler

    def notice(self, type_: str, handler: NoticeHandler) -> None:
        self.notices[type_] = handler

    def relay(self, factory: RelayFactory) -> None:
        self.relay_factories.append(factory)

    def _register_core(self) -> None:
        async def ping(session: BridgeSession, _msg: P.Inbound) -> None:
            session.send("pong", {})

        async def log_notice(session: BridgeSession, msg: P.Inbound) -> None:
            if not session.allow_log():
                return
            level = msg.data.get("level")
            text = str(msg.data.get("message", ""))[:2000]
            category = str(msg.data.get("category", "verse"))[:64]
            py_level = {"error": logging.ERROR, "warning": logging.WARNING}.get(
                level if isinstance(level, str) else "", logging.INFO
            )
            log.log(py_level, "Verse [%s] %s", category, text)

        self.notice("ping", ping)
        self.notice("log", log_notice)
        self.command("subscribe", self._subscribe)
        self.command("unsubscribe", self._unsubscribe)
        self.command("resync", self._resync)

    def _relay_for(self, session: BridgeSession, topic: str) -> Relay | None:
        for relay in session.relays:
            if topic in relay.topics:
                return relay
        return None

    async def _subscribe(self, session: BridgeSession, msg: P.Inbound) -> dict[str, Any]:
        topics = msg.data.get("topics")
        if not isinstance(topics, list) or not all(isinstance(t, str) for t in topics):
            raise P.BridgeError("bad_request", "topics must be a list of names.")
        subscribed, unavailable = [], []
        for topic in dict.fromkeys(topics):
            if topic not in self.features:
                unavailable.append(topic)
                continue
            subscribed.append(topic)
        if not subscribed and unavailable:
            raise P.BridgeError("unavailable", f"Not served: {', '.join(unavailable)}.")
        for topic in subscribed:
            session.subscribed.add(topic)
            relay = self._relay_for(session, topic)
            if relay is not None and topic in P.SNAPSHOT_TOPICS:
                # The reply goes first; the snapshot follows before any delta.
                asyncio.get_running_loop().call_soon(
                    lambda r=relay, t=topic: asyncio.ensure_future(r.subscribe(t))
                )
            elif relay is not None:
                await relay.subscribe(topic)
        return {"subscribed": subscribed, "unavailable": unavailable}

    async def _unsubscribe(self, session: BridgeSession, msg: P.Inbound) -> dict[str, Any]:
        topics = msg.data.get("topics")
        if not isinstance(topics, list) or not all(isinstance(t, str) for t in topics):
            raise P.BridgeError("bad_request", "topics must be a list of names.")
        done = []
        for topic in dict.fromkeys(topics):
            if topic in session.subscribed:
                session.subscribed.discard(topic)
                session.outbox.clear_topic(topic)
                session.last_seq_of.pop(topic, None)
                relay = self._relay_for(session, topic)
                if relay is not None:
                    await relay.unsubscribe(topic)
            done.append(topic)
        return {"unsubscribed": done}

    async def _resync(self, session: BridgeSession, msg: P.Inbound) -> dict[str, Any]:
        topic = msg.data.get("topic")
        if not isinstance(topic, str) or topic not in P.BASE_FEATURES + ("duel_stats",):
            raise P.BridgeError("bad_request", "Unknown topic.")
        if topic not in self.features:
            raise P.BridgeError("unavailable", f"{topic} is not served.")
        relay = self._relay_for(session, topic)
        pane_id = msg.data.get("pane_id")
        if topic == "screens" and pane_id is not None:
            if pane_id not in getattr(relay, "watched", {}):
                raise P.BridgeError("not_found", "Pane is not watched.")
        if relay is not None:
            asyncio.get_running_loop().call_soon(
                lambda: asyncio.ensure_future(relay.resync(topic, msg.data))
            )
        return {}

    # ------------------------------------------------------------------ serving
    async def serve(self, transport: Transport, peer_host: str | None) -> int:
        """Run one connection to its end; returns the close code it ended with."""
        if not is_loopback(peer_host):
            await transport.close(P.CLOSE_PEER, "loopback only")
            return P.CLOSE_PEER
        hello = await self._handshake(transport)
        if isinstance(hello, int):
            return hello
        previous = self.current
        session = BridgeSession(self, transport, hello, session_id=f"vb-{next(self._ids):04x}")
        if previous is not None:
            await previous.close(P.CLOSE_REPLACED, "replaced")
            await self._end(previous)
        self.current = session
        tasks: list[asyncio.Task[Any]] = []
        try:
            for factory in self.relay_factories:
                session.relays.append(factory(session))
            welcome = self.build_welcome(session)
            session.send("welcome", welcome)
            tasks = [
                asyncio.create_task(session.writer(), name="verse-bridge-writer"),
                asyncio.create_task(session.watchdog(), name="verse-bridge-watchdog"),
            ]
            for relay in session.relays:
                await relay.start()
            if self.on_session is not None:
                await self.on_session(session)
            await session.reader()
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(BaseException):
                    await task
            await self._end(session)
        return session.close_code or 1000

    async def _end(self, session: BridgeSession) -> None:
        relays, session.relays = session.relays, []
        for relay in relays:
            with contextlib.suppress(Exception):
                await relay.stop()
        if self.current is session:
            self.current = None
            if self.on_session is not None:
                with contextlib.suppress(Exception):
                    await self.on_session(None)

    async def _handshake(self, transport: Transport) -> P.Inbound | int:
        try:
            raw = await asyncio.wait_for(transport.receive(), P.HELLO_TIMEOUT_S)
        except TimeoutError:
            await transport.close(P.CLOSE_BAD_HELLO, "hello timeout")
            return P.CLOSE_BAD_HELLO
        except TransportClosed:
            return 1000
        try:
            hello = P.parse(raw)
        except P.MalformedFrame:
            await transport.close(P.CLOSE_BAD_HELLO, "malformed hello")
            return P.CLOSE_BAD_HELLO
        if hello.type != "hello":
            await transport.close(P.CLOSE_BAD_HELLO, "expected hello frame first")
            return P.CLOSE_BAD_HELLO
        token = hello.data.get("token")
        protocols = hello.data.get("protocols")
        if not isinstance(token, str) or not isinstance(protocols, list):
            await transport.close(P.CLOSE_BAD_HELLO, "hello needs token and protocols")
            return P.CLOSE_BAD_HELLO
        if not self.check_token(token):
            await transport.close(P.CLOSE_TOKEN, "unauthorized")
            return P.CLOSE_TOKEN
        if not any(p in P.SUPPORTED_PROTOCOLS for p in protocols):
            await transport.close(P.CLOSE_PROTOCOL, P.welcome_reason_unsupported())
            return P.CLOSE_PROTOCOL
        build = hello.data.get("build") if isinstance(hello.data.get("build"), dict) else {}
        log.info(
            "verse bridge: hello from pid %s build %s %s",
            hello.data.get("pid"),
            build.get("version"),
            build.get("changelist"),
        )
        return hello

    async def push_all(self, type_: str, data: dict[str, Any], *, topic: str = "lifecycle") -> bool:
        """Send one server event to the live session; False when none is connected."""
        session = self.current
        if session is None or session.closed.is_set():
            return False
        session.send(type_, data, topic=None)
        return True

    async def disconnect(self, code: int = 4401, reason: str = "launch over") -> None:
        if self.current is not None:
            await self.current.close(code, reason)


class TokenBox:
    """The tokens valid right now: the running launch's and the dev discovery one."""

    def __init__(self) -> None:
        self._tokens: dict[str, str] = {}

    def set(self, slot: str, token: str | None) -> None:
        if token:
            self._tokens[slot] = token
        else:
            self._tokens.pop(slot, None)

    def check(self, token: str) -> bool:
        ok = False
        for valid in self._tokens.values():
            # Compare against every slot so timing does not tell which one matched.
            ok |= hmac.compare_digest(valid.encode(), token.encode())
        return ok

    def __bool__(self) -> bool:
        return bool(self._tokens)


def app_pid() -> int:
    return os.getpid()
