"""Pixel Streaming 2 signalling for the IDE side panel (WP20.1).

The Verse side panel shows a Pixel Streaming 2 view of the running
``Verse.exe`` (``docs/verse/unreal/architecture.md`` section 6). The
signalling server is part of the backend, so no extra Node process ships:
one WebSocket at ``/api/verse/signal`` carries both parties.

* **Streamer** (the Pixel Streaming 2 plugin inside ``Verse.exe``):
  ``ws://127.0.0.1:<port>/api/verse/signal?role=streamer&key=<key>``. The
  plugin cannot send a first frame of its own, so it authenticates with a
  key in the URL. The key is derived from the launch token
  (:func:`derive_streamer_key`), so the bridge token itself never sits in a
  URL the plugin might log.
* **Player** (the panel component in the web UI):
  ``ws://<origin>/api/verse/signal?role=player``. Its first frame must be
  ``hello {protocol: "verse.signal/1", ticket, w, h, dpr}`` within 5 s. The
  ticket is single use and short lived, minted by ``POST
  /api/verse/signal/ticket``, which sits behind the app's UI session like
  every other route.

After authentication the server speaks the protocol of the engine's own
Pixel Streaming 2 signalling server (``PixelStreaming2Servers``,
``SignallingServer.cpp``): ``config`` and ``identify`` to a new streamer,
``endpointId`` naming it, ``listStreamers`` / ``streamerList``,
``subscribe`` / ``unsubscribe``, ``playerConnected`` /
``playerDisconnected`` to the streamer, ``offer`` / ``answer`` /
``iceCandidate`` forwarded with the ``playerId`` added towards the streamer
and removed towards the player, ``disconnectPlayer`` and ``ping`` / ``pong``.

Rules the reference server does not have:

* Loopback peers only, also when the backend listens wider (close ``4403``).
* ICE stays on this machine: ``config`` never names a STUN or TURN server
  and :class:`LocalIcePolicy` drops every candidate that is not a host
  candidate on one of this machine's own addresses (loopback first, the
  machine's interface addresses, and the browser's mDNS host names), also
  inside offer and answer SDP. Media between two addresses of one machine
  never leaves it.
* One streamer and one player. A second one replaces the first (``4409``).
* Only the message types the panel needs cross in either direction.
* The panel's visibility travels with the player socket: ``hello`` means the
  panel became visible, ``panel.resize`` resizes it, the socket closing means
  it was hidden. :class:`SignalHub` reports these as the bridge's
  ``panel.visibility`` / ``panel.resize`` data (``contracts/bridge-protocol.md``
  section 12) through ``on_panel``; the verse host (WP17) forwards them to
  ``Verse.exe``. ``panel.stream_state`` from Verse comes back through
  :meth:`SignalHub.publish_stream_state` and reaches the player as
  ``verse.streamState``.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import inspect
import ipaddress
import json
import secrets
import socket
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket
from loguru import logger

SIGNAL_PATH = "/api/verse/signal"
TICKET_PATH = "/api/verse/signal/ticket"
PROTOCOL = "verse.signal/1"

CLOSE_TOO_BIG = 1009
CLOSE_TRY_AGAIN = 1013
CLOSE_BAD_HELLO = 4400
CLOSE_TOKEN = 4401
CLOSE_PEER = 4403
CLOSE_REPLACED = 4409
CLOSE_PROTOCOL = 4426

HELLO_TIMEOUT_S = 5.0
TICKET_TTL_S = 30.0
#: Offer SDP of a single video track plus a data channel is a few KiB.
MAX_FRAME_BYTES = 64 * 1024
#: Panel geometry bounds (CSS pixels, device pixel ratio).
MAX_PANEL_PX = 8192
MAX_DPR = 8.0

#: Player -> streamer types that are forwarded (with ``playerId`` added).
PLAYER_FORWARD = frozenset({"answer", "offer", "iceCandidate"})
#: Streamer -> player types that are forwarded (with ``playerId`` removed).
STREAMER_FORWARD = frozenset({"offer", "answer", "iceCandidate"})

_STREAMER_KEY_INFO = b"verse.signal/1 streamer"
_LOOPBACK_NAMES = frozenset({"localhost"})


def derive_streamer_key(launch_token: str) -> str:
    """The key the streamer puts in its signalling URL, derived from the launch token."""
    return hmac.new(launch_token.encode("utf-8"), _STREAMER_KEY_INFO, hashlib.sha256).hexdigest()


def is_loopback_host(host: str | None) -> bool:
    """True for a loopback peer address (``127.0.0.0/8``, ``::1``, ``localhost``)."""
    if not host:
        return False
    if host in _LOOPBACK_NAMES:
        return True
    try:
        addr = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return addr.is_loopback


def machine_addresses() -> set[str]:
    """This machine's own interface addresses (best effort, loopback always included)."""
    found = {"127.0.0.1", "::1"}
    with contextlib.suppress(Exception):
        import psutil  # optional; present in the app's environment

        for addrs in psutil.net_if_addrs().values():
            for item in addrs:
                if item.family in (socket.AF_INET, socket.AF_INET6):
                    found.add(item.address.split("%", 1)[0])
    with contextlib.suppress(OSError):
        for info in socket.getaddrinfo(socket.gethostname(), None):
            found.add(str(info[4][0]).split("%", 1)[0])
    return found


