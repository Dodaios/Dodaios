"""What an approval card shows besides its three answers (display only).

Every approval source ends in ``AgentChatService._ask``: the ToolExecutor
bridge (brain runner and the MCP gateway), the API loop's folder tools, Claude
Code's stdin control protocol and ACP ``session/request_permission`` from
Hermes or OpenClaw. This module turns the call that asks ``(name, args,
summary)`` into the fields the card reads. Nothing here decides anything: the
decision set (allow / allow_always / deny / cancel / expired) and every policy
stay where they are.

Fields added to the ``approval_required`` payload. All are optional; an older
event has none of them and the card falls back to the tool name and summary.

``source``   ``{kind, app?, verb?}``. ``kind`` is one of :data:`SOURCE_KINDS`;
             ``app`` names the connector or MCP server a ``connector`` call goes
             to, ``verb`` the one-word action it performs there (``send``).
``where``    the folder, site or machine the action runs at.
``why``      the agent's own reason, when its runner passes one (Claude's Bash
             ``description``, a Codex ``reason``).
``caution``  ``""`` or one of :data:`CAUTIONS`: an action that cannot be undone,
             one that changes security settings, or one that sends data out of
             the chat.
``detail``   the exact command or request for the card's disclosure, with
             every secret masked. The raw ``input`` stays as it always was.
``rule``     what "Always allow" saves (:func:`rule_offer`), or ``None`` when
             the card offers no "Always allow" at all (a plan).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Final
from urllib.parse import urlparse

from dodaios.core.mcp_names import own_cli_tool, split_cli_tool_name
from dodaios.core.redact import redact_secrets

log = logging.getLogger(__name__)

SOURCE_KINDS: Final[tuple[str, ...]] = (
    "terminal",
    "files",
    "browser",
    "computer",
    "plan",
    "agent",
    "connector",
    "tool",
)
CAUTIONS: Final[tuple[str, ...]] = ("irreversible", "security", "data_leaves")

#: How a card answers "Always allow" in this chat when no agent rule applies.
#: ``tool``: this tool stops asking in this chat. ``all``: the chat stops asking
#: (its stance becomes auto). ``runtime``: the runtime that asked remembers it.
CHAT_EFFECTS: Final[tuple[str, ...]] = ("tool", "all", "runtime")

_MASK: Final[str] = "••••••"
_DETAIL_CHARS: Final[int] = 4000
_LINE_CHARS: Final[int] = 240

_PLAN_TOOLS: Final[frozenset[str]] = frozenset({"ExitPlanMode", "exit_plan_mode"})
_TERMINAL_TOOLS: Final[frozenset[str]] = frozenset(
    {
        "bash",
        "runcommand",
        "run_command",
        "shell",
        "local_shell",
        "exec",
        "exec_command",
        "execute",
        "terminal",
        "powershell",
        "society_shell",
        "society_sandbox",
    }
)
_FILE_TOOLS: Final[frozenset[str]] = frozenset(
    {
        "write",
        "edit",
        "multiedit",
        "notebookedit",
        "apply_patch",
        "write_file",
        "edit_file",
        "create_file",
        "str_replace",
        "str_replace_editor",
        "delete_file",
        "read",
        "read_file",
    }
)
_COMPUTER_TOOLS: Final[frozenset[str]] = frozenset(
    {
        "click",
        "click-element",
        "type-text",
        "hotkey",
        "scroll",
        "drag",
        "move-mouse",
        "switch-window",
        "open-app",
        "computer",
        "computer_use",
    }
)
_AGENT_TOOLS: Final[frozenset[str]] = frozenset({"task", "agent", "spawn_agent"})

_SECRET_KEY: Final[re.Pattern[str]] = re.compile(
    r"(?i)(pass(word|wd|phrase)?|secret|token|api[_-]?key|apikey"
    r"|(?<![a-z])auth(orization)?(?![a-z])|cookie|credential|private[_-]?key"
    r"|session[_-]?key|(?<![a-z])otp(?![a-z])|pin[_-]?code)"
)

_IRREVERSIBLE: Final[re.Pattern[str]] = re.compile(
    r"(?i)(\brm\s+-|\brm\b\s+\S|\brmdir\b|\bdel\s+/|\bremove-item\b|\brd\s+/s\b"
    r"|\bdrop\s+(table|database|schema)\b|\btruncate\b|\bpush\b[^\n]*\s(-f|--force)\b"
    r"|\breset\s+--hard\b|\bclean\s+-[a-z]*f|\bshred\b|\bmkfs\b|\bformat\s+[a-z]:"
    r"|^(delete|remove|destroy|purge|wipe|trash|uninstall|pay|purchase|buy|transfer)\b)"
)
_SECURITY: Final[re.Pattern[str]] = re.compile(
    r"(?i)(\bchmod\b|\bchown\b|\bicacls\b|\bsudo\b|\brunas\b|set-executionpolicy"
    r"|\breg\s+(add|delete)\b|\bnetsh\b|\bfirewall\b|ssh-keygen|authorized_keys"
    r"|^(grant|revoke|rotate|set_permission|share_access|make_public)\b)"
)
_DATA_LEAVES: Final[re.Pattern[str]] = re.compile(
    r"(?i)(\bgit\s+push\b|\bgh\s+(pr|issue|release)\s+create\b|\bcurl\b[^\n]*\s(-d|--data|-X\s*POST|-F)\b"
    r"|\bscp\b|\bnpm\s+publish\b|\btwine\s+upload\b"
    r"|^(send|post|publish|share|upload|tweet|reply|forward|email|message|comment|invite"
    r"|create_draft_and_send|send_message|send_email)\b)"
)


def describe_call(
    name: str,
    args: dict[str, Any] | None,
    summary: str = "",
    *,
    cwd: str = "",
    rule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The card's display fields for one call. Never raises."""
    try:
        return _describe(name or "", args if isinstance(args, dict) else {}, summary, cwd, rule)
    except Exception:  # noqa: BLE001 — a card without its extras still asks correctly
        log.warning("approval card: could not describe %s", name, exc_info=True)
        return {}


