"""Tool usage is counted from what the flight recorder already wrote."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from dodaios.telemetry.tool_usage import tool_usage

TODAY = date(2026, 10, 13)


def _write(directory: Path, name: str, rows: list[dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / name).open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _ran(tool: str, *, success: bool = True, ts_ns: int = 1_000_000_000) -> dict:
    return {
        "ts_ns": ts_ns,
        "trace_id": "t",
        "event": "ActionExecuted",
        "layer": "",
        "payload": {"tool_name": tool, "success": success, "duration_ms": 5},
    }


def test_counts_executions_per_tool_most_used_first(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "2026-10-13.jsonl",
        [_ran("search_web"), _ran("search_web", success=False), _ran("wiki-ingest")],
    )
    _write(tmp_path, "2026-10-12.jsonl", [_ran("search_web", ts_ns=9_000_000_000)])
    report = tool_usage(tmp_path, days=30, today=TODAY)
    assert report["total_calls"] == 4
    assert report["distinct_tools"] == 2
    top = report["tools"][0]
    assert top == {
        "tool": "search_web",
        "calls": 3,
        "succeeded": 2,
        "failed": 1,
        "days_used": 2,
        "last_used_ms": 9_000,
        "share": 0.75,
    }
    assert report["tools"][1]["tool"] == "wiki-ingest"


def test_only_executions_count_not_proposals_or_other_events(tmp_path: Path) -> None:
    proposed = {"event": "ActionProposed", "payload": {"tool_name": "gmail"}, "ts_ns": 1}
    mention = {
        "event": "ResponseGenerated",
        "payload": {"text": "ActionExecuted is an event name"},
        "ts_ns": 1,
    }
    _write(tmp_path, "2026-10-13.jsonl", [proposed, mention, _ran("gmail")])
    report = tool_usage(tmp_path, days=1, today=TODAY)
    assert [(t["tool"], t["calls"]) for t in report["tools"]] == [("gmail", 1)]


def test_the_window_is_taken_from_the_file_names(tmp_path: Path) -> None:
    _write(tmp_path, "2026-10-13.jsonl", [_ran("today")])
    _write(tmp_path, "2026-10-07.jsonl", [_ran("a_week_ago")])
    _write(tmp_path, "2026-08-01.jsonl", [_ran("long_ago")])
    # A rotated file of the same day belongs to that day.
    _write(tmp_path, "2026-10-13-2.jsonl", [_ran("today")])
    week = tool_usage(tmp_path, days=7, today=TODAY)
    assert {t["tool"]: t["calls"] for t in week["tools"]} == {"today": 2, "a_week_ago": 1}
    everything = tool_usage(tmp_path, days=0, today=TODAY)
    assert everything["distinct_tools"] == 3


def test_coverage_says_how_few_tools_carry_most_calls(tmp_path: Path) -> None:
    """The figure the report exists for: with one tool at 90 of 100 calls, a
    model that is shown that one tool is covered nine times in ten."""
    rows = [_ran("workhorse")] * 90 + [_ran(f"rare{i}") for i in range(10)]
    _write(tmp_path, "2026-10-13.jsonl", rows)
    report = tool_usage(tmp_path, days=1, today=TODAY)
    assert report["coverage"]["50"] == 1
    assert report["coverage"]["90"] == 1
    assert report["coverage"]["95"] == 6
    assert report["coverage"]["99"] == 10


def test_registered_tools_that_never_ran_are_named(tmp_path: Path) -> None:
    _write(tmp_path, "2026-10-13.jsonl", [_ran("search_web")])
    report = tool_usage(
        tmp_path, days=1, today=TODAY, registered=["search_web", "vercel", "slack"]
    )
    assert report["registered"] == 3
    assert report["never_used"] == ["slack", "vercel"]


def test_a_damaged_line_and_a_missing_directory_are_survived(tmp_path: Path) -> None:
    (tmp_path / "2026-10-13.jsonl").write_text(
        '{"event": "ActionExecuted", "payload": {"tool_name": "ok"}}\n'
        '{"event": "ActionExecuted", "payload": {"tool_na\n',
        encoding="utf-8",
    )
    assert tool_usage(tmp_path, days=1, today=TODAY)["total_calls"] == 1
    empty = tool_usage(tmp_path / "absent", days=30, today=TODAY)
    assert empty["total_calls"] == 0 and empty["tools"] == [] and empty["coverage"] == {}
