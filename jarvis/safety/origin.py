"""Where the target of a tool call came from (ADR-0040, audit stage).

The risk check sees a tool and its arguments. It cannot tell a recipient the
user dictated from one the model copied out of a fetched page: both are the
same string. This module supplies the missing fact, as a record only — it
changes no tier and blocks nothing.

Three pieces, all pure string work with no model call (the same constraint
AP-11 puts on the voice scrubber):

* A **ledger** per trace of the addressable values that appeared in tool
  results: e-mail addresses, URLs and their hosts, phone numbers, file paths.
  Each is remembered with the tool that produced it and whether that tool's
  output is the user's own data (``internal``) or came from outside
  (``external``). Only addressable values are tracked on purpose: a model can
  paraphrase a sentence, but an address it rewrites stops working, so exact
  matching on targets is reliable where tainting free text is not.
* **Targets**: which arguments of a call say where its effect lands, and what
  kind of effect that is. Declared here for the app's own tools, derived from
  schema property names for connected-server and marketplace tools, which
  cannot be trusted to declare it. A tool may override both with its own
  ``target_args`` / ``effect_for_args``.
* A **classification** of each target: named by the user this turn, known
  from the user's own data, seen only in external content, or found nowhere.

The values themselves never leave this module: an event carries the class and
the name of the tool the value came from, never the address.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Final

__all__ = [
    "EFFECTS",
    "TARGET_ORIGINS",
    "OriginLedger",
    "TargetOrigin",
    "addressable_values",
    "classify_targets",
    "tool_effect",
    "tool_output_origin",
    "tool_targets",
]

#: The vocabulary of ``ActionProposed.target_origin``, least to most notable.
#: ``""`` on an event means the call has no target argument.
TARGET_ORIGINS: Final[tuple[str, ...]] = ("user", "known", "unsourced", "external")

#: The vocabulary of ``ActionProposed.effect``.
EFFECTS: Final[tuple[str, ...]] = ("read", "modify", "outbound", "destructive", "spend", "unknown")

#: Tools whose output is the user's own data or the app's own state. Every
#: other tool's output counts as external, unknown tools included: content
#: nobody vouched for is not the user's word. Canonical names.
_INTERNAL_OUTPUT: Final[frozenset[str]] = frozenset(
    {
        "contact_lookup",
        "contact_upsert",
        "wiki_recall",
        "wiki_list",
        "wiki_page_read",
        "wiki_ingest",
        "remember",
        "whoami",
        "update_profile",
        "describe_app_settings",
        "find_app_action",
        "run_app_action",
        "navigate",
        "find_tools",
        "run_skill",
        "list_mutable_settings",
        "get_config_value",
        "set_config_value",
        "society_status",
        "society_memory_recall",
        "society_conversation_recall",
        "society_wiki_note",
        "society_routines",
        "switch_provider",
    }
)

#: ``tool -> action -> (target arguments, effect)``. ``"*"`` matches a tool
#: without actions, or any action not listed. Canonical tool names.
_DECLARED: Final[dict[str, dict[str, tuple[tuple[str, ...], str]]]] = {
    "gmail": {
        "send_message": (("to",), "outbound"),
        "delete_message": ((), "destructive"),
        "trash_message": ((), "modify"),
        "modify_message": ((), "modify"),
        "*": ((), "read"),
    },
    "slack": {"post_message": (("channel",), "outbound"), "*": ((), "read")},
    "google_drive": {
        "share_file": (("email_address",), "outbound"),
        "delete_file": ((), "destructive"),
        "create_file": ((), "modify"),
        "create_folder": ((), "modify"),
        "*": ((), "read"),
    },
    "google_calendar": {"list_events": ((), "read"), "*": ((), "modify")},
    "call_contact": {"*": (("name",), "outbound")},
    "run_shell": {"*": (("command",), "modify")},
    "type_text": {"*": (("text",), "modify")},
    "open_app": {"*": (("app_name", "arguments"), "modify")},
    "society_browser": {"*": (("url",), "outbound")},
    "home_assistant": {"*": (("entity_id",), "modify")},
    "search_web": {"*": ((), "read")},
}

#: Property names that hold a target on a tool nobody declared.
_TARGET_PROPERTY_NAMES: Final[frozenset[str]] = frozenset(
    {
        "to", "cc", "bcc", "recipient", "recipients", "email", "email_address",
        "url", "uri", "link", "href", "webhook", "webhook_url", "endpoint",
        "path", "file_path", "filepath", "destination",
        "channel", "channel_id", "phone", "phone_number", "number",
    }
)  # fmt: skip

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+", re.IGNORECASE)
# A sentence may end right after the number; a decimal continues with a digit.
_PHONE_RE = re.compile(r"(?<![\w.])\+?\d[\d ()/-]{6,}\d(?!\w|\.\d)")
_WINDOWS_PATH_RE = re.compile(r"\b[A-Za-z]:\\[^\s\"'<>|]+")
_UNIX_PATH_RE = re.compile(r"(?<![\w:/])/(?:[\w.-]+/)+[\w.-]+")

#: Text of one tool result that is searched for addressable values. A result
#: larger than this was capped before the model saw it anyway.
_MAX_RESULT_CHARS: Final[int] = 200_000
#: A string longer than this without whitespace is treated as encoded bytes.
_MAX_UNBROKEN_CHARS: Final[int] = 2_000
#: Addressable values remembered per trace, and traces remembered at all.
_MAX_VALUES_PER_TRACE: Final[int] = 2_000
_MAX_TRACES: Final[int] = 256


def canonical(name: str) -> str:
    """Hyphen-, dot- and case-insensitive form of a tool name."""
    return (name or "").strip().lower().replace("-", "_").replace(".", "_")


def _looks_encoded(text: str) -> bool:
    """A long run without whitespace is image or file bytes, not prose."""
    return len(text) > _MAX_UNBROKEN_CHARS and not any(ch.isspace() for ch in text[:400])


def _flatten(value: Any) -> str:
    """The TEXT of a result, encoded payloads left out.

    A screenshot rides in a result as base64; read as text it yields
    thousands of path-shaped fragments that are not addresses.
    """
    if isinstance(value, str):
        return "" if _looks_encoded(value) else value
    if isinstance(value, dict):
        return "\n".join(_flatten(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return "\n".join(_flatten(item) for item in value)
    return "" if value is None else str(value)


def addressable_values(value: Any) -> set[str]:
    """Normalised e-mail addresses, URLs with their hosts, phones and paths."""
    text = _flatten(value)[:_MAX_RESULT_CHARS]
    found: set[str] = set()
    for match in _EMAIL_RE.findall(text):
        found.add(match.lower())
    for match in _URL_RE.findall(text):
        url = match.rstrip(".,;:!?").lower()
        found.add(url.rstrip("/"))
        host = url.split("://", 1)[1].split("/", 1)[0].split("?", 1)[0]
        if host:
            found.add(host.removeprefix("www."))
    for match in _PHONE_RE.findall(text):
        digits = re.sub(r"\D", "", match)
        if 7 <= len(digits) <= 15:
            found.add("tel:" + digits)
    for match in _WINDOWS_PATH_RE.findall(text):
        found.add(match.rstrip(".,;:").replace("\\\\", "\\").lower())
    for match in _UNIX_PATH_RE.findall(text):
        found.add(match.rstrip(".,;:").lower())
    return found


def tool_output_origin(tool: Any) -> str:
    """``internal`` or ``external`` for what ``tool`` returns."""
    declared = getattr(tool, "output_origin", None)
    if declared in ("internal", "external"):
        return str(declared)
    if getattr(tool, "is_mcp_tool", False):
        return "external"
    name = str(getattr(tool, "name", "") or "")
    return "internal" if canonical(name) in _INTERNAL_OUTPUT else "external"


def _declared(tool: Any, args: dict[str, Any]) -> tuple[tuple[str, ...], str] | None:
    table = _DECLARED.get(canonical(str(getattr(tool, "name", "") or "")))
    if table is None:
        return None
    action = str(args.get("action") or "").strip()
    return table.get(action) or table.get("*")


def tool_targets(tool: Any, args: dict[str, Any]) -> tuple[str, ...]:
    """The argument names of this call that say where its effect lands."""
    own = getattr(tool, "target_args", None)
    if isinstance(own, (tuple, list)):
        return tuple(str(name) for name in own if name in args)
    declared = _declared(tool, args)
    if declared is not None:
        return tuple(name for name in declared[0] if name in args)
    return tuple(name for name in args if canonical(name) in _TARGET_PROPERTY_NAMES)


def tool_effect(tool: Any, args: dict[str, Any]) -> str:
    """What kind of effect this call has; ``unknown`` when nobody declared it."""
    hook = getattr(tool, "effect_for_args", None)
    if callable(hook):
        try:
            answer = hook(args)
        except Exception:  # noqa: BLE001 — a broken hook means "unknown", never a failed call
            answer = None
        if answer in EFFECTS:
            return str(answer)
    declared = _declared(tool, args)
    return declared[1] if declared is not None else "unknown"


@dataclass(frozen=True, slots=True)
class TargetOrigin:
    """The verdict for one call: the most notable class among its targets."""

    #: One of :data:`TARGET_ORIGINS`, or ``""`` when the call has no target.
    origin: str = ""
    #: The tool whose result held the value, for ``known`` and ``external``.
    source: str = ""
    effect: str = ""


class OriginLedger:
    """Addressable values seen in tool results, per trace. In memory only."""

    def __init__(self) -> None:
        # trace -> value -> (origin of the tool's output, tool name)
        self._traces: OrderedDict[str, dict[str, tuple[str, str]]] = OrderedDict()

    def record(self, trace: str, tool: Any, output: Any) -> None:
        """Remember what a tool result contained."""
        values = addressable_values(output)
        if not values:
            return
        origin = tool_output_origin(tool)
        name = str(getattr(tool, "name", "") or "")
        seen = self._traces.get(trace)
        if seen is None:
            seen = self._traces[trace] = {}
            while len(self._traces) > _MAX_TRACES:
                self._traces.popitem(last=False)
        else:
            self._traces.move_to_end(trace)
        for value in values:
            if len(seen) >= _MAX_VALUES_PER_TRACE:
                break
            # A value the user's own data already vouched for stays internal.
            if seen.get(value, ("", ""))[0] != "internal":
                seen[value] = (origin, name)

    def lookup(self, trace: str, value: str) -> tuple[str, str] | None:
        seen = self._traces.get(trace)
        return seen.get(value) if seen else None

    def forget(self, trace: str) -> None:
        self._traces.pop(trace, None)


def _tokens(value: Any) -> set[str]:
    """What a target argument names: its addresses, else the value itself."""
    found = addressable_values(value)
    if found:
        return found
    text = " ".join(_flatten(value).split()).strip().lower()
    return {text} if text else set()


def classify_targets(
    tool: Any,
    args: dict[str, Any],
    *,
    ledger: OriginLedger,
    trace: str,
    user_text: str,
) -> TargetOrigin:
    """Where the targets of this call came from.

    ``user``: the value is in the user's own words. ``known``: a tool that
    reads the user's own data returned it this turn. ``external``: it was
    seen only in content from outside. ``unsourced``: it appears nowhere, so
    the model produced it. A call with several targets gets the most notable
    class, external first.
    """
    effect = tool_effect(tool, args)
    names = tool_targets(tool, args) if isinstance(args, dict) else ()
    if not names:
        return TargetOrigin(effect=effect)
    spoken = " ".join((user_text or "").split()).lower()
    spoken_values = addressable_values(user_text or "")
    worst = -1
    source = ""
    for name in names:
        for token in _tokens(args.get(name)):
            hit = ledger.lookup(trace, token)
            if token in spoken_values or (len(token) >= 3 and token in spoken):
                rank, origin_source = 0, ""
            elif hit is not None and hit[0] == "internal":
                rank, origin_source = 1, hit[1]
            elif hit is not None:
                rank, origin_source = 3, hit[1]
            else:
                rank, origin_source = 2, ""
            if rank > worst:
                worst, source = rank, origin_source
    if worst < 0:
        return TargetOrigin(effect=effect)
    return TargetOrigin(origin=TARGET_ORIGINS[worst], source=source, effect=effect)
