"""Access control for the standalone Conductor server.

The standalone app (``python -m conductor serve``) exposes a job API that
runs shell commands. It must therefore never be reachable by a web page the
user happens to open, nor by another process that does not hold the token.

``StandaloneGuard`` is a plain ASGI middleware that enforces, in order:

1. **Host** — the ``Host`` header must name an allowed host (loopback names
   by default). This stops DNS rebinding, where a foreign hostname resolves
   to 127.0.0.1 and the page becomes "same-origin" with the server.
2. **Origin** — a request that carries an ``Origin`` header is refused
   unless that origin is explicitly allow-listed. ``null`` (``file://``
   pages, sandboxed frames) and every other foreign origin always fail.
3. **Token** — every route except ``/api/health`` and the token-in-URL
   webhook needs ``Authorization: Bearer <token>``. This also covers
   clients that send no ``Origin`` at all.

CORS preflights (``OPTIONS`` + ``Access-Control-Request-Method``) from an
allow-listed origin pass through without the token so the CORS middleware
can answer them; the real request still needs the token.

Embedded mode (the router mounted in the Dodaios web server) does not use
this module; there ``dodaios.ui.web.surface_security`` guards the router.
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
from collections.abc import Iterable
from pathlib import Path
from typing import Any

#: Environment variables the standalone server reads.
TOKEN_ENV = "CONDUCTOR_API_TOKEN"  # noqa: S105 - env var name, not a secret
ALLOWED_HOSTS_ENV = "CONDUCTOR_ALLOWED_HOSTS"
CORS_ORIGINS_ENV = "CONDUCTOR_CORS_ORIGINS"

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

#: Paths that never need the bearer token.
_PUBLIC_PATHS = frozenset({"/api/health"})
#: Path prefix of the webhook route: the token in the URL is its auth.
_WEBHOOK_PREFIX = "/api/conductor/hooks/"


def split_env_list(raw: str | None) -> list[str]:
    """Comma-separated env value → list of trimmed, non-empty entries."""
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def resolve_api_token(explicit: str | None = None) -> str:
    """Explicit token, else ``CONDUCTOR_API_TOKEN``, else a fresh random one."""
    token = (explicit or os.environ.get(TOKEN_ENV) or "").strip()
    return token or secrets.token_urlsafe(32)


def _write_private(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` so that no other account can ever read it.

    The file is created owner-only (never written first and restricted after)
    under a fresh name, then moved into place. ``O_EXCL`` also refuses a name
    someone else prepared.
    """
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def write_token_file(token: str, path: Path) -> None:
    """Store the token for local clients; readable by the owner only."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _write_private(path, token + "\n")


def _host_name(raw: str) -> str:
    """``Host`` header value → lower-case host name without port/brackets."""
    raw = raw.strip().lower()
    if raw.startswith("["):  # [::1]:7777
        end = raw.find("]")
        return raw[1:end] if end != -1 else raw
    if raw.count(":") == 1:
        return raw.split(":", 1)[0]
    return raw


class StandaloneGuard:
    """ASGI middleware: Host allowlist, Origin allowlist, bearer token."""

    def __init__(
        self,
        app: Any,
        *,
        token: str,
        allowed_hosts: Iterable[str] = (),
        allowed_origins: Iterable[str] = (),
    ) -> None:
        if not token:
            raise ValueError("StandaloneGuard needs a non-empty token")
        self.app = app
        self._token = token.encode("utf-8")
        self._hosts = LOOPBACK_HOSTS | {_host_name(h) for h in allowed_hosts if h}
        self._origins = frozenset(o.rstrip("/").lower() for o in allowed_origins if o)

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers") or []}
        path = scope.get("path") or ""
        is_webhook = path.startswith(_WEBHOOK_PREFIX)

        # The webhook is meant to be called from elsewhere under whatever
        # hostname the operator exposes; its URL token is the credential.
        if not is_webhook and _host_name(headers.get("host", "")) not in self._hosts:
            await self._deny(scope, send, 400, "Host not allowed")
            return

        origin = headers.get("origin")
        if origin is not None and origin.rstrip("/").lower() not in self._origins:
            await self._deny(scope, send, 403, "Origin not allowed")
            return

        if (
            scope["type"] == "http"
            and scope.get("method") == "OPTIONS"
            and origin is not None
            and "access-control-request-method" in headers
        ):
            await self.app(scope, receive, send)  # allowed-origin preflight
            return

        if is_webhook or path in _PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        auth = headers.get("authorization", "")
        scheme, _, value = auth.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(
            value.strip().encode("utf-8"), self._token,
        ):
            await self._deny(scope, send, 401, "Missing or invalid API token")
            return

        await self.app(scope, receive, send)

    @staticmethod
    async def _deny(scope: dict, send: Any, status: int, detail: str) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        body = json.dumps({"detail": detail}).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": body})
