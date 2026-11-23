"""Local open access is for this user's own processes only.

Loopback is shared by every account on the machine. With the browser lock
off, the boundary used to serve any loopback peer without a credential, so a
process of ANOTHER local account could read the API and, by sending the app's
own ``Origin``, write to it. The listener now looks up which account owns the
peer socket and grants open access only to this user (and the operating
system itself). A peer of another account needs a credential like any
network caller.
"""
from __future__ import annotations

import socket
import sys

import pytest
from fastapi.testclient import TestClient

from dodaios.core import control_key
from dodaios.ui.web import peer_owner, surface_security
from dodaios.ui.web.missions_auth import register_token, reset_tokens
from dodaios.ui.web.surface_security import COOKIE_NAME, SurfaceSecurity

pytestmark = pytest.mark.no_auto_web_auth

_BASE_URL = "http://127.0.0.1:47821"
_ORIGIN = "http://127.0.0.1:47821"
_SESSION_TOKEN = "session-token-for-peer-owner-tests"  # noqa: S105
_CONTROL_KEY = "jctl_control_key_for_peer_owner_tests"  # noqa: S105
_SOCKET = {peer_owner.SOCKET_SCOPE_KEY: True}


class _ProbeApp:
    def __init__(self) -> None:
        self.paths: list[str] = []

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope["type"] == "websocket":
            await receive()
            await send({"type": "websocket.accept"})
            await send({"type": "websocket.close", "code": 1000})
            return
        self.paths.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"reached"})


@pytest.fixture(autouse=True)
def _state(monkeypatch: pytest.MonkeyPatch):
    reset_tokens()
    register_token(_SESSION_TOKEN)
    monkeypatch.setattr(control_key, "get_control_key", lambda: _CONTROL_KEY)
    surface_security.set_browser_login_required(False)
    try:
        yield
    finally:
        peer_owner.set_resolver(None)
        surface_security.reset_browser_login_required()
        reset_tokens()


def _peers_are(verdict: peer_owner.Verdict) -> list[tuple[str, int, str, int]]:
    """Every peer socket belongs to ``verdict``'s account."""
    seen: list[tuple[str, int, str, int]] = []

    def resolver(client_host: str, client_port: int, server_host: str, server_port: int):
        seen.append((client_host, client_port, server_host, server_port))
        return verdict

    peer_owner.set_resolver(resolver)
    return seen


def _client(*, socket_listener: bool = True) -> tuple[TestClient, _ProbeApp]:
    """The boundary as a real listener serves it (or as an in-process caller)."""
    inner = _ProbeApp()
    secured = SurfaceSecurity(inner)
    app = peer_owner.from_socket(secured) if socket_listener else secured
    return TestClient(app, base_url=_BASE_URL, client=("127.0.0.1", 50_000)), inner


@pytest.mark.parametrize("verdict", ["other", "unknown"])
def test_another_accounts_process_gets_no_open_read(verdict: peer_owner.Verdict) -> None:
    _peers_are(verdict)
    client, inner = _client()

    response = client.get("/api/settings", headers={"Host": "127.0.0.1:47821"})

    assert response.status_code == 401
    assert inner.paths == []


@pytest.mark.parametrize("verdict", ["other", "unknown"])
def test_another_accounts_process_cannot_write_with_the_apps_origin(
    verdict: peer_owner.Verdict,
) -> None:
    _peers_are(verdict)
    client, inner = _client()

    response = client.post(
        "/api/agentic-ide/terminals",
        headers={"Host": "127.0.0.1:47821", "Origin": _ORIGIN},
        json={},
    )

    assert response.status_code == 401
    assert inner.paths == []


def test_another_accounts_process_cannot_open_a_socket() -> None:
    from starlette.websockets import WebSocketDisconnect

    _peers_are("other")
    client, _inner = _client()

    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect(
            "/ws", headers={"Host": "127.0.0.1:47821", "Origin": _ORIGIN}
        ) as ws:
            ws.receive_text()

    assert closed.value.code == 4401


@pytest.mark.parametrize("verdict", ["same", "system"])
def test_this_users_own_process_keeps_open_access(verdict: peer_owner.Verdict) -> None:
    seen = _peers_are(verdict)
    client, inner = _client()

    read = client.get("/api/settings", headers={"Host": "127.0.0.1:47821"})
    write = client.post(
        "/api/settings", headers={"Host": "127.0.0.1:47821", "Origin": _ORIGIN}, json={}
    )

    assert (read.status_code, write.status_code) == (200, 200)
    assert inner.paths == ["/api/settings", "/api/settings"]
    assert seen and seen[0][:2] == ("127.0.0.1", 50_000)


