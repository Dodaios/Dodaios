"""The phone app's channel: serves the mobile gateway and bridges its chat.

A message from a paired phone becomes a normal chat turn (through
``ChannelChatBridge``, like Telegram); the reply is matched back to the
waiting request by ``trace_id`` and returned in the same HTTP response.

The gateway runs its own uvicorn server on the configured public port, in the
same event loop as the rest of Jarvis. The socket is bound in :meth:`start`,
so a taken port fails the start instead of killing the process.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
import ssl
from collections.abc import AsyncIterator, Generator
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from jarvis.channels.base import ChannelMessage, ChannelSession
from jarvis.channels.manager import ChannelContext, ChannelStartError
from jarvis.core.bus import EventBus
from jarvis.core.config import MobileGatewayConfig
from jarvis.core.events import Event, ResponseGenerated
from jarvis.mobile_gateway.app import access_log, create_app
from jarvis.mobile_gateway.devices import Device, DeviceStore
from jarvis.mobile_gateway.ratelimit import RateLimiter
from jarvis.mobile_gateway.store import DeviceData
from jarvis.mobile_gateway.tls import ensure_certificate

log = logging.getLogger(__name__)

ACCESS_LOG_NAME = "access.log"


def device_session_id(device_id: str) -> UUID:
    """One stable chat session per paired phone."""
    return uuid5(NAMESPACE_URL, f"dodaios-mobile:{device_id}")


def _bind(host: str, port: int) -> socket.socket:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind((host, port))
        sock.listen(64)
        sock.setblocking(False)
    except OSError:
        sock.close()
        raise
    return sock


class MobileChannel:
    """Chat channel for the paired phone app."""

    name = "mobile"

    def __init__(self, bus: EventBus, config: MobileGatewayConfig | None = None) -> None:
        self._bus = bus
        self._cfg = config if config is not None else MobileGatewayConfig()
        self._data_dir = Path(self._cfg.data_dir)
        self._store = DeviceStore(self._data_dir)
        self._data = DeviceData(self._data_dir)
        self._inbox: asyncio.Queue[ChannelMessage] = asyncio.Queue()
        self._waiting: dict[UUID, asyncio.Future[str]] = {}
        self._sessions: dict[str, ChannelSession] = {}
        self._server: Any = None
        self._server_task: asyncio.Task[None] | None = None
        self._log_handler: logging.Handler | None = None
        self._subscribed = False
        self._started = False

    @classmethod
    def from_context(cls, ctx: ChannelContext) -> MobileChannel:
        cfg = ctx.config.get("mobile_config")
        if not isinstance(cfg, MobileGatewayConfig):
            cfg = MobileGatewayConfig()
        return cls(bus=ctx.bus, config=cfg)

    @property
    def store(self) -> DeviceStore:
        return self._store

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._started:
            return
        if not self._cfg.enabled:
            self._started = True
            log.info("MobileChannel disabled (config.enabled=False) — skipping")
            return

        import uvicorn

        cert, key = ensure_certificate(self._data_dir)
        try:
            sock = _bind(self._cfg.host, self._cfg.port)
        except OSError as exc:
            raise ChannelStartError(
                f"Mobile gateway cannot listen on [{self._cfg.host}]:{self._cfg.port}: {exc}"
            ) from None

        self._attach_access_log()
        app = create_app(
            store=self._store,
            limiter=RateLimiter(self._cfg.requests_per_minute),
            send_message=self.submit,
            max_message_chars=self._cfg.max_message_chars,
            data=self._data,
        )
        config = uvicorn.Config(
            app,
            ssl_certfile=str(cert),
            ssl_keyfile=str(key),
            ssl_version=ssl.PROTOCOL_TLS_SERVER,
            log_level="warning",
            access_log=False,
            server_header=False,
            date_header=False,
            lifespan="off",
        )
        server = _embedded_server(config)
        self._server = server
        self._bus.subscribe_all(self._on_bus_event)
        self._subscribed = True
        self._server_task = asyncio.create_task(self._serve(server, sock), name="mobile-gateway")
        self._started = True
        log.info("Mobile gateway listening on [%s]:%d", self._cfg.host, self._cfg.port)

    async def _serve(self, server: Any, sock: socket.socket) -> None:
        try:
            await server.serve(sockets=[sock])
        except (Exception, SystemExit) as exc:  # uvicorn exits on fatal startup errors
            log.error("Mobile gateway stopped: %s", exc)
        finally:
            sock.close()

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        if self._subscribed:
            with contextlib.suppress(Exception):
                self._bus.unsubscribe_all(self._on_bus_event)
            self._subscribed = False
        if self._server is not None:
            self._server.should_exit = True
        if self._server_task is not None:
            with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(self._server_task, timeout=5.0)
            self._server_task = None
        self._server = None
        for future in self._waiting.values():
            future.cancel()
        self._waiting.clear()
        if self._log_handler is not None:
            access_log.removeHandler(self._log_handler)
            self._log_handler.close()
            self._log_handler = None

    def _attach_access_log(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(self._data_dir / ACCESS_LOG_NAME, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        access_log.addHandler(handler)
        access_log.setLevel(logging.INFO)
        self._log_handler = handler

    # ------------------------------------------------------------------
    # Inbound
    # ------------------------------------------------------------------

    async def submit(self, text: str, device: Device) -> str | None:
        """Hand ``text`` to the chat path and wait for the reply."""
        session = self._session_for(device)
        msg = ChannelMessage(
            session_id=session.session_id,
            kind="text",
            content=text,
            metadata={"channel_session_id": device.device_id, "mobile_device": device.name},
        )
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._waiting[msg.trace_id] = future
        try:
            await self._inbox.put(msg)
            return await asyncio.wait_for(future, timeout=self._cfg.reply_timeout_s)
        except TimeoutError:
            return None
        finally:
            self._waiting.pop(msg.trace_id, None)

    def _session_for(self, device: Device) -> ChannelSession:
        session = self._sessions.get(device.device_id)
        if session is None:
            session = ChannelSession(
                session_id=device_session_id(device.device_id),
                channel_name=self.name,
                user_handle=device.name,
            )
            self._sessions[device.device_id] = session
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
        future = self._waiting.get(getattr(event, "trace_id", None))  # type: ignore[arg-type]
        if future is not None and not future.done() and (event.text or "").strip():
            future.set_result(event.text)

    async def send_message(self, msg: ChannelMessage) -> None:
        """Queue a message from Jarvis in the phone's inbox; the app polls it."""
        text = msg.content if isinstance(msg.content, str) else ""
        if not text.strip():
            return
        for dev in self._store.devices():
            if not dev.revoked and device_session_id(dev.device_id) == msg.session_id:
                self._data.push_inbox(dev.device_id, text)
                return
        log.debug("MobileChannel.send_message: no paired device for %s", msg.session_id)

    async def broadcast_event(self, event: Event) -> None:
        """No-op: replies are routed by ``trace_id``."""


def _embedded_server(config: Any) -> Any:
    """A uvicorn server that leaves the host process's signal handlers alone."""
    import uvicorn

    class EmbeddedServer(uvicorn.Server):
        @contextlib.contextmanager
        def capture_signals(self) -> Generator[None, None, None]:
            yield

    return EmbeddedServer(config)
