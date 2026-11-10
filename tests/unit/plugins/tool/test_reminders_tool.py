"""The ``reminders`` tool: create, list, done, snooze and the brain dump."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from dodaios.core.protocols import ExecutionContext
from dodaios.memory.vault import MemoryVault
from dodaios.memory.vault import runtime as vault_runtime
from dodaios.plugins.tool import reminders as tool_module
from dodaios.plugins.tool.reminders import RemindersTool

NOW = datetime(2026, 11, 10, 10, 30, tzinfo=ZoneInfo("Europe/Berlin"))


class _FixedNow(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
        return NOW.astimezone(tz) if tz else NOW


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MemoryVault:
    v = MemoryVault(
        tmp_path / "vault.db", clock=lambda: NOW.astimezone(UTC).isoformat(timespec="seconds")
    )
    vault_runtime.set_active(v)
    monkeypatch.setattr(tool_module, "datetime", _FixedNow)
    yield v
    vault_runtime.set_active(None)


def _ctx(said: str = "") -> ExecutionContext:
    return ExecutionContext(
        trace_id=uuid4(), user_utterance=said, config={}, memory_read=None, approved_by="auto"
    )


async def test_create_list_snooze_done(vault: MemoryVault) -> None:
    tool = RemindersTool()
    created = await tool.execute(
        {
            "action": "create",
            "text": "the taxes",
            "when": "Friday at 9",
            "timezone": "Europe/Berlin",
        },
        _ctx("remind me Friday at 9 about the taxes"),
    )
    assert created.success and created.output["due_local"] == "2026-11-13T09:00+01:00"
    assert created.output["has_time"] is True and created.output["existing"] is False
    memory_id = created.output["id"]
    assert vault.get(memory_id).source["evidence"].startswith("remind me Friday")

    listed = await tool.execute({"action": "list", "timezone": "Europe/Berlin"}, _ctx())
    assert [r["id"] for r in listed.output["items"]] == [memory_id]
    assert listed.output["items"][0]["due_local"] == "2026-11-13T09:00+01:00"

    snoozed = await tool.execute(
        {"action": "snooze", "id": memory_id, "when": "tomorrow", "timezone": "Europe/Berlin"},
        _ctx(),
    )
    assert snoozed.success and snoozed.output["due_local"] == "2026-11-11T09:00+01:00"
    done = await tool.execute({"action": "done", "id": snoozed.output["id"]}, _ctx())
    assert done.success
    empty = await tool.execute({"action": "list"}, _ctx())
    assert empty.output == "Nothing is coming up."


async def test_a_missing_time_asks_instead_of_guessing(vault: MemoryVault) -> None:
    result = await RemindersTool().execute({"action": "create", "text": "mail Anna"}, _ctx())
    assert result.success and result.output["needs_time"] is True
    assert result.output["text"] == "mail Anna"
    assert vault.upcoming(days=365) == []


async def test_the_time_may_live_in_the_utterance(vault: MemoryVault) -> None:
    result = await RemindersTool().execute(
        {"action": "create", "text": "", "timezone": "Europe/Berlin"},
        _ctx("erinnere mich morgen um 9 Uhr an die Steuer"),
    )
    assert result.success and result.output["text"] == "die Steuer"
    assert result.output["due_local"] == "2026-11-11T09:00+01:00"


async def test_capture_stores_items_and_posts_the_card(
    vault: MemoryVault, monkeypatch: pytest.MonkeyPatch
) -> None:
    posted: list[dict[str, Any]] = []

    async def _post(svc: Any, sid: str, payload: dict[str, Any]) -> str:
        posted.append(payload)
        return "n-1"

    monkeypatch.setattr(tool_module.reminders, "lead_target", lambda: (object(), "lead"))
    monkeypatch.setattr(tool_module.reminders, "post_notice", _post)
    result = await RemindersTool().execute(
        {"action": "capture", "text": "tomorrow dentist, buy milk, mail Anna about the offer"},
        _ctx(),
    )
    assert result.success
    assert [r["text"] for r in result.output["items"]] == [
        "dentist",
        "buy milk",
        "mail Anna about the offer",
    ]
    assert posted[0]["kind"] == "tasks_captured" and len(posted[0]["items"]) == 3


async def test_errors_are_named(vault: MemoryVault) -> None:
    tool = RemindersTool()
    assert (await tool.execute({"action": "dance"}, _ctx())).success is False
    assert (await tool.execute({"action": "done"}, _ctx())).error == "id is missing"
    assert (await tool.execute({"action": "done", "id": "nope"}, _ctx())).success is False
    assert (await tool.execute({"action": "snooze", "id": "nope"}, _ctx())).success is False
    assert (await tool.execute({"action": "create"}, _ctx())).error == "text is missing"
    vault_runtime.set_active(None)
    assert (await tool.execute({"action": "list"}, _ctx())).error == "memory is not running"
