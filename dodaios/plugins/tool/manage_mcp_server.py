"""``manage-mcp-server`` tool — add / remove / enable / disable MCP servers.

Router-tier, ``ask`` (echo-confirm). This is the voice/chat path for
"add a new MCP server", "enable the GitHub MCP", "remove the filesystem MCP".

It edits ``mcp.json`` via :mod:`dodaios.mcp.state` (atomic write) and best-effort
reloads the live :class:`~dodaios.mcp.registry.MCPRegistry` so an enable takes
effect without a restart. A newly *added* server is created **disabled**
(``enabled=false``) — adding an MCP server is arbitrary command execution, so
the user reviews and enables it explicitly afterward (the skill draft→activate
safety stance, AP-15 spirit).

Security boundary (binding): any credential an MCP server needs is referenced as
a ``$SECRET_NAME`` placeholder in its ``env``/``headers`` — this tool never
accepts a raw secret value as an argument (AP-2). Secret values are stored via
the UI credential flow.
"""
from __future__ import annotations

import logging
from typing import Any, ClassVar

from dodaios.core.protocols import ExecutionContext, ToolResult

log = logging.getLogger(__name__)

_ACTIONS = ("add", "remove", "enable", "disable")
_TRANSPORTS = ("stdio", "http", "sse")


