"""Connect the Agent MCP surface to an outside client, in one call.

Every MCP client configures servers the same two ways — a command it launches
and speaks stdio to, or a URL it calls with headers — but each keeps its config
in its own place and shape. This module knows both, for the clients people
actually use, and can either hand back a snippet to paste or write the entry
itself.

Path resolution is per-OS by capability, never by assumption: a client whose
config directory does not exist on this machine is reported as "not installed"
rather than created, because writing a config for a client that is not there
leaves a file nobody will ever read.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

from jarvis.core.branding import LEGACY_MCP_AGENTS_SERVER_NAMES, MCP_AGENTS_SERVER_NAME

log = logging.getLogger(__name__)

#: The server's name in a client's config.
ENTRY_NAME: Final[str] = MCP_AGENTS_SERVER_NAME

#: Names this module wrote the entry under before. An entry found under one of
#: them keeps working untouched until the next write here, which replaces it
#: (see :func:`_is_own_entry`) so a client never holds the same server twice.
LEGACY_ENTRY_NAMES: Final[tuple[str, ...]] = LEGACY_MCP_AGENTS_SERVER_NAMES

#: The module the stdio entry launches. Also how an entry is recognised as ours.
_BRIDGE_MODULE: Final[str] = "jarvis.mcp.agents.bridge"


@dataclass(frozen=True)
class ClientTarget:
    """One MCP client: where its config lives and which shape it wants."""

    key: str
    label: str
    config_path: Path | None
    #: ``"nested"`` — servers under a top-level ``mcpServers`` object (Claude
    #: Desktop, Cursor, Claude Code). ``"toml"`` — Codex' ``config.toml``.
    shape: str
    installed: bool


def _home() -> Path:
    return Path.home()


def _claude_desktop_config() -> Path | None:
    """Claude Desktop's config, per OS. ``None`` where the app cannot run."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        return Path(appdata) / "Claude" / "claude_desktop_config.json" if appdata else None
    if sys.platform == "darwin":
        return _home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    # Linux: Claude Desktop is unofficial there, but the community builds all
    # read the XDG path, so honour it rather than pretending the client is absent.
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else _home() / ".config"
    return base / "Claude" / "claude_desktop_config.json"


def _cursor_config() -> Path:
    return _home() / ".cursor" / "mcp.json"


def _claude_code_config() -> Path:
    return _home() / ".claude.json"


def _codex_config() -> Path:
    return _home() / ".codex" / "config.toml"


def targets() -> list[ClientTarget]:
    """Every client this machine could connect, with whether it is installed."""
    rows: list[ClientTarget] = []
    desktop = _claude_desktop_config()
    rows.append(
        ClientTarget(
            key="claude-desktop",
            label="Claude Desktop",
            config_path=desktop,
            shape="nested",
            installed=bool(desktop and desktop.parent.is_dir()),
        )
    )
    cursor = _cursor_config()
    rows.append(
        ClientTarget(
            key="cursor",
            label="Cursor",
            config_path=cursor,
            shape="nested",
            installed=cursor.parent.is_dir(),
        )
    )
    code = _claude_code_config()
    rows.append(
        ClientTarget(
            key="claude-code",
            label="Claude Code",
            config_path=code,
            shape="nested",
            installed=code.exists() or (_home() / ".claude").is_dir(),
        )
    )
    codex = _codex_config()
    rows.append(
        ClientTarget(
            key="codex",
            label="Codex CLI",
            config_path=codex,
            shape="toml",
            installed=codex.parent.is_dir(),
        )
    )
    return rows


