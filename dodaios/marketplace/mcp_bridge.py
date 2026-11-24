"""Bridge connected marketplace plugins into a claude-cli MCP config.

This is the missing wire between the Marketplace (where a user *connects* a
plugin by saving a token) and the delegated Heavy-Duty Worker (which runs the
`claude` CLI and can call MCP tools). The talker stays thin: it only delegates;
the worker is the one that actually issues the plugin/MCP tool calls (AD-OE4).

`assemble_claude_mcp_servers` reads every catalog plugin, keeps the ones that
have a saved token (= connected), and converts each plugin's `mcp_server`
spec + token into a claude-cli `mcpServers` entry:

* ``transport: "stdio"``  -> ``{"command", "args", "env"}`` (token resolved
  into the env_template / argv placeholders).
* ``transport: "http"``   -> ``{"type": "http", "url", "headers"}`` (token
  resolved into the Authorization bearer header); ``"sse"`` likewise with
  ``"type": "sse"``.
* ``transport: "rest_wrapper"`` (or anything else) -> skipped: it is not a
  real MCP server claude-cli can speak to.

User ``mcp.json`` servers can be merged in via ``extra_servers``.

A coding CLI that reads such a map replaces variable references in it from
its OWN environment: ``${NAME}`` in a command, an argument, an env value, a
url or a header (some CLIs also ``$NAME``). So an entry built here must hold
no ``$`` once the plugin's own placeholder is filled in. A plugin whose
entry or token still does is left out of the map (see
``_holds_variable_reference``): what came from a manifest or from the
plugin's own sign-in server must never be answered with a variable of the
owner's environment and sent to the plugin's server.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from dodaios.marketplace.bundled_servers import runs_bundled_server, runs_connected_server
from dodaios.marketplace.catalog import PluginCatalog
from dodaios.marketplace.token_store import TokenStore

log = logging.getLogger(__name__)

#: Plugins already reported as left out, so one warning per plugin and process
#: instead of one per mission.
_REPORTED_LEFT_OUT: set[str] = set()


def _resolve_placeholders(value: str, replacements: dict[str, str]) -> str:
    """Replace ``$plugin_<id>_access_token`` / ``${...}`` placeholders."""
    out = value
    for placeholder, real in replacements.items():
        out = out.replace(placeholder, real)
    return out


def _token_replacements(plugin_id: str, access_token: str) -> dict[str, str]:
    base = f"plugin_{plugin_id}_access_token"
    # Catalog uses both bare ($x) and braced (${x}) placeholder forms.
    return {f"${{{base}}}": access_token, f"${base}": access_token}


def _stdio_entry(spec: dict[str, Any], repl: dict[str, str]) -> dict[str, Any] | None:
    install = spec.get("install") or []
    if not install:
        return None
    command = _resolve_placeholders(str(install[0]), repl)
    args = [_resolve_placeholders(str(a), repl) for a in install[1:]]
    if command == "python" and runs_bundled_server([command, *args]):
        command = sys.executable
    entry: dict[str, Any] = {"command": command, "args": args}
    env_template = spec.get("env_template") or {}
    env = {str(k): _resolve_placeholders(str(v), repl) for k, v in env_template.items()}
    if env:
        entry["env"] = env
    return entry


def _http_entry(spec: dict[str, Any], repl: dict[str, str]) -> dict[str, Any] | None:
    url = spec.get("url")
    if not url:
        return None
    kind = "sse" if str(spec.get("transport") or "").lower() == "sse" else "http"
    entry: dict[str, Any] = {"type": kind, "url": str(url)}
    header_template = spec.get("auth_header_template")
    if header_template:
        resolved = _resolve_placeholders(str(header_template), repl)
        key, sep, val = resolved.partition(":")
        if sep:
            entry["headers"] = {key.strip(): val.strip()}
    return entry


def _holds_variable_reference(entry: dict[str, Any], access_token: str) -> bool:
    """Whether a CLI could replace part of ``entry`` with one of its own variables.

    True when the token the plugin was connected with contains a ``$``, or
    when any text of the built entry still does after the plugin's own
    placeholder was filled in. No shipped plugin needs one: every string of
    every ``mcp_server`` block in the bundled catalog is free of ``$`` once
    its own placeholder is resolved.

    The interpreter path a bundled server is started with is this machine's
    own (``sys.executable``), not catalog text, and is not looked at.
    """
    if "$" in access_token:
        return True
    values: list[str] = [str(entry.get("url") or "")]
    command = entry.get("command")
    if command is not None and command != sys.executable:
        values.append(str(command))
    values.extend(str(arg) for arg in entry.get("args") or ())
    for mapping in (entry.get("env"), entry.get("headers")):
        for key, value in (mapping or {}).items():
            values.extend((str(key), str(value)))
    return any("$" in value for value in values)


def _report_left_out(plugin_id: str) -> None:
    """One warning per plugin: the id only, never the entry or the token."""
    if plugin_id in _REPORTED_LEFT_OUT:
        return
    _REPORTED_LEFT_OUT.add(plugin_id)
    log.warning(
        "mcp_bridge: plugin %s is not handed to a coding CLI: its server entry "
        "or its token holds a '$', which a CLI would replace with a variable of "
        "its own environment. Reconnect the plugin or correct its entry.",
        plugin_id,
    )


def assemble_claude_mcp_servers(
    catalog: PluginCatalog,
    token_store: TokenStore,
    *,
    extra_servers: dict[str, dict] | None = None,
) -> dict[str, dict]:
    """Build a claude-cli ``mcpServers`` map from connected plugins + extras.

    A plugin counts as *connected* when ``token_store.load(plugin.id)`` returns
    a token. Plugins without an MCP-capable transport (e.g. Vercel's
    ``rest_wrapper``) are skipped, and so is a plugin whose entry or token
    still holds a ``$`` (``_holds_variable_reference``). Plugin entries take
    precedence over ``extra_servers`` on a name clash; a plugin that is left
    out also removes an extra of the same name, so its id never points at a
    different server.
    """
    servers: dict[str, dict] = dict(extra_servers or {})

    for plugin in catalog.plugins:
        spec = plugin.mcp_server
        if not spec:
            continue
        try:
            tokens = token_store.load(plugin.id)
        except Exception as exc:  # noqa: BLE001 — a corrupt token must not nuke the rest
            log.warning("mcp_bridge: token load failed for %s: %s", plugin.id, exc)
            continue
        if tokens is None:
            continue  # not connected

        repl = _token_replacements(plugin.id, tokens.access)
        transport = str(spec.get("transport") or "").lower()
        if transport == "stdio":
            entry = _stdio_entry(spec, repl)
            if entry is not None and runs_connected_server(
                [entry["command"], *entry.get("args", [])]
            ):
                entry.setdefault("env", {})["JARVIS_CONNECTOR_AUTH_TYPE"] = (
                    "oauth" if tokens.extra.get("client_id") else "pat"
                )
        elif transport in ("http", "sse"):
            entry = _http_entry(spec, repl)
        else:
            # rest_wrapper / unknown -> not a claude-cli MCP server
            entry = None

        if entry is None:
            continue
        if _holds_variable_reference(entry, tokens.access):
            _report_left_out(plugin.id)
            servers.pop(plugin.id, None)
            continue
        servers[plugin.id] = entry

    return servers
