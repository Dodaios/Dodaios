"""Catalog drift checks and the synthetic reference recording."""
from __future__ import annotations

from typing import Any

from .cases import NO_TOOL, Case
from .catalog import LeadCatalog
from .scoring import Recording, missing_requirements

#: ``action`` values that only read. Used to check a case's ``effect: read``.
READ_VERBS: frozenset[str] = frozenset(
    {
        "list", "list_messages", "get_message", "list_events", "list_files", "get_file",
        "read_file", "search", "search_messages", "read_history", "read_thread", "get_state",
        "list_entities", "now_playing", "status", "observe", "inspect", "resolve", "context",
    }
)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def catalog_problems(cases: list[Case], catalog: LeadCatalog) -> list[str]:
    """Where the golden set and the real lead catalog disagree.

    A case whose ``requires`` tools are missing is skipped here too: it waits for
    its tool. Every other case must name tools, argument keys and enum values that
    exist, so a renamed or removed tool turns this red instead of the eval going
    quietly stale.
    """
    problems: list[str] = []
    for case in cases:
        if missing_requirements(case, catalog):
            continue
        expect = case.expect
        if not expect.expects_tool:
            continue
        for tool in expect.tools:
            if not catalog.has(tool):
                problems.append(f"{case.id}: expected tool {tool!r} is not in the lead catalog")
                continue
            if expect.approval and catalog.risk_tier(tool) != "ask":
                problems.append(
                    f"{case.id}: marked approval but {tool!r} is tier {catalog.risk_tier(tool)!r}"
                )
            problems.extend(_arg_problems(case, tool, catalog))
    return problems


def _arg_problems(case: Case, tool: str, catalog: LeadCatalog) -> list[str]:
    expect = case.expect
    schema = getattr(catalog.tools.get(tool), "schema", None)
    props = (schema or {}).get("properties") if isinstance(schema, dict) else None
    out: list[str] = []
    for key, want in expect.args.items():
        if key == "*":
            continue
        if isinstance(props, dict) and key not in props:
            # Several accepted tools share one args block; only a miss on all is drift.
            if not any(_has_key(catalog, other, key) for other in expect.tools):
                out.append(f"{case.id}: {tool!r} has no argument {key!r}")
            continue
        spec = props.get(key) if isinstance(props, dict) else None
        enum = spec.get("enum") if isinstance(spec, dict) else None
        if enum:
            for item in _as_list(want):
                if isinstance(item, str) and item not in enum:
                    out.append(f"{case.id}: {tool!r} argument {key!r} has no value {item!r}")
        if key == "action" and expect.effect == "read":
            for item in _as_list(want):
                if item not in READ_VERBS:
                    out.append(f"{case.id}: effect read but action {item!r} is not a read verb")
        if key == "action" and expect.effect == "action":
            for item in _as_list(want):
                if item in READ_VERBS:
                    out.append(f"{case.id}: effect action but action {item!r} only reads")
    if expect.effect == "read" and "action" not in expect.args and catalog.risk_tier(tool) == "ask":
        out.append(f"{case.id}: effect read but {tool!r} is an ask-tier tool")
    return out


def _has_key(catalog: LeadCatalog, tool: str, key: str) -> bool:
    schema = getattr(catalog.tools.get(tool), "schema", None)
    props = schema.get("properties") if isinstance(schema, dict) else None
    return not isinstance(props, dict) or key in props


def reference_recording(case: Case) -> Recording:
    """The synthetic "perfect" first move for a case, derived from its expectation.

    It is not a model output. It exists so CI can prove the scoring and catalog
    plumbing end to end without calling any model; a real seat's recording
    (``--save-recording`` of a live run) replays the same way.
    """
    expect = case.expect
    if not expect.expects_tool:
        return Recording(tool=None, text="(answers directly)")
    args: dict[str, Any] = {}
    for key, want in expect.args.items():
        value = _as_list(want)[0]
        if key == "*":
            args["task"] = value
        else:
            args[key] = value
    return Recording(tool=expect.tools[0], input=args)


def reference_payload(cases: list[Case]) -> dict[str, Any]:
    return {
        "seat": "reference",
        "kind": "synthetic: derived from the expectations, not a model output",
        "responses": {c.id: reference_recording(c).to_json() for c in cases},
    }


__all__ = ["NO_TOOL", "READ_VERBS", "catalog_problems", "reference_payload", "reference_recording"]
