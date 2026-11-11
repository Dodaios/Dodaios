"""Lessons from corrections, how-to notes, repeat errors, consolidation (no model)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from dodaios.memory.learning.loop import tool_trace
from dodaios.memory.learning.signals import is_correction
from dodaios.memory.vault import consolidate, lessons, reconcile
from dodaios.memory.vault import runtime as vault_runtime
from dodaios.memory.vault.store import MemoryVault


class Clock:
    def __init__(self) -> None:
        self.value = "2026-11-09T09:00:00+00:00"

    def __call__(self) -> str:
        return self.value


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def vault(tmp_path: Path, clock: Clock):
    v = MemoryVault(tmp_path / "vault.db", clock=clock)
    vault_runtime.set_active(v)
    yield v
    vault_runtime.set_active(None)


def _learn(vault: MemoryVault, text: str, trigger: str, quote: str, *, pin: bool = True):
    raw = [
        {
            "op": "add",
            "kind": "procedural",
            "text": text,
            "trigger": trigger,
            "note": "lesson",
            "evidence": quote,
            "pin": pin,
        }
    ]
    ops, rejected = reconcile.validate(raw, user_texts=[quote], shown=[])
    assert not rejected
    reconcile.apply(vault, ops, source={"via": "review"})
    return next(m for m in vault.list() if m.text == text)


# Regression set: (correction stored, later situation) pairs that must recall it,
# and unrelated messages that must not.
FIXTURES = [
    (
        "Send reports as PDF, never as Word documents.",
        "sending a report by email",
        "No, I meant a PDF, not a Word document for the report",
        "please email the quarterly report as a word document",
        "what is the weather in Berlin tomorrow",
    ),
    (
        "Do not use emojis in commit messages.",
        "writing commit messages",
        "I told you, no emojis in the commit message",
        "write a commit message with some emojis for this change",
        "play some relaxing music",
    ),
    (
        "Book flights only on Lufthansa for the owner.",
        "booking a flight",
        "That's wrong, I only fly Lufthansa when you book flights",
        "book me a flight to Munich on friday",
        "summarize my unread email",
    ),
]


@pytest.mark.parametrize(("rule", "trigger", "quote", "again", "unrelated"), FIXTURES)
def test_lesson_is_recalled_in_a_similar_situation(
    vault, monkeypatch, rule, trigger, quote, again, unrelated
):
    lesson = _learn(vault, rule, trigger, quote, pin=False)
    assert lesson.source["note"] == "lesson"
    assert lesson.source["trigger"] == trigger
    assert lesson.source["evidence"] == quote
    assert [m.id for m, _ in lessons.recall(vault, again)] == [lesson.id]
    assert lessons.recall(vault, unrelated) == []
    # Procedural memories ride in the always-on block; when the budget drops one,
    # recall by situation still brings it back.
    assert rule in vault.profile_block()
    monkeypatch.setattr(vault, "profile_selection", lambda **_k: [])
    assert rule in vault_runtime.turn_block(again)
    assert vault_runtime.turn_block(unrelated) == ""


def test_how_to_note_never_pins_and_needs_valid_op(vault):
    raw = [
        {
            "op": "add",
            "kind": "profile",
            "text": "Opening the team share works only after the VPN is connected.",
            "note": "how_to",
            "trigger": "opening the team share",
            "evidence": "open the team share and list the invoices",
            "pin": True,
        }
    ]
    ops, rejected = reconcile.validate(
        raw, user_texts=["open the team share and list the invoices"], shown=[]
    )
    assert not rejected and ops[0].kind == "procedural" and ops[0].pin is False
    reconcile.apply(vault, ops, source={"via": "review"})
    note = vault.list()[0]
    assert not note.pinned and lessons.note_of(note) == "how_to"
    assert lessons.recall(vault, "list the invoices on the team share")[0][0].id == note.id


def test_repeat_correction_is_counted_and_marked(vault):
    lesson = _learn(
        vault,
        "Send reports as PDF, never as Word documents.",
        "sending a report by email",
        "No, I meant a PDF, not a Word document for the report",
        pin=False,
    )
    assert lessons.note_repeat(vault, "what is the weather today") is None
    assert lessons.metrics(vault)["repeat_errors"] == 0
    found = lessons.note_repeat(vault, "No! Not a Word document, the report must be a PDF")
    assert found is not None and found.id == lesson.id
    assert vault.get(lesson.id).pinned  # type: ignore[union-attr]
    stats = lessons.metrics(vault)
    assert stats["repeat_errors"] == 1 and stats["needs_stronger"] == 1 and stats["lessons"] == 1


def test_signals_know_undo_and_trace_finds_worked_around_failures():
    assert is_correction("please undo that, it was the wrong folder")
    events = [
        {"kind": "tool_call", "payload": {"call_id": "1", "name": "web_fetch"}},
        {"kind": "tool_result", "payload": {"call_id": "1", "is_error": True, "output": "403"}},
        {"kind": "tool_call", "payload": {"call_id": "2", "name": "browser_open"}},
        {"kind": "tool_result", "payload": {"call_id": "2", "is_error": False, "output": "ok"}},
    ]
    trace = tool_trace(events)
    assert "web_fetch" in trace and "browser_open" in trace
    assert tool_trace(events[:2]) == ""  # failed and never recovered: no note
    assert tool_trace(events[2:]) == ""  # nothing failed
    denied = [
        {"kind": "approval_required", "payload": {"approval_id": "a", "name": "delete_file"}},
        {"kind": "approval_resolved", "payload": {"approval_id": "a", "decision": "deny"}},
    ]
    assert "delete_file" in tool_trace(denied)


class Scripted:
    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    async def __call__(self, prompt: str) -> Any:
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else None


def test_consolidation_resolves_contradiction_newer_wins_and_keeps_history(vault, clock):
    old = vault.remember("The user lives in Berlin and works from home.", "profile").memory
    clock.value = "2026-11-10T09:00:00+00:00"
    new = vault.remember("The user lives in Hamburg and works from home.", "profile").memory
    notified: list[str] = []

    async def notify(text: str) -> None:
        notified.append(text)

    reviewer = Scripted({"merges": [], "conflicts": [{"keep": new.id, "drop": [old.id]}]})
    assert asyncio.run(consolidate.run_if_due(vault, reviewer, notify)) == 1
    assert [m.id for m in vault.list()] == [new.id]
    assert vault.get(old.id) is not None  # history kept
    assert len(notified) == 1 and "resolved 1" in notified[0]


def test_consolidation_never_touches_owner_pins_or_owner_words(vault, clock):
    pinned = vault.remember("The user lives in Berlin and works from home.", "profile").memory
    vault.pin(pinned.id, True)
    clock.value = "2026-11-10T09:00:00+00:00"
    vault.remember("The user lives in Hamburg and works from home.", "profile")
    reviewer = Scripted()
    assert asyncio.run(consolidate.run_if_due(vault, reviewer)) == 0
    assert vault.get(pinned.id).expired_at is None  # type: ignore[union-attr]
    assert reviewer.prompts == []  # the pinned one was never offered

    # An inferred memory cannot close what the owner said.
    owner = vault.remember("The user takes the train to the office daily.", "profile").memory
    clock.value = "2026-11-11T09:00:00+00:00"
    inferred = vault.remember(
        "The user takes the car to the office daily.", "profile", origin="inferred"
    ).memory
    groups = [[owner, inferred]]
    plan = [{"keep": inferred.id, "drop": [owner.id]}]
    assert consolidate.resolve_conflicts(vault, groups, plan) == 0
    # A silent notice: nothing changed, nothing posted.


def test_stale_items_retire_without_a_model_and_no_notice_when_nothing_changed(vault, clock):
    vault.remember(
        "The user has a dentist appointment.",
        "project",
        origin="inferred",
        due_at="2026-09-01T09:00:00+00:00",
    )
    vault.remember("The user likes tea.", "preference")
    notified: list[str] = []

    async def notify(text: str) -> None:
        notified.append(text)

    assert asyncio.run(consolidate.run_if_due(vault, Scripted(), notify)) == 1
    assert [m.text for m in vault.list()] == ["The user likes tea."]
    assert len(notified) == 1 and "retired 1" in notified[0]
    clock.value = "2026-11-12T09:00:00+00:00"
    assert asyncio.run(consolidate.run_if_due(vault, Scripted(), notify)) == 0
    assert len(notified) == 1


def test_repeated_lesson_is_reworded_by_the_pass(vault):
    lesson = _learn(
        vault,
        "Send reports as PDF, never as Word documents.",
        "sending a report by email",
        "No, I meant a PDF, not a Word document for the report",
    )
    lessons.note_repeat(vault, "No! Not a Word document, the report must be a PDF")
    reviewer = Scripted(
        {"merges": [], "strengthen": [{"id": lesson.id, "text": "Reports are ALWAYS PDF."}]}
    )
    assert asyncio.run(consolidate.run_if_due(vault, reviewer)) == 1
    current = vault.list(kind="procedural")
    assert [m.text for m in current] == ["Reports are ALWAYS PDF."]
    assert lessons.note_of(current[0]) == "lesson" and current[0].pinned
    assert lessons.metrics(vault)["needs_stronger"] == 0
    assert lessons.metrics(vault)["repeat_errors"] == 1
