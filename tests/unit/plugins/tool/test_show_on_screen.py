"""Exact content goes on screen; the voice keeps the takeaway."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from dodaios.core.events import VoiceContentShown
from dodaios.live import runtime
from dodaios.plugins.tool import show_on_screen
from dodaios.plugins.tool.show_on_screen import MAX_MARKDOWN_CHARS, ShowOnScreenTool

_TABLE = "| file | lines |\n|---|---|\n| app.py | 12 |"


class RecordingBus:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def publish(self, event: object) -> None:
        self.events.append(event)


def _ctx(session_id: str = "") -> SimpleNamespace:
    config = {"live_session_id": session_id} if session_id else {}
    return SimpleNamespace(trace_id=uuid4(), user_utterance="show me", config=config)


@pytest.mark.asyncio
async def test_in_a_live_call_the_content_is_handed_to_that_call(monkeypatch) -> None:
    shown = []

    async def show(session_id: str, *, title: str, markdown: str) -> bool:
        shown.append((session_id, title, markdown))
        return True

    monkeypatch.setattr(runtime, "show_content", show)
    monkeypatch.setattr(show_on_screen, "_app_bus", lambda: pytest.fail("the call owns it"))
    res = await ShowOnScreenTool().execute(
        {"markdown": f"  {_TABLE}\n", "title": "  Changed   files "}, _ctx("call-1")
    )
    assert res.success and res.output == {"shown": True, "kept_in_call": True}
    assert shown == [("call-1", "Changed files", _TABLE)]


@pytest.mark.asyncio
@pytest.mark.parametrize("session_id", ["", "ended-call"])
async def test_without_a_running_call_it_is_still_shown(monkeypatch, session_id) -> None:
    bus = RecordingBus()

    async def gone(session_id: str, *, title: str, markdown: str) -> bool:
        return False

    monkeypatch.setattr(runtime, "show_content", gone)
    monkeypatch.setattr(show_on_screen, "_app_bus", lambda: bus)
    res = await ShowOnScreenTool().execute({"markdown": _TABLE}, _ctx(session_id))
    assert res.success and res.output["kept_in_call"] is False
    (event,) = bus.events
    assert isinstance(event, VoiceContentShown)
    assert (event.session_id, event.title, event.markdown) == ("", "", _TABLE)


@pytest.mark.asyncio
async def test_nothing_to_show_or_nowhere_to_show_it_is_an_error(monkeypatch) -> None:
    monkeypatch.setattr(show_on_screen, "_app_bus", lambda: None)
    tool = ShowOnScreenTool()
    assert (await tool.execute({"markdown": "   "}, _ctx())).error == "markdown is missing"
    too_long = await tool.execute({"markdown": "x" * (MAX_MARKDOWN_CHARS + 1)}, _ctx())
    assert too_long.success is False and "Too long to show" in too_long.error
    nowhere = await tool.execute({"markdown": _TABLE}, _ctx())
    assert nowhere.success is False and "No screen" in nowhere.error


@pytest.mark.asyncio
async def test_the_runtime_reports_a_call_that_is_not_running() -> None:
    assert await runtime.show_content("no-such-call", title="", markdown=_TABLE) is False


# --- inside the call: kept in its record, announced to the screen ------------------


@pytest.mark.asyncio
async def test_a_call_keeps_shown_content_in_its_record_after_the_last_words(tmp_path) -> None:
    from dodaios.live.session import LiveVoiceSession
    from dodaios.live.state import LiveLedger, TranscriptFragment

    ledger = LiveLedger(tmp_path / "live.sqlite3")
    bus = RecordingBus()
    call = SimpleNamespace(session_id="call-1", _ledger=ledger, _bus=bus)
    try:
        ledger.append(TranscriptFragment("call-1", "e1", "user", "Which files changed?", 100, 900))
        await LiveVoiceSession.show_content(call, title="Changed files", markdown=_TABLE)
        rows = ledger.transcript("call-1")
    finally:
        ledger.close()
    assert [row["role"] for row in rows] == ["user", "assistant"]
    assert rows[1]["start_ms"] == 901  # right after what was said last
    assert rows[1]["delta"] == f"\n\n**Changed files**\n\n{_TABLE}\n\n"
    (event,) = bus.events
    assert isinstance(event, VoiceContentShown)
    assert (event.session_id, event.title, event.markdown) == ("call-1", "Changed files", _TABLE)


@pytest.mark.asyncio
async def test_a_title_or_id_finds_one_conversation(monkeypatch) -> None:
    from dodaios.core import runtime_refs
    from dodaios.plugins.tool import navigate

    class Store:
        def list_sessions(self, limit: int, *, surface: str):
            assert surface == "jarvis"
            return [
                SimpleNamespace(session_id="s-2", title="Trip to Lisbon"),
                SimpleNamespace(session_id="s-1", title="Trip to Lisbon"),
                SimpleNamespace(session_id="s-0", title="Tax  questions"),
            ]

    app = SimpleNamespace(state=SimpleNamespace(agent_chat=SimpleNamespace(store=Store())))
    monkeypatch.setattr(runtime_refs, "get_web_app", lambda: app)
    newest = await navigate._find_chat("trip to lisbon")
    assert newest == {"status": "found", "id": "s-2", "name": "Trip to Lisbon"}
    assert (await navigate._find_chat("s-0"))["id"] == "s-0"
    assert (await navigate._find_chat("tax questions"))["id"] == "s-0"
    assert (await navigate._find_chat("t"))["status"] == "ask"
    unknown = await navigate._find_chat("no such chat")
    assert unknown["status"] == "unknown" and "Trip to Lisbon" in unknown["available"]
    monkeypatch.setattr(runtime_refs, "get_web_app", lambda: None)
    assert (await navigate._find_chat("anything"))["status"] == "unavailable"
