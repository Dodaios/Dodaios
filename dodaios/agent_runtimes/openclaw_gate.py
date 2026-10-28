"""Dodaios' gate plugin for an agent's OpenClaw Gateway.

OpenClaw relays only exec approvals over ACP. Its file tools (``write``,
``edit``, ``apply_patch``) have no approval of their own, so in Ask they ran
without a card. This small plugin, written into each agent's state folder and
loaded through ``plugins.load.paths``, closes that gap with OpenClaw's own
``before_tool_call`` hook: every such call waits for Dodaios' answer
(``native_gate``), which follows the chat's stance. Bypass answers at once,
so the plugin's config never depends on the stance and a stance change never
restarts the Gateway.

It also registers the agent's ask tool under its plain name
(``society_ask_user``) as a direct tool, outside OpenClaw's deferred tool
search: a small model calls the name its instructions use, which the MCP
catalog only knows as ``dodaios__society_ask_user`` behind ``tool_search``.
The call goes to Dodaios' own MCP tool, with its card and limits.

The plugin talks to Dodaios with the control key the Gateway already has in
its environment (``JARVIS_CONTROL_API_KEY``); nothing secret is written.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from dodaios.agent_runtimes.base import write_if_changed

#: The plugin's id (its folder name and ``plugins.entries`` key).
PLUGIN_ID: Final[str] = "dodaios-gate"

#: OpenClaw's own tools that change files and have no approval to relay.
GATED_TOOLS: Final[tuple[str, ...]] = ("write", "edit", "apply_patch")

#: OpenClaw's own reading tools: asked about in "Always ask" only, answered
#: at once otherwise (``native_gate``), so the config stays the same.
READ_TOOLS: Final[tuple[str, ...]] = (
    "read", "ls", "grep", "find", "web_search", "web_fetch"
)

#: OpenClaw's ``process`` tool drives a command ``exec`` started. Its input
#: actions type into that process: once an interactive shell or REPL was
#: allowed, they would run any further command without a card. They ask like
#: a file change; its other actions (list, poll, log, kill, ...) run freely.
PROCESS_TOOL: Final[str] = "process"
PROCESS_INPUT_ACTIONS: Final[frozenset[str]] = frozenset({"write", "send-keys", "submit", "paste"})

#: The hook waits this long for the person (OpenClaw's ceiling for an
#: operator-set hook budget); ``native_gate`` answers before it.
HOOK_TIMEOUT_MS: Final[int] = 600_000

#: Where the gate asks (the Control API, same origin as the MCP endpoint).
APPROVAL_PATH: Final[str] = "/api/control/runtime/native-approval"

_MANIFEST: Final[dict[str, Any]] = {
    "id": PLUGIN_ID,
    "name": "Dodaios gate",
    "description": "Asks Dodaios before file changes and offers the agent's ask tool.",
    "contracts": {"tools": ["society_ask_user"]},
    "activation": {"onStartup": True},
    "configSchema": {"type": "object", "additionalProperties": True},
}

_PACKAGE: Final[dict[str, Any]] = {
    "name": PLUGIN_ID,
    "version": "1.0.0",
    "private": True,
    "type": "module",
    "openclaw": {"extensions": ["./index.mjs"]},
}

_SOURCE: Final[str] = r"""// Written by Dodaios (agent_runtimes/openclaw_gate.py). Do not edit.
const GATED = __GATED__;
const HOOK_TIMEOUT_MS = __TIMEOUT__;

function headers(cfg, extra) {
  return {
    "content-type": "application/json",
    authorization: `Bearer ${process.env.JARVIS_CONTROL_API_KEY || ""}`,
    "x-jarvis-chat-session": String(cfg.session || ""),
    ...(extra || {}),
  };
}

function title(tool, params) {
  const path = params && (params.path || params.file_path || params.filePath);
  if (typeof path === "string" && path) return `${tool}: ${path}`;
  const action = params && params.action;
  return typeof action === "string" && action ? `${tool}: ${action}` : tool;
}

