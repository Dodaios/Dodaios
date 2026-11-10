"""The actions that always ask, whatever rule, whitelist or stance says.

Four kinds, each a code the card and the Trust page can name:

``money``             paying, buying, transferring, trading.
``credentials``       a call that carries or reveals a password, key or token.
``permanent_delete``  deleting for good: no trash, no undo.
``new_recipient``     sending in the person's name to someone they never wrote
                      to from here before (``recipients.KnownRecipients``).

:func:`hard_limit_for` reads the tool's name, its one-word action and its
arguments. It never decides whether a call runs; it only says that *a person*
must decide, so every place that could answer for the person (a standing
rule, the whitelist, a bypass stance, an unattended bridge) checks it first and
steps aside.

Pattern-based on purpose: the limits must hold without a model and without a
network, and the model that proposes the call must not be able to talk its way
around them with a differently named argument.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Any, Final

HARD_LIMITS: Final[tuple[str, ...]] = (
    "money",
    "credentials",
    "permanent_delete",
    "new_recipient",
)
#: The limits for which no standing rule may even be saved. ``new_recipient``
#: is different: "always allow sending with Gmail" is a fine rule, it simply
#: never covers the FIRST mail to someone — that one asks whatever is stored.
NO_RULE_LIMITS: Final[frozenset[str]] = frozenset({"money", "credentials", "permanent_delete"})

_MONEY_VERBS: Final[frozenset[str]] = frozenset(
    {
        "pay",
        "pay_invoice",
        "purchase",
        "buy",
        "sell",
        "order",
        "checkout",
        "transfer",
        "transfer_money",
        "send_money",
        "wire",
        "trade",
        "place_order",
        "charge",
        "refund",
        "withdraw",
        "deposit",
        "tip",
        "donate",
        "subscribe",
        "top_up",
    }
)
_MONEY_TOOLS: Final[re.Pattern[str]] = re.compile(
    r"(?i)(stripe|paypal|wise|revolut|bank|wallet|coinbase|binance|kraken|broker|trading|"
    r"payment|checkout|invoice|billing)"
)
_MONEY_COMMAND: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(stripe|paypal)\b[^\n]*\b(charge|pay|payout|transfer|refund)s?\b"
)

#: Argument names that carry a credential. Exact names, not substrings:
#: ``page_token`` and ``session_key`` are plumbing, not secrets.
_CREDENTIAL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "password",
        "passwd",
        "passphrase",
        "new_password",
        "old_password",
        "current_password",
        "secret",
        "client_secret",
        "api_key",
        "apikey",
        "api_token",
        "access_token",
        "refresh_token",
        "bearer_token",
        "auth_token",
        "private_key",
        "credential",
        "credentials",
        "otp",
        "one_time_code",
        "pin",
        "pin_code",
        "recovery_code",
    }
)
_CREDENTIAL_VERBS: Final[frozenset[str]] = frozenset(
    {
        "reveal_secret",
        "reveal_password",
        "show_password",
        "export_credentials",
        "export_secrets",
        "change_password",
        "reset_password",
        "set_password",
        "rotate_key",
        "rotate_secret",
        "create_token",
        "create_api_key",
        "read_secret",
        "get_secret",
    }
)
_CREDENTIAL_COMMAND: Final[re.Pattern[str]] = re.compile(
    r"(?i)(\bkeyring\b|\bssh-keygen\b|authorized_keys|\bid_(rsa|ed25519)\b|\bcmdkey\b"
    r"|security\s+find-(generic|internet)-password|\bsecret-tool\b|\bpass\s+(show|insert)\b"
    r"|\bgh\s+auth\s+token\b|\baws\s+configure\b|\bgcloud\s+auth\s+print-access-token\b"
    r"|(^|[\s;&|])(cat|type|more|less|Get-Content)\s+[^\n]*(\.env\b|\.netrc\b|\.pgpass\b|credentials\.json|\.npmrc\b)"
    r"|\b(export|set|\$env:)\s*[A-Z0-9_]*(KEY|TOKEN|SECRET|PASSWORD|PASSWD)\s*=)"
)

_DELETE_VERBS: Final[frozenset[str]] = frozenset(
    {
        "delete_message",
        "delete_file",
        "delete_permanently",
        "permanently_delete",
        "purge",
        "destroy",
        "wipe",
        "shred",
        "delete_repository",
        "delete_repo",
        "delete_database",
        "delete_table",
        "drop_table",
        "drop_database",
        "empty_trash",
        "delete_account",
        "delete_project",
    }
)
_DELETE_COMMAND: Final[re.Pattern[str]] = re.compile(
    r"(?i)(\brm\s+(-[a-z]*\s+)*-[a-z]*[rf][a-z]*\b|\bdel\s+(/[a-z]\s+)*/[sfq]\b|\brd\s+/s\b|\brmdir\s+/s\b"
    r"|remove-item\b[^\n]*-recurse|\bshred\b|\bmkfs\b|\bformat\s+[a-z]:|\bdiskpart\b"
    r"|\bdrop\s+(table|database|schema)\b|\btruncate\s+table\b"
    r"|\bgit\s+push\b[^\n]*\s(-f|--force)\b|\bgit\s+branch\s+-D\b|\bgit\s+reset\s+--hard\b"
    r"|\bgit\s+clean\s+-[a-z]*f|\bgh\s+repo\s+delete\b)"
)

_OUTBOUND_VERBS: Final[re.Pattern[str]] = re.compile(
    r"(?i)^(send|send_message|send_mail|send_email|send_sms|send_dm|reply|reply_message|forward"
    r"|post|create_post|publish|tweet|share|share_file|invite|message|email|comment|create_comment"
    r"|create_draft_and_send|dm)$"
)
#: Tools whose "sending" is internal plumbing, not the person's name on a wire.
_INTERNAL_TOOLS: Final[re.Pattern[str]] = re.compile(
    r"(?i)(agent|worker|subagent|harness|society|mission|dispatch|spawn|notify|notification)"
)
_RECIPIENT_KEYS: Final[tuple[str, ...]] = (
    "to",
    "cc",
    "bcc",
    "recipient",
    "recipients",
    "recipient_id",
    "recipient_ids",
    "email",
    "emails",
    "phone",
    "phone_number",
    "number",
    "channel",
    "channel_id",
    "chat_id",
    "user_id",
    "username",
    "handle",
)

#: Argument names a message body travels in, for the outbound check.
BODY_KEYS: Final[tuple[str, ...]] = (
    "body",
    "text",
    "message",
    "content",
    "html",
    "caption",
    "comment",
    "description",
    "subject",
)


def bare_tool(name: str) -> str:
    """``mcp__dodaios__gmail`` -> ``gmail``; an MCP prefix never hides a tool."""
    text = name or ""
    if text.startswith("mcp__"):
        return text.split("__", 2)[-1]
    return text


def action_of(args: dict[str, Any] | None) -> str:
    """The one-word action of a mixed tool (``gmail``: ``send_message``), else ``""``."""
    for key in ("action", "operation", "method", "mode"):
        raw = (args or {}).get(key)
        if isinstance(raw, str):
            word = raw.strip().lower()
            if re.fullmatch(r"[a-z][a-z0-9_.-]{0,39}", word):
                return word
    return ""


def command_of(args: dict[str, Any] | None) -> str:
    args = args or {}
    raw = args.get("command") if "command" in args else args.get("cmd")
    if isinstance(raw, list):
        return " ".join(str(part) for part in raw)
    return raw if isinstance(raw, str) else ""


def _values(raw: Any) -> list[str]:
    if isinstance(raw, str):
        parts = re.split(r"[,;\n]+", raw)
        return [p.strip() for p in parts if p.strip()]
    if isinstance(raw, (list, tuple)):
        out: list[str] = []
        for item in raw:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif isinstance(item, dict):
                for key in ("email", "address", "id", "name"):
                    value = item.get(key)
                    if isinstance(value, str) and value.strip():
                        out.append(value.strip())
                        break
        return out
    if isinstance(raw, dict):
        return _values([raw])
    return []


def recipients_of(tool_name: str, args: dict[str, Any] | None) -> list[str]:
    """Every address, handle or channel the call writes to, in call order."""
    args = args or {}
    nested = args.get("arguments")
    pool = [args, nested] if isinstance(nested, dict) else [args]
    found: list[str] = []
    for part in pool:
        for key in _RECIPIENT_KEYS:
            if key in part:
                for value in _values(part[key]):
                    if value not in found:
                        found.append(value)
    return found


def is_outbound(tool_name: str, args: dict[str, Any] | None) -> bool:
    """Whether this call puts something on a wire in the person's name."""
    bare = bare_tool(tool_name).lower()
    if _INTERNAL_TOOLS.search(bare):
        return False
    verb = action_of(args)
    if verb and _OUTBOUND_VERBS.match(verb):
        return True
    if not verb and re.search(r"(?i)^(send|post|publish|share|tweet|reply|forward)(_|-|$)", bare):
        return True
    return False


