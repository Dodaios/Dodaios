"""Tests for the per-tool spawn cooldown.

Live regression 2026-05-27 (mission_019e6983-{82e7,a83b,b0be}): ONE user
voice request ("Subagent für HTML-Slideshow") produced THREE mission cards  # i18n-allow: verbatim forensic quote of the live German voice utterance under test
in the Outputs UI within 10 seconds. Root cause: the user's long utterance
was VAD-fragmented across multiple turns, and each turn that landed in the
brain either re-matched a force-spawn phrase or the brain issued another
spawn_worker tool_call referencing the prior turn's utterance from
history. Result: triplicate sub-agent missions for one task.

Fix: cooldown inside the spawn tool. After a dispatched spawn, subsequent
``execute`` calls within ``_COOLDOWN_SECONDS`` (default 30s) return a
short voice-friendly ACK and do NOT call ``manager.dispatch``.

These tests verify the SUPPRESS branch in isolation by pre-arming
``_last_spawn_at`` rather than going through the fire-and-forget
``_background_dispatch`` (which would require a full asyncio dance). The
arming itself is covered by ``test_first_spawn_arms_the_cooldown``.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import uuid4

import pytest

from jarvis.brain.ack_brain.spawn_announcement import (
    _FALLBACK_ALREADY_RUNNING,
    _fix_en_article,
)
from jarvis.core.bus import EventBus
from jarvis.core.protocols import ExecutionContext
from jarvis.plugins.tool.spawn_worker import (
    _COOLDOWN_SECONDS,
    SpawnWorkerTool,
)

# The suppress ACK is composed by SpawnAnnouncementComposer in its
# deterministic "already_running" mode — de/en/es pools, no LLM. All three
# supported languages are included so a Spanish suppress ACK never false-fails
# the pool assertions (the composer's _resolve_language can return "es").
# The pools are {agent} templates; a bare default announcer speaks them with
# the NEUTRAL brand (no brand provider wired -> "Assistant-Agent").
_SUPPRESS_POOL = {
    _fix_en_article(p.replace("{agent}", "Assistant-Agent"))
    for p in (
        _FALLBACK_ALREADY_RUNNING["de"]
        + _FALLBACK_ALREADY_RUNNING["en"]
        + _FALLBACK_ALREADY_RUNNING["es"]
    )
}


class _FakeMissionManager:
    """Records dispatch calls; nothing else."""

    def __init__(self) -> None:
        self.dispatch_calls: list[dict[str, Any]] = []

    async def dispatch(
        self, *, prompt: str, language: str, source_actor: str
    ) -> str:
        mid = f"mission_{len(self.dispatch_calls):04d}"
        self.dispatch_calls.append(
            {"prompt": prompt, "language": language, "id": mid}
        )
        return mid


def _ctx() -> ExecutionContext:
    return ExecutionContext(
        trace_id=uuid4(), user_utterance="", config={}, memory_read=None
    )


def _tool(manager: _FakeMissionManager) -> SpawnWorkerTool:
    return SpawnWorkerTool(bus=EventBus(), manager=manager)


# --------------------------------------------------------------------------- #
# Suppress branch                                                             #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_cooldown_suppresses_duplicate_spawn() -> None:
    """When ``_last_spawn_at`` was set < _COOLDOWN_SECONDS ago AND a dispatch
    is still in flight, ``execute`` must return a suppress ACK and NOT call
    ``dispatch`` (the VAD-fragment dedup case)."""
    mgr = _FakeMissionManager()
    tool = _tool(mgr)
    # Simulate a successful prior spawn 1s ago with the mission still running.
    tool._last_spawn_at = time.monotonic() - 1.0
    tool._active_dispatches = 1

    result = await tool.execute(
        {"utterance": "Drogen in Schulen", "action": "noch eine Slideshow"},  # i18n-allow: simulated German user utterance, content under test
        _ctx(),
    )

    assert result.success is True, "suppressed call returns success (ACK only)"
    assert result.output in _SUPPRESS_POOL, (
        f"suppress ACK must come from the already-running pool, got {result.output!r}"
    )
    assert mgr.dispatch_calls == [], (
        f"duplicate spawn within cooldown must NOT dispatch, got {mgr.dispatch_calls!r}"
    )


@pytest.mark.asyncio
async def test_suppress_artifact_carries_marker() -> None:
    """The suppressed result must surface a ``cooldown_suppressed`` flag in
    its artifacts so telemetry can count duplicate-spawn rejections."""
    mgr = _FakeMissionManager()
    tool = _tool(mgr)
    tool._last_spawn_at = time.monotonic() - 5.0
    tool._active_dispatches = 1

    result = await tool.execute(
        {"utterance": "anything", "action": "x"}, _ctx()
    )
    # artifacts is a tuple of dicts (per ToolResult contract)
    artifacts = list(result.artifacts or ())
    assert any(
        isinstance(a, dict) and a.get("cooldown_suppressed") is True
        for a in artifacts
    ), f"artifacts must mark cooldown_suppressed=True, got {artifacts!r}"


# --------------------------------------------------------------------------- #
# Liveness gate (2026-05-27 hardening audit)                                  #
#                                                                             #
# The cooldown is a LIVENESS gate, not a pure fixed timer: it suppresses a    #
# duplicate spawn only while a dispatch is actually in flight AND within the  #
# window. Two confirmed findings drove this:                                  #
#   #3 spawn-cooldown-no-failure-reset — a fast mission failure left the      #
#      30s timer armed, so a legit follow-up got a false "already running"    #
#      ACK and was never dispatched.                                          #
#   #4 cooldown-arm-after-await-concurrent-fragment-race — the arm happened   #
#      AFTER `await bus.publish`, so two concurrent execute() coroutines      #
#      could both pass the gate and double-spawn.                             #
# --------------------------------------------------------------------------- #


class _OkKontrollierer:
    def __init__(self) -> None:
        self.runs: list[str] = []

    async def run_mission(self, mission_id: str) -> None:
        self.runs.append(mission_id)


class _RaisingMissionManager:
    async def dispatch(
        self, *, prompt: str, language: str, source_actor: str
    ) -> str:
        raise RuntimeError("decompose_failed")


class _YieldingBus:
    """Bus whose publish yields control — reproduces the concurrent-execute
    interleaving the real EventBus exhibits when subscribers are active."""

    def __init__(self) -> None:
        self.published: list[Any] = []

    async def publish(self, event: Any) -> None:
        self.published.append(event)
        await asyncio.sleep(0)  # yield to the other gathered coroutine


@pytest.mark.asyncio
async def test_not_suppressed_when_no_dispatch_in_flight() -> None:
    """#3 reset-on-failure: a prior spawn within the window but with NO
    in-flight dispatch (the mission already terminated) must NOT be
    suppressed — the user's legitimate retry has to dispatch."""
    mgr = _FakeMissionManager()
    tool = _tool(mgr)
    tool._last_spawn_at = time.monotonic() - 1.0  # within the 30s window
    tool._active_dispatches = 0  # nothing running anymore (mission ended)

    result = await tool.execute(
        {"utterance": "andere Aufgabe, neuer Versuch", "action": "x"}, _ctx()
    )

    assert result.output not in _SUPPRESS_POOL, (
        f"must NOT suppress a retry when nothing is in flight, got {result.output!r}"
    )
    await asyncio.sleep(0.05)  # let the fire-and-forget bg task run dispatch
    assert mgr.dispatch_calls, "legit retry after mission end must dispatch"


