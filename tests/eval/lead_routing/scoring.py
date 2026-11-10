"""Deterministic scoring of recorded (or live) first moves against the golden set."""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .cases import NO_TOOL, Case
from .catalog import LeadCatalog


@dataclass(frozen=True, slots=True)
class Recording:
    """The first move a seat made: a tool call (``tool`` + ``input``) or none."""

    tool: str | None = None
    input: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    error: str = ""  # the call failed: a failure of the run, never "answered directly"

    @classmethod
    def from_json(cls, raw: Any) -> Recording:
        if not isinstance(raw, dict):
            return cls()
        tool = raw.get("tool")
        args = raw.get("input")
        return cls(
            tool=str(tool) if tool and tool != NO_TOOL else None,
            input=dict(args) if isinstance(args, dict) else {},
            text=str(raw.get("text") or ""),
            error=str(raw.get("error") or ""),
        )

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"tool": self.tool or NO_TOOL}
        if self.input:
            out["input"] = self.input
        if self.text:
            out["text"] = self.text
        if self.error:
            out["error"] = self.error
        return out


def load_recordings(path: Path) -> tuple[str, dict[str, Recording]]:
    """A recording file: ``{"seat": ..., "responses": {case_id: {tool, input, text}}}``."""
    data = json.loads(path.read_text(encoding="utf-8"))
    seat = str(data.get("seat") or path.stem) if isinstance(data, dict) else path.stem
    responses = data.get("responses", {}) if isinstance(data, dict) else {}
    return seat, {str(cid): Recording.from_json(raw) for cid, raw in responses.items()}


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    return " ".join(text.split())


def _matches(expected: Any, actual: Any) -> bool:
    """One expected value against one actual value.

    A list expects any of its entries. A string matches as a normalised substring
    (so ``T2`` matches ``terminal T2``). Other scalars match by equality.
    """
    if isinstance(expected, list):
        return any(_matches(item, actual) for item in expected)
    if isinstance(expected, (bool, int, float)):
        return bool(actual == expected)
    return actual is not None and _norm(expected) in _norm(actual)


def _flatten(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [text for item in value.values() for text in _flatten(item)]
    if isinstance(value, (list, tuple)):
        return [text for item in value for text in _flatten(item)]
    return [] if value is None else [str(value)]


def args_mismatches(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    """Why the arguments do not satisfy the expectation. The key ``*`` means "any argument"."""
    problems: list[str] = []
    for key, want in expected.items():
        if key == "*":
            if not any(_matches(want, value) for value in _flatten(actual)):
                problems.append(f"no argument mentions {want!r}")
        elif key not in actual or not _matches(want, actual[key]):
            problems.append(f"{key}: want {want!r}, got {actual.get(key)!r}")
    return problems


@dataclass(frozen=True, slots=True)
class CaseResult:
    case: Case
    status: str  # "pass" | "wrong_tool" | "wrong_args" | "error" | "skipped"
    detail: str = ""
    tool_ok: bool = False

    @property
    def passed(self) -> bool:
        return self.status == "pass"


def missing_requirements(case: Case, catalog: LeadCatalog) -> list[str]:
    return [name for name in case.requires if not catalog.has(name)]


def score_case(case: Case, recording: Recording | None, catalog: LeadCatalog) -> CaseResult:
    missing = missing_requirements(case, catalog)
    if missing:
        return CaseResult(case, "skipped", f"needs {', '.join(missing)}")
    if recording is None:
        return CaseResult(case, "wrong_tool", "no recorded response")
    if recording.error:
        return CaseResult(case, "error", recording.error)
    expect = case.expect
    if not expect.accepts(recording.tool):
        want = "no tool" if not expect.expects_tool else " or ".join(expect.tools)
        got = recording.tool or "no tool"
        return CaseResult(case, "wrong_tool", f"want {want}, got {got}")
    if not expect.expects_tool:
        return CaseResult(case, "pass", tool_ok=True)
    problems = args_mismatches(expect.args, recording.input)
    if problems:
        return CaseResult(case, "wrong_args", "; ".join(problems), tool_ok=True)
    return CaseResult(case, "pass", tool_ok=True)


@dataclass(slots=True)
class Report:
    seat: str
    results: list[CaseResult]

    def _rows(self, category: str | None = None) -> list[CaseResult]:
        return [
            r
            for r in self.results
            if r.status != "skipped" and (category is None or r.case.category == category)
        ]

    @staticmethod
    def _rate(rows: list[CaseResult], pick: Any) -> float | None:
        return sum(1 for r in rows if pick(r)) / len(rows) if rows else None

    def summary(self) -> dict[str, Any]:
        categories: dict[str, dict[str, Any]] = {}
        for category in sorted({r.case.category for r in self.results}):
            rows = self._rows(category)
            categories[category] = {
                "cases": len(rows),
                "passed": sum(1 for r in rows if r.passed),
                "accuracy": self._rate(rows, lambda r: r.passed),
                "tool_accuracy": self._rate(rows, lambda r: r.tool_ok),
            }
        rows = self._rows()
        return {
            "seat": self.seat,
            "cases": len(rows),
            "skipped": sum(1 for r in self.results if r.status == "skipped"),
            "passed": sum(1 for r in rows if r.passed),
            "accuracy": self._rate(rows, lambda r: r.passed),
            "tool_accuracy": self._rate(rows, lambda r: r.tool_ok),
            "categories": categories,
        }

    def failures(self) -> list[CaseResult]:
        return [r for r in self.results if r.status in ("wrong_tool", "wrong_args")]

    def to_json(self) -> dict[str, Any]:
        return {
            **self.summary(),
            "results": [
                {
                    "id": r.case.id,
                    "category": r.case.category,
                    "status": r.status,
                    "detail": r.detail,
                }
                for r in self.results
            ],
        }


def score_cases(
    cases: list[Case],
    recordings: dict[str, Recording],
    catalog: LeadCatalog,
    seat: str = "recorded",
) -> Report:
    return Report(seat, [score_case(c, recordings.get(c.id), catalog) for c in cases])


def format_table(reports: list[Report]) -> str:
    """Accuracy per category (rows) and seat (columns), as plain text."""
    summaries = [r.summary() for r in reports]
    categories = sorted({c for s in summaries for c in s["categories"]})

    def cell(summary: dict[str, Any], category: str | None) -> str:
        block = summary if category is None else summary["categories"].get(category)
        if not block or not block["cases"]:
            return "-"
        return f"{block['passed']}/{block['cases']} {block['accuracy']:.0%}"

    seats = [s["seat"] for s in summaries]
    width = max([len("category"), *(len(c) for c in categories), len("ALL")])
    col = max([14, *(len(s) for s in seats)])
    lines = ["category".ljust(width) + "  " + "  ".join(s.ljust(col) for s in seats)]
    lines.append("-" * len(lines[0]))
    for category in categories:
        cells = "  ".join(cell(s, category).ljust(col) for s in summaries)
        lines.append(category.ljust(width) + "  " + cells)
    lines.append("-" * len(lines[0]))
    lines.append("ALL".ljust(width) + "  " + "  ".join(cell(s, None).ljust(col) for s in summaries))
    return "\n".join(lines)
