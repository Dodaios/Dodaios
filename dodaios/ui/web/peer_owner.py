"""Who owns the other end of a loopback connection.

Loopback is shared by every account on the machine: a process of another
user (a second login, a service account) can connect to ``127.0.0.1`` just
like the owner's browser, and it can send any header it likes. Local open
access (``surface_security.open_access_granted``) is meant for the machine's
own user, so the peer socket's owning process is looked up and its account
compared with the account this process runs under.

The lookup applies only to requests that arrived on a real socket: the place
that binds the listener wraps its app in :func:`from_socket`, which marks each
scope. In-process ASGI callers (the app calling its own routes, tests,
embedders) have no socket to look up and are left alone.

Verdicts:

``same``     the peer runs as this process's user;
``system``   the peer runs as the operating system itself (``SYSTEM`` /
             ``root``) — it already controls the machine, and local traffic
             filters run under it;
``other``    the peer runs as a different account;
``unknown``  the connection could not be found or its owner not read.

Only ``same`` and ``system`` count as the local user. Supported on Windows
(``GetExtendedTcpTable``) and Linux (``/proc/net/tcp``); elsewhere there is no
cheap, dependency-free lookup, so the check stays out of the way there.

Dependency-light on purpose (stdlib only): the module is imported by the
security boundary on the boot critical path.
"""

from __future__ import annotations

import ipaddress
import os
import sys
import threading
import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any, Literal

Verdict = Literal["same", "system", "other", "unknown"]
#: ``(client_host, client_port, server_host, server_port) -> Verdict``
Resolver = Callable[[str, int, str, int], Verdict]

#: Scope key set by :func:`from_socket`. Clients cannot forge it: an ASGI
#: scope is built by the server from the wire request, and no header or
#: query value becomes a scope key.
SOCKET_SCOPE_KEY = "dodaios.peer_owner.socket"

_LOCK = threading.Lock()
_RESOLVER: Resolver | None = None
_RESOLVER_LOADED = False

#: Verdicts already reached, keyed by the identity of the connection's
#: ``scope["client"]`` tuple. The server builds that tuple once per connection
#: and hands the same object to every request on it; the cache keeps a
#: reference, so the identity cannot be reused by a later connection while its
#: entry lives. A new connection therefore always gets a fresh lookup, even
#: when it reuses the port of one that just closed.
_CACHE: dict[int, tuple[Any, Verdict, float]] = {}
_CACHE_TTL_S = 30.0
_CACHE_MAX = 512


def from_socket(
    app: Callable[[Any, Any, Any], Awaitable[None]],
) -> Callable[[Any, Any, Any], Awaitable[None]]:
    """Wrap the app a real listener serves, so its peers are looked up.

    Returns a plain async function on purpose: the server's ASGI-version
    probe reads a bound method or callable object as ASGI2.
    """

    async def socket_app(scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") in ("http", "websocket"):
            scope[SOCKET_SCOPE_KEY] = True
        await app(scope, receive, send)

    return socket_app


def set_resolver(resolver: Resolver | None) -> None:
    """Replace the platform lookup (tests). ``None`` restores the default."""
    global _RESOLVER, _RESOLVER_LOADED
    with _LOCK:
        _RESOLVER = resolver
        _RESOLVER_LOADED = resolver is not None
        _CACHE.clear()


def _platform_resolver() -> Resolver | None:
    if sys.platform == "win32":
        return _windows_owner
    if sys.platform.startswith("linux"):
        return _linux_owner
    return None


def _resolver() -> Resolver | None:
    global _RESOLVER, _RESOLVER_LOADED
    with _LOCK:
        if not _RESOLVER_LOADED:
            _RESOLVER = _platform_resolver()
            _RESOLVER_LOADED = True
        return _RESOLVER


def _endpoint(value: Any) -> tuple[str, int] | None:
    if not isinstance(value, (tuple, list)) or len(value) < 2:
        return None
    host, port = value[0], value[1]
    if not isinstance(host, str) or not isinstance(port, int) or not 0 < port <= 65535:
        return None
    return host, port


def peer_verdict(scope: MutableMapping[str, Any]) -> Verdict | None:
    """The owner of ``scope``'s peer, or ``None`` when no lookup applies."""
    if scope.get(SOCKET_SCOPE_KEY) is not True:
        return None
    resolver = _resolver()
    if resolver is None:
        return None
    raw_client = scope.get("client")
    client = _endpoint(raw_client)
    server = _endpoint(scope.get("server"))
    if client is None or server is None:
        return "unknown"

    now = time.monotonic()
    key = id(raw_client)
    with _LOCK:
        hit = _CACHE.get(key)
        if hit is not None and hit[0] is raw_client and hit[2] >= now:
            return hit[1]

    try:
        verdict = resolver(client[0], client[1], server[0], server[1])
        if verdict == "unknown":
            # The table is read without a lock on the stack; one retry covers
            # a connection that was mid-setup in the first snapshot.
            verdict = resolver(client[0], client[1], server[0], server[1])
    except Exception:  # noqa: BLE001 — a failed lookup must deny, never crash a request
        verdict = "unknown"

    with _LOCK:
        if len(_CACHE) >= _CACHE_MAX:
            for stale in [k for k, v in _CACHE.items() if v[2] < now]:
                del _CACHE[stale]
            if len(_CACHE) >= _CACHE_MAX:
                _CACHE.clear()
        _CACHE[key] = (raw_client, verdict, now + _CACHE_TTL_S)
    return verdict


def peer_is_local_user(scope: MutableMapping[str, Any]) -> bool:
    """Whether the peer may count as the machine's own user.

    True when no lookup applies (an in-process request, or a platform without
    a lookup), so callers combine it with their other loopback checks.
    """
    verdict = peer_verdict(scope)
    return verdict is None or verdict in ("same", "system")


# ---------------------------------------------------------------------------
# Linux — /proc/net/tcp and /proc/net/tcp6 list every socket with its uid.
# ---------------------------------------------------------------------------


def _proc_address(text: str) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, int] | None:
    """``0100007F:1F90`` / 32-hex-digit IPv6 form → (address, port)."""
    raw, _, port_hex = text.partition(":")
    try:
        port = int(port_hex, 16)
        data = bytes.fromhex(raw)
    except ValueError:  # not an address column; the caller skips the line
        return None
    # The kernel prints each 32-bit word in host byte order.
    if sys.byteorder == "little":
        data = b"".join(data[i : i + 4][::-1] for i in range(0, len(data), 4))
    if len(data) == 4:
        return ipaddress.IPv4Address(data), port
    if len(data) == 16:
        address = ipaddress.IPv6Address(data)
        return (address.ipv4_mapped or address), port
    return None


