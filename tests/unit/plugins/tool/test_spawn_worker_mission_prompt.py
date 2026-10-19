"""Tests for the mission-prompt construction in spawn_worker.

Live incident 2026-05-29 (mission 019e70a9): the user's request reached the
worker as a VAD-cut fragment. STT captured only 'die Detailwürfelspiele.html'
(1.7s of speech); the brain still understood the intent and emitted
action='eine HTML-Seite namens Würfelspiel.html baut', but the mission prompt
used the verbatim `utterance` field alone, so the worker built from the
fragment. The tool schema deliberately keeps `utterance` verbatim (no detail
loss), so the fix enriches the mission prompt with the interpreted `action`
(+ target + context_hints) while preserving the verbatim words.
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from dodaios.core.bus import EventBus
from dodaios.core.protocols import ExecutionContext
from dodaios.plugins.tool.spawn_worker import (
    SpawnWorkerTool,
    _build_mission_prompt,
)


class _RecordingManager:
    def __init__(self) -> None:
        self.dispatched: list[str] = []

    async def dispatch(self, *, prompt: str, language: str, source_actor: str) -> str:
        self.dispatched.append(prompt)
        return f"mission_{len(self.dispatched)}"


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        trace_id=uuid4(), user_utterance="", config={}, memory_read=None
    )


def test_fragment_utterance_is_enriched_with_action() -> None:
    """A fragment utterance + a rich interpreted action must yield a mission
    prompt that carries the action's intent (the real filename), not just the
    fragment."""
    prompt = _build_mission_prompt(
        utterance="die Detailwürfelspiele.html",
        action="eine HTML-Seite namens Würfelspiel.html baut",
        target="Desktop-App Outputs",
    )
    assert "Würfelspiel.html" in prompt, (
        f"interpreted filename missing from mission prompt: {prompt!r}"
    )
    # The verbatim words are preserved as context (schema's no-detail-loss rule).
    assert "die Detailwürfelspiele.html" in prompt
    # The target is carried too.
    assert "Desktop-App Outputs" in prompt


def test_context_hints_are_included() -> None:
    prompt = _build_mission_prompt(
        utterance="bau das",
        action="eine Flask-App baut",
        target="",
        context_hints=["Port 8000", "mit /health-Endpoint"],
    )
    assert "Flask-App" in prompt
    assert "Port 8000" in prompt
    assert "/health-Endpoint" in prompt


def test_no_action_falls_back_to_raw_utterance() -> None:
    """Force-spawn path passes action='' — there is no interpretation, so the
    mission prompt carries the raw utterance verbatim (no Task/action
    enrichment)."""
    prompt = _build_mission_prompt(
        utterance="lies die Datei x und fasse sie zusammen", action=""
    )
    assert "lies die Datei x und fasse sie zusammen" in prompt
    assert "Task:" not in prompt  # no interpretation enrichment


def test_no_action_keeps_bounded_recent_context_for_references() -> None:
    """A forced follow-up must not reach a stateless worker without its topic."""
    long_hint = "bounded-marker " + ("x" * 10_000)
    prompt = _build_mission_prompt(
        utterance="Where is it? I also installed it as a plugin.",
        action="",
        context_hints=[
            "Conversation context (recent turns, newest last):",
            (
                "Earlier turn — User: 'Please inspect my Gmail plugin.' | "
                "Assistant: 'The lookup did not finish.'"
            ),
            long_hint,
        ],
    )

    assert "Please inspect my Gmail plugin" in prompt
    assert "The lookup did not finish" in prompt
    assert "Supporting context from the recent conversation" in prompt
    assert "bounded-marker" in prompt
    assert long_hint not in prompt


def test_empty_no_action_stays_empty_even_when_context_exists() -> None:
    assert _build_mission_prompt(
        utterance="", action="", context_hints=["old context"],
    ) == ""


def test_generic_default_action_is_not_treated_as_interpretation() -> None:
    """The generic ACK filler ('einer komplexen Aufgabe nachgeht') is NOT a
    real interpretation — it must not become the worker's task; fall back to
    the verbatim utterance."""
    prompt = _build_mission_prompt(
        utterance="mach das für mich",
        action="einer komplexen Aufgabe nachgeht",
    )
    assert "mach das für mich" in prompt
    assert "Task:" not in prompt
    assert "komplexen Aufgabe nachgeht" not in prompt


def test_empty_everything_returns_empty() -> None:
    assert _build_mission_prompt(utterance="", action="") == ""


def test_mission_prompt_no_longer_carries_the_quality_directive() -> None:
    """The worker contract lives in ``worker_prompt.WORKER_CONTRACT``; the
    mission prompt is only the task, in English labels."""
    from dodaios.missions.kontrollierer.worker_prompt import WORKER_CONTRACT

    for action in ("eine Landingpage baut", ""):
        prompt = _build_mission_prompt(
            utterance="bau mir eine schöne Landingpage", action=action,
        )
        assert "production-quality" not in prompt.lower()
        assert "Landingpage" in prompt
    enriched = _build_mission_prompt(
        utterance="bau mir eine schöne Landingpage", action="eine Landingpage baut",
    )
    assert enriched.startswith("Task: eine Landingpage baut.")
    assert "User's words (verbatim):" in enriched
    # The honest-impossibility escape moved into the contract.
    assert "say so and stop" in WORKER_CONTRACT


@pytest.mark.asyncio
async def test_execute_dispatches_enriched_prompt_not_raw_fragment() -> None:
    """End-to-end: execute() must dispatch the mission with the enriched
    prompt (carrying the interpreted filename), not the raw VAD fragment."""
    mgr = _RecordingManager()
    tool = SpawnWorkerTool(bus=EventBus(), manager=mgr)

    await tool.execute(
        {
            "utterance": "die Detailwürfelspiele.html",
            "action": "eine HTML-Seite namens Würfelspiel.html baut",
            "target": "Desktop-App Outputs",
        },
        _ctx(),
    )
    await asyncio.sleep(0.05)  # let the fire-and-forget bg task reach dispatch

    assert mgr.dispatched, "execute() must have dispatched a mission"
    prompt = mgr.dispatched[0]
    assert "Würfelspiel.html" in prompt, (
        f"dispatched prompt must carry the interpreted intent, got {prompt!r}"
    )


def test_forcespawn_strips_spawn_meta_from_worker_task() -> None:
    """Live regression (2026-06-16, "move to the USA" mission): an explicit
    voice trigger ("spawn a sub-agent which will help me find out X") routes to
    the force-spawn path (action=""), where the verbatim utterance became the
    worker's task. The worker then read "spawn a sub-agent" as ITS task — which
    it cannot do (no spawn tool, AP-5) — instead of doing the research, and the
    mission died critic_loop_exhausted. The routing wrapper must be stripped so
    the worker receives the REAL task."""
    prompt = _build_mission_prompt(
        utterance=(
            "Create and spawn a sub-agent which will help me find out what I "
            "have to be aware of when I move to the USA"
        ),
        action="",
    )
    low = prompt.lower()
    # the routing wrapper is gone — the worker is not told to spawn anything
    assert "spawn a sub-agent" not in low
    assert "create and spawn" not in low
    # the actual research task survives verbatim
    assert "move to the USA" in prompt


def test_forcespawn_german_spawn_meta_stripped() -> None:
    """German is a first-class voice language here. An inflected "Sub-Agenten"
    must also be recognised as routing meta and stripped, leaving the real
    research task for the worker."""
    prompt = _build_mission_prompt(
        utterance=(
            "Spawne einen Sub-Agenten, der herausfindet, was ich beim "  # i18n-allow
            "USA-Umzug beachten muss"  # i18n-allow
        ),
        action="",
    )
    low = prompt.lower()
    assert "sub-agent" not in low
    assert "sub-agenten" not in low
    # the real task survives
    assert "USA-Umzug" in prompt


def test_forcespawn_topic_request_does_not_leave_an_orphaned_article() -> None:
    """Exact 2026-07-13 regression: routing removal stranded an article.

    The worker interpreted it as a missing deliverable noun and returned only a
    format question instead of researching the topic.
    """
    prompt = _build_mission_prompt(
        utterance=(
            "Kannst du bitte einen Subagent spawnen "  # i18n-allow: fixture
            "zum Thema Drogen in Schulen und was "  # i18n-allow: fixture
            "damit verbunden ist?"  # i18n-allow: fixture
        ),
        action="",
    )
    low = prompt.lower()

    assert "subagent spawnen" not in low
    assert "einen zum thema" not in low
    assert "research and analyze this topic thoroughly" in low
    assert "Drogen in Schulen" in prompt  # i18n-allow: quoted speech input
    assert "instead of asking which format" in low


def test_forcespawn_pure_meta_phrase_falls_back_to_raw() -> None:
    """If stripping leaves nothing real (the utterance was ONLY the routing
    wrapper), the worker must never get an empty task — fall back to the raw
    utterance so it still has something."""
    prompt = _build_mission_prompt(utterance="spawn a sub-agent", action="")
    assert prompt.strip() == "spawn a sub-agent"


def test_forcespawn_genuine_deliverable_survives() -> None:
    """A genuine do-task wrapped in a spawn trigger must keep its deliverable:
    only the routing wrapper is stripped, not the real "writes a file" task."""
    prompt = _build_mission_prompt(
        utterance="spawn a sub-agent that writes a file poem.txt with a poem",
        action="",
    )
    low = prompt.lower()
    assert "spawn a sub-agent" not in low
    assert "poem.txt" in prompt
    assert "writes a file" in low


def test_forcespawn_no_meta_utterance_unchanged() -> None:
    """A force-spawn utterance WITHOUT any routing meta must be carried verbatim
    (the strip is a no-op) — existing force-spawn behaviour is preserved."""
    prompt = _build_mission_prompt(
        utterance="lies die Datei x und fasse sie zusammen", action=""
    )
    assert "lies die Datei x und fasse sie zusammen" in prompt
    assert "Task:" not in prompt
