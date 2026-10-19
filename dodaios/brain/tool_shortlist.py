"""Which tools a model is SHOWN, as opposed to which it may use.

A turn's tool dict says what the model is allowed to call. Sending every
schema of that dict is a separate decision, and until now it was the only one
made: a 32k local model was handed whatever fit, and what did not fit was
dropped largest-first. The richly described tools went first — a save tool
with a real schema disappeared before a parameterless list tool — and a
dropped tool was gone for the turn.

This module splits the dict in two:

* the **direct** set, whose schemas ride the request, chosen by priority
  (what the turn mandated, the caller's own hands, the everyday core) until a
  token budget or a count limit is reached;
* the **deferred** rest, which stays callable. The model reaches it through
  one small ``find_tools`` tool that searches it by intent; what it finds is
  shown as a real tool definition from the next round on, and a deferred tool
  the model names outright simply runs.

Nothing becomes unreachable, so narrowing the direct set never recreates
"a tool the model cannot see is the bug users report". ``find_tools`` only
ever searches the dict it was built from: it cannot widen what a turn is
allowed to call, and it is not part of any standing tool set.

Pure and synchronous; no registry is imported here (AP-26).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from dodaios.core.protocols import ExecutionContext, RiskTier, Tool, ToolResult

__all__ = [
    "CORE_PRIORITY",
    "FIND_TOOLS_NAME",
    "FindToolsTool",
    "ROLE_BASE",
    "SurfacePlan",
    "canonical",
    "plan_surface",
    "tool_tokens",
]

FIND_TOOLS_NAME: Final[str] = "find_tools"

#: The everyday tools, most needed first: what stays in front of a small
#: model when not everything fits. Canonical names (see :func:`canonical`).
#: Anything not listed keeps its registry order behind these.
CORE_PRIORITY: Final[tuple[str, ...]] = (
    "search_web",
    "wiki_recall",
    "wiki_ingest",
    "remember",
    "wiki_list",
    "wiki_page_read",
    "run_skill",
    "contact_lookup",
    "call_contact",
    "contact_upsert",
    "update_profile",
    "computer_use",
    "screenshot",
    "screen_snapshot",
    "spawn_worker",
    "run_shell",
    "find_app_action",
    "run_app_action",
    "describe_app_settings",
    "navigate",
    "create_artifact",
    "delegate_to_agent",
    "message_agent",
    "society_status",
    "switch_provider",
    "google_calendar",
    "gmail",
    "google_drive",
    "spotify",
    "youtube_music",
    "slack",
    "home_assistant",
    "vercel",
    "list_mutable_settings",
    "get_config_value",
    "set_config_value",
)

#: What a caller with a role is shown besides the tools the role names: the
#: reads nearly every job starts with. Canonical names.
ROLE_BASE: Final[frozenset[str]] = frozenset(
    {"search_web", "wiki_recall", "wiki_list", "wiki_page_read", "run_skill"}
)

#: Chars per token for the size estimate; the same conservative figure the
#: brain manager budgets the rest of the request with.
_CHARS_PER_TOKEN: Final[int] = 3

#: How many tools one ``find_tools`` answer names. A small model that asked
#: for one tool must not get forty.
_FIND_MAX_RESULTS: Final[int] = 6
#: Length of the one-line description each named tool gets in the answer. The
#: schema itself is not repeated there: it arrives as a tool definition.
_FIND_LINE_CHARS: Final[int] = 200
#: Query words that say nothing about which tool is meant.
_STOP_WORDS: Final[frozenset[str]] = frozenset(
    {"a", "an", "and", "for", "from", "i", "in", "is", "it", "me", "my", "of", "on", "or",
     "please", "the", "this", "to", "want", "with"}
)
#: Names listed in the tool's own description, so a model can ask for an exact
#: one instead of guessing words.
_INDEX_MAX_NAMES: Final[int] = 80
_INDEX_MAX_CHARS: Final[int] = 1_600

_WORD_RE = re.compile(r"[a-z0-9]+")


def canonical(name: str) -> str:
    """Hyphen-, dot- and case-insensitive form of a tool name."""
    return (name or "").strip().lower().replace("-", "_").replace(".", "_")


def tool_tokens(name: str, tool: Any) -> int:
    """What ONE tool costs on the wire: name, description and schema."""
    description = getattr(tool, "description", "") or ""
    schema = getattr(tool, "schema", None) or {}
    try:
        wire = json.dumps(
            {"name": name, "description": description, "input_schema": schema},
            ensure_ascii=False,
            default=str,
        )
    except (TypeError, ValueError):  # unserialisable schema: size its repr instead
        wire = f"{name} {description} {schema}"
    return len(wire) // _CHARS_PER_TOKEN + 1


@dataclass(frozen=True, slots=True)
class SurfacePlan:
    """The split of one turn's tools."""

    #: Shown to the model, in the order they were chosen.
    direct: dict[str, Tool]
    #: Callable but not shown, in the order they were passed over.
    deferred: dict[str, Tool]