function parsed(value) {
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

// Small models send question ids such as "color-pref" and options as plain
// strings; the card takes any of it.
function normalizeAsk(raw) {
  const args = parsed(raw);
  if (!args || typeof args !== "object") return args;
  const out = { ...args };
  const questions = parsed(out.questions);
  if (Array.isArray(questions)) {
    out.questions = questions.map((item, index) => {
      const q = parsed(item);
      if (!q || typeof q !== "object") return q;
      const next = { ...q };
      if (next.id !== undefined) {
        const id = String(next.id)
          .toLowerCase()
          .replace(/[^a-z0-9_]+/g, "_")
          .replace(/^[^a-z]+/, "");
        next.id = id || `question_${index + 1}`;
      }
      // Dodaios' MCP schema requires the reason; a model that left it out
      // still gets its card (the recommendation simply goes unexplained).
      if (typeof next.recommendation_reason !== "string") next.recommendation_reason = "";
      const options = parsed(next.options);
      if (Array.isArray(options)) {
        next.options = options.map((o) => (typeof o === "string" ? { label: o } : o));
      }
      return next;
    });
  }
  return out;
}

export default {
  id: "dodaios-gate",
  name: "Dodaios gate",
  description: "Asks Dodaios before file changes and offers the agent's ask tool.",
  register(api) {
    const cfg = api.pluginConfig || {};
    api.on(
      "before_tool_call",
      async (event, ctx) => {
        const refuse = (reason) => ({ block: true, blockReason: reason });
        if (!cfg.gateUrl) {
          return refuse("Dodaios cannot ask for approval here, so the action was not run.");
        }
        try {
          const params = event.params || {};
          const res = await fetch(cfg.gateUrl, {
            method: "POST",
            headers: headers(cfg),
            body: JSON.stringify({
              tool: event.toolName,
              params,
              tool_call_id: event.toolCallId || "",
              title: title(event.toolName, params),
            }),
            signal: ctx && ctx.abortSignal,
          });
          if (!res.ok) {
            return refuse(
              `Dodaios could not ask for approval (HTTP ${res.status}), so the action was not run.`,
            );
          }
          const body = await res.json();
          if (body && body.decision === "allow") return undefined;
          return refuse(String((body && body.reason) || "The person declined this action."));
        } catch {
          return refuse("Dodaios could not ask for approval, so the action was not run.");
        }
      },
      { matcher: GATED, priority: 1000, timeoutMs: HOOK_TIMEOUT_MS },
    );
    const ask = cfg.ask;
    if (cfg.mcpUrl && ask && ask.name) {
      api.registerTool({
        name: ask.name,
        label: "Ask the user",
        description: String(ask.description || ""),
        catalogMode: "direct-only",
        parameters: ask.schema || { type: "object", properties: {} },
        prepareArguments: normalizeAsk,
        async execute(_toolCallId, params, signal) {
          const res = await fetch(cfg.mcpUrl, {
            method: "POST",
            headers: headers(cfg, { accept: "application/json, text/event-stream" }),
            body: JSON.stringify({
              jsonrpc: "2.0",
              id: 1,
              method: "tools/call",
              params: { name: ask.wire || ask.name, arguments: normalizeAsk(params) || {} },
            }),
            signal,
          });
          if (!res.ok) throw new Error(`Dodaios did not take the question (HTTP ${res.status}).`);
          const body = await res.json();
          if (body.error) {
            throw new Error(String(body.error.message || "The question could not be shown."));
          }
          const result = body.result || {};
          const text = (result.content || [])
            .filter((part) => part && part.type === "text")
            .map((part) => part.text)
            .join("\n");
          if (result.isError) throw new Error(text || "The question could not be shown.");
          return { content: [{ type: "text", text }], details: { text } };
        },
      });
    }
  },
};
"""


def kind(tool: str, params: dict[str, Any] | None) -> str:
    """How Dodaios treats one call the plugin holds: ``free`` (runs at once),
    ``read`` (asks in "Always ask" only) or ``change`` (asks outside Bypass)."""
    if tool == PROCESS_TOOL:
        action = str((params or {}).get("action") or "").strip().lower()
        return "change" if action in PROCESS_INPUT_ACTIONS else "free"
    return "read" if tool in READ_TOOLS else "change"


def source() -> str:
    """The plugin's entry module."""
    matched = [*GATED_TOOLS, *READ_TOOLS, PROCESS_TOOL]
    return _SOURCE.replace("__GATED__", json.dumps(matched)).replace(
        "__TIMEOUT__", str(HOOK_TIMEOUT_MS)
    )


@dataclass(frozen=True, slots=True)
class Installed:
    """Where the plugin lives in an agent's folder, and which build it is."""

    path: Path
    digest: str


def install(home: Path) -> Installed:
    """Write the plugin into ``home/plugins/dodaios-gate`` (only what changed).

    The digest goes into the Gateway's config, so a new build of the plugin
    restarts the Gateway like any other config change.
    """
    folder = home / "plugins" / PLUGIN_ID
    files = {
        "index.mjs": source(),
        "openclaw.plugin.json": json.dumps(_MANIFEST, indent=2) + "\n",
        "package.json": json.dumps(_PACKAGE, indent=2) + "\n",
    }
    digest = hashlib.sha256()
    for name, text in sorted(files.items()):
        write_if_changed(folder / name, text)
        digest.update(name.encode("utf-8") + b"\0" + text.encode("utf-8"))
    return Installed(folder, digest.hexdigest()[:16])


def ask_spec(mcp_server: str) -> dict[str, Any]:
    """The ask tool as the plugin offers it: Dodaios' own description and schema."""
    from dodaios.society.ask_tool import ASK_USER_TOOL_NAME, AskUserTool

    return {
        "name": ASK_USER_TOOL_NAME,
        "wire": ASK_USER_TOOL_NAME,
        "description": AskUserTool.description,
        "schema": _lenient(AskUserTool.schema),
        "catalogName": f"{mcp_server}__{ASK_USER_TOOL_NAME}",
    }


def _lenient(schema: dict[str, Any]) -> dict[str, Any]:
    """The ask schema as OpenClaw validates a plugin tool's input: only the
    question text is required. OpenClaw refuses a call that misses any other
    required field before Dodaios sees it (live: a small model left out
    ``recommendation_reason``); Dodaios' own parser decides the rest."""
    copy = json.loads(json.dumps(schema))
    questions = copy.get("properties", {}).get("questions", {})
    items = questions.get("items")
    if isinstance(items, dict):
        items["required"] = ["question"]
    return copy


def approval_url(mcp_url: str) -> str:
    """The gate's endpoint on the same Dodaios server as ``mcp_url``."""
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(mcp_url)
    return urlunsplit((parts.scheme, parts.netloc, APPROVAL_PATH, "", ""))
