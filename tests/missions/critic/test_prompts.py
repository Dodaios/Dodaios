"""Tests for the Critic prompt templates.

Pins the contract the critic needs: evidence formats, no defect quota
(ADR-0009 amendment), the verbatim anchor token, the ``# ground-truth:``
marker every runtime-verified evidence block carries, and the output contract.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from dodaios.missions.critic.prompts import (
    ADVERSARIAL_REFRAME_PREFIX,
    CODEX_FLAT_OUTPUT_CONTRACT,
    CRITIC_SYSTEM_PROMPT,
    render_critic_prompt,
)
from dodaios.missions.critic.verdict import CRITIC_JSON_SCHEMA

# --- No defect quota ---


def test_template_forbids_a_defect_quota() -> None:
    assert "find at least three" not in CRITIC_SYSTEM_PROMPT
    assert "non-blocking" in CRITIC_SYSTEM_PROMPT


def test_template_only_revises_for_blocking_defects() -> None:
    assert "revise = cited blocking defect" in CRITIC_SYSTEM_PROMPT
    assert "non-blocking" in CRITIC_SYSTEM_PROMPT
    assert "requirements not in the goal" in CRITIC_SYSTEM_PROMPT


def test_template_names_the_role() -> None:
    assert "Dodaios mission critic" in CRITIC_SYSTEM_PROMPT


def test_codex_prompt_uses_only_the_flat_output_contract() -> None:
    prompt = render_critic_prompt(
        mission_prompt="Build a report",
        worker_diff="diff",
        log_summary="log",
        prior_reflections="none",
        iteration=0,
        codex_flat=True,
    )

    assert CODEX_FLAT_OUTPUT_CONTRACT in prompt
    assert "blocking_issue" in prompt
    assert '"axes"' not in prompt
    assert '"issues"' not in prompt


def test_default_prompt_leaves_the_schema_to_the_call_site() -> None:
    prompt = render_critic_prompt(
        mission_prompt="Build a report",
        worker_diff="diff",
        log_summary="log",
        prior_reflections="none",
        iteration=0,
    )

    assert CODEX_FLAT_OUTPUT_CONTRACT not in prompt


# --- Evidence ---


def test_template_requires_evidence_format() -> None:
    assert "file:line" in CRITIC_SYSTEM_PROMPT
    assert "log_line:N" in CRITIC_SYSTEM_PROMPT
    assert "test:name" in CRITIC_SYSTEM_PROMPT


def test_template_rejects_an_axis_without_evidence() -> None:
    assert "without evidence is rejected" in CRITIC_SYSTEM_PROMPT


# --- Anchor Token ---


def test_anchor_token_triple_bracketed_in_template() -> None:
    """The template contains the bracket markers — not the substituted string."""
    assert "<<<{mission_prompt}>>>" in CRITIC_SYSTEM_PROMPT


def test_render_includes_mission_prompt_verbatim() -> None:
    user_request = "Schreibe eine Funktion is_palindrome(s: str) -> bool"
    out = render_critic_prompt(
        mission_prompt=user_request,
        worker_diff="diff --git ...",
        log_summary="log...",
        prior_reflections="",
        iteration=0,
    )
    assert f"<<<{user_request}>>>" in out


def test_render_does_not_paraphrase_mission_prompt() -> None:
    """Insert verbatim even for long prompts with special characters."""
    weird = "Build X with !@#$%^&*() in the name and \"quoted\" parts."
    out = render_critic_prompt(
        mission_prompt=weird,
        worker_diff="d",
        log_summary="l",
        prior_reflections="r",
        iteration=1,
    )
    assert weird in out


# --- Schema + rules ---


def test_json_schema_carries_the_verdict_keys() -> None:
    for key in (
        "verdict",
        "axes",
        "issues",
        "correction_instruction",
        "summary",
        "confidence",
        "suggested_next_action",
    ):
        assert key in CRITIC_JSON_SCHEMA["properties"]


def test_template_states_read_only_mode() -> None:
    assert "Read-only" in CRITIC_SYSTEM_PROMPT


def test_template_has_ground_truth_rule() -> None:
    assert "diff is ground truth" in CRITIC_SYSTEM_PROMPT
    assert "hearsay" in CRITIC_SYSTEM_PROMPT


def test_template_has_meta_phrase_rule() -> None:
    """A "spawn a subagent to do X" request is judged on X: the worker is the
    spawned agent, so spawning evidence is never a deliverable."""
    assert "spawn a subagent" in CRITIC_SYSTEM_PROMPT
    assert "judge X" in CRITIC_SYSTEM_PROMPT


def test_template_points_at_runtime_verified_blocks() -> None:
    assert "# ground-truth:" in CRITIC_SYSTEM_PROMPT
    assert "# untracked-not-in-diff:" in CRITIC_SYSTEM_PROMPT


def test_every_verified_evidence_block_carries_the_ground_truth_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The prompt refers to ``# ground-truth:``; every block renderer must emit it."""
    from dodaios.missions.critic import runner
    from dodaios.missions.kontrollierer import orchestrator

    blocks = [
        orchestrator._format_external_write_block(Path("C:/out/report.md"), b"hello"),
        orchestrator._format_command_evidence_block([("git push", "")]),
        orchestrator._format_desktop_action_evidence_block([("start chrome", "")]),
    ]
    for block in blocks:
        assert "\n# ground-truth: " in block
    monkeypatch.setattr(
        runner, "extract_verified_external_actions", lambda _log: [("mcp_send", "sent")]
    )
    mcp_block = runner._render_external_action_evidence("log")
    assert "# verified-external-action\n# ground-truth: " in mcp_block


