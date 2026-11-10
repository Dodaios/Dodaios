"""The undo ledger and the built-in inverses."""

from __future__ import annotations

import asyncio
from typing import Any

from dodaios.core.protocols import ToolResult
from dodaios.trust import inverses
from dodaios.trust.undo import UndoLedger, inverse_for, register_inverse


def test_archiving_a_mail_is_undone_by_putting_it_back() -> None:
    args = {"action": "modify_message", "message_id": "m1", "remove_labels": ["INBOX", "UNREAD"]}
    inverse = inverses.gmail_inverse(args, {"id": "m1"})
    assert inverse == {
        "tool": "gmail",
        "args": {
            "action": "modify_message",
            "message_id": "m1",
            "add_labels": ["INBOX", "UNREAD"],
            "remove_labels": [],
        },
        "label": "Archived a mail",
    }
    assert inverses.gmail_inverse({"action": "send_message", "to": "a@b.c"}, {}) is None


def test_a_created_event_is_undone_by_deleting_it() -> None:
    args = {
        "action": "create_event",
        "summary": "Dentist",
        "start": "s",
        "end": "e",
        "calendar_id": "work",
    }
    inverse = inverses.calendar_inverse(args, {"id": "ev1", "summary": "Dentist"})
    assert inverse == {
        "tool": "google_calendar",
        "args": {"action": "delete_event", "event_id": "ev1", "calendar_id": "work"},
        "label": "Created an event: Dentist",
    }
    assert inverses.calendar_inverse(args, {"status": "ok"}) is None, "no id, no undo"


def test_a_saved_memory_is_undone_by_forgetting_that_fact() -> None:
    inverse = inverses.remember_inverse({"fact": "I like tea"}, "Saved to memory: I like tea")
    assert inverse == {
        "tool": "memory-forget",
        "args": {"about": "I like tea"},
        "label": "Saved a memory: I like tea",
    }
    assert inverses.remember_inverse({"fact": "x"}, "Already in memory: x") is None


def test_the_ledger_records_tells_and_runs_the_inverse() -> None:
    ledger = UndoLedger()
    heard: list[dict[str, Any]] = []
    off = ledger.on_recorded(heard.append)
    ran: list[tuple[str, dict[str, Any], str]] = []

    async def runner(tool: str, args: dict[str, Any], entry: dict[str, Any]) -> ToolResult:
        ran.append((tool, args, entry["id"]))
        return ToolResult(success=True, output="ok")

    ledger.set_runner(runner)
    args = {"action": "modify_message", "message_id": "m1", "remove_labels": ["INBOX"]}
    entry = ledger.record(
        "mcp__dodaios__gmail", args, {"id": "m1"}, {"approval_ref": "agent-chat:s1"}
    )
    assert entry is not None and entry["session_id"] == "s1" and entry["tool"] == "gmail"
    assert heard == [entry]
    assert ledger.record("gmail", {"action": "list_messages"}, {}, None) is None, (
        "no inverse, no entry"
    )
    assert ledger.record("gmail", args, {"id": "m1"}, {"undo_of": "x"}) is None, (
        "an undo is not undoable"
    )

    done = asyncio.run(ledger.undo(entry["id"]))
    assert done["state"] == "undone" and ran == [("gmail", entry["inverse"]["args"], entry["id"])]
    assert asyncio.run(ledger.undo(entry["id"]))["state"] == "undone", (
        "a second click changes nothing"
    )
    off()
    ledger.record("gmail", args, {"id": "m2"}, None)
    assert len(heard) == 1


def test_an_expired_or_failing_undo_says_so() -> None:
    ledger = UndoLedger(window_ms=-1)
    entry = ledger.record(
        "gmail", {"action": "modify_message", "message_id": "m", "add_labels": ["X"]}, {}, None
    )
    assert asyncio.run(ledger.undo(entry["id"]))["state"] == "expired"

    ledger = UndoLedger()
    entry = ledger.record(
        "gmail", {"action": "modify_message", "message_id": "m", "add_labels": ["X"]}, {}, None
    )
    assert asyncio.run(ledger.undo(entry["id"]))["state"] == "failed", "no runner installed"

    async def refuse(tool: str, args: dict[str, Any], entry: dict[str, Any]) -> ToolResult:
        return ToolResult(success=False, output=None, error="approval-unavailable")

    ledger = UndoLedger()
    ledger.set_runner(refuse)
    entry = ledger.record(
        "gmail", {"action": "modify_message", "message_id": "m", "add_labels": ["X"]}, {}, None
    )
    done = asyncio.run(ledger.undo(entry["id"]))
    assert done["state"] == "failed" and done["error"] == "approval-unavailable"


def test_a_plugin_registers_its_own_inverse() -> None:
    register_inverse(
        "my-notes",
        lambda args, out: {
            "tool": "my-notes",
            "args": {"action": "delete", "id": out},
            "label": "Added a note",
        },
    )
    assert inverse_for("my-notes", {"action": "add"}, "n1") == {
        "tool": "my-notes",
        "args": {"action": "delete", "id": "n1"},
        "label": "Added a note",
    }
    register_inverse("my-notes", lambda args, out: 1 / 0)
    assert inverse_for("my-notes", {}, "n1") is None, (
        "a broken inverse means no undo, never an error"
    )
