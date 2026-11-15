"""A channel whose start fails for a passing reason is tried again in the background.

The app starts at login, often before the network is up, so Telegram's first
``getMe`` times out. Before the retry the channel then stayed off until the
next restart (2026-11-15). These tests drive :class:`ChannelManager` with fake
channels and a stand-in ``sleep`` that records each wait, so no test waits
for a real delay and nothing goes out on the network.
"""

from __future__ import annotations

import asyncio
import errno
import logging
import socket
import sys
import types
import warnings
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
import telegram.error as tg_error

from dodaios.channels.base import ChannelMessage, ChannelSession
from dodaios.channels.chat_bridge import ChannelChatBridge
from dodaios.channels.manager import (
    ChannelContext,
    ChannelManager,
    ChannelStartError,
    is_transient_start_error,
)
from dodaios.channels.telegram import TelegramChannel
from dodaios.core.bus import EventBus
from dodaios.core.config import TelegramConfig
from dodaios.core.events import Event, MessageSent

FAKE_TOKEN = "987654321:AAFakeTokenForTestsOnly_abcdefghijklmnop"  # noqa: S105 - a fake


# --- helpers ---------------------------------------------------------------------


class _Channel:
    """``start()`` raises the queued ``failures`` one by one, then starts.

    With ``hold`` set, a start that is not failing waits for it first (an
    attempt still in flight), and notes whether it was cancelled there.
    """

    name = "flaky"
    made: list[_Channel] = []

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self.failures: list[BaseException] = []
        self.hold: asyncio.Event | None = None
        self.attempts = 0
        self.started = False
        self.stopped = False
        self.cancelled = False
        self.queue: asyncio.Queue[ChannelMessage] = asyncio.Queue()
        type(self).made.append(self)

    async def start(self) -> None:
        self.attempts += 1
        if self.failures:
            raise self.failures.pop(0)
        if self.hold is not None:
            try:
                await self.hold.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        self.started = True

    async def stop(self) -> None:
        self.stopped = True
        self.started = False

    async def send_message(self, msg: ChannelMessage) -> None: ...
    async def broadcast_event(self, event: Event) -> None: ...

    async def messages(self) -> AsyncIterator[ChannelMessage]:
        while True:
            yield await self.queue.get()

    async def sessions(self) -> list[ChannelSession]:
        return []


@dataclass
class _EntryPoint:
    name: str
    target: Any

    def load(self) -> Any:
        return self.target


def _patch_channels(monkeypatch: pytest.MonkeyPatch, **classes: type) -> None:
    eps = [_EntryPoint(name=name, target=cls) for name, cls in classes.items()]

    def _fake_entry_points(*, group: str) -> list[_EntryPoint]:
        return eps if group == "jarvis.channel" else []

    monkeypatch.setattr("dodaios.channels.manager.entry_points", _fake_entry_points)


def _manager(
    monkeypatch: pytest.MonkeyPatch,
    *names: str,
    sleep: Callable[[float], Awaitable[object]],
    delays: tuple[float, ...] = (5.0, 10.0, 20.0),
) -> ChannelManager:
    _patch_channels(monkeypatch, **{name: _Channel for name in names})
    return ChannelManager(ChannelContext(bus=EventBus()), retry_delays=delays, sleep=sleep)


class _Clock:
    """Stands in for ``asyncio.sleep``: records each wait. ``hold=True`` keeps
    every wait open until :meth:`release` (a retry that is still pending)."""

    def __init__(self, *, hold: bool = False) -> None:
        self.waits: list[float] = []
        self._open = asyncio.Event()
        if not hold:
            self._open.set()

    async def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        await self._open.wait()
        await asyncio.sleep(0)

    def release(self) -> None:
        self._open.set()