def _describe(
    name: str, args: dict[str, Any], summary: str, cwd: str, rule: dict[str, Any] | None
) -> dict[str, Any]:
    source = source_of(name, args)
    kind = source["kind"]
    command = _command_text(args)
    verb = action_verb(args)
    if kind == "connector" and verb:
        source = {**source, "verb": verb}
    fields: dict[str, Any] = {
        "source": source,
        "where": _where(kind, args, cwd),
        "why": _why(args),
        "caution": caution_of(kind, command, verb),
        "detail": "" if kind == "plan" else request_detail(args, command),
        "rule": None if kind == "plan" else rule,
    }
    return fields


def source_of(name: str, args: dict[str, Any]) -> dict[str, str]:
    """``{kind, app?}``: what is asking, as the card's source chip shows it."""
    own = own_cli_tool(name)
    other = None if own is not None else split_cli_tool_name(name)
    bare = own or (other[1] if other else name)
    low = bare.lower()
    if bare in _PLAN_TOOLS:
        return {"kind": "plan"}
    if low in _TERMINAL_TOOLS or (low.endswith("shell") and "command" in args):
        return {"kind": "terminal"}
    if low in _FILE_TOOLS:
        return {"kind": "files"}
    if "browser" in low or low in {"webfetch", "web_fetch", "navigate", "fetch"}:
        return {"kind": "browser"}
    if low in _COMPUTER_TOOLS:
        return {"kind": "computer"}
    if low in _AGENT_TOOLS:
        return {"kind": "agent"}
    if other is not None:
        # Another MCP server's tool: that server is the connector asking.
        return {"kind": "connector", "app": app_label(other[0])}
    if own is not None or _looks_like_connector(bare):
        return {"kind": "connector", "app": app_label(bare)}
    if isinstance(args.get("command"), (str, list)) and not args.get("action"):
        return {"kind": "terminal"}
    if isinstance(args.get("file_path"), str):
        return {"kind": "files"}
    return {"kind": "tool", "app": bare[:60]}


def _looks_like_connector(bare: str) -> bool:
    """A plugin/API tool name (``gmail``, ``google_calendar``, ``api_notion``)."""
    return bool(re.fullmatch(r"[a-z][a-z0-9_]*(-[a-z0-9]+)*", bare)) and bare.lower() not in {
        "read",
        "grep",
        "glob",
        "ls",
        "list",
        "search",
    }


_APP_WORDS: Final[dict[str, str]] = {"github": "GitHub", "gitlab": "GitLab", "api": ""}


def app_label(raw: str) -> str:
    """``google_calendar`` -> ``Google Calendar``; a label stays as it is."""
    text = (raw or "").strip()
    if not text:
        return ""
    if any(ch.isupper() for ch in text) or " " in text:
        return text[:60]
    words = [w for w in re.split(r"[_\-.]+", text) if w]
    shown = [_APP_WORDS.get(w, w[:1].upper() + w[1:]) for w in words]
    return " ".join(w for w in shown if w)[:60] or text[:60]