def plan_surface(
    tools: Mapping[str, Tool],
    *,
    keep: Iterable[str] = (),
    priority: Iterable[str] = CORE_PRIORITY,
    budget_tokens: int | None = None,
    max_direct: int = 0,
    only: Iterable[str] | None = None,
) -> SurfacePlan:
    """Choose the direct set of ``tools``.

    ``keep`` names are always direct, whatever the budget: the tool a
    deterministic gate mandated this turn, and the caller's own hands.
    The rest is taken in this order until ``budget_tokens`` (``None`` = no
    token limit) or ``max_direct`` (``0`` = no count limit) is reached:
    names in ``priority`` by their position, then everything else in the
    order of ``tools``, connected-server tools last — they are additions to
    the app's own surface, each one a full JSON schema.

    ``only``, when given, is the whole direct set besides ``keep``: an agent
    whose role names the tools it works with is shown those and nothing
    else. A tool that does not fit is passed over and the next one is tried,
    so one oversized schema cannot starve the smaller ones behind it.
    """
    kept = {name for name in keep if name in tools}
    rank = {canonical(name): index for index, name in enumerate(priority)}
    allowed = None if only is None else {canonical(name) for name in only}
    position = {name: index for index, name in enumerate(tools)}
    candidates = [name for name in tools if name not in kept]
    unranked = len(rank)
    candidates.sort(
        key=lambda name: (
            rank.get(canonical(name), unranked),
            1 if getattr(tools[name], "is_mcp_tool", False) else 0,
            position[name],
        )
    )
    direct: dict[str, Tool] = {name: tools[name] for name in tools if name in kept}
    spent = sum(tool_tokens(name, tools[name]) for name in direct)
    passed: list[str] = []
    for name in candidates:
        if allowed is not None and canonical(name) not in allowed:
            passed.append(name)
            continue
        if max_direct > 0 and len(direct) >= max_direct:
            passed.append(name)
            continue
        cost = tool_tokens(name, tools[name])
        if budget_tokens is not None and spent + cost > budget_tokens:
            passed.append(name)
            continue
        direct[name] = tools[name]
        spent += cost
    return SurfacePlan(direct=direct, deferred={name: tools[name] for name in passed})


def _words(text: str) -> set[str]:
    return set(_WORD_RE.findall((text or "").lower()))


class FindToolsTool:
    """Search the tools of this turn that were not put in front of the model.

    Read-only. The answer names the matching tools with one line each;
    ``reveal`` is called with those names, and the loop then sends their
    schemas as real tool definitions from the next round on. The schema is
    deliberately not repeated in the answer: paid once, not twice.

    ``reveal_tokens`` bounds what one turn may reveal when the window is what
    forced the deferral. A match beyond it is still named, so the model can
    call it; only its definition does not ride along. ``None`` = no bound.

    A lookup is not an action: ``is_lookup_only`` keeps it out of the record
    of tools that ran, which the honesty guards and the spoken "done" read.
    """

    name: str = FIND_TOOLS_NAME
    risk_tier: RiskTier = "safe"
    is_lookup_only: bool = True

    def __init__(
        self,
        deferred: Mapping[str, Tool],
        *,
        reveal: Callable[[Iterable[str]], None] | None = None,
        reveal_tokens: int | None = None,
    ) -> None:
        self._deferred = dict(deferred)
        self._reveal = reveal
        self._reveal_tokens = reveal_tokens
        self._revealed: set[str] = set()
        names = sorted(self._deferred)
        listed: list[str] = []
        used = 0
        for candidate in names[:_INDEX_MAX_NAMES]:
            if used + len(candidate) + 2 > _INDEX_MAX_CHARS:
                break
            listed.append(candidate)
            used += len(candidate) + 2
        more = len(names) - len(listed)
        index = ", ".join(listed) + (f" and {more} more" if more > 0 else "")
        self.description = (
            "More tools are available than the ones listed here. Call this with a "
            "few words for what you want to do, or an exact tool name. The matching "
            "tools are then added to your tools and you call the one you need by "
            f"its name. Not listed above: {index}."
        )
        self.schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What you want to do, or a tool name.",
                }
            },
            "required": ["query"],
        }

    def bind(self, reveal: Callable[[Iterable[str]], None]) -> None:
        """Attach the loop that shows revealed tools from its next round on."""
        self._reveal = reveal

    def read_only_for_args(self, args: dict[str, Any]) -> bool:
        return True

    def _ranked(self, query: str) -> list[str]:
        wanted = canonical(query)
        exact = [name for name in self._deferred if canonical(name) == wanted]
        if exact:
            return exact
        terms = _words(query) - _STOP_WORDS
        if not terms:
            return sorted(self._deferred)
        scored: list[tuple[int, str]] = []
        for name, tool in self._deferred.items():
            in_name = len(terms & _words(name))
            in_text = len(terms & _words(getattr(tool, "description", "") or ""))
            score = in_name * 3 + in_text
            if score:
                scored.append((score, name))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [name for _score, name in scored]

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        query = str((args or {}).get("query") or "").strip()
        ranked = self._ranked(query)
        found: list[dict[str, Any]] = []
        newly: list[str] = []
        for name in ranked[:_FIND_MAX_RESULTS]:
            tool = self._deferred[name]
            line = " ".join((getattr(tool, "description", "") or "").split())
            entry: dict[str, Any] = {"name": name, "description": line[:_FIND_LINE_CHARS]}
            if name not in self._revealed:
                cost = tool_tokens(name, tool)
                if self._reveal_tokens is not None and cost > self._reveal_tokens:
                    # No room left to show its definition this turn. It can
                    # still be called; the arguments are named here instead.
                    properties = (getattr(tool, "schema", None) or {}).get("properties")
                    entry["arguments"] = sorted(properties) if isinstance(properties, dict) else []
                else:
                    if self._reveal_tokens is not None:
                        self._reveal_tokens -= cost
                    self._revealed.add(name)
                    newly.append(name)
            found.append(entry)
        if not found:
            return ToolResult(
                success=True,
                output={
                    "tools": [],
                    "note": "No tool matches. Try other words, or answer without one.",
                    "available": sorted(self._deferred)[:_INDEX_MAX_NAMES],
                },
            )
        if self._reveal is not None and newly:
            self._reveal(newly)
        return ToolResult(
            success=True,
            output={
                "tools": found,
                "note": "These are now among your tools. Call the one you need by its name.",
            },
        )