async def _until(check: Callable[[], bool], within_s: float = 3.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + within_s
    while not check():
        assert loop.time() < deadline, "the expected state was not reached in time"
        await asyncio.sleep(0.01)


def _retry_tasks() -> list[asyncio.Task[Any]]:
    return [
        task
        for task in asyncio.all_tasks()
        if task.get_name().startswith("channel-start-retry:") and not task.done()
    ]


def _caused_by(error: BaseException, cause: BaseException) -> BaseException:
    error.__cause__ = cause  # as ``raise error from cause`` leaves it
    return error


def _retry_after(seconds: int) -> BaseException:
    with warnings.catch_warnings():
        # python-telegram-bot 22.2+ announces a type change of ``retry_after``.
        warnings.simplefilter("ignore", DeprecationWarning)
        return tg_error.RetryAfter(seconds)


# --- passing or lasting -----------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(tg_error.TimedOut(), id="telegram-timed-out"),
        pytest.param(
            tg_error.NetworkError(
                "httpx.ConnectError: [Errno 8] nodename nor servname provided, or not known"
            ),
            id="telegram-no-dns-yet",
        ),
        pytest.param(_retry_after(3), id="telegram-asks-to-wait"),
        pytest.param(httpx.ConnectError("All connection attempts failed"), id="httpx-connect"),
        pytest.param(httpx.ConnectTimeout("timed out"), id="httpx-connect-timeout"),
        pytest.param(
            socket.gaierror(socket.EAI_NONAME, "nodename nor servname provided, or not known"),
            id="dns-failure",
        ),
        pytest.param(OSError(errno.ENETUNREACH, "Network is unreachable"), id="no-network"),
        pytest.param(
            OSError(errno.EADDRNOTAVAIL, "Can't assign requested address"), id="no-address-yet"
        ),
        pytest.param(ConnectionRefusedError(errno.ECONNREFUSED, "refused"), id="refused"),
        pytest.param(ConnectionResetError(errno.ECONNRESET, "reset by peer"), id="reset"),
        pytest.param(TimeoutError(), id="timeout"),  # asyncio.TimeoutError is this one
        pytest.param(ChannelStartError("anything", transient=True), id="channel-says-passing"),
        pytest.param(
            ChannelStartError("Telegram getMe failed: TimedOut: Timed out"),
            id="only-the-text-tells",
        ),
        pytest.param(
            _caused_by(
                ChannelStartError("Discord login failed: x"),
                OSError(errno.EHOSTUNREACH, "No route to host"),
            ),
            id="the-cause-tells",
        ),
    ],
)
def test_a_network_problem_is_passing(error: BaseException) -> None:
    assert is_transient_start_error(error) is True


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(tg_error.InvalidToken("Unauthorized"), id="telegram-refused-token"),
        pytest.param(tg_error.Forbidden("Forbidden"), id="telegram-forbidden"),
        # A NetworkError subclass by type, yet a request Telegram refused.
        pytest.param(tg_error.BadRequest("Bad Request: chat not found"), id="telegram-bad-request"),
        pytest.param(
            ChannelStartError("Telegram token missing. Setup: run the wizard."), id="no-token"
        ),
        pytest.param(
            ChannelStartError("Telegram token invalid (InvalidToken). Check the token."),
            id="token-refused-text",
        ),
        pytest.param(ChannelStartError("Timed out", transient=False), id="channel-says-lasting"),
        pytest.param(
            _caused_by(
                ChannelStartError("python-telegram-bot not installed."), ImportError("telegram")
            ),
            id="library-missing",
        ),
        pytest.param(KeyError("Channel 'x' not available."), id="unknown-channel"),
        pytest.param(TypeError("start() takes 1 positional argument"), id="programming-error"),
        pytest.param(AttributeError("'NoneType' has no attribute 'bot'"), id="attribute-error"),
        pytest.param(FileNotFoundError(errno.ENOENT, "No such file"), id="file-not-found"),
        pytest.param(RuntimeError("something nobody expected"), id="unknown-error"),
    ],
)
def test_a_refused_token_a_missing_setup_or_a_bug_is_lasting(error: BaseException) -> None:
    assert is_transient_start_error(error) is False