# --- Render-Behavior ---


def test_render_includes_diff_log_reflections_iteration() -> None:
    out = render_critic_prompt(
        mission_prompt="P",
        worker_diff="MY_DIFF_TOKEN",
        log_summary="MY_LOG_TOKEN",
        prior_reflections="MY_REFL_TOKEN",
        iteration=2,
    )
    assert "MY_DIFF_TOKEN" in out
    assert "MY_LOG_TOKEN" in out
    assert "MY_REFL_TOKEN" in out
    assert "CURRENT ITERATION: 2" in out


def test_render_handles_empty_reflections() -> None:
    out = render_critic_prompt(
        mission_prompt="p",
        worker_diff="d",
        log_summary="l",
        prior_reflections="",
        iteration=0,
    )
    assert "<<<>>>" in out  # explicitly empty anchor bracket


def test_render_adversarial_reframe_prepends_prefix() -> None:
    plain = render_critic_prompt(
        mission_prompt="p",
        worker_diff="d",
        log_summary="l",
        prior_reflections="r",
        iteration=0,
        adversarial_reframe=False,
    )
    reframed = render_critic_prompt(
        mission_prompt="p",
        worker_diff="d",
        log_summary="l",
        prior_reflections="r",
        iteration=0,
        adversarial_reframe=True,
    )
    assert reframed.startswith(ADVERSARIAL_REFRAME_PREFIX)
    assert plain in reframed
    assert ADVERSARIAL_REFRAME_PREFIX not in plain


def test_adversarial_prefix_stays_short_and_honest() -> None:
    assert "do not invent a blocker" in ADVERSARIAL_REFRAME_PREFIX
    assert "default position is now FAIL" not in ADVERSARIAL_REFRAME_PREFIX
    assert "Keep it short" in ADVERSARIAL_REFRAME_PREFIX


def test_render_anchor_present_in_both_modes() -> None:
    """The anchor token must also be present in adversarial-reframe mode."""
    out = render_critic_prompt(
        mission_prompt="ANCHOR_X",
        worker_diff="d",
        log_summary="l",
        prior_reflections="r",
        iteration=0,
        adversarial_reframe=True,
    )
    assert "<<<ANCHOR_X>>>" in out


def test_the_prompt_schema_drops_titles_but_keeps_the_contract() -> None:
    import json

    from dodaios.missions.critic.runner import _schema_for_prompt

    rendered = _schema_for_prompt(CRITIC_JSON_SCHEMA)
    assert '"title"' not in rendered
    assert json.loads(rendered)["properties"].keys() == CRITIC_JSON_SCHEMA["properties"].keys()
    assert len(rendered) < len(json.dumps(CRITIC_JSON_SCHEMA))
