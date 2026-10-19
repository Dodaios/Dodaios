"""Agent screens — a screen the agent owns, isolated from the user's desktop.

Computer-Use drives ONE physical pointer, so a background agent using it takes
the machine away from the user. An agent screen removes that trade: the agent
gets its own session (a Windows Sandbox, a virtual X display) with its own
framebuffer and its own input stream, and works there while the user keeps
typing on theirs.

Public surface:

* :mod:`~dodaios.agent_screen.manager` — leases screens, one per owner.
* :mod:`~dodaios.agent_screen.port` — the seam the Computer-Use engine
  perceives through; ``RealScreenPort`` preserves today's behaviour exactly.
* :mod:`~dodaios.agent_screen.tools` — action tools with the SAME names as the
  desktop tools, so swapping the tool map redirects a whole mission.
"""

from dodaios.agent_screen.manager import (
    AgentScreenManager,
    ScreenSettings,
    get_agent_screen_manager,
    peek_agent_screen_manager,
    set_agent_screen_manager,
)
from dodaios.agent_screen.port import RealScreenPort, RemoteScreenPort, resolve_port
from dodaios.agent_screen.protocol import (
    AgentScreenUnavailable,
    ProbeResult,
    ScreenLease,
    ScreenSession,
    ScreenSpec,
)
from dodaios.agent_screen.tools import screen_bound_tools

__all__ = [
    "AgentScreenManager",
    "AgentScreenUnavailable",
    "ProbeResult",
    "RealScreenPort",
    "RemoteScreenPort",
    "ScreenLease",
    "ScreenSession",
    "ScreenSettings",
    "ScreenSpec",
    "get_agent_screen_manager",
    "peek_agent_screen_manager",
    "resolve_port",
    "screen_bound_tools",
    "set_agent_screen_manager",
]
