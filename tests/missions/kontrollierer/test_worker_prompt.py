"""Tests for the worker-prompt composer and the one worker contract.

``compose_worker_prompt`` is the single chokepoint every mission worker prompt
passes through (``orchestrator._run_iterations`` and the sub-agent fan-out),
so the contract pins live here.
"""
from __future__ import annotations

from dodaios.missions.kontrollierer.worker_prompt import (
    SUBAGENT_CONTRACT,
    WORKER_CONTRACT,
    compose_worker_prompt,
)

# --- The contract itself ------------------------------------------------------


def test_contract_mandates_english_code_artifacts() -> None:
    text = WORKER_CONTRACT.lower()
    assert "english" in text
    assert "comments" in text


def test_contract_says_no_user_can_answer() -> None:
    text = WORKER_CONTRACT.lower()
    assert "no user" in text
    assert "background" in text


def test_contract_names_the_diff_review_and_forbids_commits() -> None:
    assert "git diff HEAD" in WORKER_CONTRACT
    assert "Do not commit" in WORKER_CONTRACT


def test_contract_lets_the_verbatim_words_win() -> None:
    assert "verbatim words win" in WORKER_CONTRACT


def test_contract_stops_honestly_without_a_tool() -> None:
    assert "say so and stop" in WORKER_CONTRACT


def test_contract_excludes_live_control_surfaces() -> None:
    text = WORKER_CONTRACT.lower()
    assert "jarvisctl" in text
    assert "configuration" in text


def test_contract_ends_with_spoken_summary_and_written_line() -> None:
    assert "read aloud" in WORKER_CONTRACT
    assert "Written:" in WORKER_CONTRACT
    assert "No file output required." in WORKER_CONTRACT


def test_contract_is_provider_agnostic() -> None:
    text = WORKER_CONTRACT.lower()
    for banned in ("claude", "gemini", "codex", "grok", "anthropic", "openai"):
        assert banned not in text


# --- compose_worker_prompt ----------------------------------------------------


def test_compose_puts_contract_before_the_step_prompt() -> None:
    step = "Build a single HTML page."
    out = compose_worker_prompt("", step)
    assert WORKER_CONTRACT in out
    assert step in out
    assert out.index(WORKER_CONTRACT) < out.index(step)


def test_compose_keeps_prior_reflections_and_orders_contract_first() -> None:
    prior = "PRIOR CRITIC FEEDBACK: the previous attempt left a stub."
    step = "Finish the deliverable."
    out = compose_worker_prompt(prior, step)
    assert out.index(WORKER_CONTRACT) < out.index(prior) < out.index(step)


def test_compose_without_prior_block_has_no_dangling_separator() -> None:
    out = compose_worker_prompt("", "do the thing")
    assert "\n\n\n" not in out
    assert out.strip() == out


def test_compose_accepts_the_subagent_contract() -> None:
    out = compose_worker_prompt("", "Sub-task: x", contract=SUBAGENT_CONTRACT)
    assert out.startswith(SUBAGENT_CONTRACT)
    assert WORKER_CONTRACT not in out
    # A fan-out child is not in a git worktree.
    assert "git diff" not in SUBAGENT_CONTRACT
