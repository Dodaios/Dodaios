"""Structural bounding of a tool result: valid JSON within a character budget.

A tool result that is too large used to be cut mid-string, which left invalid
JSON the model could not parse. This trims the *structure* instead: long
strings are shortened and long lists lose their tail, as little as the budget
needs. The result is always valid JSON and says so when it was trimmed
(``truncated: true`` plus a ``truncation`` note with a hint on how to ask for
the rest). The budget is a provider/receiver limit, never a cost lever.
"""

from __future__ import annotations

import json
from typing import Any

#: String length tiers tried in turn, longest first: keep as much prose as the
#: budget allows before dropping list items.
_STRING_TIERS: tuple[int, ...] = (20_000, 4_000, 1_000, 300, 100, 24)
#: A tier is accepted once it can keep at least this many items of the longest list.
_MIN_COMFORTABLE_ITEMS = 20

DEFAULT_HINT = (
    "The result was too large. Ask for a narrower slice: use the tool's limit, "
    "cursor, state or id arguments, or a summary mode."
)


class _Stats:
    __slots__ = ("items", "strings")

    def __init__(self) -> None:
        self.items = 0
        self.strings = 0


def _shrink(value: Any, str_cap: int, list_cap: int, stats: _Stats) -> Any:
    if isinstance(value, str):
        if len(value) > str_cap:
            stats.strings += 1
            return f"{value[:str_cap]}… [+{len(value) - str_cap} chars]"
        return value
    if isinstance(value, list):
        if len(value) > list_cap:
            stats.items += len(value) - list_cap
        return [_shrink(item, str_cap, list_cap, stats) for item in value[:list_cap]]
    if isinstance(value, dict):
        return {key: _shrink(item, str_cap, list_cap, stats) for key, item in value.items()}
    return value


def _longest_list(value: Any) -> int:
    if isinstance(value, list):
        return max([len(value), *(_longest_list(item) for item in value)])
    if isinstance(value, dict):
        return max([0, *(_longest_list(item) for item in value.values())])
    return 0


def _marked(shrunk: Any, stats: _Stats, hint: str) -> dict[str, Any]:
    note = {
        "omitted_items": stats.items,
        "shortened_strings": stats.strings,
        "hint": hint,
    }
    if isinstance(shrunk, dict):
        return {**shrunk, "truncated": True, "truncation": note}
    return {"truncated": True, "truncation": note, "value": shrunk}


def bound_json(
    value: Any,
    max_chars: int,
    *,
    hint: str = DEFAULT_HINT,
    **dumps_kwargs: Any,
) -> str:
    """``value`` serialized to at most ``max_chars`` characters of valid JSON.

    Within the budget the serialization is returned untouched. Over it, strings
    and lists are trimmed structurally and the top level gains ``truncated:
    true`` and a ``truncation`` note carrying ``hint``.
    """
    dumps_kwargs.setdefault("ensure_ascii", False)
    dumps_kwargs.setdefault("default", str)
    full = json.dumps(value, **dumps_kwargs)
    if len(full) <= max_chars:
        return full
    plain = json.loads(full)
    longest = _longest_list(plain)

    def attempt(str_cap: int, list_cap: int) -> tuple[str, bool]:
        stats = _Stats()
        shrunk = _shrink(plain, str_cap, list_cap, stats)
        text = json.dumps(_marked(shrunk, stats, hint), **dumps_kwargs)
        return text, len(text) <= max_chars

    best: str | None = None
    for str_cap in _STRING_TIERS:
        low, high, found = 1, max(longest, 1), None
        if not attempt(str_cap, low)[1]:
            continue
        while low <= high:  # the largest list cap that still fits
            mid = (low + high) // 2
            text, fits = attempt(str_cap, mid)
            if fits:
                found, low = (text, mid), mid + 1
            else:
                high = mid - 1
        assert found is not None
        best = found[0]
        if found[1] >= min(longest, _MIN_COMFORTABLE_ITEMS):
            return best
    if best is not None:
        return best
    preview = full[: max(0, max_chars - 400)]
    note = json.dumps(
        {"truncated": True, "truncation": {"hint": hint}, "preview": preview}, **dumps_kwargs
    )
    if len(note) > max_chars:  # an absurdly small budget: keep the marker only
        note = json.dumps({"truncated": True}, **dumps_kwargs)
    return note


def bound_text(text: str, max_chars: int, *, hint: str = DEFAULT_HINT) -> str:
    """A plain-text result cut to ``max_chars`` with an honest marker."""
    if len(text) <= max_chars:
        return text
    marker = f"… [truncated: {len(text)} chars, showing {max_chars}. {hint}]"
    return text[: max(0, max_chars - len(marker))] + marker