def _same_address(a: ipaddress.IPv4Address | ipaddress.IPv6Address, text: str) -> bool:
    try:
        b: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(text)
    except ValueError:  # a host name is never the address being looked for
        return False
    if isinstance(b, ipaddress.IPv6Address) and b.ipv4_mapped is not None:
        b = b.ipv4_mapped
    return a == b


def _uid_from_proc_table(
    table: str, client_host: str, client_port: int, server_host: str, server_port: int
) -> int | None:
    """The uid of the socket whose local end is the client, or ``None``."""
    for line in table.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 8:
            continue
        local = _proc_address(fields[1])
        remote = _proc_address(fields[2])
        if local is None or remote is None:
            continue
        if local[1] != client_port or remote[1] != server_port:
            continue
        if not _same_address(local[0], client_host) or not _same_address(remote[0], server_host):
            continue
        try:
            return int(fields[7])
        except ValueError:  # a malformed uid column counts as "not found"
            return None
    return None


def _linux_owner(client_host: str, client_port: int, server_host: str, server_port: int) -> Verdict:
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(path, encoding="ascii", errors="replace") as fh:
                table = fh.read()
        except OSError:  # no such table here (IPv6 off); the other one decides
            continue
        uid = _uid_from_proc_table(table, client_host, client_port, server_host, server_port)
        if uid is None:
            continue
        if uid == os.geteuid():  # type: ignore[attr-defined]  # POSIX only
            return "same"
        return "system" if uid == 0 else "other"
    return "unknown"


# ---------------------------------------------------------------------------
# Windows — the TCP table names the owning process; its token names the user.
# ---------------------------------------------------------------------------

_AF_INET = 2
_AF_INET6 = 23
_TCP_TABLE_OWNER_PID_CONNECTIONS = 4
_ERROR_INSUFFICIENT_BUFFER = 122
_ERROR_ACCESS_DENIED = 5
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_TOKEN_QUERY = 0x0008
_TOKEN_USER_CLASS = 1
_WIN_LOCAL_SYSTEM_SID = 22
_SYSTEM_PID = 4


