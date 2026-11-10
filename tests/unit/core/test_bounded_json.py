"""Structural bounding keeps tool results valid JSON inside the receiver's limit."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from dodaios.core.bounded_json import bound_json, bound_text
from dodaios.core.page_cursor import decode_cursor, encode_cursor
from dodaios.mcp.dodaios_tools_server import _render, mcp_max_output_chars


def _big_list(count: int, size: int) -> dict:
    return {"rows": [{"id": i, "text": "x" * size} for i in range(count)], "total": count}


def test_within_the_budget_nothing_changes():
    value = {"a": [1, 2, 3], "b": "text"}
    assert bound_json(value, 1000) == json.dumps(value, ensure_ascii=False)


@pytest.mark.parametrize(
    "value",
    [
        _big_list(2000, 300),  # a long list
        {"blob": "y" * 500_000},  # one huge string
        {"nested": {"deep": [_big_list(50, 5000) for _ in range(20)]}},
        [{"k": "v" * 1000} for _ in range(5000)],  # a bare top-level list
    ],
)
def test_oversized_results_stay_valid_json_within_the_budget(value):
    text = bound_json(value, 20_000, separators=(",", ":"))
    assert len(text) <= 20_000
    parsed = json.loads(text)
    assert parsed["truncated"] is True
    assert parsed["truncation"]["hint"]


def test_a_list_keeps_as_many_items_as_fit_and_says_how_many_were_left_out():
    parsed = json.loads(bound_json(_big_list(1000, 100), 30_000))
    kept = len(parsed["rows"])
    assert 20 <= kept < 1000
    assert parsed["truncation"]["omitted_items"] == 1000 - kept
    assert parsed["total"] == 1000  # the fields around the list survive


def test_a_hopeless_budget_still_returns_valid_json():
    text = bound_json({f"k{i}": "v" * 100 for i in range(500)}, 600)
    assert len(text) <= 600
    assert json.loads(text)["truncated"] is True


def test_bound_text_marks_the_cut_and_respects_the_limit():
    text = bound_text("a" * 10_000, 500)
    assert len(text) <= 500 and "truncated" in text
    assert bound_text("short", 500) == "short"


def test_cursor_round_trips_and_rejects_garbage():
    assert decode_cursor(encode_cursor(1700, "abc")) == (1700, "abc")
    with pytest.raises(ValueError):
        decode_cursor("not-a-cursor")


def test_mcp_limit_is_the_receivers_token_limit_and_configurable(monkeypatch):
    monkeypatch.delenv("DODAIOS_MCP_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.delenv("MAX_MCP_OUTPUT_TOKENS", raising=False)
    assert mcp_max_output_chars() == 25_000 * 3
    monkeypatch.setenv("MAX_MCP_OUTPUT_TOKENS", "50000")
    assert mcp_max_output_chars() == 150_000
    monkeypatch.setenv("DODAIOS_MCP_MAX_OUTPUT_TOKENS", "10000")
    assert mcp_max_output_chars() == 30_000
    monkeypatch.setenv("DODAIOS_MCP_MAX_OUTPUT_TOKENS", "junk")
    assert mcp_max_output_chars() == 150_000


def test_the_mcp_path_bounds_a_huge_result_as_valid_json(monkeypatch):
    monkeypatch.delenv("DODAIOS_MCP_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.delenv("MAX_MCP_OUTPUT_TOKENS", raising=False)
    result = SimpleNamespace(success=True, error=None, output=_big_list(3000, 400))
    text = _render(result)
    assert len(text) <= mcp_max_output_chars()
    assert json.loads(text)["truncated"] is True
    plain = SimpleNamespace(success=True, error=None, output="z" * 400_000)
    assert len(_render(plain)) <= mcp_max_output_chars()
