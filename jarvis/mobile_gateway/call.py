"""Voice calls: relay a phone's audio socket to the PC's own voice endpoint.

The phone speaks the browser-voice protocol (``audio_start`` then 16-bit PCM
frames; 24 kHz PCM and JSON events come back). The gateway adds nothing but
the hop: it opens the web UI's loopback ``/ws/audio`` with the in-process
control key and copies frames both ways until either side hangs up.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from fastapi import WebSocket

MAX_FRAME_BYTES = 1024 * 1024


class Upstream(Protocol):
    async def send(self, message: str | bytes) -> None: ...

    def __aiter__(self) -> AsyncIterator[str | bytes]: ...


#: Opens one upstream voice socket per call.
OpenUpstream = Callable[[], AbstractAsyncContextManager[Upstream]]


class UpstreamUnavailable(Exception):
    """The PC's voice endpoint cannot be reached."""


def local_voice() -> OpenUpstream:
    """Connect to this process' web UI voice socket on loopback."""

    def open_upstream() -> AbstractAsyncContextManager[Any]:
        from websockets.asyncio.client import connect

        from jarvis.core import runtime_refs
        from jarvis.core.control_key import get_control_key

        base = runtime_refs.get_api_base_url()
        key = get_control_key()
        if not base or not key:
            raise UpstreamUnavailable("voice endpoint not ready")
        return connect(
            base.replace("http://", "ws://", 1) + "/ws/audio",
            additional_headers={"Authorization": f"Bearer {key}"},
            max_size=MAX_FRAME_BYTES,
            open_timeout=10,
        )

    return open_upstream


async def relay(ws: WebSocket, upstream: Upstream) -> None:
    """Copy frames both ways; return when either side is done."""

    async def phone_to_pc() -> None:
        while True:
            message = await ws.receive()
            if message.get("type") == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                await upstream.send(message["bytes"])
            elif message.get("text") is not None:
                await upstream.send(message["text"])

    async def pc_to_phone() -> None:
        async for message in upstream:
            if isinstance(message, bytes):
                await ws.send_bytes(message)
            else:
                await ws.send_text(message)

    tasks = [asyncio.create_task(phone_to_pc()), asyncio.create_task(pc_to_phone())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(BaseException):
                await task
