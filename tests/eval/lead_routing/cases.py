"""The golden set: schema, loading and static validation."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "lead_routing"

#: The expected "first move" for a request that must not spawn or call anything.
NO_TOOL = "none"

CATEGORIES: tuple[str, ...] = (
    "delegate_agent",
    "ask_agent",
    "coding_pane",
    "team_thread",
    "mission_artifact",
    "status",
    "memory",
    "settings",
    "mail_calendar",
    "web_browser",
    "computer_use",
    "routines",
    "costs_ui",
    "answer_directly",
    "approval",
    "ambiguous",
)
LANGS: frozenset[str] = frozenset({"en", "de", "es", "pt"})
_CASE_KEYS = frozenset({"id", "category", "lang", "utterance", "expect", "requires", "note"})
_EXPECT_KEYS = frozenset({"tool", "tools", "also_accept", "args", "approval", "effect"})


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


@dataclass(frozen=True, slots=True)
class Case:
    id: str
    category: str
    lang: str
    utterance: str
    expect: Expect
    requires: tuple[str, ...] = ()  # tools that must exist in the lead catalog, else skipped
    note: str = ""


def _names(raw: Any, where: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, list) and all(isinstance(x, str) and x for x in raw):
        return tuple(raw)
    raise ValueError(f"{where}: expected a tool name or a list of tool names, got {raw!r}")


def _parse_expect(raw: Any, where: str) -> Expect:
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: 'expect' must be a mapping")
    unknown = set(raw) - _EXPECT_KEYS
    if unknown:
        raise ValueError(f"{where}: unknown expect keys {sorted(unknown)}")
    tools = _names(raw.get("tool"), where) + _names(raw.get("tools"), where)
    if not tools:
        raise ValueError(f"{where}: expect needs 'tool' (a name, or 'none')")
    if NO_TOOL in tools and len(tools) > 1:
        raise ValueError(f"{where}: 'none' cannot be mixed with tool names")
    args = raw.get("args") or {}
    if not isinstance(args, dict):
        raise ValueError(f"{where}: 'args' must be a mapping")
    if args and tools == (NO_TOOL,):
        raise ValueError(f"{where}: a no-tool case cannot expect arguments")
    effect = str(raw.get("effect") or "")
    if effect not in ("", "read", "action"):
        raise ValueError(f"{where}: effect must be 'read' or 'action'")
    return Expect(
        tools=tools,
        also_accept=_names(raw.get("also_accept"), where),
        args=dict(args),
        approval=bool(raw.get("approval", False)),
        effect=effect,
    )


def parse_case(raw: Any, source: str) -> Case:
    if not isinstance(raw, dict):
        raise ValueError(f"{source}: every case must be a mapping")
    where = f"{source}:{raw.get('id', '?')}"
    unknown = set(raw) - _CASE_KEYS
    if unknown:
        raise ValueError(f"{where}: unknown keys {sorted(unknown)}")
    for key in ("id", "category", "lang", "utterance", "expect"):
        if not raw.get(key):
            raise ValueError(f"{where}: missing '{key}'")
    return Case(
        id=str(raw["id"]),
        category=str(raw["category"]),
        lang=str(raw["lang"]),
        utterance=str(raw["utterance"]),
        expect=_parse_expect(raw["expect"], where),
        requires=_names(raw.get("requires"), where),
        note=str(raw.get("note") or ""),
    )


def load_cases(directory: Path | None = None) -> list[Case]:
    """Every case of every ``*.yaml`` file in *directory*, in file then document order."""
    root = directory or FIXTURE_DIR
    cases: list[Case] = []
    for path in sorted(root.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        if not isinstance(data, list):
            raise ValueError(f"{path.name}: expected a list of cases")
        cases.extend(parse_case(item, path.name) for item in data)
    return cases


def validate_cases(cases: list[Case]) -> list[str]:
    """Structural problems of the set itself (no catalog needed). Empty = fine."""
    problems: list[str] = []
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            problems.append(f"{case.id}: duplicate id")
        seen.add(case.id)
        if case.category not in CATEGORIES:
            problems.append(f"{case.id}: unknown category {case.category!r}")
        if case.lang not in LANGS:
            problems.append(f"{case.id}: unknown lang {case.lang!r}")
        if case.expect.approval and not case.expect.expects_tool:
            problems.append(f"{case.id}: approval needs an expected tool")
    return problems