class ManageMcpServerTool:
    """Add/remove/enable/disable an MCP server in mcp.json."""

    name: ClassVar[str] = "manage-mcp-server"
    risk_tier: ClassVar[str] = "ask"
    description: ClassVar[str] = (
        "Manage the MCP (Model Context Protocol) servers Dodaios connects to, by "
        "editing mcp.json. Actions: 'add' a new server (give a name and the command "
        "to run, or a url for http/sse), 'remove' a server, 'enable' a server (start "
        "it), or 'disable' a server (stop using it). Use this for requests like "
        "'add a new MCP server', 'enable the GitHub MCP', or 'update the MCP config'. "
        "A newly added server starts DISABLED so the user can review it first. Never "
        "put a raw API key in here — reference secrets as $SECRET_NAME placeholders; "
        "real keys are entered in the Settings tab."
    )
    schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(_ACTIONS),
                "description": "add, remove, enable, or disable.",
            },
            "name": {
                "type": "string",
                "minLength": 1,
                "description": "The MCP server name (key in mcp.json).",
            },
            "command": {
                "type": "string",
                "description": "Executable for the server (add, stdio): npx / uvx / docker.",
            },
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Arguments for the command (add only).",
            },
            "transport": {
                "type": "string",
                "enum": list(_TRANSPORTS),
                "description": "Transport (add only); default 'stdio'.",
            },
            "url": {
                "type": "string",
                "description": "Server URL (add only, for http/sse transport).",
            },
            "description": {
                "type": "string",
                "description": "Human-readable description (add only).",
            },
            "reason": {
                "type": "string",
                "description": "Short reason for the change (for the echo / audit).",
            },
        },
        "required": ["action", "name", "reason"],
        "additionalProperties": False,
        "input_examples": [
            {
                "action": "add",
                "name": "github",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
                "description": "GitHub integration",
                "reason": "user wants GitHub MCP",
            },
            {"action": "enable", "name": "github", "reason": "user asked to turn it on"},
            {"action": "remove", "name": "filesystem", "reason": "no longer needed"},
        ],
    }

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:  # noqa: ARG002
        if not isinstance(args, dict):
            return ToolResult(
                success=False, output=None, error="invalid_input: args must be an object"
            )

        action = str(args.get("action", "")).strip().lower()
        name = str(args.get("name", "")).strip()
        reason = str(args.get("reason", "")).strip()

        if action not in _ACTIONS:
            return ToolResult(
                success=False, output=None,
                error=f"invalid_input: action must be one of {', '.join(_ACTIONS)}",
            )
        if not name:
            return ToolResult(success=False, output=None, error="invalid_input: 'name' is required")
        if not reason:
            return ToolResult(
                success=False, output=None, error="invalid_input: 'reason' is required"
            )

        try:
            from dodaios.mcp import state as mcp_state
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, output=None, error=f"mcp state unavailable: {exc}")

        try:
            if action == "add":
                return await self._add(mcp_state, name, args, reason)
            if action == "remove":
                return await self._remove(mcp_state, name, reason)
            # enable / disable
            return await self._toggle(mcp_state, name, enabled=(action == "enable"), reason=reason)
        except Exception as exc:  # noqa: BLE001
            log.warning("manage-mcp-server %s/%s failed: %s", action, name, exc, exc_info=True)
            return ToolResult(
                success=False, output=None,
                error=f"mcp {action} failed: {type(exc).__name__}: {exc}",
            )

    # -- actions ----------------------------------------------------------

    async def _add(
        self, mcp_state: Any, name: str, args: dict[str, Any], reason: str
    ) -> ToolResult:
        transport = str(args.get("transport") or "stdio").strip().lower()
        if transport not in _TRANSPORTS:
            return ToolResult(
                success=False, output=None,
                error=f"invalid_input: transport must be one of {', '.join(_TRANSPORTS)}",
            )
        command = str(args.get("command") or "").strip()
        url = str(args.get("url") or "").strip()
        if transport == "stdio" and not command:
            return ToolResult(
                success=False, output=None,
                error="invalid_input: 'command' is required for stdio transport",
            )
        if transport in ("http", "sse") and not url:
            return ToolResult(
                success=False, output=None,
                error=f"invalid_input: 'url' is required for {transport} transport",
            )

        raw_args = args.get("args") or []
        if not isinstance(raw_args, list) or any(not isinstance(a, str) for a in raw_args):
            return ToolResult(
                success=False,
                output=None,
                error="invalid_input: 'args' must be a list of strings",
            )

        spec: dict[str, Any] = {
            "transport": transport,
            "env": {},
            # Safe default: a newly added server is NOT auto-started. The user
            # reviews it, then enables it (AP-15 spirit — no auto-activation).
            "enabled": False,
            "description": str(args.get("description") or "").strip(),
        }
        if command:
            spec["command"] = command
        if raw_args:
            spec["args"] = list(raw_args)
        if url:
            spec["url"] = url

        mcp_state.upsert_server(name, spec)
        log.info("manage-mcp-server: added %r (disabled) reason=%r", name, reason)
        return ToolResult(
            success=True,
            output={
                "action": "add",
                "name": name,
                "enabled": False,
                "applied_live": True,  # nothing to start; file written
                "requires_restart": False,
                "note": (
                    f"Server added but disabled. Say 'enable the {name} MCP' "
                    "to start it."
                ),
            },
        )

    @staticmethod
    def _unknown_name_error(mcp_state: Any, name: str) -> str:
        """Name the configured servers so a miss is actionable, not a dead end.

        Forensic 2026-07-13 18:33: "reconnect the GitHub MCP" failed with a
        bare unknown-name error — GitHub was a marketplace PLUGIN, not an
        mcp.json server — and the spoken outcome gave the user nothing to
        correct with.
        """
        try:
            names = sorted(mcp_state.load_config().get("mcpServers", {}).keys())
        except Exception:  # noqa: BLE001 — the base error must still surface
            names = []
        configured = ", ".join(names) if names else "none"
        return (
            f"no MCP server named {name!r} — configured MCP servers: "
            f"{configured}. A marketplace plugin (e.g. GitHub) is not an "
            "MCP server and is managed from the Plugins view."
        )

    async def _remove(self, mcp_state: Any, name: str, reason: str) -> ToolResult:
        existed = mcp_state.remove_server(name)
        if not existed:
            return ToolResult(
                success=False,
                output=None,
                error=self._unknown_name_error(mcp_state, name),
            )
        was_running = self._is_running(name)
        stopped_live = False
        if was_running:
            stopped_live = await self._stop_active_server(name)
            if stopped_live:
                await self._notify_tools_changed(f"mcp_removed:{name}")
        requires_restart = was_running and not stopped_live
        log.info(
            "manage-mcp-server: removed %r (was_running=%s, requires_restart=%s) reason=%r",
            name, was_running, requires_restart, reason,
        )
        return ToolResult(
            success=True,
            output={
                "action": "remove",
                "name": name,
                "applied_live": not requires_restart,
                "requires_restart": requires_restart,
            },
        )

    async def _toggle(self, mcp_state: Any, name: str, *, enabled: bool, reason: str) -> ToolResult:
        if mcp_state.get_server_entry(name) is None:
            return ToolResult(
                success=False,
                output=None,
                error=self._unknown_name_error(mcp_state, name),
            )
        mcp_state.set_enabled(name, enabled)

        applied_live = False
        requires_restart = True
        registry = self._registry()
        if enabled and registry is not None:
            try:
                registry.load_from_mcp_json()
                await registry.start_enabled([name])
                applied_live = name in self._active_client_names(registry)
                requires_restart = not applied_live
                if applied_live:
                    await self._sync_live_tools(registry, name, adding=True)
                    await self._notify_tools_changed(f"mcp_enabled:{name}")
            except Exception as exc:  # noqa: BLE001
                log.error("manage-mcp-server: live enable of %r failed: %s", name, exc)
        elif not enabled:
            was_running = self._is_running(name)
            if was_running:
                stopped_live = await self._stop_active_server(name)
                if stopped_live:
                    await self._notify_tools_changed(f"mcp_disabled:{name}")
                requires_restart = not stopped_live
            else:
                requires_restart = False
            applied_live = not requires_restart

        log.info(
            "manage-mcp-server: %s %r (live=%s restart=%s) reason=%r",
            "enable" if enabled else "disable", name, applied_live, requires_restart, reason,
        )
        return ToolResult(
            success=True,
            output={
                "action": "enable" if enabled else "disable",
                "name": name,
                "applied_live": applied_live,
                "requires_restart": requires_restart,
            },
        )

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _registry() -> Any:
        from dodaios.core import runtime_refs

        return runtime_refs.get_mcp_registry()

    @staticmethod
    def _active_client_names(registry: Any) -> set[str]:
        if registry is None:
            return set()
        active_clients = getattr(registry, "active_clients", None)
        if callable(active_clients):
            clients = active_clients()
            if isinstance(clients, dict):
                return set(clients.keys())
            return set(clients)
        active_names = getattr(registry, "active_names", None)
        if callable(active_names):
            return set(active_names())
        return set()

    @classmethod
    def _is_running(cls, name: str) -> bool:
        try:
            return name in cls._active_client_names(cls._registry())
        except Exception:  # noqa: BLE001
            return False

    @classmethod
    async def _stop_active_server(cls, name: str) -> bool:
        registry = cls._registry()
        if registry is None:
            return False
        try:
            active_clients = getattr(registry, "active_clients", None)
            if not callable(active_clients):
                return False
            active = active_clients()
            if not isinstance(active, dict) or name not in active:
                return False
            client = active[name]
            stop_fn = getattr(client, "stop", None)
            if callable(stop_fn):
                await stop_fn()
            clients_dict = getattr(registry, "_clients", None)
            if isinstance(clients_dict, dict):
                clients_dict.pop(name, None)
            await cls._sync_live_tools(registry, name, adding=False)
            return name not in cls._active_client_names(registry)
        except Exception as exc:  # noqa: BLE001
            log.warning("manage-mcp-server: live stop of %r failed: %s", name, exc)
            return False

    @staticmethod
    async def _sync_live_tools(registry: Any, server_name: str, *, adding: bool) -> None:
        try:
            from dodaios.core import runtime_refs

            app = runtime_refs.get_web_app()
            state = getattr(app, "state", None) if app is not None else None
            tool_registry = getattr(state, "tool_registry", None)
            if not isinstance(tool_registry, dict):
                return
            prefix = f"{server_name}/"
            if not adding:
                for key in list(tool_registry.keys()):
                    if key.startswith(prefix):
                        tool_registry.pop(key, None)
                return
            from dodaios.mcp.adapter import MCPToolAdapter

            active = registry.active_clients() if hasattr(registry, "active_clients") else {}
            client = active.get(server_name) if isinstance(active, dict) else None
            if client is None:
                return
            cfg = getattr(state, "cfg", None) or getattr(state, "config", None)
            risk_tier = getattr(getattr(cfg, "harness", None), "default_risk_tier", "monitor")
            list_tools = getattr(client, "list_tools", None)
            tools = (
                await list_tools()
                if callable(list_tools)
                else getattr(client, "_tools_cache", [])
            )
            for mcp_tool in tools or []:
                adapter = MCPToolAdapter(client, mcp_tool, risk_tier=risk_tier)
                tool_registry[adapter.name] = adapter
        except Exception as exc:  # noqa: BLE001
            log.warning("manage-mcp-server: tool_registry sync for %r failed: %s", server_name, exc)

    @staticmethod
    async def _notify_tools_changed(reason: str) -> None:
        import asyncio

        from dodaios.core import runtime_refs
        from dodaios.core.events import BrainToolsChanged

        event = BrainToolsChanged(
            source_layer="manage_mcp_server",
            reason=reason,
        )
        app = runtime_refs.get_web_app()
        bus = getattr(getattr(app, "state", None), "bus", None) if app is not None else None
        brain = runtime_refs.get_brain_manager()
        if bus is None and brain is not None:
            bus = getattr(brain, "_bus", None)
        if bus is not None:
            try:
                if asyncio.iscoroutinefunction(bus.publish):
                    await bus.publish(event)
                else:
                    bus.publish(event)
                return
            except Exception as exc:  # noqa: BLE001
                log.debug("manage-mcp-server: BrainToolsChanged publish failed: %s", exc)
        if brain is not None:
            try:
                refresh_async = getattr(brain, "refresh_tools_async", None)
                if callable(refresh_async):
                    await refresh_async()
                elif hasattr(brain, "refresh_tools"):
                    brain.refresh_tools()
            except Exception as exc:  # noqa: BLE001
                log.debug("manage-mcp-server: direct brain tool refresh failed: %s", exc)
