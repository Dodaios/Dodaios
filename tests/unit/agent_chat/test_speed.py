"""The speed pick: Claude Code's fast mode and Codex's service tiers."""

from __future__ import annotations

from pathlib import Path

from dodaios.agent_chat.catalog import CLAUDE_CODE_MODELS
from dodaios.agent_chat.cli_catalog import parse_codex_models
from dodaios.agent_chat.speed import apply_speed, codex_speeds, normalize_speed, speed_args
from dodaios.agent_chat.store import AgentChatStore


def test_normalize_keeps_tier_ids_and_drops_anything_else() -> None:
    assert normalize_speed(" Fast ") == "fast"
    assert normalize_speed("priority") == "priority"
    assert normalize_speed("standard") == ""
    assert normalize_speed(None) == ""
    assert normalize_speed('x" --yolo') == ""


def test_claude_fast_mode_is_one_flag() -> None:
    assert speed_args("claude-cli", "fast") == ["--fast-mode", "on"]
    assert speed_args("claude-cli", "") == []
    assert speed_args("claude-cli", "priority") == []


def test_codex_tier_goes_in_front_of_the_stdin_marker() -> None:
    argv = ["codex", "exec", "--json", "--model", "gpt-6-astra", "-"]
    apply_speed(argv, "codex-cli", "priority")
    assert argv == [
        "codex", "exec", "--json", "--model", "gpt-6-astra",
        "-c", 'service_tier="priority"', "-",
    ]


def test_runners_without_a_speed_switch_are_left_alone() -> None:
    argv = ["grok", "-m", "grok-4.7"]
    apply_speed(argv, "grok-cli", "fast")
    apply_speed(argv, "glm-cli", "fast")
    assert argv == ["grok", "-m", "grok-4.7"]


def test_codex_catalog_carries_the_accounts_tiers() -> None:
    rows = parse_codex_models([
        {
            "model": "gpt-6-astra",
            "displayName": "GPT-6 Astra",
            "supportedReasoningEfforts": [{"reasoningEffort": "high"}],
            "serviceTiers": [
                {"id": "priority", "name": "Fast", "description": "2x speed, increased usage"},
                {"id": "ultrafast", "name": "Ultrafast", "description": ""},
            ],
        },
        {
            "model": "gpt-6-luna",
            "displayName": "GPT-6 Luna",
            "supportedReasoningEfforts": [],
            "serviceTiers": [],
        },
    ])
    assert rows[0]["speeds"] == [
        {"id": "priority", "label": "Fast", "note": "2x speed, increased usage"},
        {"id": "ultrafast", "label": "Ultrafast", "note": ""},
    ]
    # A plan without tiers (a free login) gets no speed pick.
    assert "speeds" not in rows[1]


def test_codex_speeds_skip_malformed_tiers() -> None:
    assert codex_speeds({"serviceTiers": [{"id": "bad id!"}, "x", {"id": "priority"}]}) == [
        {"id": "priority", "label": "priority", "note": ""}
    ]


def test_only_fast_mode_claude_models_offer_a_speed() -> None:
    fast = {m.id for m in CLAUDE_CODE_MODELS if "speeds" in m.to_dict()}
    assert "claude-opus-5-5" in fast
    assert "claude-fable-5-2" not in fast


def test_store_keeps_the_speed_per_session(tmp_path: Path) -> None:
    store = AgentChatStore(tmp_path / "chat.db")
    try:
        session = store.create_session(
            provider="codex", model="gpt-6-astra", effort="", cwd="", speed="priority"
        )
        assert session.speed == "priority"
        updated = store.update_session(session.session_id, speed="")
        assert updated is not None and updated.speed == ""
    finally:
        store.close()
