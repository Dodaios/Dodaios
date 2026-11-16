# === F-FRIENDS [F0] · feature/friends-section · ruben-2026-04-30 ===
"""ChannelManager: discovery + lifecycle for all registered channels.

Analogous to :class:`dodaios.harness.manager.HarnessManager`, but for channels.
Channels require more dependencies (EventBus + optional FriendRegistry +
platform-specific config), so the bus and dependencies are bundled in
a :class:`ChannelContext` and passed to plugins.

Discovery:
    Lazy-load via ``dodaios.core.entry_points.entry_points(group="jarvis.channel")``,
    which also reads the group's ``dodaios.channel`` spelling.
    Failed loads end up in ``self._failed_load`` and do not block the others.

Instantiation:
    Channels may optionally implement ``classmethod from_context(ctx)``
    to pull arbitrary dependencies from the :class:`ChannelContext`.
    If the method is absent, ``cls(ctx.bus)`` is used as a fallback
    — this keeps the existing ``WebChannel`` compatible.

Lifecycle:
    ``start_all()`` starts all channels but collects errors individually.
    ``stop_all()`` is symmetric and idempotent.

Retry:
    A start that fails for a passing reason (no network yet, a timeout, a
    refused connection, a failed DNS lookup) is tried again in the background
    after growing waits (:data:`RETRY_DELAYS_S`) until the channel is up. The
    app starts at login, often before the network is, so a first Telegram
    ``getMe`` that times out is the normal case at boot. A lasting failure (no
    token, a refused token, a missing library, a programming error) is not
    tried again; :func:`is_transient_start_error` makes that call. ``start``,
    ``stop``, ``reload`` and ``stop_all`` cancel a pending retry. A channel a
    retry starts is announced to the late-start listeners, so whatever binds
    to channels at boot (the chat bridge's consumers) binds to it as well.

One at a time:
    ``start``, ``stop`` and ``reload`` of one channel never overlap (a lock per
    channel). Two reloads at once (a connect and a "pair again" a moment
    later) would otherwise both build and start an instance, and the one the
    manager forgot would keep its link open, unstopped, taking messages
    nobody reads.
"""

from __future__ import annotations

import asyncio
import errno
import logging
from collections.abc import Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from dodaios.core.bus import EventBus
from dodaios.core.entry_points import entry_points
from dodaios.core.protocols import ChannelAdapter

if TYPE_CHECKING:  # pragma: no cover
    from dodaios.friends.registry import FriendRegistry

log = logging.getLogger(__name__)

PLUGIN_GROUP = "jarvis.channel"

#: Waits before each background retry of a start that failed for a passing
#: reason; the last one repeats until the channel is up. The first ones are
#: seconds: the app starts at login, often before the network is up.
RETRY_DELAYS_S: tuple[float, ...] = (5.0, 10.0, 20.0, 30.0, 60.0, 120.0, 300.0, 600.0)

#: Called with a channel's name after a background retry started it.
LateStartListener = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class ChannelContext:
    """Dependencies that channels can receive upon instantiation."""

    bus: EventBus
    friend_registry: FriendRegistry | None = None
    config: dict[str, Any] = field(default_factory=dict)


class ChannelManagerError(RuntimeError):
    """Base class for ChannelManager-specific errors."""


class ChannelStartError(ChannelManagerError):
    """Channel could not be started (token missing, connection refused).

    ``transient`` is the channel's own verdict on whether a later try may work.
    A channel sets it when it drops the original error to keep a credential
    out of every traceback, so the error's type still decides (see
    :func:`is_transient_start_error`). ``None`` leaves the call to the cause
    and the text.
    """

    def __init__(self, *args: object, transient: bool | None = None) -> None:
        super().__init__(*args)
        self.transient = transient


# ----------------------------------------------------------------------
# Passing or lasting: may a failed start work when tried again later?
# ----------------------------------------------------------------------

