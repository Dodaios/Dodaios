"""Which risky actions ask the person, in which permission mode, and which never run.

One table for every surface (the assistant's browser, its tools, the shell),
so the rule a person reads in Settings is the rule the code applies.

Four severities, from the person's point of view:

``free``
    Runs in every mode: reading, searching, opening pages, filling forms.
``ask``
    A consequential step the person usually wants to see (send, publish,
    delete, book, cancel). Asks in Ask, Accept edits and Auto; runs in
    Bypass and under a standing "always allow" rule.
``confirm``
    Money and the person's identity: buying, paying, transferring money,
    typing payment details, deleting an account. Always asks, in every mode,
    including Bypass, and a standing "always allow" rule does not silence
    it. The person answers each one.
``block``
    Never runs, whatever the mode or the person's rules: the dark web (Tor,
    I2P and the gateways that reach them from a normal browser). The agent
    is told why, so it explains instead of trying another way.

Pure functions, no IO.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final
from urllib.parse import urlsplit

__all__ = [
    "PERMISSION_MODES",
    "RiskFinding",
    "Severity",
    "commit_severity",
    "host_risk",
    "input_risk",
    "prompts_in_mode",
    "shell_risk",
    "tool_call_risk",
]


class Severity(StrEnum):
    FREE = "free"
    ASK = "ask"
    CONFIRM = "confirm"
    BLOCK = "block"


#: The permission modes a conversation can be in, from strictest to loosest.
PERMISSION_MODES: Final[tuple[str, ...]] = ("always_ask", "ask", "accept_edits", "auto", "bypass")


@dataclass(frozen=True, slots=True)
class RiskFinding:
    """Why an action is risky: what the card or the refusal says."""

    severity: Severity
    category: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"severity": str(self.severity), "category": self.category, "reason": self.reason}


def prompts_in_mode(severity: Severity, mode: str) -> bool:
    """Whether an action of this severity stops for the person in ``mode``.

    ``block`` never prompts: it is refused. ``confirm`` prompts in every mode.
    ``ask`` prompts in every mode but Bypass. ``free`` prompts only in Always ask.
    """
    if severity is Severity.BLOCK:
        return False
    if severity is Severity.CONFIRM:
        return True
    if severity is Severity.ASK:
        return mode != "bypass"
    return mode == "always_ask"


# --- Sites -----------------------------------------------------------------

#: Overlay networks a normal browser reaches only through Tor or I2P.
_DARK_TLDS: Final[tuple[str, ...]] = (".onion", ".i2p", ".loki", ".bit")
#: Gateways that open .onion sites from a normal browser ("tor2web").
_DARK_GATEWAYS: Final[re.Pattern[str]] = re.compile(
    r"(^|\.)(onion\.(ws|ly|to|pet|re|cab|city|direct|sh|dog|link|moe|si|ink|foundation|"
    r"casa|top|in\.net|lu)|tor2web\.(org|io|fi)|torproject-gateway\.\w+|onion\.cab|"
    r"darknetlive\.com|dark\.fail)$",
    re.I,
)


def host_risk(url: str) -> RiskFinding | None:
    """A site the assistant never opens, or ``None`` for an ordinary site."""
    host = (urlsplit(str(url or "")).hostname or "").lower().rstrip(".")
    if not host:
        return None
    if host.endswith(_DARK_TLDS) or _DARK_GATEWAYS.search(host):
        return RiskFinding(
            Severity.BLOCK,
            "dark_web",
            f"{host} is a dark-web address. Dodaios does not open Tor, I2P or their "
            "gateways: what is sold and shared there can make the person liable.",
        )
    return None


# --- Committing clicks -------------------------------------------------------

#: Kinds of committing click (``commit_gate._KINDS``) that move money.
_MONEY_KINDS: Final[frozenset[str]] = frozenset({"buy", "pay", "transfer"})
#: Kinds that end the person's account, hand a site their card or bank account,
#: or grant an app access to their account (an OAuth consent screen).
_ACCOUNT_KINDS: Final[frozenset[str]] = frozenset(
    {"close_account", "payment_details", "authorize"}
)


def commit_severity(kind: str) -> Severity:
    """How a committing click asks: money and accounts always, the rest by mode."""
    if kind in _MONEY_KINDS or kind in _ACCOUNT_KINDS:
        return Severity.CONFIRM
    return Severity.ASK


# --- Typing into a field -------------------------------------------------------

#: A field for payment details, read from its autocomplete, name, id, placeholder
#: and label (``commit_target.describe_node``). English and German page wording.
_PAYMENT_FIELD: Final[re.Pattern[str]] = re.compile(
    r"\bcc-(number|csc|exp\w*)\b|card.?number|cardnumber|credit.?card|debit.?card|"
    r"\bcvc\b|\bcvv\b|\bcsc\b|security.?code|expir\w*|\biban\b|\bbic\b|routing.?number|"
    r"account.?number|kartennummer|kreditkarte|prüfnummer|ablaufdatum|kontonummer",  # i18n-allow
    re.I,
)
#: What a card number looks like when it is typed: 13 to 19 digits.
_CARD_DIGITS: Final[re.Pattern[str]] = re.compile(r"^(?:\d[ -]?){13,19}$")


def input_risk(target: Any, text: str = "") -> RiskFinding | None:
    """Typing payment details into a page always asks; any other field is page work."""
    field = ""
    if isinstance(target, dict):
        field = " ".join(str(target.get(k) or "") for k in ("field", "label", "type"))
    typed = str(text or "").strip()
    if _PAYMENT_FIELD.search(field) or _CARD_DIGITS.match(typed):
        return RiskFinding(
            Severity.CONFIRM,
            "payment_details",
            "Typing payment details (card or bank account) into the page.",
        )
    return None


# --- Shell ---------------------------------------------------------------

_SHELL_RULES: Final[tuple[tuple[Severity, str, re.Pattern[str], str], ...]] = (
    (
        Severity.BLOCK,
        "dark_web",
        re.compile(r"\btor(\.exe)?\s|\btorsocks\b|\bproxychains\b.*\.onion|\.onion\b|\bi2pd?\b",
                   re.I),
        "Starts Tor or I2P or reaches a dark-web address.",
    ),
    (
        Severity.CONFIRM,
        "disk_wipe",
        re.compile(
            r"\brm\s+-[a-z]*r[a-z]*f?[a-z]*\s+(/|~|\$HOME|/\*|c:\\?)(\s|$)|"
            r"\bformat(\.com)?\s+[a-z]:|\bmkfs(\.\w+)?\b|\bdd\s+.*\bof=/dev/|"
            r"\bdiskpart\b|Remove-Item\s+.*-Recurse.*\s(c:\\?|\$env:USERPROFILE)\s*$|"
            r"\bcipher\s+/w\b",
            re.I,
        ),
        "Erases a whole disk, the home folder or the system drive.",
    ),
    (
        Severity.CONFIRM,
        "credentials",
        re.compile(
            r"\bcmdkey\s+/list\b|\bsecurity\s+find-(generic|internet)-password\b|"
            r"Login Data|\\Credentials\\|\.ssh/id_\w+(?!\.pub)|\bmimikatz\b",
            re.I,
        ),
        "Reads stored passwords, browser logins or private keys.",
    ),
    (
        Severity.CONFIRM,
        "money",
        re.compile(r"\bstripe\s+(charges|payment_intents|payouts|transfers|refunds)\s+create\b",
                   re.I),
        "Moves real money through a payment provider.",
    ),
    (
        Severity.ASK,
        "remote_code",
        re.compile(r"\b(curl|wget|iwr|Invoke-WebRequest)\b[^|]*\|\s*(ba|z)?sh\b|"
                   r"\biex\s*\(|Invoke-Expression", re.I),
        "Downloads code from the internet and runs it at once.",
    ),
    (
        Severity.ASK,
        "history_rewrite",
        re.compile(r"\bgit\s+push\b.*(--force\b|-f\b)|\bgit\s+reset\s+--hard\b|"
                   r"\bgit\s+clean\s+-[a-z]*f", re.I),
        "Rewrites or throws away git history or uncommitted work.",
    ),
)


def shell_risk(command: str) -> RiskFinding | None:
    """The most severe rule a shell command matches, or ``None``."""
    text = str(command or "")
    for severity, category, pattern, reason in _SHELL_RULES:
        if pattern.search(text):
            return RiskFinding(severity, category, reason)
    return None


# --- Any tool call -------------------------------------------------------------


def tool_call_risk(tool_name: str, args: dict[str, Any] | None) -> RiskFinding | None:
    """What this table says about one tool call: ``confirm``, ``block`` or ``None``.

    A call that moves money (``trust.hard_limits`` "money") always asks; a
    shell command is read by :func:`shell_risk`; a URL argument on the dark
    web is blocked. Anything else is left to the tool's own tier and the mode.
    """
    from dodaios.trust.hard_limits import command_of, hard_limit_for

    args = args if isinstance(args, dict) else {}
    for key in ("url", "start_url", "href"):
        found = host_risk(str(args.get(key) or ""))
        if found is not None:
            return found
    command = command_of(args)
    if command:
        found = shell_risk(command)
        if found is not None and found.severity in (Severity.BLOCK, Severity.CONFIRM):
            return found
    try:
        limit = hard_limit_for(tool_name, args, recipients_known=lambda _: True)
    except Exception:  # noqa: BLE001 — a broken check must not invent a card
        limit = None
    if limit == "money":
        return RiskFinding(
            Severity.CONFIRM, "money", "Moves real money: paying, buying or transferring."
        )
    return None
