"""Screen providers, one per way of getting an isolated session on a host."""

from dodaios.agent_screen.providers.attached import AttachedProvider
from dodaios.agent_screen.providers.windows_sandbox import WindowsSandboxProvider
from dodaios.agent_screen.providers.xvfb import XvfbProvider

__all__ = ["AttachedProvider", "WindowsSandboxProvider", "XvfbProvider"]