def stdio_entry(
    *,
    python: str | None = None,
    include_key: bool = False,
    token: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """The stdio shape: the client launches the bridge and speaks to it.

    This is the form to prefer. It needs no URL in the client, survives Jarvis
    changing port, and works from a client that has no way to send an
    Authorization header.

    ``token`` embeds a per-client MCP token, which is what makes a config
    paste-and-go: the client authenticates as itself, and that one credential
    can be revoked without touching any other client. Prefer it over
    ``include_key``, which embeds the master control key — a key in a config
    file is a key in every backup (AP-12), and revoking it logs out everything.
    """
    from .bridge import api_base_url, control_key

    env: dict[str, str] = {"JARVIS_API_URL": base_url or api_base_url()}
    if token:
        env["JARVIS_MCP_TOKEN"] = token
    elif include_key:
        key = control_key()
        if key:
            env["JARVIS_CONTROL_KEY"] = key
    return {
        "command": python or sys.executable,
        "args": ["-m", _BRIDGE_MODULE],
        "env": env,
    }


def http_entry(*, token: str | None = None, base_url: str | None = None) -> dict[str, Any]:
    """The direct shape: the client calls the surface over HTTP with a header.

    Fewer moving parts, but the credential is IN the config file and the client
    must support custom headers. With a ``token`` that is an acceptable trade —
    it is scoped and revocable on its own; with the control key it is not.
    """
    from .bridge import SURFACE_PATH, api_base_url, control_key

    credential = token or control_key() or "<your Dodaios control key>"
    return {
        "type": "http",
        "url": f"{base_url or api_base_url()}{SURFACE_PATH}",
        "headers": {"Authorization": f"Bearer {credential}"},
    }


def _is_own_entry(entry: Any) -> bool:
    """Whether a config entry points at this app's agent surface.

    Decided by the entry's target and never by its name: the stdio shape
    launches the bridge module, the HTTP shape calls the surface path. An
    entry somebody wrote by hand under the same name, pointing anywhere else,
    is theirs.
    """
    from .bridge import SURFACE_PATH

    if not isinstance(entry, dict):
        return False
    args = entry.get("args")
    if isinstance(args, list) and ("-m", _BRIDGE_MODULE) in pairwise(args):
        return True
    url = entry.get("url")
    return isinstance(url, str) and urlsplit(url).path.rstrip("/") == SURFACE_PATH


def entry_for(
    *,
    transport: str = "stdio",
    token: str | None = None,
    base_url: str | None = None,
    include_key: bool = False,
) -> dict[str, Any]:
    """The config entry for one transport — the single place that chooses."""
    if transport == "http":
        return http_entry(token=token, base_url=base_url)
    return stdio_entry(token=token, base_url=base_url, include_key=include_key)


def snippet(
    client: str = "claude-desktop",
    *,
    transport: str = "stdio",
    token: str | None = None,
    base_url: str | None = None,
) -> str:
    """A ready-to-paste config block for one client."""
    entry = entry_for(transport=transport, token=token, base_url=base_url)
    target = next((t for t in targets() if t.key == client), None)
    if target is not None and target.shape == "toml":
        lines = [f"[mcp_servers.{ENTRY_NAME}]"]
        if transport == "stdio":
            lines.append(f"command = {json.dumps(entry['command'])}")
            lines.append(f"args = {json.dumps(entry['args'])}")
            if entry.get("env"):
                lines.append(f"env = {json.dumps(entry['env'])}")
        else:
            lines.append(f"url = {json.dumps(entry['url'])}")
            lines.append(f"http_headers = {json.dumps(entry['headers'])}")
        return "\n".join(lines)
    return json.dumps({"mcpServers": {ENTRY_NAME: entry}}, indent=2)


def install(
    client: str,
    *,
    transport: str = "stdio",
    include_key: bool = False,
    token: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Write the entry into the client's own config file.

    Merges rather than replaces: an existing ``mcpServers`` object keeps every
    other server, and only our named entry is rewritten. An entry this module
    wrote under an earlier name is replaced by the new one, so the client does
    not list every tool twice; an entry under such a name that points
    somewhere else was written by the person and stays. TOML clients are not
    written to — a hand-formatted ``config.toml`` is easy to corrupt and hard
    to restore, so Codex gets a snippet to paste instead.
    """
    target = next((t for t in targets() if t.key == client), None)
    if target is None:
        known = ", ".join(t.key for t in targets())
        return {"ok": False, "error": f"unknown client {client!r}. Known: {known}"}
    if target.shape == "toml":
        return {
            "ok": False,
            "error": f"{target.label} keeps a hand-formatted config — paste this instead.",
            "snippet": snippet(client, transport=transport, token=token, base_url=base_url),
            "path": str(target.config_path),
        }
    path = target.config_path
    if path is None:
        return {"ok": False, "error": f"{target.label} has no config location on this OS."}
    entry = entry_for(transport=transport, token=token, base_url=base_url, include_key=include_key)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            # Line and column let the user repair their own file; the parser's
            # message itself is not echoed.
            return {
                "ok": False,
                "error": (f"{path} is not readable JSON (line {exc.lineno}, column {exc.colno})."),
            }
        except OSError:
            log.warning("MCP client config %s could not be read", path, exc_info=True)
            return {
                "ok": False,
                "error": f"{path} is not readable JSON: the file could not be opened.",
            }
        if not isinstance(existing, dict):
            return {"ok": False, "error": f"{path} does not hold a JSON object."}
    servers = existing.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        return {"ok": False, "error": f"{path} has an mcpServers key that is not an object."}
    replaced = ENTRY_NAME in servers
    renamed_from = [name for name in LEGACY_ENTRY_NAMES if _is_own_entry(servers.get(name))]
    for name in renamed_from:
        del servers[name]
    servers[ENTRY_NAME] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write through a sibling temp file: a client reading a half-written config
    # at the wrong moment loses every server it has, not just ours.
    tmp = path.with_suffix(path.suffix + ".jarvis-tmp")
    tmp.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return {
        "ok": True,
        "client": target.label,
        "path": str(path),
        "replaced": replaced or bool(renamed_from),
        "renamed_from": renamed_from,
        "transport": transport,
        "restart_required": True,
    }


__all__ = [
    "ENTRY_NAME",
    "LEGACY_ENTRY_NAMES",
    "ClientTarget",
    "entry_for",
    "http_entry",
    "install",
    "snippet",
    "stdio_entry",
    "targets",
]