def test_a_credential_still_works_for_another_accounts_process() -> None:
    _peers_are("other")
    client, inner = _client()

    with_key = client.get(
        "/api/settings",
        headers={"Host": "127.0.0.1:47821", "Authorization": f"Bearer {_CONTROL_KEY}"},
    )
    with_session = client.get(
        "/api/settings",
        headers={"Host": "127.0.0.1:47821", "Cookie": f"{COOKIE_NAME}={_SESSION_TOKEN}"},
    )

    assert (with_key.status_code, with_session.status_code) == (200, 200)


def test_public_reads_do_not_depend_on_the_peer() -> None:
    _peers_are("other")
    client, _inner = _client()

    assert client.get("/api/health", headers={"Host": "127.0.0.1:47821"}).status_code == 200


def test_no_lookup_for_an_in_process_caller() -> None:
    """The app calling its own routes in-process has no socket to look up."""
    peer_owner.set_resolver(lambda *_: "other")
    client, inner = _client(socket_listener=False)

    assert client.get("/api/settings", headers={"Host": "127.0.0.1:47821"}).status_code == 200


def test_a_failing_lookup_denies() -> None:
    def broken(*_args: object) -> peer_owner.Verdict:
        raise OSError("table unavailable")

    peer_owner.set_resolver(broken)
    client, inner = _client()

    assert client.get("/api/settings", headers={"Host": "127.0.0.1:47821"}).status_code == 401


def test_verdict_is_cached_per_connection_not_per_port() -> None:
    calls: list[int] = []

    def resolver(_ch: str, client_port: int, _sh: str, _sp: int) -> peer_owner.Verdict:
        calls.append(client_port)
        return "same"

    peer_owner.set_resolver(resolver)
    first = ("127.0.0.1", 50_000)
    scope = {**_SOCKET, "client": first, "server": ("127.0.0.1", 47821)}

    assert peer_owner.peer_verdict(scope) == "same"
    assert peer_owner.peer_verdict(scope) == "same"
    assert calls == [50_000]

    # A later connection that reuses the port is a different connection.
    reused = tuple(["127.0.0.1", 50_000])
    assert reused == first and reused is not first
    again = {**_SOCKET, "client": reused, "server": ("127.0.0.1", 47821)}
    assert peer_owner.peer_verdict(again) == "same"
    assert calls == [50_000, 50_000]


def test_proc_table_names_the_clients_uid() -> None:
    table = (
        "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt"
        "   uid  timeout inode\n"
        "   0: 0100007F:BAD5 0100007F:BACD 01 00000000:00000000 00:00000000 00000000"
        "  1001        0 12345 1 0000000000000000 20 4 30 10 -1\n"
        "   1: 0100007F:BACD 0100007F:BAD5 01 00000000:00000000 00:00000000 00000000"
        "  1000        0 12346 1 0000000000000000 20 4 30 10 -1\n"
    )
    if sys.byteorder != "little":
        pytest.skip("the sample is a little-endian kernel's table")

    uid = peer_owner._uid_from_proc_table(table, "127.0.0.1", 0xBAD5, "127.0.0.1", 0xBACD)

    assert uid == 1001
    assert peer_owner._uid_from_proc_table(table, "127.0.0.1", 1, "127.0.0.1", 0xBACD) is None


@pytest.mark.skipif(
    not (sys.platform == "win32" or sys.platform.startswith("linux")),
    reason="no peer lookup on this platform",
)
def test_live_lookup_recognises_this_process_as_the_same_user() -> None:
    server = socket.socket()
    client = socket.socket()
    try:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        client.connect(("127.0.0.1", port))
        accepted, peer = server.accept()
        try:
            scope = {**_SOCKET, "client": (peer[0], peer[1]), "server": ("127.0.0.1", port)}
            assert peer_owner.peer_verdict(scope) == "same"
            missing = {**_SOCKET, "client": ("127.0.0.1", 1), "server": ("127.0.0.1", port)}
            assert peer_owner.peer_verdict(missing) == "unknown"
        finally:
            accepted.close()
    finally:
        client.close()
        server.close()
