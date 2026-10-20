"""Authentication for the Jarvis Control API (``/api/control/*``).

A per-user Bearer key (see ``dodaios.core.control_key``) is the security boundary
for the Control API — NOT the localhost binding. This keeps the existing
same-origin desktop UI routes (``/api/settings/*`` etc.) untouched (zero
regression) while the new control surface, which external local agents (Codex
CLI, Claude Code) drive, is key-gated.

- ``require_control_key`` — every control route. Bearer required, constant-time
  compared. Never logs the presented or stored key.
- ``require_control_key_or_session`` — key-reveal / rotate and local permission
  endpoints. A valid authenticated UI session may use them; a raw loopback peer
  is never treated as authenticated.
- ``assert_bind_safe`` — fail-closed boot check (cloud-first): never expose a
  non-loopback bind without a key.
"""
from __future__ import annotations

from fastapi import HTTPException, Request, status

from dodaios.core import control_key as ck

from .missions_auth import validate_token
from .surface_security import COOKIE_NAME, open_access_granted

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_UNAUTHORIZED = {
    "status_code": status.HTTP_401_UNAUTHORIZED,
    "detail": "Invalid or missing Dodaios Control API key.",
    "headers": {"WWW-Authenticate": "Bearer"},
}


def _bearer_token(request: Request) -> str | None:
    """Extract a non-empty Bearer token, or ``None``. Never logs it."""
    header = request.headers.get("authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return None


def person_at_window(request: Request) -> bool:
    """Whether the request positively comes from the person at the app's window.

    The person is identified by what only the desktop UI carries: its session
    cookie, or (open local access, the default, has no cookie at all) the
    browser-set ``Sec-Fetch-Site: same-origin`` header on a request without an
    ``Authorization`` header. A script presenting the control key, an
    in-process app command the brain made, and a local process presenting no
    credential at all are not the person.

    Honest limit: ``Sec-Fetch-Site`` is a "forbidden header" for page scripts,
    so a page cannot fake it, but a local process that deliberately forges it
    is indistinguishable from the WebView. This tells a person from an agent
    that follows its instructions; it is not a boundary against malware.
    """
    if validate_token(request.cookies.get(COOKIE_NAME, "")):
        return True
    if _bearer_token(request) is not None:
        return False
    return request.headers.get("sec-fetch-site", "").strip().lower() == "same-origin"


async def require_control_key(request: Request) -> None:
    """FastAPI dependency: require a valid Bearer control key (401 otherwise).

    Loopback does NOT bypass this — a local agent on desktop must present the
    key, otherwise the key would be meaningless for the very callers it exists
    to gate.
    """
    if not ck.verify_control_key(_bearer_token(request)):
        raise HTTPException(**_UNAUTHORIZED)


async def require_control_key_or_session(request: Request) -> None:
    """Allow a control Bearer, an authenticated UI session, or local open access.

    Open access mirrors the outer boundary (``surface_security``): when the
    optional browser lock is off, a loopback-to-loopback UI has no session
    cookie at all, yet must still reach the key panel — otherwise the user
    could never see the key they would need to turn the lock ON.
    """
    session_token = request.cookies.get(COOKIE_NAME, "")
    if validate_token(session_token) or ck.verify_control_key(_bearer_token(request)):
        return
    if open_access_granted(request.scope):
        return
    raise HTTPException(**_UNAUTHORIZED)


def assert_bind_safe(host: str, key: str | None) -> None:
    """Fail-closed: refuse a non-loopback bind without a control key.

    On a VPS the key is the only boundary — binding ``0.0.0.0`` with no key
    would expose an unauthenticated control surface. Desktop (127.0.0.1) needs
    no key to bind. Called at the bind site before uvicorn starts.
    """
    if host and host not in _LOOPBACK_HOSTS and not key:
        raise RuntimeError(
            "Refusing to bind the Dodaios Control API to a non-loopback address "
            f"({host!r}) without a control key. The API key is the security "
            "boundary on a VPS — generate one first (control_key.ensure_control_key)."
        )