@pytest.mark.asyncio
async def test_background_dispatch_releases_gate_on_failure() -> None:
    """#3: a worker failure must decrement the liveness counter back to 0 so
    the next request is not falsely suppressed."""
    tool = SpawnWorkerTool(bus=EventBus(), manager=_RaisingMissionManager())
    tool._active_dispatches = 1  # as execute() would have armed it

    await tool._background_dispatch("x", "x", tool._manager, None)

    assert tool._active_dispatches == 0, (
        "liveness gate must release after a failed dispatch"
    )


@pytest.mark.asyncio
async def test_background_dispatch_releases_gate_on_success() -> None:
    """The counter must also return to 0 on the happy path."""
    mgr = _FakeMissionManager()
    kontrollierer = _OkKontrollierer()
    tool = SpawnWorkerTool(bus=EventBus(), manager=mgr)
    tool._active_dispatches = 1

    await tool._background_dispatch("x", "x", mgr, kontrollierer)

    assert tool._active_dispatches == 0
    assert kontrollierer.runs, "run_mission should have been invoked"


@pytest.mark.asyncio
async def test_concurrent_executes_dispatch_only_once() -> None:
    """#4: two concurrent execute() coroutines must not both dispatch. The
    cooldown has to arm (increment the liveness counter) BEFORE the first
    `await bus.publish`, so the second coroutine — running during that await
    — sees the in-flight gate and is suppressed."""
    bus = _YieldingBus()
    mgr = _FakeMissionManager()
    tool = SpawnWorkerTool(bus=bus, manager=mgr)

    await asyncio.gather(
        tool.execute({"utterance": "Aufgabe A", "action": "x"}, _ctx()),
        tool.execute({"utterance": "Aufgabe B", "action": "y"}, _ctx()),
    )
    await asyncio.sleep(0.05)  # let any launched bg tasks reach dispatch

    assert len(mgr.dispatch_calls) == 1, (
        f"concurrent executes double-spawned: {mgr.dispatch_calls!r}"
    )