def _windows_pid(
    client_host: str, client_port: int, server_host: str, server_port: int
) -> int | None:
    """PID of the process whose socket is the client end, or ``None``."""
    import ctypes
    import struct
    from ctypes import wintypes

    try:
        client_ip = ipaddress.ip_address(client_host)
        server_ip = ipaddress.ip_address(server_host)
    except ValueError:  # a host name, not an address: nothing to look up
        return None
    if client_ip.version != server_ip.version:
        return None
    family = _AF_INET if client_ip.version == 4 else _AF_INET6

    iphlpapi = ctypes.WinDLL("iphlpapi")  # type: ignore[attr-defined]
    get_table = iphlpapi.GetExtendedTcpTable
    get_table.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.BOOL,
        wintypes.ULONG,
        ctypes.c_int,
        wintypes.ULONG,
    ]
    get_table.restype = wintypes.DWORD

    size = wintypes.DWORD(0)
    get_table(None, ctypes.byref(size), False, family, _TCP_TABLE_OWNER_PID_CONNECTIONS, 0)
    buf = ctypes.create_string_buffer(0)
    for _ in range(4):  # the table can grow between the size call and the read
        buf = ctypes.create_string_buffer(size.value + 4096)
        size = wintypes.DWORD(len(buf))
        rc = get_table(buf, ctypes.byref(size), False, family, _TCP_TABLE_OWNER_PID_CONNECTIONS, 0)
        if rc == 0:
            break
        if rc != _ERROR_INSUFFICIENT_BUFFER:
            return None
    else:
        return None

    (count,) = struct.unpack_from("<I", buf, 0)
    client_port_be = client_port.to_bytes(2, "big")
    server_port_be = server_port.to_bytes(2, "big")
    if family == _AF_INET:
        # MIB_TCPROW_OWNER_PID: state, local addr, local port, remote addr,
        # remote port, pid — six DWORDs; addresses and ports in network order.
        row = 24
        want_local = client_ip.packed
        want_remote = server_ip.packed
        for i in range(count):
            base = 4 + i * row
            if base + row > len(buf):
                break
            if (
                buf[base + 4 : base + 8] == want_local
                and buf[base + 8 : base + 10] == client_port_be
                and buf[base + 12 : base + 16] == want_remote
                and buf[base + 16 : base + 18] == server_port_be
            ):
                return int(struct.unpack_from("<I", buf, base + 20)[0])
        return None
    # MIB_TCP6ROW_OWNER_PID: local addr[16], local scope, local port,
    # remote addr[16], remote scope, remote port, state, pid.
    row = 56
    want_local = client_ip.packed
    want_remote = server_ip.packed
    for i in range(count):
        base = 4 + i * row
        if base + row > len(buf):
            break
        if (
            buf[base : base + 16] == want_local
            and buf[base + 20 : base + 22] == client_port_be
            and buf[base + 24 : base + 40] == want_remote
            and buf[base + 44 : base + 46] == server_port_be
        ):
            return int(struct.unpack_from("<I", buf, base + 52)[0])
    return None


def _windows_token_user(kernel32: Any, advapi32: Any, token: Any) -> Any | None:
    """``TOKEN_USER`` buffer of ``token`` (the SID pointer is its first field)."""
    import ctypes
    from ctypes import wintypes

    needed = wintypes.DWORD(0)
    advapi32.GetTokenInformation(token, _TOKEN_USER_CLASS, None, 0, ctypes.byref(needed))
    if not needed.value:
        return None
    buf = ctypes.create_string_buffer(needed.value)
    if not advapi32.GetTokenInformation(
        token, _TOKEN_USER_CLASS, buf, needed.value, ctypes.byref(needed)
    ):
        return None
    return buf


def _windows_owner(
    client_host: str, client_port: int, server_host: str, server_port: int
) -> Verdict:
    import ctypes
    from ctypes import wintypes

    pid = _windows_pid(client_host, client_port, server_host, server_port)
    if pid is None or pid == 0:
        return "unknown"
    if pid == _SYSTEM_PID:
        return "system"
    if pid == os.getpid():
        return "same"

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    advapi32.EqualSid.restype = wintypes.BOOL
    advapi32.IsWellKnownSid.argtypes = [ctypes.c_void_p, ctypes.c_int]
    advapi32.IsWellKnownSid.restype = wintypes.BOOL

    def token_user(process: Any) -> Any | None:
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(process, _TOKEN_QUERY, ctypes.byref(token)):
            return None
        try:
            return _windows_token_user(kernel32, advapi32, token)
        finally:
            kernel32.CloseHandle(token)

    def sid_of(buf: Any) -> int:
        return int(ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0] or 0)

    own = token_user(kernel32.GetCurrentProcess())
    if own is None:
        return "unknown"

    process = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        # A process of this user can always be opened for a limited query, so
        # a refusal means the peer belongs to someone else.
        return "other" if ctypes.get_last_error() == _ERROR_ACCESS_DENIED else "unknown"
    try:
        peer = token_user(process)
        if peer is None:
            return "other" if ctypes.get_last_error() == _ERROR_ACCESS_DENIED else "unknown"
        if advapi32.EqualSid(sid_of(peer), sid_of(own)):
            return "same"
        if advapi32.IsWellKnownSid(sid_of(peer), _WIN_LOCAL_SYSTEM_SID):
            return "system"
        return "other"
    finally:
        kernel32.CloseHandle(process)


__all__ = [
    "SOCKET_SCOPE_KEY",
    "Resolver",
    "Verdict",
    "from_socket",
    "peer_is_local_user",
    "peer_verdict",
    "set_resolver",
]
