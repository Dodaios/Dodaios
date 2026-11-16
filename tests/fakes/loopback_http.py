"""An HTTP server for test stand-ins that binds without a host name lookup.

``HTTPServer.server_bind`` resolves ``socket.getfqdn(host)`` after the bind.
On the hosted macOS runners that reverse lookup can stall for many seconds
(about 35 s in #450, past the 30 s boot window in #1724), so a stand-in
started under a short readiness wait is not listening yet when the test talks
to it. A stand-in never uses the looked-up name, so the plain TCP bind is all
it needs.
"""

from __future__ import annotations

import socketserver
from http.server import ThreadingHTTPServer


class LoopbackHTTPServer(ThreadingHTTPServer):
    """``ThreadingHTTPServer`` without the reverse DNS lookup in ``server_bind``."""

    daemon_threads = True

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)
