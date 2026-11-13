"""The context ring's numbers: live from the stream, from the record, and /context."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dodaios.agent_chat import context_window
from dodaios.agent_chat.runner_cli import _ClaudeState, translate_claude_line

# Claude Code 2.1.325's own `/context` report (headless, `--output-format json`).
REPORT = """## Context Usage

**Model:** claude-opus-5-5
**Tokens:** 139.4k / 1m (14%)

### Estimated usage by category

| Category | Tokens | Percentage |
|----------|--------|------------|
| System prompt | 2.8k | 0.3% |
| System tools | 2.5k | 0.3% |
| System tools (deferred) | 14.7k | 1.5% |
| Memory files | 3.1k | 0.3% |
| Skills | 8.3k | 0.8% |
| Messages | 122.7k | 12.3% |
| Free space | 827.6k | 82.8% |
| Autocompact buffer | 33k | 3.3% |

### Skills

| Skill | Source | Tokens |
|-------|--------|--------|
| dataviz | Built-in | ~480 |
"""


@pytest.fixture(autouse=True)
def _fresh_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(context_window, "_WINDOWS", {})
    monkeypatch.setattr(context_window, "_probe_cache", {})


def test_sizes_read_like_the_cli_writes_them() -> None:
    assert context_window.parse_size("14.9k") == 14_900
    assert context_window.parse_size("1m") == 1_000_000
    assert context_window.parse_size("10") == 10
    assert context_window.parse_size("~480") == 480
    assert context_window.parse_size("n/a") is None


def test_the_report_gives_totals_and_only_the_category_table() -> None:
    breakdown = context_window.parse_breakdown(REPORT)
    assert breakdown is not None
    assert (breakdown.model, breakdown.used, breakdown.window) == ("claude-opus-5-5", 139_400, 1_000_000)
    keys = [part["key"] for part in breakdown.categories]
    assert keys == [
        "system_prompt",
        "system_tools",
        "deferred_tools",
        "memory",
        "skills",
        "messages",
        "free",
        "autocompact",
    ]
    assert breakdown.categories[5]["tokens"] == 122_700
    # The window is learned for the model the report names.
    assert context_window.known_window("claude-opus-5-5") == 1_000_000


def test_a_report_without_numbers_is_no_breakdown() -> None:
    assert context_window.parse_breakdown("Unknown command: /context") is None


def _assistant(model: str, usage: dict, *, sidechain: bool = False) -> dict:
    return {
        "type": "assistant",
        "isSidechain": sidechain,
        "message": {"model": model, "usage": usage, "content": []},
    }


def _write(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def test_the_record_reads_the_main_agents_last_message(tmp_path: Path) -> None:
    usage = {
        "input_tokens": 2,
        "cache_read_input_tokens": 100_000,
        "cache_creation_input_tokens": 5_000,
        "output_tokens": 300,
    }
    path = _write(
        tmp_path / "s.jsonl",
        [
            _assistant("claude-opus-5-5", usage),
            # A sub-agent's message and the CLI's own notice come later; neither counts.
            _assistant("claude-haiku-5-5", {"input_tokens": 9_999}, sidechain=True),
            _assistant("<synthetic>", {"input_tokens": 0, "output_tokens": 0}),
            {"type": "user", "message": {"content": "next"}},
        ],
    )
    context_window.learn_window("claude-opus-5-5", 1_000_000)
    assert context_window.read_recorded(path) == {
        "used": 105_302,
        "window": 1_000_000,
        "model": "claude-opus-5-5",
    }


def test_a_compaction_after_the_last_message_makes_the_record_say_nothing(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "s.jsonl",
        [
            _assistant("claude-opus-5-5", {"input_tokens": 900_000}),
            {"type": "system", "subtype": "compact_boundary"},
        ],
    )
    assert context_window.read_recorded(path) is None


def test_the_session_file_is_found_under_the_seat_that_holds_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seat = tmp_path / "seat"
    (seat / "projects" / "-work").mkdir(parents=True)
    record = seat / "projects" / "-work" / "abc.jsonl"
    record.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        context_window, "_claude_homes", lambda account: [(tmp_path / "none", None), (seat, "s2")]
    )
    assert context_window.find_session_file("abc") == (record, "s2")
    assert context_window.find_session_file("missing") is None
    assert context_window.find_session_file("../abc") is None


def _assistant_line(mid: str, usage: dict, model: str = "claude-opus-5-5") -> dict:
    return {
        "type": "assistant",
        "message": {"id": mid, "model": model, "usage": usage, "content": []},
    }


def test_the_stream_sends_the_newest_message_as_the_context() -> None:
    st = _ClaudeState(turn_id="t1")
    first = translate_claude_line(_assistant_line("m1", {"input_tokens": 40_000, "output_tokens": 10}), st)
    delta = [ev for ev in first if ev["kind"] == "usage_delta"][0]
    assert delta["payload"]["context"] == {"used": 40_010, "window": None, "model": "claude-opus-5-5"}

    # The next message read the whole conversation again: the context is ITS
    # count, not the turn's sum.
    second = translate_claude_line(
        _assistant_line("m2", {"cache_read_input_tokens": 40_010, "input_tokens": 500}), st
    )
    delta = [ev for ev in second if ev["kind"] == "usage_delta"][0]
    assert delta["payload"]["usage"]["input_tokens"] == 40_500
    assert delta["payload"]["context"]["used"] == 40_510


def test_the_result_stores_the_reading_with_the_window_it_names() -> None:
    st = _ClaudeState(turn_id="t1")
    translate_claude_line(_assistant_line("m1", {"input_tokens": 50_000, "output_tokens": 20}), st)
    result = {
        "type": "result",
        "subtype": "success",
        "result": "ok",
        "usage": {"input_tokens": 50_000, "output_tokens": 20},
        "modelUsage": {
            "claude-haiku-5-5": {"contextWindow": 200_000},
            "claude-opus-5-5": {"contextWindow": 1_000_000},
        },
    }
    events = translate_claude_line(result, st)
    stored = [ev for ev in events if ev["kind"] == "context_usage"]
    assert stored and stored[0]["payload"] == {
        "turn_id": "t1",
        "used": 50_020,
        "window": 1_000_000,
        "model": "claude-opus-5-5",
    }
    # Learned: the next turn's live readings carry the window from the start.
    assert context_window.known_window("claude-opus-5-5") == 1_000_000


def test_a_sub_agents_messages_never_move_the_ring() -> None:
    st = _ClaudeState(turn_id="t1")
    translate_claude_line(_assistant_line("m1", {"input_tokens": 1_000}), st)
    line = _assistant_line("s1", {"input_tokens": 90_000}, model="claude-haiku-5-5")
    line["parent_tool_use_id"] = "call-1"
    translate_claude_line(line, st)
    assert st.context_used == 1_000
    assert st.context_model == "claude-opus-5-5"


def test_a_turn_without_a_model_answer_stores_nothing() -> None:
    st = _ClaudeState(turn_id="t1")
    events = translate_claude_line({"type": "result", "subtype": "success", "result": ""}, st)
    assert not [ev for ev in events if ev["kind"] == "context_usage"]
