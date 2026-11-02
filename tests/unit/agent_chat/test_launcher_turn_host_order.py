"""The web launcher turns the host switch on before the agent-chat service can exist.

The background service (``launcher --headless``) takes over when the desktop
app closes. Its init chain in ``server.start`` can build the agent-chat
service; built while ``host_mode`` was still off, the service saw no turn host
and closed every thread turn the host was still running as "The app
restarted" (2026-11-02). The desktop shell already turned the switch on early.
"""

from __future__ import annotations

import inspect

from dodaios.ui.web import launcher


def test_headless_launcher_enables_host_mode_before_the_server_exists() -> None:
    source = inspect.getsource(launcher._run_headless)
    enable = source.find("host_mode.enable()")
    assert enable != -1, "the headless launcher must turn host_mode on itself"
    assert enable < source.find("WebServer(cfg)")
    assert enable < source.find("await server.start(")
