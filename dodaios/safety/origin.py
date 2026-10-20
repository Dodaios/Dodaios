"""Where the target of a tool call came from (ADR-0040, audit stage).

The risk check sees a tool and its arguments. It cannot tell a recipient the
user dictated from one the model copied out of a fetched page: both are the
same string. This module supplies the missing fact, as a record only — it
changes no tier and blocks nothing.

Three pieces, all pure string work with no model call (the same constraint
AP-11 puts on the voice scrubber):

* A **ledger** per trace of the addressable values that appeared in tool
  results: e-mail addresses, URLs and their hosts, phone numbers, file paths.
  Each is remembered with the tool that produced it and whether that tool
  reads data the user owns (``internal``) or anything else (``external``).
  Only addressable values are tracked on purpose: a model can paraphrase a
  sentence, but an address it rewrites stops working, so exact matching on
  targets is reliable where tainting free text is not. A value a call passed
  in itself is not evidence when the same call hands it back.
* **Targets**: which arguments of a call say where its effect lands, and what
  kind of effect that is. Declared here for the app's own tools, derived from
  schema property names for connected-server and marketplace tools, which
  cannot be trusted to declare it. A tool may override both with its own
  ``target_args`` / ``effect_for_args``.
* A **classification** of each target: named by the user this turn, known
  from the user's own data, seen only in external content, or found nowhere.

The values themselves never leave this module: an event carries the class and
the name of the tool the value came from, never the address.

Everything here runs on the event loop inside ``ToolExecutor``, so every scan
is linear in the size of a result and that size is bounded.
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

#: Tools that READ data the user owns and return more than they were given.
#: Deliberately short. A tool that writes hands its own arguments back, and
#: the wiki holds pages that were ingested from the web, so neither can vouch
#: for an address: listing them here would let a page launder its address
#: through one save. Every other tool's output counts as external, unknown
#: tools included. Canonical names.
_INTERNAL_OUTPUT: Final[frozenset[str]] = frozenset(
    {
        "contact_lookup",
        "whoami",
        "describe_app_settings",
        "find_app_action",
        "find_tools",
        "list_mutable_settings",
        "get_config_value",
        "society_status",
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
    "google_calendar": {
        "list_events": ((), "read"),
        "delete_event": ((), "destructive"),
        "*": ((), "modify"),
    },
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

# Every pattern is anchored on its left edge and bounded in length, so a scan
# is linear: an unanchored ``[...]+@`` re-reads a long run of letters from
# every position in it, which freezes the event loop on a page of dashes.
_EMAIL_RE = re.compile(
    r"(?<![\w.%+-])[\w.%+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,8}(?![\w-])"
)
_URL_RE = re.compile(r"(?<![\w])https?://[^\s\"'<>)\]]{1,480}", re.IGNORECASE)
# A sentence may end right after the number; a decimal continues with a digit.
_PHONE_RE = re.compile(r"(?<![\w.])\+?\d[\d ()/-]{6,22}\d(?!\w|\.\d)")
_WINDOWS_PATH_RE = re.compile(r"(?<![\w])[A-Za-z]:[\\/][^\s\"'<>|]{1,480}")
_UNIX_PATH_RE = re.compile(r"(?<![\w:/.])/(?:[\w.-]{1,120}/){1,24}[\w.-]{1,120}")

#: Text of one tool result that is searched for addressable values.
_MAX_RESULT_CHARS: Final[int] = 100_000
#: A whitespace-free run longer than this is encoded bytes, not an address.
_MAX_TOKEN_CHARS: Final[int] = 512
#: Values remembered per trace and per origin, and traces remembered at all.
_MAX_VALUES_PER_TRACE: Final[int] = 2_000
_MAX_TRACES: Final[int] = 256
#: A free-text target (a contact name, a channel) shorter than this is too
#: likely to sit inside an unrelated word of the user's sentence.
_MIN_FREE_TEXT_CHARS: Final[int] = 4


def canonical(name: str) -> str:
    """Hyphen-, dot- and case-insensitive form of a tool name."""
    return (name or "").strip().lower().replace("-", "_").replace(".", "_")


def _text(value: Any, budget: int = _MAX_RESULT_CHARS) -> str:
    """The searchable text of ``value``, bounded while it is collected.

    Encoded payloads are left out as they are met: ``bytes`` are skipped and
    a whitespace-free run longer than :data:`_MAX_TOKEN_CHARS` is dropped, so
    a screenshot in a result costs nothing and yields no path-shaped noise.
    """
    parts: list[str] = []
    left = budget

    def walk(item: Any) -> None:
        nonlocal left
        if left <= 0 or item is None or isinstance(item, (bytes, bytearray, memoryview)):
            return
        if isinstance(item, str):
            for token in item[: left * 2].split():
                if left <= 0:
                    return
                if len(token) <= _MAX_TOKEN_CHARS:
                    parts.append(token)
                    left -= len(token) + 1
            return
        if isinstance(item, dict):
            for child in item.values():
                walk(child)
            return
        if isinstance(item, (list, tuple, set, frozenset)):
            for child in item:
                walk(child)
            return
        if isinstance(item, (int, float, bool)):
            parts.append(str(item))
            left -= 24

    walk(value)
    return " ".join(parts)


def _host(url: str) -> str:
    rest = url.split("://", 1)[1] if "://" in url else url
    host = rest.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0].split("@")[-1]
    return host.split(":", 1)[0].removeprefix("www.")


def _groups(text: str) -> list[tuple[str, ...]]:
    """Addressable values in ``text``, each with the weaker forms that also
    identify it: a URL comes with its host."""
    groups: list[tuple[str, ...]] = []
    for match in _EMAIL_RE.findall(text):
        groups.append((match.lower(),))
    for match in _URL_RE.findall(text):
        url = match.rstrip(".,;:!?").lower().rstrip("/")
        host = _host(url)
        groups.append((url, host) if host else (url,))
    for match in _PHONE_RE.findall(text):
        digits = re.sub(r"\D", "", match)
        if 7 <= len(digits) <= 15:
            groups.append(("tel:" + digits,))
    for match in _WINDOWS_PATH_RE.findall(text):
        path = match.rstrip(".,;:").replace("/", "\\")
        groups.append((re.sub(r"\\+", r"\\", path).lower(),))
    for match in _UNIX_PATH_RE.findall(text):
        groups.append((match.rstrip(".,;:").lower(),))
    return groups


def addressable_values(value: Any) -> set[str]:
    """Normalised e-mail addresses, URLs with their hosts, phones and paths."""
    return {form for group in _groups(_text(value)) for form in group}


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
    """Addressable values seen in tool results, per trace. In memory only.

    What the user's own data vouched for and what came from outside are kept
    apart and bounded apart, so one large page cannot crowd a contact out.
    """

    def __init__(self) -> None:
        # trace -> (internal values, external values); value -> tool name
        self._traces: OrderedDict[str, tuple[dict[str, str], dict[str, str]]] = OrderedDict()

    def record(self, trace: str, tool: Any, output: Any, args: Any = None) -> None:
        """Remember what a tool result contained.

        ``args`` are the arguments of the call that produced ``output``. A
        value the call passed in is left out: a tool that echoes its input
        back has added no evidence about where that input came from.
        """
        values = addressable_values(output)
        if args is not None and values:
            values -= addressable_values(args)
        if not values:
            return
        internal = tool_output_origin(tool) == "internal"
        name = str(getattr(tool, "name", "") or "")
        entry = self._traces.get(trace)
        if entry is None:
            entry = self._traces[trace] = ({}, {})
            while len(self._traces) > _MAX_TRACES:
                self._traces.popitem(last=False)
        else:
            self._traces.move_to_end(trace)
        bucket = entry[0] if internal else entry[1]
        for value in values:
            if value in bucket or len(bucket) < _MAX_VALUES_PER_TRACE:
                bucket.setdefault(value, name)

    def lookup(self, trace: str, value: str) -> tuple[str, str] | None:
        """``(origin, tool name)`` for ``value``; the user's own data wins."""
        entry = self._traces.get(trace)
        if entry is None:
            return None
        if value in entry[0]:
            return "internal", entry[0][value]
        if value in entry[1]:
            return "external", entry[1][value]
        return None

    def forget(self, trace: str) -> None:
        self._traces.pop(trace, None)


