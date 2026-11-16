"""A stand-in for Slack on this computer: the Web API over HTTP and a Socket Mode link.

The Slack channel talks to it exactly as it talks to Slack: ``httpx`` posts
JSON with ``Authorization: Bearer <key>`` to ``<api_base>/<method>``, and
``apps.connections.open`` hands out a ``ws://`` link (with a ticket and the
app id, like Slack's) that the channel opens with ``websockets``. The link
greets with ``hello``, carries ``events_api`` and ``interactive`` envelopes,
expects an acknowledgement for each, and can end with Slack's ``disconnect``
or just drop. Files of a message are served at ``url_private_download`` and
only to the bot key.

Envelope and method shapes follow Slack's documentation (Socket Mode,
``auth.test``, ``apps.connections.open``, ``chat.postMessage``,
``chat.update``, ``bots.info``, ``users.info``). What a test (or the demo
script) does to the stand-in is what Slack would do: send an event, press a
button, refresh the link, revoke a key, turn Socket Mode off, go offline.

The HTTP side runs in a thread (``http.server``), the link in the caller's
event loop (``websockets``), so a test needs nothing that is not already a
dependency of the app.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
import socket
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler
from typing import Any

from tests.fakes.loopback_http import LoopbackHTTPServer

# Made-up keys in Slack's shapes. Joined at run time, so no tracked line looks
# like a real key to the secret scanners.
FAKE_BOT_TOKEN = "xoxb" + "-000000000001-000000000002-StandInBotKeyForTestsOnly"
FAKE_APP_TOKEN = "xapp" + "-1-A0STANDIN1-000000000003-standinappkeyfortestsonly0123"
FAKE_USER_TOKEN = "xoxp" + "-000000000001-000000000004-StandInUserKeyForTests"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class Person:
    user_id: str
    name: str
    locale: str = "en-US"
    dm: str = ""


@dataclass
class SlackStandIn:
    """``async with SlackStandIn() as slack: ...``; ``slack.api_base`` goes into the config."""

    team_id: str = "T0STANDIN1"
    team_name: str = "Acme Studio"
    bot_user_id: str = "U0NOVABOT1"
    bot_name: str = "nova"
    bot_id: str = "B0NOVABOT1"
    app_id: str = "A0STANDIN1"
    bot_token: str = FAKE_BOT_TOKEN
    app_token: str = FAKE_APP_TOKEN
    user_token: str = FAKE_USER_TOKEN
    people: dict[str, Person] = field(default_factory=dict)
    #: Off: ``apps.connections.open`` answers like an app without Socket Mode.
    socket_mode_enabled: bool = True
    #: Revoked keys: Slack answers ``invalid_auth``.
    bot_revoked: bool = False
    app_revoked: bool = False
    #: Set: the app-level key belongs to this other app (a pasted mix-up).
    link_app_id: str = ""

    def __post_init__(self) -> None:
        if not self.people:
            self.people = {
                "U0OWNER001": Person("U0OWNER001", "Alex Rivera", "de-DE", "D0OWNERDM1"),
                "U0OTHER001": Person("U0OTHER001", "Sam Stranger", "en-US", "D0OTHERDM1"),
            }
        self._lock = threading.Lock()
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.posts: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self.acks: list[str] = []
        self.files: dict[str, tuple[bytes, str]] = {}
        self.downloads: list[str] = []
        self.links_opened = 0
        self._ts = itertools.count(1)
        self._http: LoopbackHTTPServer | None = None
        self._http_thread: threading.Thread | None = None
        self._ws_server: Any = None
        self._conns: list[Any] = []
        self.http_port = 0
        self.ws_port = 0

    # ------------------------------------------------------------ lifecycle

    async def __aenter__(self) -> SlackStandIn:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    @property
    def api_base(self) -> str:
        return f"http://127.0.0.1:{self.http_port}/api"

    async def start(self) -> None:
        from websockets.asyncio.server import serve

        self.ws_port = self.ws_port or _free_port()
        # The stand-in's own server log would show each ticket; it is not the app.
        quiet = logging.getLogger("tests.fakes.slack_standin.server")
        quiet.propagate = False
        quiet.setLevel(logging.CRITICAL)
        self._ws_server = await serve(self._ws_handler, "127.0.0.1", self.ws_port, logger=quiet)
        self.go_online()

    async def stop(self) -> None:
        self.go_offline()
        if self._ws_server is not None:
            self._ws_server.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._ws_server.wait_closed(), 5)
            self._ws_server = None

    def go_offline(self) -> None:
        """The Web API stops answering (connection refused), like no network."""
        server, self._http = self._http, None
        if server is not None:
            server.shutdown()
            server.server_close()
        if self._http_thread is not None:
            self._http_thread.join(timeout=5)
            self._http_thread = None

    def go_online(self) -> None:
        if self._http is not None:
            return
        handler = _make_handler(self)
        port = self.http_port or 0
        server = LoopbackHTTPServer(("127.0.0.1", port), handler)
        server.daemon_threads = True
        self.http_port = int(server.server_address[1])
        self._http = server
        self._http_thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._http_thread.start()

    # ------------------------------------------------------------ the link

    async def _ws_handler(self, ws: Any) -> None:
        path = getattr(getattr(ws, "request", None), "path", "") or ""
        if "ticket=" not in path:
            await ws.close(code=4001, reason="no ticket")
            return
        with self._lock:
            self.links_opened += 1
        await ws.send(
            json.dumps(
                {
                    "type": "hello",
                    "num_connections": 1,
                    "debug_info": {"host": "standin-1", "approximate_connection_time": 18060},
                    "connection_info": {"app_id": self.app_id},
                }
            )
        )
        self._conns.append(ws)
        try:
            async for raw in ws:
                data = json.loads(raw)
                if isinstance(data, dict) and data.get("envelope_id"):
                    with self._lock:
                        self.acks.append(str(data["envelope_id"]))
        except Exception:  # noqa: BLE001, S110 — a link that ends is the point of some tests
            pass
        finally:
            if ws in self._conns:
                self._conns.remove(ws)

    def _live(self) -> Any:
        if not self._conns:
            raise RuntimeError("no Socket Mode link is open")
        return self._conns[-1]

    async def wait_link(self, *, count: int = 1, timeout: float = 10.0) -> None:
        """Wait until ``count`` links were opened in total and one is open."""
        await self._until(lambda: self.links_opened >= count and bool(self._conns), timeout)

    async def send_envelope(self, kind: str, payload: dict[str, Any]) -> str:
        envelope_id = str(uuid.uuid4())
        await self._live().send(
            json.dumps(
                {
                    "envelope_id": envelope_id,
                    "type": kind,
                    "payload": payload,
                    "accepts_response_payload": kind == "interactive",
                    "retry_attempt": 0,
                    "retry_reason": "",
                }
            )
        )
        return envelope_id

    async def send_event(self, event: dict[str, Any]) -> str:
        """An Events API envelope around ``event``, as Slack sends it."""
        payload = {
            "token": "verification-token-unused",
            "team_id": self.team_id,
            "api_app_id": self.app_id,
            "event": event,
            "type": "event_callback",
            "event_id": f"Ev{uuid.uuid4().hex[:10].upper()}",
            "event_time": int(time.time()),
            "authorizations": [
                {"team_id": self.team_id, "user_id": self.bot_user_id, "is_bot": True}
            ],
        }
        return await self.send_envelope("events_api", payload)

    def next_ts(self) -> str:
        return f"{int(time.time())}.{next(self._ts):06d}"

    async def dm(
        self, user_id: str, text: str, *, files: list[dict[str, Any]] | None = None
    ) -> str:
        """``user_id`` writes ``text`` in their direct message with the app."""
        person = self.people[user_id]
        event: dict[str, Any] = {
            "type": "message",
            "channel": person.dm,
            "channel_type": "im",
            "user": user_id,
            "text": text,
            "ts": self.next_ts(),
            "event_ts": self.next_ts(),
        }
        if files:
            event["subtype"] = "file_share"
            event["files"] = files
        await self.send_event(event)
        return str(event["ts"])

    async def mention(self, user_id: str, text: str, *, channel: str = "C0GENERAL1") -> str:
        ts = self.next_ts()
        await self.send_event(
            {
                "type": "app_mention",
                "channel": channel,
                "user": user_id,
                "text": f"<@{self.bot_user_id}> {text}",
                "ts": ts,
                "event_ts": ts,
            }
        )
        return ts

    async def press(self, user_id: str, action_id: str, post: dict[str, Any]) -> str:
        """``user_id`` presses a button of the posted message ``post``."""
        payload = {
            "type": "block_actions",
            "user": {"id": user_id, "team_id": self.team_id},
            "team": {"id": self.team_id},
            "channel": {"id": post["channel"]},
            "container": {
                "type": "message",
                "message_ts": post["ts"],
                "channel_id": post["channel"],
                "is_ephemeral": False,
            },
            "message": {
                "ts": post["ts"],
                "text": post.get("text", ""),
                "blocks": post.get("blocks"),
            },
            "actions": [
                {
                    "type": "button",
                    "action_id": action_id,
                    "block_id": "approval",
                    "value": "x",
                    "action_ts": self.next_ts(),
                }
            ],
            "response_url": f"http://127.0.0.1:{self.http_port}/response",
            "trigger_id": "1.2.3",
        }
        return await self.send_envelope("interactive", payload)

    async def disconnect(self, reason: str = "refresh_requested") -> None:
        ws = self._live()
        await ws.send(
            json.dumps(
                {"type": "disconnect", "reason": reason, "debug_info": {"host": "standin-1"}}
            )
        )
        with contextlib.suppress(Exception):
            await ws.close()

    async def drop(self) -> None:
        """The link dies without a word (a network change, a Mac waking from sleep)."""
        ws = self._live()
        transport = getattr(ws, "transport", None)
        if transport is not None:
            transport.abort()
        else:  # pragma: no cover
            await ws.close()

    def add_file(self, data: bytes, mime: str, name: str) -> dict[str, Any]:
        file_id = f"F{uuid.uuid4().hex[:9].upper()}"
        with self._lock:
            self.files[file_id] = (data, mime)
        url = f"http://127.0.0.1:{self.http_port}/files-pri/{self.team_id}-{file_id}/{name}"
        return {
            "id": file_id,
            "name": name,
            "mimetype": mime,
            "size": len(data),
            "mode": "hosted",
            "is_external": False,
            "url_private": url,
            "url_private_download": url + "?download=1",
        }

    # ------------------------------------------------------------ waiting

    @staticmethod
    async def _until(check: Callable[[], bool], timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while not check():
            if time.monotonic() > deadline:
                raise TimeoutError("the stand-in did not see it in time")
            await asyncio.sleep(0.02)

    async def wait_posts(self, count: int, timeout: float = 10.0) -> list[dict[str, Any]]:
        await self._until(lambda: len(self.posts) >= count, timeout)
        return list(self.posts)

    async def wait_updates(self, count: int, timeout: float = 10.0) -> list[dict[str, Any]]:
        await self._until(lambda: len(self.updates) >= count, timeout)
        return list(self.updates)

    async def wait_acks(self, count: int, timeout: float = 10.0) -> None:
        await self._until(lambda: len(self.acks) >= count, timeout)

    # ------------------------------------------------------------ the Web API

    def answer(self, method: str, key: str, body: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.calls.append((method, key[:5], body))
        if method == "apps.connections.open":
            if key != self.app_token or self.app_revoked:
                return {"ok": False, "error": "invalid_auth"}
            if not self.socket_mode_enabled:
                return {"ok": False, "error": "socket_mode_not_enabled"}
            ticket = uuid.uuid4().hex
            return {
                "ok": True,
                "url": f"ws://127.0.0.1:{self.ws_port}/link/?ticket={ticket}"
                f"&app_id={self.link_app_id or self.app_id}",
            }
        if key == self.user_token and method == "auth.test":
            owner = next(iter(self.people.values()))
            return {
                "ok": True,
                "url": "https://acme-studio.slack.com/",
                "team": self.team_name,
                "user": "alex",
                "team_id": self.team_id,
                "user_id": owner.user_id,
            }
        if key != self.bot_token or self.bot_revoked:
            return {"ok": False, "error": "invalid_auth"}
        if method == "auth.test":
            return {
                "ok": True,
                "url": "https://acme-studio.slack.com/",
                "team": self.team_name,
                "user": self.bot_name,
                "team_id": self.team_id,
                "user_id": self.bot_user_id,
                "bot_id": self.bot_id,
                "is_enterprise_install": False,
            }
        if method == "bots.info":
            return {
                "ok": True,
                "bot": {
                    "id": self.bot_id,
                    "app_id": self.app_id,
                    "user_id": self.bot_user_id,
                    "name": self.bot_name,
                },
            }
        if method == "users.info":
            person = self.people.get(str(body.get("user") or ""))
            if person is None:
                return {"ok": False, "error": "user_not_found"}
            return {
                "ok": True,
                "user": {
                    "id": person.user_id,
                    "team_id": self.team_id,
                    "name": person.name.split()[0].lower(),
                    "real_name": person.name,
                    "profile": {"real_name": person.name, "display_name": person.name.split()[0]},
                    "locale": person.locale if body.get("include_locale") else None,
                },
            }
        if method == "chat.postMessage":
            channel = str(body.get("channel") or "")
            person = self.people.get(channel)
            if person is not None:  # posting to a member id lands in their DM with the app
                channel = person.dm
            ts = self.next_ts()
            post = {**body, "channel": channel, "ts": ts}
            with self._lock:
                self.posts.append(post)
            return {
                "ok": True,
                "channel": channel,
                "ts": ts,
                "message": {"text": body.get("text"), "ts": ts, "bot_id": self.bot_id},
            }
        if method == "chat.update":
            with self._lock:
                self.updates.append(dict(body))
            return {
                "ok": True,
                "channel": body.get("channel"),
                "ts": body.get("ts"),
                "text": body.get("text"),
            }
        return {"ok": False, "error": "unknown_method"}

    def file_bytes(self, path: str, key: str) -> tuple[int, bytes, str]:
        with self._lock:
            self.downloads.append(path)
        if key != self.bot_token:
            # Slack answers a file request without a valid key with its sign-in page.
            return 200, b"<html>sign in</html>", "text/html"
        file_id = path.split("/")[2].split("-", 1)[-1] if path.count("/") >= 3 else ""
        item = self.files.get(file_id)
        if item is None:
            return 404, b"", "text/plain"
        return 200, item[0], item[1]


def _make_handler(standin: SlackStandIn) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:  # quiet
            return

        def _key(self) -> str:
            auth = self.headers.get("Authorization", "")
            return auth[7:] if auth.startswith("Bearer ") else ""

        def _send(self, status: int, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            if not self.path.startswith("/api/"):
                self._send(404, b"", "text/plain")
                return
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                body = {}
            answer = standin.answer(self.path[5:].split("?")[0], self._key(), body)
            self._send(200, json.dumps(answer).encode(), "application/json; charset=utf-8")

        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/files-pri/"):
                status, data, kind = standin.file_bytes(self.path.split("?")[0], self._key())
                self._send(status, data, kind)
                return
            self._send(404, b"", "text/plain")

    return Handler


__all__ = ["FAKE_APP_TOKEN", "FAKE_BOT_TOKEN", "FAKE_USER_TOKEN", "Person", "SlackStandIn"]
