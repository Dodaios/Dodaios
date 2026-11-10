"""A warming FastBootstrap must NOT hold a WS handshake open; it must
accept-then-close with code 1013 so the client gets a fast, readable
"try again later" and reconnects (instead of the browser timing out the
pending handshake -> escalating backoff -> a long spurious 'OFFLINE')."""
from __future__ import annotations

import asyncio
import logging
import socket

import pytest
import websockets

from dodaios.ui.web.fast_bootstrap import FastBootstrap

_TOKEN = "fast-bootstrap-websocket-session"  # noqa: S105


def _free_port() -> int:
    """A port the OS just handed out, so parallel test workers never collide
    on a fixed number (a fixed port made the bind fail with SystemExit)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.mark.asyncio
async def test_warming_ws_is_fast_closed_with_1013() -> None:
    logging.disable(logging.CRITICAL)
    bs = FastBootstrap(session_token=_TOKEN)
    port = _free_port()
    await bs.serve("127.0.0.1", port)  # NOT set_app -> warming
    try:
        # Must connect quickly (handshake accepted) -- the old hold made this
        # time out. open_timeout well under the old 120s hold proves no-hold.
        async with websockets.connect(
            f"ws://127.0.0.1:{port}/ws",
            open_timeout=3,
            origin=f"http://127.0.0.1:{port}",
            additional_headers={"Cookie": f"jarvis_session={_TOKEN}"},
        ) as ws:
            with pytest.raises(websockets.ConnectionClosed) as exc:
                await asyncio.wait_for(ws.recv(), timeout=3)
            assert exc.value.code == 1013
    finally:
        await bs.stop()
        logging.disable(logging.NOTSET)


@pytest.mark.asyncio
async def test_warming_ws_gets_1013_even_without_any_credential() -> None:
    """The macOS/Linux desktop reality (BUG-065): WebKit engines drop the
    HttpOnly session cookie from WS handshakes. A warming socket must still
    receive the readable accept-then-close 1013 — an auth reject here would
    surface as an opaque 1006 and render the boot as a spurious OFFLINE."""
    logging.disable(logging.CRITICAL)
    bs = FastBootstrap(session_token=_TOKEN)
    port = _free_port()
    await bs.serve("127.0.0.1", port)  # NOT set_app -> warming
    try:
        async with websockets.connect(
            f"ws://127.0.0.1:{port}/ws",
            open_timeout=3,
            origin=f"http://127.0.0.1:{port}",
            # No Cookie header at all — the cookie-less WebKit handshake.
        ) as ws:
            with pytest.raises(websockets.ConnectionClosed) as exc:
                await asyncio.wait_for(ws.recv(), timeout=3)
            assert exc.value.code == 1013
    finally:
        await bs.stop()
        logging.disable(logging.NOTSET)