def _spoken(token: str, spoken: str) -> bool:
    """Whether ``token`` stands in the user's sentence as a whole value.

    A bare substring test reads ``bob@corp.com`` as spoken when the user said
    ``bob@corp.com.au``, and ``dir`` as spoken inside "directory".
    """
    if not token or not spoken:
        return False
    start = spoken.find(token)
    while start >= 0:
        end = start + len(token)
        before = spoken[start - 1] if start else " "
        after = spoken[end] if end < len(spoken) else " "
        tail = spoken[end + 1] if end + 1 < len(spoken) else " "
        clean_before = not (before.isalnum() or before in "@._-/\\")
        clean_after = not (after.isalnum() or after in "@_-/\\")
        if after == "." and tail.isalnum():
            clean_after = False
        if clean_before and clean_after:
            return True
        start = spoken.find(token, start + 1)
    return False


def _rank(
    group: tuple[str, ...], *, ledger: OriginLedger, trace: str, spoken: str
) -> tuple[int, str]:
    """``(index into TARGET_ORIGINS, source tool)`` for one target value.

    Any form of the value counts: a URL the user named only by its host is
    still the user's. The strongest evidence wins within one value.
    """
    if any(_spoken(form, spoken) for form in group):
        return 0, ""
    hits = [hit for form in group if (hit := ledger.lookup(trace, form)) is not None]
    for origin, source in hits:
        if origin == "internal":
            return 1, source
    if hits:
        return 3, hits[0][1]
    return 2, ""


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
    spoken = " ".join((user_text or "")[:_MAX_RESULT_CHARS].split()).lower()
    worst = -1
    source = ""
    for name in names:
        text = _text(args.get(name), 8_000)
        groups = _groups(text)
        if not groups:
            free = text.strip().lower()
            # A name or a channel has no address form; it can only be matched
            # against what the user said.
            groups = [(free,)] if len(free) >= _MIN_FREE_TEXT_CHARS else []
        for group in groups:
            rank, origin_source = _rank(group, ledger=ledger, trace=trace, spoken=spoken)
            if rank > worst:
                worst, source = rank, origin_source
    if worst < 0:
        return TargetOrigin(effect=effect)
    return TargetOrigin(origin=TARGET_ORIGINS[worst], source=source, effect=effect)
