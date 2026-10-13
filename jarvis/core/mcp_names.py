"""Tool names as a client spells them once it has mounted this app's tools server.

A coding CLI names an MCP tool after the server it came from, and each one in
its own way: Claude Code ``mcp__<server>__<tool>``, Grok Build
``<server>__<tool>``, Hermes ``mcp_<server>_<tool>``, opencode
``<server>_<tool>``. The server part is the name this app registered itself
under (``jarvis.core.branding.MCP_TOOLS_SERVER_NAME``), so it changed when the
product was renamed, and both spellings exist from then on: registrations a
tool still holds, transcripts already written, a client that was not restarted.

Everything that reads such a name asks this module instead of comparing against
one literal, so a call is recognised as the app's own under every name the
server has had. Standard-library only and import-light: it sits under matchers
on the event path.
"""

from __future__ import annotations

from typing import Final

from .branding import LEGACY_MCP_TOOLS_SERVER_NAMES, MCP_TOOLS_SERVER_NAME

__all__ = [
    "CLI_TOOL_PREFIX",
    "TOOLS_SERVER_NAMES",
    "cli_tool_name",
    "is_tools_server",
    "own_cli_tool",
    "own_cli_tool_prefixes",
    "split_cli_tool_name",
]

#: What Claude Code puts in front of every MCP tool name.
CLI_TOOL_PREFIX: Final[str] = "mcp__"

#: Every name the tools server has been registered under, the current one first.
TOOLS_SERVER_NAMES: Final[tuple[str, ...]] = (
    MCP_TOOLS_SERVER_NAME,
    *LEGACY_MCP_TOOLS_SERVER_NAMES,
)


def is_tools_server(server: str) -> bool:
    """Whether ``server`` is a name this app's tools server is registered under."""
    return server in TOOLS_SERVER_NAMES


def cli_tool_name(tool: str, server: str = MCP_TOOLS_SERVER_NAME) -> str:
    """``mcp__<server>__<tool>``, the canonical spelling of an MCP tool call."""
    return f"{CLI_TOOL_PREFIX}{server}__{tool}"


def own_cli_tool_prefixes() -> tuple[str, ...]:
    """``mcp__dodaios__``, ``mcp__jarvis__``: the prefix under each server name."""
    return tuple(cli_tool_name("", server) for server in TOOLS_SERVER_NAMES)


def split_cli_tool_name(name: str) -> tuple[str, str] | None:
    """``("server", "tool")`` of an ``mcp__<server>__<tool>`` name, else ``None``."""
    if not name.startswith(CLI_TOOL_PREFIX):
        return None
    server, separator, tool = name[len(CLI_TOOL_PREFIX) :].partition("__")
    if not separator or not server or not tool:
        return None
    return server, tool


def own_cli_tool(name: str) -> str | None:
    """The tool behind a call to this app's own server, else ``None``.

    ``mcp__dodaios__gmail`` and ``mcp__jarvis__gmail`` both answer ``"gmail"``;
    another server's tool and a name without the MCP prefix answer ``None``.
    """
    parts = split_cli_tool_name(name)
    if parts is None or not is_tools_server(parts[0]):
        return None
    return parts[1]
