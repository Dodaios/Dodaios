"""A model is shown the tools it needs; the rest stays reachable.

Reported from testing with local models: a 9B model never called the save
tool, a larger one only ever listed. Two causes met. The whole tool set was
sent to every turn, and when it did not fit a small window the largest schemas
were dropped first — the richly described save tool before the parameterless
list tool — and a dropped tool was gone for the turn.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest

from dodaios.brain.manager import (
    _SMALL_MODEL_DIRECT_TOOLS,
    BrainManager,
)
from dodaios.brain.tool_shortlist import (
    CORE_PRIORITY,
    FIND_TOOLS_NAME,
    FindToolsTool,
    canonical,
    plan_surface,
    tool_tokens,
)
from dodaios.brain.tool_use_loop import ToolUseLoop
from dodaios.core.protocols import BrainDelta, BrainRequest, ExecutionContext, ToolResult


@dataclass
class _Tool:
    name: str
    description: str = "does a thing"
    schema: dict[str, Any] = field(default_factory=dict)
    risk_tier: str = "safe"
    is_mcp_tool: bool = False

    async def execute(self, args: dict[str, Any], ctx: Any) -> ToolResult:
        return ToolResult(success=True, output={"ran": self.name, "args": args})


def _tool(name: str, *, size: int = 1, mcp: bool = False, description: str = "") -> _Tool:
    props = {f"p{i}": {"type": "string", "description": "x" * 40} for i in range(size)}
    return _Tool(
        name=name,
        description=description or f"{name} tool",
        schema={"type": "object", "properties": props},
        is_mcp_tool=mcp,
    )


class _Brain:
    name = "fake"

    def __init__(self, window: int) -> None:
        self.context_window = window


def _ctx() -> ExecutionContext:
    return ExecutionContext(trace_id=uuid4(), user_utterance="", config={}, memory_read=None)


# ── Choosing what is shown ───────────────────────────────────────────────


def test_the_save_tool_outlives_a_larger_budget_squeeze_than_the_list_tool_did() -> None:
    """The reported shape: a described save tool, a parameterless list tool,
    and a budget that holds only some of the surface. Largest-first dropped
    the save tool. Priority keeps both and lets the unranked extras go."""
    tools = {
        "wiki-list": _tool("wiki-list", size=0),
        "extra_a": _tool("extra_a", size=6),
        "extra_b": _tool("extra_b", size=6),
        "wiki-ingest": _tool("wiki-ingest", size=4),
    }
    budget = tool_tokens("wiki-list", tools["wiki-list"]) + tool_tokens(
        "wiki-ingest", tools["wiki-ingest"]
    )
    plan = plan_surface(tools, budget_tokens=budget)
    assert set(plan.direct) == {"wiki-ingest", "wiki-list"}
    assert set(plan.deferred) == {"extra_a", "extra_b"}


def test_priority_matches_hyphen_and_underscore_spellings() -> None:
    assert canonical("wiki-ingest") == canonical("wiki_ingest") == "wiki_ingest"
    tools = {"zzz": _tool("zzz"), "search_web": _tool("search_web"), "wiki-recall": _tool("x")}
    plan = plan_surface(tools, max_direct=2)
    assert list(plan.direct) == ["search_web", "wiki-recall"]


def test_a_count_limit_shows_the_everyday_tools_first() -> None:
    tools = {f"other{i}": _tool(f"other{i}") for i in range(30)}
    for name in ("search_web", "wiki-ingest", "run-skill"):
        tools[name] = _tool(name)
    plan = plan_surface(tools, max_direct=5)
    assert {"search_web", "wiki-ingest", "run-skill"} <= set(plan.direct)
    assert len(plan.direct) == 5


def test_connected_server_tools_wait_behind_the_apps_own() -> None:
    tools = {
        "github/create_issue": _tool("github/create_issue", mcp=True),
        "own_a": _tool("own_a"),
        "own_b": _tool("own_b"),
    }
    plan = plan_surface(tools, max_direct=2)
    assert set(plan.direct) == {"own_a", "own_b"}


def test_pinned_tools_are_shown_whatever_the_budget() -> None:
    tools = {"mandated": _tool("mandated", size=40), "other": _tool("other")}
    plan = plan_surface(tools, keep={"mandated"}, budget_tokens=0)
    assert list(plan.direct) == ["mandated"]
    assert list(plan.deferred) == ["other"]


def test_one_oversized_tool_does_not_starve_the_ones_behind_it() -> None:
    tools = {"huge": _tool("huge", size=60), "small": _tool("small")}
    plan = plan_surface(tools, budget_tokens=tool_tokens("small", tools["small"]))
    assert list(plan.direct) == ["small"]


def test_a_role_shows_only_its_tools_and_what_is_pinned() -> None:
    tools = {name: _tool(name) for name in ("gmail", "slack", "run_shell", "own_note")}
    plan = plan_surface(tools, keep={"own_note"}, only={"gmail"})
    assert set(plan.direct) == {"own_note", "gmail"}
    assert set(plan.deferred) == {"slack", "run_shell"}


def test_everything_fits_means_nothing_is_deferred() -> None:
    tools = {"a": _tool("a"), "b": _tool("b")}
    plan = plan_surface(tools, budget_tokens=1_000_000)
    assert plan.deferred == {}
    assert list(plan.direct) == ["a", "b"]


def test_the_core_list_has_no_duplicates() -> None:
    assert len(set(CORE_PRIORITY)) == len(CORE_PRIORITY)
    assert all(name == canonical(name) for name in CORE_PRIORITY)


# ── Reaching the rest ────────────────────────────────────────────────────


async def test_find_tools_names_what_was_asked_and_reveals_it() -> None:
    deferred = {
        "calendar_create": _tool("calendar_create", description="Create a calendar event"),
        "mail_send": _tool("mail_send", description="Send an email message"),
    }
    revealed: list[str] = []
    finder = FindToolsTool(deferred, reveal=revealed.extend)
    result = await finder.execute({"query": "I want to send an email"}, _ctx())
    names = [entry["name"] for entry in result.output["tools"]]
    assert names == ["mail_send"]
    # The definition arrives as a real tool next round; repeating the schema
    # here would pay for it twice in a window that is already full.
    assert "input_schema" not in result.output["tools"][0]
    assert revealed == ["mail_send"]


async def test_a_tool_found_twice_is_revealed_once() -> None:
    revealed: list[str] = []
    finder = FindToolsTool({"mail_send": _tool("mail_send")}, reveal=revealed.extend)
    await finder.execute({"query": "mail_send"}, _ctx())
    await finder.execute({"query": "mail_send"}, _ctx())
    assert revealed == ["mail_send"]


async def test_a_full_window_bounds_what_one_turn_reveals() -> None:
    """Shown tools already fill the window. What a lookup adds must fit the
    room that was held back for it; a match beyond that is still named, with
    its arguments, so it can be called."""
    deferred = {
        "mail_send": _tool("mail_send", size=1, description="send mail"),
        "mail_search": _tool("mail_search", size=30, description="search mail"),
    }
    revealed: list[str] = []
    room = tool_tokens("mail_send", deferred["mail_send"])
    finder = FindToolsTool(deferred, reveal=revealed.extend, reveal_tokens=room)
    result = await finder.execute({"query": "mail"}, _ctx())
    assert revealed == ["mail_send"]
    by_name = {entry["name"]: entry for entry in result.output["tools"]}
    assert set(by_name) == {"mail_send", "mail_search"}
    assert "arguments" not in by_name["mail_send"]
    assert by_name["mail_search"]["arguments"] == sorted(f"p{i}" for i in range(30))


async def test_find_tools_resolves_an_exact_name_in_either_spelling() -> None:
    finder = FindToolsTool({"wiki-ingest": _tool("wiki-ingest"), "other": _tool("other")})
    result = await finder.execute({"query": "wiki_ingest"}, _ctx())
    assert [entry["name"] for entry in result.output["tools"]] == ["wiki-ingest"]


async def test_find_tools_says_so_when_nothing_matches() -> None:
    finder = FindToolsTool({"mail_send": _tool("mail_send")})
    result = await finder.execute({"query": "teleport"}, _ctx())
    assert result.success is True
    assert result.output["tools"] == []
    assert result.output["available"] == ["mail_send"]


def test_find_tools_names_what_it_holds_and_never_anything_else() -> None:
    finder = FindToolsTool({"b_tool": _tool("b_tool"), "a_tool": _tool("a_tool")})
    assert "a_tool, b_tool" in finder.description
    assert finder.risk_tier == "safe"
    assert finder.read_only_for_args({}) is True


def test_a_long_tail_of_names_is_summarised_not_dumped() -> None:
    finder = FindToolsTool({f"tool_number_{i:03d}": _tool("t") for i in range(300)})
    assert "more" in finder.description
    assert len(finder.description) < 2_400


# ── The loop ─────────────────────────────────────────────────────────────


class _RunningExecutor:
    """Runs the tool for real, as ``ToolExecutor.execute`` would."""

    def __init__(self) -> None:
        self.ran: list[str] = []

    async def execute(self, tool: Any, args: dict[str, Any], **_: Any) -> ToolResult:
        self.ran.append(tool.name)
        return await tool.execute(args, _ctx())


class _ScriptedBrain:
    """Answers each round with the next scripted tool call, then with text."""

    def __init__(self, calls: list[tuple[str, dict[str, Any]]]) -> None:
        self._calls = list(calls)
        self.requests: list[BrainRequest] = []

    async def complete(self, req: BrainRequest) -> AsyncIterator[BrainDelta]:
        self.requests.append(req)
        index = len(self.requests) - 1
        if index < len(self._calls):
            name, args = self._calls[index]
            yield BrainDelta(tool_call={"id": f"c{index}", "name": name, "input": args})
            yield BrainDelta(finish_reason="tool_use")
            return
        yield BrainDelta(content="done")
        yield BrainDelta(finish_reason="stop")

    def shown(self, round_index: int) -> list[str]:
        return [spec["name"] for spec in self.requests[round_index].tools]


def _surface() -> tuple[dict[str, Any], frozenset[str]]:
    deferred = {"mail_send": _tool("mail_send", description="Send an email message")}
    tools: dict[str, Any] = {"search_web": _tool("search_web")}
    tools[FIND_TOOLS_NAME] = FindToolsTool(deferred)
    tools.update(deferred)
    return tools, frozenset(deferred)


@pytest.mark.asyncio
async def test_a_deferred_tool_is_not_shown_until_it_was_found() -> None:
    tools, deferred = _surface()
    brain = _ScriptedBrain(
        [(FIND_TOOLS_NAME, {"query": "send email"}), ("mail_send", {"to": "anna"})]
    )
    executor = _RunningExecutor()
    loop = ToolUseLoop(brain, tools, executor, deferred_tools=deferred)  # type: ignore[arg-type]
    result = await loop.run([], user_utterance="send anna the notes by email")
    assert brain.shown(0) == ["search_web", FIND_TOOLS_NAME]
    # Found in round one, so its schema rides every round after that.
    assert "mail_send" in brain.shown(1)
    assert executor.ran == [FIND_TOOLS_NAME, "mail_send"]
    assert "done" in result.text


@pytest.mark.asyncio
async def test_a_lookup_is_not_recorded_as_something_that_was_done() -> None:
    """The honesty guards read the record of tools that ran. A turn that only
    searched for the mail tool must not be able to say the mail was sent."""
    tools, deferred = _surface()
    brain = _ScriptedBrain([(FIND_TOOLS_NAME, {"query": "send email"})])
    executor = _RunningExecutor()
    loop = ToolUseLoop(brain, tools, executor, deferred_tools=deferred)  # type: ignore[arg-type]
    result = await loop.run([], user_utterance="send anna the notes by email")
    assert executor.ran == [FIND_TOOLS_NAME]
    assert result.executed_tool_names == set()


def test_the_dispatcher_payload_leaves_deferred_tools_out() -> None:
    from dodaios.brain.dispatcher import BrainDispatcher

    tools, deferred = _surface()
    dispatcher = BrainDispatcher(_Brain(32_768), tools=tools, deferred_tools=deferred)  # type: ignore[arg-type]
    assert [spec["name"] for spec in dispatcher.tools_payload()] == [
        "search_web",
        FIND_TOOLS_NAME,
    ]


@pytest.mark.asyncio
async def test_a_deferred_tool_named_outright_simply_runs() -> None:
    """Deferred means not shown, never not allowed."""
    tools, deferred = _surface()
    brain = _ScriptedBrain([("mail_send", {"to": "anna"})])
    executor = _RunningExecutor()
    loop = ToolUseLoop(brain, tools, executor, deferred_tools=deferred)  # type: ignore[arg-type]
    await loop.run([], user_utterance="send anna the notes by email")
    assert executor.ran == ["mail_send"]


@pytest.mark.asyncio
async def test_without_deferred_tools_the_loop_is_unchanged() -> None:
    tools = {"search_web": _tool("search_web"), "mail_send": _tool("mail_send")}
    brain = _ScriptedBrain([])
    loop = ToolUseLoop(brain, tools, _RunningExecutor())  # type: ignore[arg-type]
    await loop.run([], user_utterance="hello")
    assert brain.shown(0) == ["search_web", "mail_send"]


# ── The manager's decision ───────────────────────────────────────────────


def _mgr() -> BrainManager:
    m = BrainManager.__new__(BrainManager)  # bypass heavy __init__
    m._tools = {}
    m._evidence_required_tool = None
    m._skill_turn_match = None
    return m


def _shown(surface: dict[str, Any], deferred: frozenset[str]) -> list[str]:
    return [name for name in surface if name not in deferred]


def test_a_hosted_model_with_room_is_handed_the_same_dict() -> None:
    tools = {f"t{i}": _tool(f"t{i}", size=10) for i in range(221)}
    surface, deferred = _mgr()._shortlist_tools(
        tools, _Brain(1_048_576), system_prompt="x" * 40_000, history=None
    )
    assert surface is tools
    assert deferred == frozenset()


def test_a_small_model_is_shown_a_short_list_even_when_more_would_fit() -> None:
    """Choosing well from 80 tools is the hard part for a small model, not
    fitting them into the window."""
    tools = {f"other{i}": _tool(f"other{i}", size=0) for i in range(80)}
    tools["wiki-ingest"] = _tool("wiki-ingest", size=4)
    tools["wiki-list"] = _tool("wiki-list", size=0)
    surface, deferred = _mgr()._shortlist_tools(
        tools, _Brain(32_768), system_prompt="", history=None
    )
    shown = _shown(surface, deferred)
    assert len(shown) == _SMALL_MODEL_DIRECT_TOOLS + 1  # plus find_tools
    assert {"wiki-ingest", "wiki-list", FIND_TOOLS_NAME} <= set(shown)
    # Nothing was lost: every tool is still in the dict the loop executes from.
    assert set(tools) <= set(surface)


def test_what_the_turn_pinned_is_shown_on_top_of_the_short_list() -> None:
    m = _mgr()
    m._evidence_required_tool = "other79"
    tools = {f"other{i}": _tool(f"other{i}", size=0) for i in range(80)}
    surface, deferred = m._shortlist_tools(
        tools, _Brain(16_384), system_prompt="", history=None, own_tools=("other78",)
    )
    shown = _shown(surface, deferred)
    assert {"other78", "other79"} <= set(shown)


def test_an_agent_with_a_role_is_shown_its_tools_on_any_provider() -> None:
    tools = {name: _tool(name) for name in ("gmail", "slack", "run_shell", "search_web")}
    tools["society_note"] = _tool("society_note")
    surface, deferred = _mgr()._shortlist_tools(
        tools,
        _Brain(1_048_576),
        system_prompt="",
        history=None,
        own_tools=("society_note",),
        direct_tools=frozenset({"gmail"}),
    )
    shown = _shown(surface, deferred)
    # Its own hands, what its role names, and the reads every job starts with.
    assert set(shown) == {"society_note", "gmail", "search_web", FIND_TOOLS_NAME}
    assert deferred == frozenset({"slack", "run_shell"})


def test_an_agent_whose_role_covers_everything_gets_no_find_tool() -> None:
    tools = {"gmail": _tool("gmail"), "society_note": _tool("society_note")}
    surface, deferred = _mgr()._shortlist_tools(
        tools,
        _Brain(1_048_576),
        system_prompt="",
        history=None,
        own_tools=("society_note",),
        direct_tools=frozenset({"gmail"}),
    )
    assert surface is tools and deferred == frozenset()


def test_a_providers_count_cap_defers_instead_of_dropping() -> None:
    class _Capped(_Brain):
        max_tools = 10

    tools = {f"t{i}": _tool(f"t{i}") for i in range(30)}
    surface, deferred = _mgr()._shortlist_tools(
        tools, _Capped(1_048_576), system_prompt="", history=None
    )
    shown = _shown(surface, deferred)
    # The cap counts what is sent, find_tools included.
    assert len(shown) == 10 and FIND_TOOLS_NAME in shown
    assert len(deferred) == 21


def test_a_full_window_holds_room_back_for_what_a_lookup_adds() -> None:
    """Filling the window to the brim with shown tools left no room for the
    finder or for a single revealed definition: the first lookup overflowed."""
    tools = {f"t{i}": _tool(f"t{i}", size=10) for i in range(221)}
    brain = _Brain(60_000)
    surface, deferred = _mgr()._shortlist_tools(
        tools, brain, system_prompt="x" * 60_000, history=None
    )
    finder = surface[FIND_TOOLS_NAME]
    shown_cost = sum(
        tool_tokens(name, tool)
        for name, tool in surface.items()
        if name not in deferred and name != FIND_TOOLS_NAME
    )
    budget = 60_000 - (60_000 // 3 + 1) - 4_096
    assert finder._reveal_tokens is not None and finder._reveal_tokens > 0
    assert shown_cost + finder._reveal_tokens + tool_tokens(FIND_TOOLS_NAME, finder) <= budget


def test_a_real_tool_called_find_tools_is_never_overwritten() -> None:
    tools = {f"t{i}": _tool(f"t{i}") for i in range(80)}
    tools[FIND_TOOLS_NAME] = _tool(FIND_TOOLS_NAME)
    surface, deferred = _mgr()._shortlist_tools(
        tools, _Brain(8_192), system_prompt="", history=None
    )
    assert surface is tools and deferred == frozenset()


def test_a_count_cap_of_one_still_caps() -> None:
    class _One(_Brain):
        max_tools = 1

    tools = {f"t{i}": _tool(f"t{i}") for i in range(5)}
    surface, deferred = _mgr()._shortlist_tools(
        tools, _One(1_048_576), system_prompt="", history=None
    )
    assert len(deferred) == 4