def hard_limit_for(
    tool_name: str,
    args: dict[str, Any] | None,
    *,
    recipients_known: Callable[[Iterable[str]], bool] | None = None,
) -> str | None:
    """The hard limit this call touches, or ``None``.

    ``recipients_known`` answers whether every recipient of an outbound call
    was written to before; without it the default ledger
    (:func:`dodaios.trust.recipients.known_recipients`) is asked.
    """
    args = args if isinstance(args, dict) else {}
    bare = bare_tool(tool_name)
    low = bare.lower()
    verb = action_of(args)
    command = command_of(args)

    reads_only = verb.startswith(("list", "get", "read", "search"))
    if verb in _MONEY_VERBS or (_MONEY_TOOLS.search(low) and verb and not reads_only):
        return "money"
    if command and _MONEY_COMMAND.search(command):
        return "money"

    if verb in _CREDENTIAL_VERBS:
        return "credentials"
    if any(
        key.lower() in _CREDENTIAL_KEYS and isinstance(value, str) and value.strip()
        for key, value in args.items()
    ):
        return "credentials"
    if command and _CREDENTIAL_COMMAND.search(command):
        return "credentials"

    if verb in _DELETE_VERBS:
        return "permanent_delete"
    if command and _DELETE_COMMAND.search(command):
        return "permanent_delete"

    if is_outbound(tool_name, args):
        recipients = recipients_of(tool_name, args)
        if recipients:
            if recipients_known is None:
                from .recipients import known_recipients

                recipients_known = known_recipients().knows_all
            if not recipients_known(recipients):
                return "new_recipient"
    return None


__all__ = [
    "BODY_KEYS",
    "HARD_LIMITS",
    "NO_RULE_LIMITS",
    "action_of",
    "bare_tool",
    "command_of",
    "hard_limit_for",
    "is_outbound",
    "recipients_of",
]