# --------------------------------------------------------------------------- #
# Pass-through branches                                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_first_spawn_passes_cooldown_gate() -> None:
    """No prior spawn → cooldown branch must NOT trigger. We verify by
    looking past the cooldown check: the gate would short-circuit to a
    suppress ACK; here we expect to reach the bootstrap-failed / manager-
    resolution stage instead. With a real fake manager the call proceeds
    past the gate (we don't await the bg task — just verify no suppress)."""
    mgr = _FakeMissionManager()
    tool = _tool(mgr)
    assert tool._last_spawn_at == 0.0, "fresh tool has no prior spawn"

    # The cooldown check inspects _last_spawn_at; with 0.0 it MUST be skipped.
    # Direct: call the gate predicate via execute and verify the result is
    # NOT one of the suppress ACKs.
    result = await tool.execute(
        {"utterance": "Subagent spawnen, eine Datei macht", "action": "test"},
        _ctx(),
    )
    # The first call must succeed (real bg dispatch fires) and the output
    # must NOT be a suppress-ACK string.
    assert result.success is True
    assert result.output not in _SUPPRESS_POOL, (
        f"first call must not hit the suppress branch, got {result.output!r}"
    )


@pytest.mark.asyncio
async def test_cooldown_expires_after_threshold() -> None:
    """When the prior spawn is older than _COOLDOWN_SECONDS, a new call must
    NOT be suppressed — even if a (long-running) dispatch is still counted as
    in flight, the window expiry alone re-opens the gate so a genuinely new
    request 30s+ later is never blocked."""
    mgr = _FakeMissionManager()
    tool = _tool(mgr)
    # Prior spawn happened cooldown_seconds + 1 ago — gate must open.
    tool._last_spawn_at = time.monotonic() - (_COOLDOWN_SECONDS + 1.0)
    tool._active_dispatches = 1  # still "in flight" — window expiry must win

    result = await tool.execute(
        {"utterance": "Anderer Subagent, andere Aufgabe", "action": "test"},
        _ctx(),
    )
    assert result.success is True
    assert result.output not in _SUPPRESS_POOL, (
        "after cooldown expired, the suppress branch MUST NOT fire — got "
        f"{result.output!r}"
    )


# --------------------------------------------------------------------------- #
# Constants + ACK shape                                                       #
# --------------------------------------------------------------------------- #


def test_cooldown_seconds_is_positive_and_reasonable() -> None:
    assert _COOLDOWN_SECONDS >= 10.0, (
        "cooldown must cover at least one VAD-fragmentation window"
    )
    assert _COOLDOWN_SECONDS <= 120.0, (
        "cooldown must NOT block legitimate follow-up requests for too long"
    )


def test_suppress_acks_are_short_and_unique() -> None:
    for lang, pool in _FALLBACK_ALREADY_RUNNING.items():
        assert len(pool) >= 3, "need variety to avoid robot repetition"
        assert len(set(pool)) == len(pool)
        in_flight_markers = {
            # German/Spanish marker words below are the data under test.
            "de": ("schon", "läuft", "dabei", "dran", "bereits", "arbeit"),  # i18n-allow
            "en": ("already", "still", "running", "working", "progress"),
            "es": ("marcha", "sigo", "proceso", "está", "ya tiene"),  # i18n-allow
            "pt": ("curso", "ainda", "já", "trabalhar", "está com"),
        }[lang]
        for ack in pool:
            assert 5 <= len(ack) <= 60, (
                f"ACK must be TTS-readable, got {len(ack)} chars: {ack!r}"
            )
            # Must signal an in-flight job, not a refusal
            text = ack.lower()
            assert any(k in text for k in in_flight_markers), (
                f"ACK must indicate in-flight job: {ack!r}"
            )


