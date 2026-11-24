"""Lead turns on record: what the lead's CLI was handed, and its first move.

``docs/self-improvement.md``, "Lead turns on record". A row is written for a
lead turn only, never fails or slows the turn, ages out, and goes with its chat.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.rsi import lead_turns
from dodaios.rsi.lead_turns import LeadTurn, LeadTurnStore

_DAY_MS = 24 * 60 * 60 * 1000


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The app's ``lead_turns.db`` in a folder of the test's own."""
    path = tmp_path / "data" / lead_turns.DB_NAME
    monkeypatch.setattr(lead_turns, "_db_path", lambda: path)
    monkeypatch.setattr(lead_turns, "_FORGOTTEN", set())
    monkeypatch.setattr(lead_turns, "_warned", False)

    async def no_tools(_session_id: str) -> str:
        return "tools-hash"

    monkeypatch.setattr(lead_turns, "_tools_digest", no_tools)
    yield path
    for found in list(lead_turns._OPEN.values()):  # noqa: SLF001
        found.close()
    lead_turns._OPEN.clear()  # noqa: SLF001


def _turn(session_id: str = "lead-1", *, ts_ms: int = 0, text: str = "x") -> LeadTurn:
    return LeadTurn(
        session_id=session_id,
        turn_id=f"turn-{ts_ms}",
        cli="claude-cli",
        model="m",
        effort="high",
        system=text,
        message="hello",
        tools_digest="t",
        first_kind="text",
        ts_ms=ts_ms,
    )


# ------------------------------------------------------------------ a real turn


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _rows(path: Path) -> list[LeadTurn]:
    return lead_turns.store().turns() if path.exists() else []


def _lead_turn_setup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    moves: list[dict[str, Any]],
    seen: dict[str, Any],
) -> Any:
    """Run ``run_cli_turn`` for real up to the CLI process, which ``moves`` stands in for."""
    from dodaios.agent_chat import dodaios_harness, runner_cli

    identity_file = tmp_path / "identity.md"

    async def no_briefing(_session: Any) -> None:
        return None

    async def build_identity(**kwargs: Any) -> Any:
        identity_file.write_text("SYSTEM: the lead's layers", encoding="utf-8")
        return dodaios_harness.Identity(
            kwargs["session_id"],
            "SYSTEM: the lead's layers",
            "SYSTEM",
            path=identity_file,
            catchup="<since_your_last_turn>a report came in</since_your_last_turn>\n\n",
        )

    async def spawn(plan: Any, cwd: Any, tree: Any, runner: str) -> Any:
        return SimpleNamespace()

    async def drive(handle: Any, proc: Any, plan: Any, runner: str, **_kwargs: Any) -> Any:
        seen["stdin"] = json.loads(plan.stdin_text.splitlines()[0])["message"]["content"]
        seen["system"] = _read(identity_file)
        seen["argv"] = list(plan.argv)
        for move in moves:
            await handle.emit({"kind": move["kind"], "payload": {"turn_id": "t1", **move}})
        return runner_cli._Outcome("done", None, {}, None, plan.vendor_session)  # noqa: SLF001

    monkeypatch.setattr(runner_cli, "_surface_identity", no_briefing)
    monkeypatch.setattr(dodaios_harness, "build_identity", build_identity)
    monkeypatch.setattr(dodaios_harness, "mcp_config_json", lambda *_a: '{"mcpServers": {}}')
    monkeypatch.setattr(runner_cli, "claude_argv_prefix", lambda: ["claude"])
    monkeypatch.setattr(runner_cli, "warm_claude_capabilities", lambda: None)
    monkeypatch.setattr(runner_cli, "_spawn_child", spawn)
    monkeypatch.setattr(runner_cli, "_drive_cli", drive)
    monkeypatch.setattr("dodaios.core.brief_wishes.wishes_line", lambda: "")


def _handle(tmp_path: Path, *, surface: str = "jarvis", events: list | None = None) -> Any:
    from dodaios.agent_chat.runner_api import TurnHandle

    async def emit(event: dict[str, Any]) -> None:
        if events is not None:
            events.append(event)

    async def deny(*_args: Any) -> str:
        return "deny"

    return TurnHandle(
        session=SimpleNamespace(
            surface=surface,
            session_id="lead-1",
            vendor_session="vendor-1",
            account_id="",
            cwd=str(tmp_path),
            provider="claude",
            model="claude-test",
            effort="high",
            permission_mode="default",
        ),
        turn_id="t1",
        emit=emit,
        request_approval=deny,
        cancel=asyncio.Event(),
        surface=surface,
        stance="ask",
    )