def test_discord_and_aiohttp_errors_are_told_apart() -> None:
    discord = pytest.importorskip("discord")
    aiohttp = pytest.importorskip("aiohttp")
    no_server = _caused_by(
        ChannelStartError("Discord login failed: Server disconnected"),
        aiohttp.ServerDisconnectedError(),
    )
    refused = _caused_by(
        ChannelStartError("Discord token invalid (LoginFailure)."),
        discord.LoginFailure("Improper token has been passed."),
    )
    assert is_transient_start_error(no_server) is True
    assert is_transient_start_error(discord.GatewayNotFound()) is True
    assert is_transient_start_error(refused) is False


# --- the retry ---------------------------------------------------------------------


async def test_a_start_that_times_out_is_tried_again_until_it_works(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    clock = _Clock(hold=True)
    manager = _manager(monkeypatch, "flaky", sleep=clock.sleep, delays=(5.0, 10.0, 20.0))
    channel = manager.get("flaky")
    channel.failures = [TimeoutError("getMe timed out"), TimeoutError("getMe timed out")]
    late: list[str] = []

    async def _late(name: str) -> None:
        late.append(name)

    manager.add_late_start_listener(_late)
    with caplog.at_level(logging.INFO, logger="dodaios.channels.manager"):
        errors = await manager.start_all()
        assert "flaky" in errors
        await _until(lambda: clock.waits == [5.0])
        # While it waits: not started, the error is shown, a retry is pending.
        assert manager.started() == []
        assert manager.retrying() == ["flaky"]
        assert "TimeoutError" in manager.start_errors()["flaky"]

        clock.release()
        await _until(lambda: "flaky" in manager.started())
        await _until(lambda: not _retry_tasks())

    assert channel.attempts == 3  # the boot start and two retries
    assert clock.waits == [5.0, 10.0]
    assert manager.start_errors() == {}
    assert manager.retrying() == []
    assert late == ["flaky"]
    lines = [r.getMessage() for r in caplog.records if r.name == "dodaios.channels.manager"]
    assert lines.count("Channel 'flaky' started on retry 2") == 1
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    await manager.stop_all()
    assert channel.stopped is True


async def test_the_last_wait_repeats_until_the_channel_is_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    manager = _manager(monkeypatch, "flaky", sleep=clock.sleep, delays=(1.0, 2.0))
    channel = manager.get("flaky")
    channel.failures = [TimeoutError("timed out") for _ in range(5)]
    with pytest.raises(ChannelStartError):
        await manager.start("flaky")
    await _until(lambda: "flaky" in manager.started())
    assert clock.waits == [1.0, 2.0, 2.0, 2.0, 2.0]
    await manager.stop_all()


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(
            ChannelStartError(
                "Telegram token invalid (InvalidToken). Check the token or renew it."
            ),
            id="refused-token",
        ),
        pytest.param(tg_error.InvalidToken("Unauthorized"), id="refused-token-raw"),
        pytest.param(ChannelStartError("Telegram token missing. Setup: ..."), id="no-token"),
        pytest.param(TypeError("start() takes 1 positional argument"), id="programming-error"),
    ],
)
async def test_a_lasting_failure_is_not_tried_again(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, error: BaseException
) -> None:
    clock = _Clock()
    manager = _manager(monkeypatch, "flaky", sleep=clock.sleep)
    channel = manager.get("flaky")
    channel.failures = [error]
    with caplog.at_level(logging.INFO, logger="dodaios.channels.manager"):
        with pytest.raises(ChannelStartError) as raised:
            await manager.start("flaky")
        for _ in range(5):  # a retry, had one been made, would have begun to wait
            await asyncio.sleep(0)
    assert raised.value.transient is False
    assert manager.retrying() == [] and not _retry_tasks()
    assert clock.waits == []
    assert channel.attempts == 1
    assert "flaky" in manager.start_errors()
    failed = [r for r in caplog.records if "start failed" in r.getMessage()]
    assert [r.levelno for r in failed] == [logging.ERROR]


