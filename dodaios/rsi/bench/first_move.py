"""The first_move domain: is the lead's first move for a request the right one.

The lead is the one assistant the person talks to, and its first move decides
the rest of the turn: answer in text, ask a question on the card, hand work to
an agent, look something up, change a setting. A task is one request and what
that first move should be (``check``):

* ``expect``: the first tool call that is right (``tools``, and ``also_accept``
  when those exist), the arguments it must carry (``args``), or ``none`` when
  the right move is to answer in text. This is the routing eval's expectation
  (``tests/fixtures/lead_routing``, ``docs/lead-routing-evals.md``); the rules
  that match a move against it live here, and the eval reads them from here,
  so the benchmark and the eval cannot disagree on what "right" means;
* ``opening``: a short line of text must come before the first tool call (the
  reply style's line that takes the task on; ``FIRST_LINE`` asks for it beside
  every message). Set on tasks whose right move is a tool call.

**Score.** 1.0 when the move is right (tool and arguments, as the routing eval
judges it) and, where an opening is asked for, a line came first; 0.5 when the
move is right but the line is missing; 0.0 when the move is wrong. So a change
that keeps the routing but loses the line before the tool shows up, at half the
weight of a wrong route.

**Cost.** The message the lead gets, in tokens (characters / 4). The lines that
ride beside every message are part of it and stay in the conversation for every
later turn; the system prompt is the same on both sides of a comparison and is
left out, so a shorter message shows as the share it is of what grows.

What this check cannot see: anything after the first move (what the tool then
did, the reply's shape and length, a brief's wording), and what the line before
the tool says (only that it came).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from .model import Measured

__all__ = [
    "LOADING_TOOLS",
    "NO_TOOL",
    "Expect",
    "Move",
    "args_mismatches",
    "matches",
    "score",
    "tool_name",
    "verdict",
]

#: The expected "first move" for a request that must not call anything.
NO_TOOL: Final = "none"
#: Steps a CLI takes to load a tool's schema before it calls the tool. They are
#: not a move: the move is the call that follows.
LOADING_TOOLS: Final[frozenset[str]] = frozenset({"ToolSearch"})
#: The score of a right move without the line that should come before it.
NO_OPENING: Final[float] = 0.5
_CHARS_PER_TOKEN: Final = 4


def _server_prefixes() -> tuple[str, ...]:
    from dodaios.core.branding import MCP_TOOLS_SERVER_NAME

    # Claude Code names the app's tools ``mcp__<server>__<tool>``; Grok Build ``<server>__<tool>``.
    return (f"mcp__{MCP_TOOLS_SERVER_NAME}__", f"{MCP_TOOLS_SERVER_NAME}__")


def tool_name(raw: str) -> str:
    """A tool as the app lists it: the CLI's prefix for the app's own server taken off."""
    text = str(raw or "")
    for prefix in _server_prefixes():
        if text.startswith(prefix):
            return text[len(prefix) :]
    return text


def _names(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (raw,) if raw else ()
    return tuple(str(item) for item in raw if str(item))


@dataclass(frozen=True, slots=True)
class Expect:
    """What the first move of the lead must be."""

    tools: tuple[str, ...]  # accepted first tools; ("none",) = answer directly
    also_accept: tuple[str, ...] = ()  # accepted when they exist, never required to exist
    args: dict[str, Any] = field(default_factory=dict)
    approval: bool = False  # the chosen tool must be an ask-tier tool in the catalog
    effect: str = ""  # "read" or "action": the chosen tool must not contradict it

    @property
    def expects_tool(self) -> bool:
        return self.tools != (NO_TOOL,)

    def accepts(self, tool: str | None) -> bool:
        if tool is None:
            return not self.expects_tool
        return tool in self.tools or tool in self.also_accept

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"tools": list(self.tools)}
        if self.also_accept:
            out["also_accept"] = list(self.also_accept)
        if self.args:
            out["args"] = dict(self.args)
        if self.approval:
            out["approval"] = True
        if self.effect:
            out["effect"] = self.effect
        return out

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> Expect:
        tools = _names(raw.get("tools")) or (NO_TOOL,)
        args = raw.get("args")
        return cls(
            tools=tools,
            also_accept=_names(raw.get("also_accept")),
            args=dict(args) if isinstance(args, Mapping) else {},
            approval=bool(raw.get("approval")),
            effect=str(raw.get("effect") or ""),
        )


@dataclass(frozen=True, slots=True)
class Move:
    """The first move a model made: a tool call, or text only."""

    #: The tool as the app lists it (:func:`tool_name`); ``None``: it answered in text.
    tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    #: Text that came before the first tool call (the line that takes the task on).
    opening: str = ""
    #: The answer, when no tool was called (kept short).
    text: str = ""
    #: The run failed: a failure of the run, never "answered directly".
    error: str = ""
    #: The model the CLI said it ran on ("" when it did not say).
    model: str = ""


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    return " ".join(text.split())


def matches(expected: Any, actual: Any) -> bool:
    """One expected value against one actual value.

    A list expects any of its entries. A string matches as a normalised substring
    (so ``T2`` matches ``terminal T2``). Other scalars match by equality.
    """
    if isinstance(expected, list):
        return any(matches(item, actual) for item in expected)
    if isinstance(expected, (bool, int, float)):
        return bool(actual == expected)
    return actual is not None and _norm(expected) in _norm(actual)


def _flatten(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [text for item in value.values() for text in _flatten(item)]
    if isinstance(value, (list, tuple)):
        return [text for item in value for text in _flatten(item)]
    return [] if value is None else [str(value)]


def args_mismatches(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> list[str]:
    """Why the arguments do not satisfy the expectation. The key ``*`` means "any argument"."""
    problems: list[str] = []
    for key, want in expected.items():
        if key == "*":
            if not any(matches(want, value) for value in _flatten(dict(actual))):
                problems.append(f"no argument mentions {want!r}")
        elif key not in actual or not matches(want, actual[key]):
            problems.append(f"{key}: want {want!r}, got {actual.get(key)!r}")
    return problems


def verdict(expect: Expect, move: Move | None) -> tuple[str, str]:
    """The routing eval's verdict: ``pass``, ``wrong_tool``, ``wrong_args`` or ``error``."""
    if move is None:
        return "wrong_tool", "no recorded response"
    if move.error:
        return "error", move.error
    if not expect.accepts(move.tool):
        want = "no tool" if not expect.expects_tool else " or ".join(expect.tools)
        return "wrong_tool", f"want {want}, got {move.tool or 'no tool'}"
    if not expect.expects_tool:
        return "pass", ""
    problems = args_mismatches(expect.args, move.args)
    if problems:
        return "wrong_args", "; ".join(problems)
    return "pass", ""


def score(check: Mapping[str, Any], move: Move, *, message: str, seat: str = "") -> Measured:
    """Score one move against a task's ``check``. ``message`` is what the lead was given."""
    tokens = round(len(message) / _CHARS_PER_TOKEN)
    expect = Expect.from_json(check.get("expect") or {})
    status, detail = verdict(expect, move)
    if status == "error":
        return Measured(0.0, tokens, detail[:200], seat=seat, void="could not run", calls=1)
    if status != "pass":
        return Measured(0.0, tokens, f"{status}: {detail}"[:200], seat=seat, calls=1)
    if check.get("opening") and move.tool is not None and not move.opening.strip():
        return Measured(NO_OPENING, tokens, "no line before the tool call", seat=seat, calls=1)
    return Measured(1.0, tokens, seat=seat, calls=1)