@dataclass(frozen=True)
class IceCandidate:
    """The fields of an ICE candidate line this policy looks at (RFC 8839)."""

    transport: str
    address: str
    port: int
    kind: str

    @classmethod
    def parse(cls, line: str) -> IceCandidate | None:
        text = line.strip()
        if text.startswith("a="):
            text = text[2:]
        if not text.startswith("candidate:"):
            return None
        parts = text[len("candidate:") :].split()
        if len(parts) < 8 or parts[6] != "typ":
            return None
        try:
            port = int(parts[5])
        except ValueError:
            return None
        return cls(transport=parts[2].lower(), address=parts[4], port=port, kind=parts[7].lower())


class LocalIcePolicy:
    """Keeps every ICE candidate on this machine: host candidates only, own addresses only."""

    def __init__(self, local_addresses: Iterable[str] | None = None) -> None:
        addresses = machine_addresses() if local_addresses is None else set(local_addresses)
        self._local: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
        for item in addresses:
            with contextlib.suppress(ValueError):
                self._local.add(ipaddress.ip_address(item.split("%", 1)[0]))

    def allows(self, candidate: str, *, from_player: bool) -> bool:
        parsed = IceCandidate.parse(candidate)
        if parsed is None or parsed.kind != "host" or parsed.transport not in ("udp", "tcp"):
            return False
        if not 0 < parsed.port < 65536:
            return False
        if from_player and parsed.address.lower().endswith(".local"):
            # The browser hides its host address behind an mDNS name that only
            # resolves on this network segment; it still is a host candidate.
            return True
        try:
            addr = ipaddress.ip_address(parsed.address.split("%", 1)[0])
        except ValueError:
            return False
        return addr.is_loopback or addr in self._local

    def filter_sdp(self, sdp: str, *, from_player: bool) -> str:
        newline = "\r\n" if "\r\n" in sdp else "\n"
        kept = [
            line
            for line in sdp.splitlines()
            if not line.startswith("a=candidate:") or self.allows(line, from_player=from_player)
        ]
        return newline.join(kept) + (newline if sdp.endswith(("\n", "\r\n")) else "")


def _config_message() -> dict[str, Any]:
    # No STUN, no TURN: the peers only ever use their own host candidates.
    return {"type": "config", "peerConnectionOptions": {"iceServers": []}}


def _panel_geometry(data: dict[str, Any]) -> dict[str, Any] | None:
    try:
        w = int(data["w"])
        h = int(data["h"])
        dpr = float(data.get("dpr", 1.0))
    except (KeyError, TypeError, ValueError):
        return None
    if not (0 < w <= MAX_PANEL_PX and 0 < h <= MAX_PANEL_PX and 0 < dpr <= MAX_DPR):
        return None
    return {"w": w, "h": h, "dpr": dpr}


@dataclass
class _Peer:
    ws: Any
    role: str
    peer_id: str
    streamer_id: str = ""
    subscribed: bool = False
    geometry: dict[str, Any] = field(default_factory=dict)
    closed: bool = False

    async def send(self, message: dict[str, Any]) -> None:
        if self.closed:
            return
        try:
            await self.ws.send_text(json.dumps(message, separators=(",", ":")))
        except Exception:  # noqa: BLE001 - a dead socket is handled by its reader
            self.closed = True

    async def close(self, code: int, reason: str = "") -> None:
        if self.closed:
            return
        self.closed = True
        with contextlib.suppress(Exception):
            await self.ws.close(code=code, reason=reason)


PanelCallback = Callable[[str, dict[str, Any]], Awaitable[None] | None]


