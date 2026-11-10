"""Open loops: what the person said they would do, remembered with a due time."""

from __future__ import annotations

from datetime import date

import pytest

from dodaios.agent_chat import open_loops
from dodaios.memory.vault.store import MemoryVault

TODAY = date(2026, 11, 10)  # a Tuesday


@pytest.mark.parametrize(
    ("text", "what", "due"),
    [
        ("I'll call Max tomorrow.", "call Max", date(2026, 11, 11)),
        ("I'll call Max, Anna and Tom tomorrow.", "call Max, Anna and Tom", date(2026, 11, 11)),
        ("Sure. I will send the report by Friday, promise.", "send the report", date(2026, 11, 13)),
        ("I need to book the dentist next week", "book the dentist", date(2026, 11, 17)),
        ("Tonight I have to finish the slides", "finish the slides", date(2026, 11, 10)),
        ("I'm going to fix the bike in 3 days", "fix the bike", date(2026, 11, 13)),
        ("Ich werde morgen Max anrufen.", "Max anrufen", date(2026, 11, 11)),  # i18n-allow
        (
            "Ich muss am Donnerstag die Steuer machen",  # i18n-allow
            "die Steuer machen",  # i18n-allow
            date(2026, 11, 12),
        ),
    ],
)
def test_detects_a_dated_commitment(text: str, what: str, due: date) -> None:
    loops = open_loops.detect(text, today=TODAY)
    assert [(loop.what, loop.due) for loop in loops] == [(what, due)]
    assert loops[0].text == f"Open loop: {what}"


@pytest.mark.parametrize(
    "text",
    [
        "Should I call Max tomorrow?",
        "I'll think about it.",  # no day: nothing to ask back
        "Tomorrow is a holiday.",
        "You should call Max tomorrow.",
        "Will you remind me tomorrow?",
    ],
)
def test_questions_undated_plans_and_other_people_are_not_loops(text: str) -> None:
    assert open_loops.detect(text, today=TODAY) == []


def test_a_message_yields_a_few_distinct_loops_at_most() -> None:
    text = (
        "I'll call Max tomorrow. I'll call Max tomorrow. I need to pay rent on Monday! "
        "I will water the plants tonight. I have to write to Anna next week."
    )
    loops = open_loops.detect(text, today=TODAY)
    assert [loop.what for loop in loops] == ["call Max", "pay rent", "water the plants"]


def test_note_remembers_in_the_vault_and_asks_back_once(tmp_path, monkeypatch) -> None:
    clock = {"now": "2026-11-10T09:00:00+00:00"}
    vault = MemoryVault(tmp_path / "vault.db", clock=lambda: clock["now"])
    monkeypatch.setattr(open_loops, "_vault", lambda: vault)
    detect = open_loops.detect
    monkeypatch.setattr(open_loops, "detect", lambda text, today=None: detect(text, today=TODAY))
    try:
        added = open_loops.note_user_text(
            "I'll call Max tomorrow.", session_id="lead", timezone="Europe/Berlin"
        )
        assert added == 1
        # Said twice: still one memory.
        assert open_loops.note_user_text("I'll call Max tomorrow.") == 0
        memory = vault.list(kind="project")[0]
        assert memory.text == "Open loop: call Max" and memory.origin == "inferred"
        assert memory.source["via"] == "open_loop" and memory.source["session"] == "lead"
        # 18:00 Berlin on the due day, written as the vault writes times.
        assert memory.due_at == "2026-11-11T17:00:00+00:00"
        # Not due yet: the check has nothing to ask.
        assert open_loops.due_loops() == []
        clock["now"] = "2026-11-11T17:30:00+00:00"
        due = open_loops.due_loops()
        assert [m.id for m in due] == [memory.id]
        assert open_loops.mark_asked([m.id for m in due]) == 1
        assert open_loops.due_loops() == []
        # Asking does not erase what was said; the memory is closed, not forgotten.
        assert vault.get(memory.id) is not None
    finally:
        vault.close()


def test_without_a_vault_nothing_happens(monkeypatch) -> None:
    monkeypatch.setattr(open_loops, "_vault", lambda: None)
    assert open_loops.note_user_text("I'll call Max tomorrow.") == 0
    assert open_loops.due_loops() == []
    assert open_loops.mark_asked(["x"]) == 0