#: Error types of a start that may work later: the network is not up yet, a
#: host is briefly unreachable, a server is overloaded or asks to wait. Keyed
#: by (top-level package, class name), so the optional chat libraries need not
#: be imported to tell their errors; a subclass matches through its MRO.
_PASSING_TYPES: frozenset[tuple[str, str]] = frozenset(
    {
        ("builtins", "TimeoutError"),  # asyncio.TimeoutError too
        ("builtins", "ConnectionError"),  # refused, reset, aborted, broken pipe
        ("socket", "gaierror"),  # DNS: no network yet at login
        ("socket", "herror"),
        ("telegram", "TimedOut"),
        ("telegram", "NetworkError"),
        ("telegram", "RetryAfter"),
        ("httpx", "TimeoutException"),
        ("httpx", "NetworkError"),
        ("httpx", "RemoteProtocolError"),
        ("httpx", "ProxyError"),
        ("httpcore", "TimeoutException"),
        ("httpcore", "NetworkError"),
        ("httpcore", "RemoteProtocolError"),
        ("aiohttp", "ClientConnectionError"),
        ("discord", "DiscordServerError"),
        ("discord", "GatewayNotFound"),
    }
)

#: Error types no retry can fix: a missing or refused credential, a request
#: the server refuses, a library that is not installed, a programming error.
#: Checked before the passing ones at each step of the MRO, so a subclass
#: listed here wins over its passing base (Telegram's ``BadRequest`` is a
#: ``NetworkError``).
_LASTING_TYPES: frozenset[tuple[str, str]] = frozenset(
    {
        ("builtins", "ImportError"),
        ("builtins", "TypeError"),
        ("builtins", "AttributeError"),
        ("builtins", "NameError"),
        ("builtins", "LookupError"),
        ("builtins", "ValueError"),
        ("builtins", "AssertionError"),
        ("builtins", "NotImplementedError"),
        ("telegram", "InvalidToken"),
        ("telegram", "Unauthorized"),  # python-telegram-bot before 20
        ("telegram", "Forbidden"),
        ("telegram", "BadRequest"),
        ("telegram", "Conflict"),
        ("telegram", "EndPointNotFound"),
        ("discord", "LoginFailure"),
        ("discord", "PrivilegedIntentsRequired"),
        ("discord", "Forbidden"),
        ("discord", "NotFound"),
    }
)

#: ``OSError`` numbers of a network that is down or not up yet. A Mac that has
#: just logged in has no address yet ("Can't assign requested address").
_NETWORK_ERRNOS: frozenset[int] = frozenset(
    number
    for number in (
        getattr(errno, name, None)
        for name in (
            "ENETDOWN",
            "ENETUNREACH",
            "ENETRESET",
            "EHOSTDOWN",
            "EHOSTUNREACH",
            "ECONNABORTED",
            "ECONNRESET",
            "ECONNREFUSED",
            "ETIMEDOUT",
            "EADDRNOTAVAIL",
            "WSAENETDOWN",
            "WSAENETUNREACH",
            "WSAEHOSTDOWN",
            "WSAEHOSTUNREACH",
            "WSAECONNABORTED",
            "WSAECONNRESET",
            "WSAECONNREFUSED",
            "WSAETIMEDOUT",
            "WSAEADDRNOTAVAIL",
        )
    )
    if number is not None
)

#: Read only when no type in the error chain is known (a plugin channel that
#: raises a bare ``RuntimeError``, say). A lasting word wins over a passing one.
_LASTING_WORDS: tuple[str, ...] = (
    "invalidtoken",
    "invalid token",
    "token invalid",
    "token missing",
    "unauthorized",
    "forbidden",
    "loginfailure",
    "improper token",
    "not installed",
)
_PASSING_WORDS: tuple[str, ...] = (
    "timed out",
    "timedout",
    "timeout",
    "connection refused",
    "connection reset",
    "connection aborted",
    "network is unreachable",
    "network is down",
    "no route to host",
    "host is down",
    "can't assign requested address",
    "nodename nor servname",
    "name or service not known",
    "name resolution",
    "getaddrinfo failed",
    "cannot connect to host",
    "connecterror",
    "connecttimeout",
    "networkerror",
    "server disconnected",
    "temporarily unavailable",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
)