class SignalHub:
    """One streamer, one player, the reference signalling protocol, the panel's visibility."""

    def __init__(
        self,
        launch_token: Callable[[], str | None],
        *,
        on_panel: PanelCallback | None = None,
        ice_policy: LocalIcePolicy | None = None,
        hello_timeout: float = HELLO_TIMEOUT_S,
        ticket_ttl: float = TICKET_TTL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._launch_token = launch_token
        self._on_panel = on_panel
        self._ice = ice_policy or LocalIcePolicy()
        self._hello_timeout = hello_timeout
        self._ticket_ttl = ticket_ttl
        self._clock = clock
        self._tickets: dict[str, float] = {}
        self._streamer: _Peer | None = None
        self._player: _Peer | None = None
        self._next_player = 0
        self._stream_state: dict[str, Any] = {"state": "stopped"}
        self._dropped_types: set[str] = set()

    # -- state the verse host and tests read -------------------------------

    @property
    def streamer_connected(self) -> bool:
        return self._streamer is not None and not self._streamer.closed

    @property
    def player_connected(self) -> bool:
        return self._player is not None and not self._player.closed

    @property
    def stream_state(self) -> dict[str, Any]:
        return dict(self._stream_state)

    def mint_player_ticket(self) -> str:
        now = self._clock()
        self._tickets = {t: exp for t, exp in self._tickets.items() if exp > now}
        ticket = secrets.token_urlsafe(32)
        self._tickets[ticket] = now + self._ticket_ttl
        return ticket

    def _redeem(self, ticket: Any) -> bool:
        if not isinstance(ticket, str) or not ticket:
            return False
        now = self._clock()
        match = None
        for known, expires in self._tickets.items():
            if hmac.compare_digest(known, ticket):
                match = (known, expires)
                break
        if match is None:
            return False
        del self._tickets[match[0]]
        return match[1] > now

    async def publish_stream_state(self, data: dict[str, Any]) -> None:
        """Forward ``panel.stream_state`` from Verse to the panel."""
        state = data.get("state")
        if state not in ("starting", "streaming", "stopped", "failed"):
            state = "failed"
        message: dict[str, Any] = {"state": state}
        if isinstance(data.get("error"), str):
            message["error"] = data["error"][:64]
        self._stream_state = message
        if self._player is not None:
            if state in ("stopped", "failed"):
                # The streamer ended its peer; the next start needs a fresh subscribe.
                self._player.subscribed = False
            await self._player.send({"type": "verse.streamState", **message})

    # -- connection entry --------------------------------------------------

    async def serve(self, ws: Any) -> None:
        """Run one signalling connection (a Starlette ``WebSocket``) to its end."""
        await ws.accept()
        client = getattr(ws, "client", None)
        if not is_loopback_host(getattr(client, "host", None)):
            await _close(ws, CLOSE_PEER, "loopback only")
            return
        role = ws.query_params.get("role", "")
        if role == "streamer":
            await self._serve_streamer(ws)
        elif role == "player":
            await self._serve_player(ws)
        else:
            await _close(ws, CLOSE_BAD_HELLO, "role must be streamer or player")

    # -- streamer ----------------------------------------------------------

    async def _serve_streamer(self, ws: Any) -> None:
        token = self._launch_token()
        key = ws.query_params.get("key", "")
        if not token:
            await _close(ws, CLOSE_TRY_AGAIN, "no Verse launch")
            return
        if not key:
            await _close(ws, CLOSE_BAD_HELLO, "key missing")
            return
        if not hmac.compare_digest(key, derive_streamer_key(token)):
            await _close(ws, CLOSE_TOKEN, "bad key")
            return
        peer = _Peer(ws=ws, role="streamer", peer_id="streamer", streamer_id="Verse")
        previous, self._streamer = self._streamer, peer
        if previous is not None:
            await previous.close(CLOSE_REPLACED, "replaced")
        await peer.send(_config_message())
        await peer.send({"type": "identify"})
        try:
            async for message in _frames(ws):
                if message is None:
                    await peer.close(CLOSE_TOO_BIG, "frame too large")
                    break
                await self._on_streamer_message(peer, message)
        finally:
            peer.closed = True
            if self._streamer is peer:
                self._streamer = None
                if self._player is not None:
                    self._player.subscribed = False

    async def _on_streamer_message(self, peer: _Peer, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "endpointId":
            if isinstance(message.get("id"), str) and message["id"]:
                peer.streamer_id = message["id"][:64]
            # A player that subscribed before the streamer was ready gets connected now.
            if self._player is not None and self._player.geometry and not self._player.subscribed:
                await self._subscribe(self._player)
            return
        if kind == "ping":
            await peer.send({"type": "pong", "time": time.time()})
            return
        if kind == "disconnectPlayer":
            player = self._player
            if player is not None and str(message.get("playerId")) == player.peer_id:
                await player.close(1000, "disconnected by the streamer")
            return
        if kind not in STREAMER_FORWARD:
            self._drop(f"streamer:{kind}")
            return
        player = self._player
        if player is None or str(message.get("playerId")) != player.peer_id:
            return
        out = {k: v for k, v in message.items() if k != "playerId"}
        if not self._sanitize(out, from_player=False):
            return
        await player.send(out)

    # -- player ------------------------------------------------------------

    async def _serve_player(self, ws: Any) -> None:
        try:
            hello = await asyncio.wait_for(_first_frame(ws), timeout=self._hello_timeout)
        except TimeoutError:
            await _close(ws, CLOSE_BAD_HELLO, "no hello")
            return
        if not isinstance(hello, dict) or hello.get("type") != "hello":
            await _close(ws, CLOSE_BAD_HELLO, "hello first")
            return
        if hello.get("protocol") != PROTOCOL:
            await _close(ws, CLOSE_PROTOCOL, f"supported: {PROTOCOL}")
            return
        if not self._redeem(hello.get("ticket")):
            await _close(ws, CLOSE_TOKEN, "bad ticket")
            return
        geometry = _panel_geometry(hello)
        if geometry is None:
            await _close(ws, CLOSE_BAD_HELLO, "panel size missing")
            return
        self._next_player += 1
        peer = _Peer(ws=ws, role="player", peer_id=str(self._next_player), geometry=geometry)
        previous, self._player = self._player, peer
        if previous is not None:
            await self._unsubscribe(previous)
            await previous.close(CLOSE_REPLACED, "replaced")
        await peer.send(_config_message())
        await peer.send({"type": "verse.streamState", **self._stream_state})
        await self._panel("panel.visibility", {"visible": True, **geometry})
        try:
            async for message in _frames(ws):
                if message is None:
                    await peer.close(CLOSE_TOO_BIG, "frame too large")
                    break
                await self._on_player_message(peer, message)
        finally:
            peer.closed = True
            if self._player is peer:
                self._player = None
                await self._unsubscribe(peer)
                await self._panel(
                    "panel.visibility",
                    {"visible": False, "w": 0, "h": 0, "dpr": peer.geometry.get("dpr", 1.0)},
                )

    async def _on_player_message(self, peer: _Peer, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "ping":
            await peer.send({"type": "pong", "time": time.time()})
        elif kind == "listStreamers":
            ids = [self._streamer.streamer_id] if self.streamer_connected and self._streamer else []
            await peer.send({"type": "streamerList", "ids": ids})
        elif kind == "subscribe":
            wanted = message.get("streamerId")
            streamer = self._streamer
            if streamer is not None and wanted not in (None, "", streamer.streamer_id):
                return  # one streamer only; a name that is not it subscribes to nothing
            await self._subscribe(peer)
        elif kind == "unsubscribe":
            await self._unsubscribe(peer)
        elif kind == "panel.resize":
            geometry = _panel_geometry(message)
            if geometry is not None and geometry != peer.geometry:
                peer.geometry = geometry
                await self._panel("panel.resize", dict(geometry))
        elif kind in PLAYER_FORWARD:
            streamer = self._streamer
            if streamer is None or streamer.closed:
                return
            if not peer.subscribed:
                await self._subscribe(peer)
            out = {k: v for k, v in message.items() if k != "playerId"}
            if not self._sanitize(out, from_player=True):
                return
            out["playerId"] = peer.peer_id
            await streamer.send(out)
        else:
            self._drop(f"player:{kind}")

    async def _subscribe(self, peer: _Peer) -> None:
        streamer = self._streamer
        if streamer is None or streamer.closed or peer.subscribed:
            return
        peer.subscribed = True
        await streamer.send(
            {
                "type": "playerConnected",
                "playerId": peer.peer_id,
                "dataChannel": True,
                "sfu": False,
                "sendOffer": True,
            }
        )

    async def _unsubscribe(self, peer: _Peer) -> None:
        if not peer.subscribed:
            return
        peer.subscribed = False
        streamer = self._streamer
        if streamer is not None:
            await streamer.send({"type": "playerDisconnected", "playerId": peer.peer_id})

    # -- helpers -----------------------------------------------------------

    def _sanitize(self, message: dict[str, Any], *, from_player: bool) -> bool:
        kind = message.get("type")
        if kind in ("offer", "answer"):
            sdp = message.get("sdp")
            if not isinstance(sdp, str):
                return False
            message["sdp"] = self._ice.filter_sdp(sdp, from_player=from_player)
            return True
        if kind == "iceCandidate":
            candidate = message.get("candidate")
            line = candidate.get("candidate") if isinstance(candidate, dict) else None
            if not isinstance(line, str):
                return False
            if line == "":
                return True  # end-of-candidates marker
            return self._ice.allows(line, from_player=from_player)
        return False

    async def _panel(self, kind: str, data: dict[str, Any]) -> None:
        if self._on_panel is None:
            return
        try:
            result = self._on_panel(kind, data)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:  # noqa: BLE001 - the panel link must not kill signalling
            logger.opt(exception=exc).warning("Verse signal: panel callback failed for {}", kind)

    def _drop(self, kind: str) -> None:
        if kind not in self._dropped_types:
            self._dropped_types.add(kind)
            logger.debug("Verse signal: dropped message type {}", kind)


async def _close(ws: Any, code: int, reason: str) -> None:
    with contextlib.suppress(Exception):
        await ws.close(code=code, reason=reason)


def _decode(raw: dict[str, Any]) -> dict[str, Any] | None | bool:
    """One received ASGI frame: a JSON object, ``None`` when too big, ``False`` when unusable."""
    text = raw.get("text")
    if text is None and raw.get("bytes") is not None:
        data: bytes = raw["bytes"]
        if len(data) > MAX_FRAME_BYTES:
            return None
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return False
    if not isinstance(text, str):
        return False
    if len(text.encode("utf-8")) > MAX_FRAME_BYTES:
        return None
    try:
        message = json.loads(text)
    except ValueError:
        return False
    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        return False
    return message


async def _first_frame(ws: Any) -> dict[str, Any] | None:
    raw = await ws.receive()
    if raw.get("type") == "websocket.disconnect":
        return None
    decoded = _decode(raw)
    return decoded if isinstance(decoded, dict) else None


async def _frames(ws: Any):
    """Yield JSON objects until the socket closes; ``None`` once for an oversized frame."""
    while True:
        try:
            raw = await ws.receive()
        except Exception:  # noqa: BLE001 - disconnect surfaces differently per server
            return
        if raw.get("type") == "websocket.disconnect":
            return
        decoded = _decode(raw)
        if decoded is None:
            yield None
            return
        if decoded is False:
            continue
        yield decoded


def build_router(get_hub: Callable[[], SignalHub | None]):
    """The ticket route and the signalling socket, for the verse host to mount.

    ``get_hub`` returns the hub of the running launch, or ``None`` while no
    ``Verse.exe`` runs; then the ticket route answers 503 and the socket
    closes ``1013`` (try again later).
    """
    router = APIRouter()

    @router.post(TICKET_PATH)
    async def signal_ticket(request: Request) -> dict[str, Any]:
        if not is_loopback_host(request.client.host if request.client else None):
            raise HTTPException(status_code=403, detail="loopback only")
        hub = get_hub()
        if hub is None:
            raise HTTPException(status_code=503, detail="Verse is not running")
        return {
            "ticket": hub.mint_player_ticket(),
            "expires_in": TICKET_TTL_S,
            "path": SIGNAL_PATH,
            "protocol": PROTOCOL,
        }

    @router.websocket(SIGNAL_PATH)
    async def signal_socket(websocket: WebSocket) -> None:
        hub = get_hub()
        if hub is None:
            await websocket.accept()
            await _close(websocket, CLOSE_TRY_AGAIN, "Verse is not running")
            return
        await hub.serve(websocket)

    return router


__all__ = [
    "CLOSE_BAD_HELLO",
    "CLOSE_PEER",
    "CLOSE_PROTOCOL",
    "CLOSE_REPLACED",
    "CLOSE_TOKEN",
    "CLOSE_TOO_BIG",
    "CLOSE_TRY_AGAIN",
    "PROTOCOL",
    "SIGNAL_PATH",
    "TICKET_PATH",
    "IceCandidate",
    "LocalIcePolicy",
    "SignalHub",
    "build_router",
    "derive_streamer_key",
    "is_loopback_host",
    "machine_addresses",
]