# --------------------------------------------------------------------------- #
# A second typed order is not a duplicate                                     #
#                                                                             #
# The window above exists for fragments of ONE utterance. A typed message is  #
# a whole turn the person finished; a second order typed in another message   #
# has to dispatch while the first is still running, or "do X" ... "and also   #
# do Y" silently loses Y. Spoken turns stay under the window.                 #
# --------------------------------------------------------------------------- #


class _HeldKontrollierer:
    """A mission that is still running when the next order arrives."""

    async def run_mission(self, mission_id: str) -> None:
        del mission_id
        await asyncio.Event().wait()


async def _typed(tool: SpawnWorkerTool, turn: str, typed: str, utterance: str | None = None):
    from jarvis.core.protocols import ChatTurn, current_chat_turn

    token = current_chat_turn.set(ChatTurn("chat-1", turn, typed, True, "trace"))
    try:
        return await tool.execute({"utterance": utterance or typed}, _ctx())
    finally:
        current_chat_turn.reset(token)


def _held_tool() -> tuple[SpawnWorkerTool, _FakeMissionManager]:
    mgr = _FakeMissionManager()
    return SpawnWorkerTool(bus=EventBus(), manager=mgr, kontrollierer=_HeldKontrollierer()), mgr


@pytest.mark.asyncio
async def test_second_order_from_another_typed_message_dispatches() -> None:
    tool, mgr = _held_tool()
    first = await _typed(tool, "turn-1", "Research the flight prices to Lisbon")
    second = await _typed(tool, "turn-2", "Build a slideshow about solar power")
    await asyncio.sleep(0.05)
    assert first.output not in _SUPPRESS_POOL and second.output not in _SUPPRESS_POOL
    assert len(mgr.dispatch_calls) == 2, f"the second order was lost: {mgr.dispatch_calls!r}"
    assert "solar power" in mgr.dispatch_calls[1]["prompt"]


@pytest.mark.asyncio
async def test_the_same_typed_order_again_stays_a_duplicate() -> None:
    tool, mgr = _held_tool()
    await _typed(tool, "turn-1", "Research the flight prices to Lisbon.")
    repeat = await _typed(tool, "turn-2", "research the flight prices to lisbon")
    await asyncio.sleep(0.05)
    assert repeat.output in _SUPPRESS_POOL
    assert len(mgr.dispatch_calls) == 1


@pytest.mark.asyncio
async def test_a_short_follow_up_does_not_respawn_the_running_order() -> None:
    """ "and?" orders nothing: a reworded spawn of the running order is a duplicate."""
    tool, mgr = _held_tool()
    await _typed(tool, "turn-1", "Research the flight prices to Lisbon")
    again = await _typed(
        tool, "turn-2", "and?", utterance="Look up what flights to Lisbon cost right now"
    )
    await asyncio.sleep(0.05)
    assert again.output in _SUPPRESS_POOL
    assert len(mgr.dispatch_calls) == 1


@pytest.mark.asyncio
async def test_a_spawn_unrelated_to_the_typed_message_stays_a_duplicate() -> None:
    tool, mgr = _held_tool()
    await _typed(tool, "turn-1", "Research the flight prices to Lisbon")
    drifted = await _typed(
        tool, "turn-2", "What is the weather tomorrow?",
        utterance="Look up what flights to Lisbon cost right now",
    )
    await asyncio.sleep(0.05)
    # The call repeats the running order under a message about something else.
    assert drifted.output in _SUPPRESS_POOL
    assert len(mgr.dispatch_calls) == 1


@pytest.mark.asyncio
async def test_a_spoken_spawn_keeps_the_fragment_window() -> None:
    """Speech names no finished order: a different text inside the window is
    still treated as a fragment of the running request, on every voice engine."""
    tool, mgr = _held_tool()
    live = ExecutionContext(
        trace_id=uuid4(), user_utterance="",
        config={"live_session_id": "call-1", "task_revision": 4}, memory_read=None,
    )
    later = ExecutionContext(
        trace_id=uuid4(), user_utterance="",
        config={"live_session_id": "call-1", "task_revision": 6}, memory_read=None,
    )
    await tool.execute({"utterance": "Build a slideshow"}, live)
    fragment = await tool.execute({"utterance": "about drugs in schools"}, later)
    plain = await tool.execute({"utterance": "and make it colourful"}, _ctx())
    await asyncio.sleep(0.05)
    assert fragment.output in _SUPPRESS_POOL and plain.output in _SUPPRESS_POOL
    assert len(mgr.dispatch_calls) == 1