async def test_stop_cancels_a_pending_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock(hold=True)
    manager = _manager(monkeypatch, "flaky", sleep=clock.sleep)
    channel = manager.get("flaky")
    channel.failures = [TimeoutError("timed out")]
    with pytest.raises(ChannelStartError):
        await manager.start("flaky")
    await _until(lambda: clock.waits == [5.0])

    await manager.stop("flaky")
    assert manager.retrying() == [] and not _retry_tasks()
    clock.release()  # the wait would be over now: nothing may start
    for _ in range(5):
        await asyncio.sleep(0)
    assert channel.attempts == 1
    assert manager.started() == [] and channel.started is False


async def test_stop_during_a_retry_attempt_leaves_the_channel_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    manager = _manager(monkeypatch, "flaky", sleep=clock.sleep)
    channel = manager.get("flaky")
    channel.failures = [TimeoutError("timed out")]
    channel.hold = asyncio.Event()  # the retry's attempt hangs (no answer yet)
    with pytest.raises(ChannelStartError):
        await manager.start("flaky")
    await _until(lambda: channel.attempts == 2)

    await manager.stop("flaky")
    assert channel.cancelled is True  # the attempt was cancelled, not awaited to its end
    assert manager.started() == [] and manager.retrying() == [] and not _retry_tasks()
    channel.hold.set()
    for _ in range(5):
        await asyncio.sleep(0)
    assert channel.started is False


async def test_reload_replaces_a_pending_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock(hold=True)
    manager = _manager(monkeypatch, "flaky", sleep=clock.sleep)
    old = manager.get("flaky")
    old.failures = [TimeoutError("timed out")]
    with pytest.raises(ChannelStartError):
        await manager.start("flaky")
    await _until(lambda: clock.waits == [5.0])

    await manager.reload("flaky")  # a fresh instance, started at once
    new = manager.get("flaky")
    assert new is not old and new.started is True
    assert manager.started() == ["flaky"]
    assert manager.retrying() == [] and manager.start_errors() == {}
    clock.release()
    for _ in range(5):
        await asyncio.sleep(0)
    assert old.attempts == 1  # the old instance's retry never ran
    await manager.stop_all()