async def test_a_lead_turn_is_kept_with_what_the_cli_got_and_its_first_tool_call(
    db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dodaios.agent_chat import runner_cli

    seen: dict[str, Any] = {}
    moves = [
        {"kind": "assistant_text", "text": "Looking for trains now."},
        {
            "kind": "tool_call",
            "call_id": "c1",
            "name": "mcp__dodaios__search_web",
            "input": {"query": "train Hamburg"},
        },
        {"kind": "tool_call", "call_id": "c2", "name": "mcp__dodaios__other", "input": {}},
    ]
    _lead_turn_setup(monkeypatch, tmp_path, moves, seen)
    events: list[dict[str, Any]] = []
    await runner_cli.run_cli_turn(
        _handle(tmp_path, events=events), "Find me a train", "claude-cli", identity=True
    )
    await lead_turns.drain()

    assert events[-1]["kind"] == "turn_finished"
    [row] = lead_turns.store().turns()
    # Exactly what the CLI got: its system-prompt file and its stream-json message.
    assert row.system == seen["system"] == "SYSTEM: the lead's layers"
    assert row.message == seen["stdin"]
    assert row.message.startswith("<since_your_last_turn>")
    assert "<jarvis_turn_settings>" in row.message and "Find me a train" in row.message
    assert row.message.endswith(runner_cli.dodaios_harness.QUESTION_CARD_LINE)
    assert (row.cli, row.model, row.effort) == ("claude-cli", "claude-test", "high")
    assert (row.session_id, row.turn_id, row.resumed) == ("lead-1", "t1", "vendor-1")
    assert row.tools_digest == "tools-hash"
    # The first move: the first tool call, after a line of text.
    assert row.first_kind == "tool"
    assert row.first_tool == "mcp__dodaios__search_web"
    assert row.first_args == {"query": "train Hamburg"}
    assert row.text_before_tool is True
    assert not row.continuation and row.images == 0 and row.app


async def test_a_turn_that_answers_in_text_is_kept_as_text(
    db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dodaios.agent_chat import runner_cli

    seen: dict[str, Any] = {}
    moves = [
        # A sub-agent's call is its own, not the lead's move.
        {"kind": "tool_call", "call_id": "s1", "name": "Read", "input": {}, "agent_id": "a1"},
        {"kind": "assistant_text", "text": "It is sunny."},
    ]
    _lead_turn_setup(monkeypatch, tmp_path, moves, seen)
    await runner_cli.run_cli_turn(
        _handle(tmp_path), "How is the weather?", "claude-cli", identity=True
    )
    await lead_turns.drain()

    [row] = lead_turns.store().turns()
    assert (row.first_kind, row.first_tool, row.first_args) == ("text", "", {})
    assert row.text_before_tool is False


@pytest.mark.parametrize(
    ("surface", "identity", "text"),
    [
        ("jarvis", True, "/project list"),
        ("jarvis", True, "  /context"),
        ("agent", False, "Fix the failing test"),
    ],
)
async def test_a_slash_command_and_another_chat_are_not_kept(
    db_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
    identity: bool,
    text: str,
) -> None:
    from dodaios.agent_chat import runner_cli

    moves = [{"kind": "tool_call", "call_id": "c1", "name": "Read", "input": {}}]
    _lead_turn_setup(monkeypatch, tmp_path, moves, {})
    await runner_cli.run_cli_turn(
        _handle(tmp_path, surface=surface), text, "claude-cli", identity=identity
    )
    await lead_turns.drain()
    assert _rows(db_path) == []


async def test_a_failing_record_never_fails_the_turn_and_is_logged_once(
    db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    from dodaios.agent_chat import runner_cli

    def broken(_turn: LeadTurn) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(lead_turns, "_append", broken)
    moves = [{"kind": "tool_call", "call_id": "c1", "name": "Read", "input": {}}]
    _lead_turn_setup(monkeypatch, tmp_path, moves, {})
    caplog.set_level(logging.DEBUG, logger=lead_turns.__name__)
    for _ in range(2):
        events: list[dict[str, Any]] = []
        result = await runner_cli.run_cli_turn(
            _handle(tmp_path, events=events), "Find me a train", "claude-cli", identity=True
        )
        await lead_turns.drain()
        assert events[-1]["kind"] == "turn_finished"
        assert events[-1]["payload"]["status"] == "done"
        assert result == "vendor-1"
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "logged once" in warnings[0].getMessage()


def test_a_recorder_that_cannot_read_an_event_carries_on(db_path: Path) -> None:
    record = lead_turns.TurnRecorder("lead-1", "t1")
    record.planned(SimpleNamespace(), resume=None)
    record.observe({"kind": "tool_call", "payload": "not a mapping"})  # never raises
    record.finish()


# ------------------------------------------------------------------ the file


def test_rows_older_than_the_retention_go(db_path: Path) -> None:
    now = 1_000 * _DAY_MS
    found = lead_turns.store()
    found.append(_turn(ts_ms=now - (lead_turns.RETENTION_DAYS + 1) * _DAY_MS), now_ms=now)
    found.append(_turn(ts_ms=now - (lead_turns.RETENTION_DAYS - 1) * _DAY_MS), now_ms=now)
    found.append(_turn(ts_ms=now), now_ms=now)
    assert [t.ts_ms for t in found.turns()] == [
        now,
        now - (lead_turns.RETENTION_DAYS - 1) * _DAY_MS,
    ]


def test_the_oldest_rows_go_when_the_file_is_full(db_path: Path) -> None:
    import os

    found = lead_turns.store()
    now = 1_000 * _DAY_MS
    for minute in range(6):
        # Text that does not compress, so each row has a known size.
        found.append(_turn(ts_ms=now + minute, text=os.urandom(3000).hex()), now_ms=now)
    each = found.stored_bytes() // 6
    removed = found.prune(now_ms=now, max_bytes=each * 3 + each // 2)
    assert removed == 3
    assert [t.ts_ms for t in found.turns()] == [now + 5, now + 4, now + 3]
    assert found.stored_bytes() <= each * 3 + each // 2


def test_a_row_is_never_changed(db_path: Path) -> None:
    import sqlite3

    lead_turns.store().append(_turn(ts_ms=lead_turns._now()))  # noqa: SLF001
    raw = sqlite3.connect(db_path)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="never changed"):
            raw.execute("UPDATE turns SET model = 'other'")
    finally:
        raw.close()


def test_deleting_a_chat_deletes_its_rows(db_path: Path, tmp_path: Path) -> None:
    from dodaios.agent_chat.store import AgentChatStore

    chats = AgentChatStore(tmp_path / "chat.db")
    try:
        kept = chats.create_session(
            provider="claude", model="", effort="", surface="jarvis", cwd=str(tmp_path)
        )
        gone = chats.create_session(
            provider="claude", model="", effort="", surface="jarvis", cwd=str(tmp_path)
        )
        now = lead_turns._now()  # noqa: SLF001
        for sid in (kept.session_id, gone.session_id, gone.session_id):
            lead_turns.store().append(_turn(sid, ts_ms=now))
        assert chats.delete_session(gone.session_id)
        assert [t.session_id for t in lead_turns.store().turns()] == [kept.session_id]
        # A turn of the deleted chat still being written is dropped, not stored.
        lead_turns._append(_turn(gone.session_id, ts_ms=now))  # noqa: SLF001
        assert [t.session_id for t in lead_turns.store().turns()] == [kept.session_id]
    finally:
        chats.close()


def test_deleting_a_chat_without_a_record_file_creates_none(db_path: Path) -> None:
    assert lead_turns.forget_session("some-chat") == 0
    assert not db_path.exists()


def test_a_file_from_a_newer_app_is_left_alone(db_path: Path) -> None:
    import sqlite3

    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(db_path)
    raw.execute(f"PRAGMA user_version = {lead_turns.SCHEMA.version + 1}")
    raw.close()
    found = LeadTurnStore(db_path)
    try:
        assert found.readonly
        assert found.forget_session("lead-1") == 0 and found.prune() == 0
    finally:
        found.close()