def action_verb(args: dict[str, Any]) -> str:
    """The one-word action a mixed tool performs (``gmail``: ``send``), else ``""``.

    Stricter than the gate's own verb reading on purpose: only a single word is
    a verb a person can read in a rule. A shell command is never one.
    """
    for key in ("action", "operation", "method", "mode"):
        raw = args.get(key)
        if isinstance(raw, str):
            word = raw.strip().lower()
            if re.fullmatch(r"[a-z][a-z0-9_.-]{0,39}", word):
                return word
    return ""


def _command_text(args: dict[str, Any]) -> str:
    raw = args.get("command") if "command" in args else args.get("cmd")
    if isinstance(raw, list):
        return " ".join(str(part) for part in raw)
    return raw if isinstance(raw, str) else ""


def caution_of(kind: str, command: str, verb: str) -> str:
    """The caution caption a card wears, from what the call does."""
    for text in (command, verb):
        if not text:
            continue
        if _IRREVERSIBLE.search(text):
            return "irreversible"
        if _SECURITY.search(text):
            return "security"
        if _DATA_LEAVES.search(text):
            return "data_leaves"
    return ""


def _where(kind: str, args: dict[str, Any], cwd: str) -> str:
    if kind in ("terminal", "files"):
        folder = args.get("cwd") or args.get("workdir") or cwd
        return str(folder)[:_LINE_CHARS] if isinstance(folder, str) else ""
    if kind == "browser":
        url = args.get("url") or args.get("href")
        if isinstance(url, str) and url.strip():
            host = urlparse(url.strip()).hostname
            return (host or "")[:_LINE_CHARS]
    return ""


def _why(args: dict[str, Any]) -> str:
    for key in ("description", "reason", "justification", "explanation"):
        raw = args.get(key)
        if isinstance(raw, str) and raw.strip():
            line = " ".join(raw.split())
            return redact_secrets(line)[:_LINE_CHARS]
    return ""


def mask_secrets(value: Any, _depth: int = 0) -> Any:
    """``value`` with every secret-named field masked, recursively."""
    if _depth > 8:
        return _MASK
    if isinstance(value, dict):
        return {
            str(k): (
                _MASK
                if _SECRET_KEY.search(str(k)) and isinstance(v, str) and v.strip()
                else mask_secrets(v, _depth + 1)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [mask_secrets(v, _depth + 1) for v in value[:200]]
    if isinstance(value, str):
        return redact_secrets(value)
    return value


def request_detail(args: dict[str, Any], command: str = "") -> str:
    """The exact command or request, secrets masked, for the card's disclosure."""
    if command:
        return redact_secrets(command)[:_DETAIL_CHARS]
    if not args:
        return ""
    masked = mask_secrets(args)
    try:
        text = json.dumps(masked, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):  # unserialisable args still show, as their plain repr
        text = str(masked)
    return redact_secrets(text)[:_DETAIL_CHARS]


def rule_offer(
    surface: str, name: str, args: dict[str, Any], agent_rule: dict[str, Any] | None
) -> dict[str, Any]:
    """What "Always allow" saves on this card.

    ``scopes`` lists where a rule can live: ``agent`` (the society agent's own
    approval rules, persistent) and ``chat`` (this conversation). ``chat``
    names what a chat-wide "always" does on this surface (:data:`CHAT_EFFECTS`).
    A society agent's own tool carries ``app``, ``verb``, ``pattern`` and
    ``broad`` (the pattern for every action of that app).
    """
    if surface == "society" and agent_rule:
        return {"scopes": ["agent", "chat"], "chat": "tool", **agent_rule}
    bare = own_cli_tool(name) or name
    if surface == "jarvis":
        return {"scopes": ["chat"], "chat": "tool", "app": app_label(bare)}
    if surface == "society":
        # A runtime's own tool: its "always" is the runtime's to remember.
        return {"scopes": [], "chat": "runtime"}
    return {"scopes": ["chat"], "chat": "all"}


__all__ = [
    "CAUTIONS",
    "CHAT_EFFECTS",
    "SOURCE_KINDS",
    "action_verb",
    "app_label",
    "caution_of",
    "describe_call",
    "mask_secrets",
    "request_detail",
    "rule_offer",
    "source_of",
]