async def test_stop_all_leaves_no_retry_behind(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock(hold=True)
    manager = _manager(monkeypatch, "flaky", "other", sleep=clock.sleep)
    for name in ("flaky", "other"):
        manager.get(name).failures = [TimeoutError("timed out")]
    errors = await manager.start_all()
    assert sorted(errors) == ["flaky", "other"]
    assert manager.started() == []  # nothing to stop: only retries to cancel
    await _until(lambda: len(_retry_tasks()) == 2)
    tasks = _retry_tasks()

    await manager.stop_all()
    assert manager.retrying() == []
    assert all(task.done() for task in tasks)
    assert not _retry_tasks()


async def test_retry_logs_never_carry_a_token(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    clock = _Clock()
    manager = _manager(monkeypatch, "flaky", sleep=clock.sleep)
    channel = manager.get("flaky")
    url = f"https://api.telegram.org/bot{FAKE_TOKEN}/getMe"
    channel.failures = [
        TimeoutError(f"timed out: {url}"),
        ConnectionResetError(errno.ECONNRESET, f"reset: {url}"),
        tg_error.InvalidToken(f"The token `{FAKE_TOKEN}` was rejected by the server."),
    ]
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ChannelStartError) as raised:
            await manager.start("flaky")
        await _until(lambda: not _retry_tasks())

    assert channel.attempts == 3
    assert FAKE_TOKEN not in str(raised.value)
    assert FAKE_TOKEN not in caplog.text
    assert FAKE_TOKEN not in str(manager.start_errors())
    levels = [r.levelname for r in caplog.records if r.name == "dodaios.channels.manager"]
    # The boot start, retry 1 (passing), retry 2 (the token was refused: the end).
    assert levels == ["WARNING", "INFO", "WARNING"]
    assert manager.retrying() == []


async def test_a_failing_late_start_listener_keeps_the_channel_started(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    manager = _manager(monkeypatch, "flaky", sleep=_Clock().sleep)
    manager.get("flaky").failures = [TimeoutError("timed out")]

    async def _broken(_name: str) -> None:
        raise RuntimeError("listener broke")

    manager.add_late_start_listener(_broken)
    with caplog.at_level(logging.WARNING, logger="dodaios.channels.manager"):
        with pytest.raises(ChannelStartError):
            await manager.start("flaky")
        await _until(lambda: not _retry_tasks() and "flaky" in manager.started())
    assert "late-start listener failed" in caplog.text
    assert manager.start_errors() == {}
    await manager.stop_all()


# --- what a late start must reach ------------------------------------------------------


async def test_the_chat_bridge_consumes_a_channel_that_started_late(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock(hold=True)
    manager = _manager(monkeypatch, "telegram", sleep=clock.sleep)
    channel = manager.get("telegram")
    channel.failures = [TimeoutError("getMe timed out")]
    bus = EventBus()
    seen: list[MessageSent] = []

    async def _capture(event: MessageSent) -> None:
        seen.append(event)

    bus.subscribe(MessageSent, _capture)
    await manager.start_all()  # no network at login: Telegram is not up
    bridge = ChannelChatBridge(bus=bus, manager=manager)
    bridge.start()
    await channel.queue.put(
        ChannelMessage(
            session_id=uuid4(),
            kind="text",
            content="hello after boot",
            metadata={"telegram_chat_id": 12345},
        )
    )

    clock.release()
    await _until(lambda: "telegram" in manager.started())
    await _until(lambda: bool(seen))
    assert seen[0].text == "hello after boot"
    assert seen[0].source_layer == "channel.telegram"
    await bridge.stop()
    await manager.stop_all()


async def test_a_stopped_bridge_binds_no_late_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock(hold=True)
    manager = _manager(monkeypatch, "telegram", sleep=clock.sleep)
    manager.get("telegram").failures = [TimeoutError("getMe timed out")]
    await manager.start_all()
    bridge = ChannelChatBridge(bus=EventBus(), manager=manager)
    bridge.start()
    await bridge.stop()  # the app shuts down while the retry still waits

    clock.release()
    await _until(lambda: "telegram" in manager.started() and not _retry_tasks())
    consumers = [t for t in asyncio.all_tasks() if t.get_name().startswith("channel-chat-bridge:")]
    assert consumers == []
    await manager.stop_all()


async def test_a_shutdown_during_boot_stops_what_the_bootstrap_started(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from dodaios.channels.bootstrap import bootstrap_channels

    class _Registry:
        made: list[_Registry] = []

        def __init__(self, _path: Any) -> None:
            self.closed = False
            type(self).made.append(self)

        async def open(self) -> None: ...

        async def close(self) -> None:
            self.closed = True

    class _Fine(_Channel):
        made: list[_Channel] = []

    class _Offline(_Channel):
        made: list[_Channel] = []

        def __init__(self, bus: EventBus) -> None:
            super().__init__(bus)
            self.failures = [TimeoutError("getMe timed out")]

    class _Slow(_Channel):
        made: list[_Channel] = []

        def __init__(self, bus: EventBus) -> None:
            super().__init__(bus)
            self.hold = asyncio.Event()  # still connecting when the app quits

    monkeypatch.setattr("dodaios.channels.bootstrap.FriendRegistry", _Registry)
    _patch_channels(monkeypatch, fine=_Fine, offline=_Offline, slow=_Slow)
    boot = asyncio.create_task(
        bootstrap_channels(bus=EventBus(), friends_db_path=tmp_path / "friends.db")
    )
    await _until(lambda: bool(_Slow.made) and _Slow.made[0].attempts == 1)
    await _until(lambda: len(_retry_tasks()) == 1)  # the offline one waits to try again

    boot.cancel()
    await asyncio.gather(boot, return_exceptions=True)
    assert boot.cancelled()
    assert _Fine.made[0].stopped is True
    assert _Slow.made[0].cancelled is True
    assert not _retry_tasks()
    assert _Registry.made[0].closed is True


# --- Telegram's own start --------------------------------------------------------------


async def test_telegram_get_me_timing_out_is_passing_and_a_refused_token_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import telegram

    monkeypatch.setattr("dodaios.channels.telegram.get_secret", lambda *_a, **_k: FAKE_TOKEN)
    answers: list[BaseException] = [
        tg_error.TimedOut(),
        tg_error.NetworkError("httpx.ConnectError: [Errno 51] Network is unreachable"),
        tg_error.InvalidToken(f"The token `{FAKE_TOKEN}` was rejected by the server."),
    ]

    async def _get_me(self: Any, *_a: Any, **_k: Any) -> Any:
        raise answers.pop(0)

    monkeypatch.setattr(telegram.Bot, "get_me", _get_me)
    verdicts = []
    for _ in range(3):
        channel = TelegramChannel(EventBus(), TelegramConfig(enabled=True))
        with pytest.raises(ChannelStartError) as raised:
            await channel.start()
        assert FAKE_TOKEN not in str(raised.value)
        assert raised.value.__cause__ is None and raised.value.__context__ is None
        verdicts.append(raised.value.transient)
    assert verdicts == [True, True, False]


class _FakeUpdater:
    def __init__(self, app: _FakeApp) -> None:
        self.app = app
        self.running = False

    async def start_polling(self, **_k: Any) -> None:
        self.running = True
        if self.app.polling is not None:
            await self.app.polling.wait()  # hangs: cancelled from outside
        raise tg_error.TimedOut()

    async def stop(self) -> None:
        self.app.calls.append("updater.stop")
        self.running = False


class _FakeApp:
    def __init__(self, polling: asyncio.Event | None) -> None:
        self.polling = polling
        self.calls: list[str] = []
        self.running = False
        self.updater = _FakeUpdater(self)

    def add_handler(self, *_a: Any, **_k: Any) -> None: ...

    async def initialize(self) -> None:
        self.calls.append("initialize")

    async def start(self) -> None:
        self.running = True

    async def stop(self) -> None:
        self.calls.append("stop")
        self.running = False

    async def shutdown(self) -> None:
        self.calls.append("shutdown")


def _install_fake_application(
    monkeypatch: pytest.MonkeyPatch, polling: asyncio.Event | None = None
) -> list[_FakeApp]:
    built: list[_FakeApp] = []

    class _Builder:
        def token(self, _token: str) -> _Builder:
            return self

        def build(self) -> _FakeApp:
            built.append(_FakeApp(polling))
            return built[-1]

    ext = types.ModuleType("telegram.ext")
    ext.ApplicationBuilder = _Builder  # type: ignore[attr-defined]
    ext.MessageHandler = lambda *_a, **_k: None  # type: ignore[attr-defined]
    ext.filters = types.SimpleNamespace(ALL=object())  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "telegram.ext", ext)
    monkeypatch.setattr("dodaios.channels.telegram.get_secret", lambda *_a, **_k: FAKE_TOKEN)

    async def _valid(self: TelegramChannel, _token: str) -> None:
        self._bot_username = "jarvis_bot"

    monkeypatch.setattr(TelegramChannel, "_validate_token", _valid)
    return built


async def test_a_failed_telegram_start_leaves_no_application_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = _install_fake_application(monkeypatch)
    channel = TelegramChannel(EventBus(), TelegramConfig(enabled=True))
    with pytest.raises(ChannelStartError) as raised:
        await channel.start()
    assert raised.value.transient is True  # polling timed out: tried again later
    assert built[0].calls == ["initialize", "updater.stop", "stop", "shutdown"]
    assert channel._app is None


async def test_a_cancelled_telegram_start_leaves_no_poller_behind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = _install_fake_application(monkeypatch, polling=asyncio.Event())
    channel = TelegramChannel(EventBus(), TelegramConfig(enabled=True))
    start = asyncio.create_task(channel.start())
    await _until(lambda: bool(built) and built[0].updater.running)

    start.cancel()
    await asyncio.gather(start, return_exceptions=True)
    assert start.cancelled()
    assert built[0].calls == ["initialize", "updater.stop", "stop", "shutdown"]
    assert channel._app is None