def is_transient_start_error(exc: BaseException) -> bool:
    """Whether a channel start that failed with ``exc`` may work when tried later.

    Type first: a ``ChannelStartError`` carrying the channel's own verdict,
    then the error and its causes (``__cause__``, else ``__context__``)
    against the lasting and passing types, and an ``OSError`` by its network
    errno. The outermost error with a known type decides. Only when no type
    tells is the text read. Anything still unknown counts as lasting: it is
    not tried again.
    """
    chain = list(_error_chain(exc))
    for item in chain:
        verdict = _verdict_by_type(item)
        if verdict is not None:
            return verdict
    text = " ".join(str(item) for item in chain).lower()
    if any(word in text for word in _LASTING_WORDS):
        return False
    return any(word in text for word in _PASSING_WORDS)


def _error_chain(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(seen) < 16:
        seen.add(id(current))
        yield current
        if current.__cause__ is not None:
            current = current.__cause__
        elif current.__suppress_context__:  # ``raise ... from None``: the chain ends here
            current = None
        else:
            current = current.__context__


def _verdict_by_type(exc: BaseException) -> bool | None:
    if isinstance(exc, ChannelStartError) and exc.transient is not None:
        return exc.transient
    for cls in type(exc).__mro__:
        key = (cls.__module__.partition(".")[0], cls.__name__)
        if key in _LASTING_TYPES:
            return False
        if key in _PASSING_TYPES:
            return True
    if isinstance(exc, OSError) and exc.errno in _NETWORK_ERRNOS:
        return True
    return None


def _redacted(exc: BaseException) -> str:
    from dodaios.core.redact import redact_secrets

    # A channel error may carry a credential (a Telegram token sits in every
    # Bot API URL): only a redacted text is stored, logged or raised.
    return redact_secrets(str(exc))


def _wait_text(seconds: float) -> str:
    return f"{seconds / 60:g} min" if seconds >= 60 else f"{seconds:g} s"


class ChannelManager:
    """Discovery + lifecycle for all channels (Web, Telegram, ...)."""

    def __init__(
        self,
        context: ChannelContext,
        *,
        retry_delays: Sequence[float] = RETRY_DELAYS_S,
        sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
    ) -> None:
        self._ctx = context
        self._classes: dict[str, type] = {}
        self._failed_load: dict[str, str] = {}
        self._instances: dict[str, ChannelAdapter] = {}
        self._start_errors: dict[str, str] = {}
        self._loaded = False
        self._started: set[str] = set()
        self._retry_delays = tuple(retry_delays) or RETRY_DELAYS_S
        self._sleep = sleep
        #: One background retry task per channel whose start failed for a
        #: passing reason; gone once it started the channel or gave up.
        self._retries: dict[str, asyncio.Task[None]] = {}
        self._late_start_listeners: list[LateStartListener] = []
        #: One lock per channel: its start, stop and reload never overlap.
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, name: str) -> asyncio.Lock:
        lock = self._locks.get(name)
        if lock is None:
            lock = self._locks[name] = asyncio.Lock()
        return lock

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _load_classes(self) -> None:
        if self._loaded:
            return
        for ep in entry_points(group=PLUGIN_GROUP):
            try:
                cls = ep.load()
                self._classes[ep.name] = cls
            except Exception as exc:  # noqa: BLE001
                self._failed_load[ep.name] = f"{type(exc).__name__}: {exc}"
                log.warning("Channel '%s' load failed: %s", ep.name, exc)
        self._loaded = True

    def available(self) -> list[str]:
        self._load_classes()
        return sorted(self._classes.keys())

    def failed(self) -> dict[str, str]:
        self._load_classes()
        return dict(self._failed_load)

    def start_errors(self) -> dict[str, str]:
        return dict(self._start_errors)

    def started(self) -> list[str]:
        return sorted(self._started)

    def retrying(self) -> list[str]:
        """Channels whose start failed for a passing reason and is tried again."""
        return sorted(
            name
            for name, task in self._retries.items()
            if not task.done() and name not in self._started
        )

    # ------------------------------------------------------------------
    # Late starts
    # ------------------------------------------------------------------

    def add_late_start_listener(self, listener: LateStartListener) -> None:
        """Call ``await listener(name)`` whenever a background retry started a channel.

        A start the caller of :meth:`start` / :meth:`start_all` did not see:
        whatever it bound to the channels started then must bind to this one
        too. A listener that raises is logged; the channel stays started.
        """
        if listener not in self._late_start_listeners:
            self._late_start_listeners.append(listener)

    def remove_late_start_listener(self, listener: LateStartListener) -> None:
        if listener in self._late_start_listeners:
            self._late_start_listeners.remove(listener)

    # ------------------------------------------------------------------
    # Context (mutable so a live reload can pick up fresh config)
    # ------------------------------------------------------------------

    @property
    def context(self) -> ChannelContext:
        return self._ctx

    def set_context(self, context: ChannelContext) -> None:
        """Swap the context used to instantiate channels from now on.

        Existing cached instances are untouched; call :meth:`reload` to rebuild
        a single channel against the new context (used by the marketplace
        connect flow to apply a freshly written config without a restart).
        """
        self._ctx = context

    # ------------------------------------------------------------------
    # Instantiation
    # ------------------------------------------------------------------

    def get(self, name: str) -> ChannelAdapter:
        self._load_classes()
        if name in self._instances:
            return self._instances[name]
        if name not in self._classes:
            raise KeyError(
                f"Channel '{name}' not available. "
                f"Known: {self.available()}. Failed: {list(self._failed_load)}."
            )
        cls = self._classes[name]
        instance = self._instantiate(cls)
        self._instances[name] = instance
        return instance

    def _instantiate(self, cls: type) -> ChannelAdapter:
        from_context = getattr(cls, "from_context", None)
        if callable(from_context):
            return from_context(self._ctx)
        return cls(self._ctx.bus)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, name: str) -> None:
        """Start ``name``; raise :class:`ChannelStartError` when it fails.

        A failure for a passing reason is also tried again in the background
        (see :meth:`retrying`); the error stays in :meth:`start_errors` until
        a retry succeeds.
        """
        async with self._lock(name):
            await self._start_locked(name)

    async def _start_locked(self, name: str) -> None:
        if name in self._started:
            return
        # Two starts of one instance never run at once: a direct start
        # replaces a pending retry.
        await self._cancel_retry(name)
        try:
            await self.get(name).start()
        except Exception as exc:  # noqa: BLE001
            detail = self._record_start_error(name, exc)
            passing = is_transient_start_error(exc)
            if passing:
                # Expected at login (no network yet): a warning, not an error.
                log.warning(
                    "Channel '%s' start failed: %s; trying again in %s",
                    name,
                    detail,
                    _wait_text(self._retry_delays[0]),
                )
                self._schedule_retry(name)
            else:
                log.error("Channel '%s' start failed: %s", name, detail)
            raise ChannelStartError(
                f"Channel '{name}' could not start: {detail}", transient=passing
            ) from None
        self._started.add(name)
        log.info("Channel '%s' started", name)

    def _record_start_error(self, name: str, exc: BaseException) -> str:
        detail = _redacted(exc)
        self._start_errors[name] = f"{type(exc).__name__}: {detail}"
        return detail

    def _schedule_retry(self, name: str) -> None:
        pending = self._retries.get(name)
        if pending is not None and not pending.done():
            return  # one retry per channel: two concurrent starts failed alike
        self._retries[name] = asyncio.create_task(
            self._retry(name), name=f"channel-start-retry:{name}"
        )

    async def _retry(self, name: str) -> None:
        """Start ``name`` again after growing waits, until it is up or fails for good."""
        attempt = 0
        try:
            while True:
                await self._sleep(self._retry_delays[min(attempt, len(self._retry_delays) - 1)])
                attempt += 1
                try:
                    await self.get(name).start()
                except Exception as exc:  # noqa: BLE001 — logged below, redacted
                    detail = self._record_start_error(name, exc)
                    if not is_transient_start_error(exc):
                        log.warning(
                            "Channel '%s' retry %d failed for good, no more retries: %s",
                            name,
                            attempt,
                            detail,
                        )
                        return
                    log.info(
                        "Channel '%s' retry %d failed: %s; next try in %s",
                        name,
                        attempt,
                        detail,
                        _wait_text(self._retry_delays[min(attempt, len(self._retry_delays) - 1)]),
                    )
                    continue
                self._started.add(name)
                self._start_errors.pop(name, None)
                log.info("Channel '%s' started on retry %d", name, attempt)
                await self._announce_late_start(name)
                return
        finally:
            # A cancelled retry was already taken out (and may be replaced).
            if self._retries.get(name) is asyncio.current_task():
                del self._retries[name]

    async def _announce_late_start(self, name: str) -> None:
        for listener in list(self._late_start_listeners):
            try:
                await listener(name)
            except Exception as exc:  # noqa: BLE001 — a listener never undoes the start
                log.warning("Channel '%s' late-start listener failed: %s", name, _redacted(exc))

    async def _cancel_retry(self, name: str) -> None:
        """Cancel ``name``'s pending retry and wait until it has ended.

        A retry in the middle of an attempt is cancelled too: the channel's
        ``start()`` then cleans up what it began (a stop, a reload or the
        shutdown must not wait for a network timeout).
        """
        task = self._retries.pop(name, None)
        if task is None or task is asyncio.current_task():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def reload(self, name: str) -> None:
        """Stop, drop the cached instance, and start ``name`` afresh.

        Re-instantiates from the current context, so a config swapped in via
        :meth:`set_context` takes effect. Raises :class:`ChannelStartError` if
        the fresh start fails (same contract as :meth:`start`). A pending retry
        of the old instance is cancelled first.
        """
        async with self._lock(name):
            await self._stop_locked(name)
            old = self._instances.pop(name, None)
            self._start_errors.pop(name, None)
            self._carry_over(old, name)
            await self._start_locked(name)

    def _carry_over(self, old: Any, name: str) -> None:
        """Hand the old instance's approval-button handler to the new one.

        The approval bridge sets ``on_approval_callback`` on the instance it
        sends a request through; without this a button on a message sent
        before the reload would do nothing.
        """
        callback = getattr(old, "on_approval_callback", None)
        if callback is None:
            return
        try:
            fresh = self.get(name)
        except Exception:  # noqa: BLE001 — the start below reports a channel that cannot be built
            return
        if getattr(fresh, "on_approval_callback", "absent") is None:
            fresh.on_approval_callback = callback  # type: ignore[attr-defined]

    async def start_all(self) -> dict[str, str]:
        names = self.available()
        if not names:
            return {}
        results = await asyncio.gather(*(self._start_safe(n) for n in names))
        return {n: err for n, err in zip(names, results, strict=True) if err is not None}

    async def _start_safe(self, name: str) -> str | None:
        try:
            await self.start(name)
            return None
        except ChannelStartError as exc:
            return str(exc)
        except Exception as exc:  # noqa: BLE001
            return f"{type(exc).__name__}: {_redacted(exc)}"

    async def stop(self, name: str) -> None:
        """Stop ``name``; a pending retry is cancelled, so it never starts it later."""
        async with self._lock(name):
            await self._stop_locked(name)

    async def _stop_locked(self, name: str) -> None:
        await self._cancel_retry(name)
        if name not in self._started:
            return
        instance = self._instances.get(name)
        if instance is None:
            self._started.discard(name)
            return
        try:
            await instance.stop()
        except Exception as exc:  # noqa: BLE001
            log.warning("Channel '%s' stop raised: %s", name, _redacted(exc))
        finally:
            self._started.discard(name)
            log.info("Channel '%s' stopped", name)

    async def stop_all(self) -> None:
        """Stop every started channel and cancel every pending retry."""
        retrying = list(self._retries)
        if retrying:
            await asyncio.gather(*(self._cancel_retry(n) for n in retrying), return_exceptions=True)
        names = list(self._started)
        if not names:
            return
        await asyncio.gather(*(self.stop(n) for n in names), return_exceptions=True)
