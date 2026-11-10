"""The lead keeps one endless conversation (dodaios/agent_chat/lead.py)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from dodaios.agent_chat import lead
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore, ChatSelection


def _service(cwd: Path, path: str = ":memory:") -> AgentChatService:
    store = AgentChatStore(path)
    return AgentChatService(store, assistant_name=lambda: "Dodaios", default_cwd=lambda: str(cwd))


def test_first_use_creates_one_conversation_on_the_chat_pick(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.store.save_chat_selection(ChatSelection("openai", "m", "low"))
    first = svc.lead_session()
    assert first is not None
    assert (first.provider, first.model, first.surface) == ("openai", "m", "jarvis")
    assert svc.lead_session().session_id == first.session_id
    assert svc.store.lead_session_id() == first.session_id
    assert len(svc.store.list_sessions(limit=10, surface="jarvis")) == 1


def test_an_upgrade_adopts_the_newest_existing_chat(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.create_session(provider="openai", model="m", effort="low", surface="jarvis")
    newest = svc.create_session(provider="openai", model="m", effort="low", surface="jarvis")
    svc.store._conn.execute(  # noqa: SLF001 — make "newest" unambiguous
        "UPDATE agent_chat_sessions SET updated_ms = updated_ms + 10000 WHERE session_id = ?",
        (newest.session_id,),
    )
    assert svc.lead_session().session_id == newest.session_id
    # Once chosen, a later chat never takes the lead's place.
    svc.create_session(provider="openai", model="m", effort="low", surface="jarvis")
    assert svc.lead_session().session_id == newest.session_id


def test_the_choice_survives_a_restart(tmp_path: Path) -> None:
    db = str(tmp_path / "agent_chat.db")
    first = _service(tmp_path, db)
    first.store.save_chat_selection(ChatSelection("openai", "m", "low"))
    sid = first.lead_session().session_id
    first.store.close()
    again = _service(tmp_path, db)
    assert again.lead_session().session_id == sid


def test_a_deleted_lead_is_replaced(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.store.save_chat_selection(ChatSelection("openai", "m", "low"))
    sid = svc.lead_session().session_id
    svc.store.delete_session(sid)
    replacement = svc.lead_session()
    assert replacement is not None and replacement.session_id != sid
    assert lead.is_lead(svc, replacement.session_id)


def test_create_false_never_writes(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    assert lead.lead_session(svc, create=False) is None
    assert svc.store.list_sessions(limit=10, surface="jarvis") == []


def test_a_new_pick_changes_the_seat_not_the_conversation(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    svc.store.save_chat_selection(ChatSelection("openai", "m", "low"))
    sid = svc.lead_session().session_id
    updated = lead.adopt_seat(svc, {"provider": "openai", "model": "other", "effort": None})
    assert updated.session_id == sid
    assert updated.model == "other"
    with pytest.raises(ValueError):
        lead.adopt_seat(svc, {"provider": "no-such-provider"})


def test_voice_history_is_the_conversation_tail(tmp_path: Path) -> None:
    async def scenario() -> None:
        svc = _service(tmp_path)
        svc.store.save_chat_selection(ChatSelection("openai", "m", "low"))
        sid = svc.lead_session().session_id
        for i in range(30):
            await svc.import_voice_turn(sid, f"question {i}", f"answer {i}", voice_turn_id=f"v{i}")
        events = svc.store.list_events(sid)
        # More than the old 40-message window; the char budget decides.
        full = lead.voice_history(sid, events)
        assert len(full) == 60
        assert full[-1].content == "answer 29"
        small = lead.voice_history(sid, events, max_chars=200)
        assert 0 < len(small) < 60
        assert small[-1].content == "answer 29"
        # An unbound call starts on the lead's conversation.
        assert [m.content for m in svc.voice_chat_history()][-1] == "answer 29"

    asyncio.run(scenario())


def test_routes_return_the_one_conversation_and_keep_it(tmp_path: Path, monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from dodaios.ui.web import agent_chat_routes

    async def no_live_models() -> dict:
        return {}

    monkeypatch.setattr(agent_chat_routes, "_live_cli_models", no_live_models)
    monkeypatch.setattr(agent_chat_routes, "_cli_installed", lambda runner: False)
    application = FastAPI()
    application.include_router(agent_chat_routes.router)
    application.state.agent_chat = _service(tmp_path, str(tmp_path / "chat.db"))
    with TestClient(application) as client:
        body = {"surface": "jarvis", "provider": "openai", "model": "first", "cwd": str(tmp_path)}
        first = client.post("/api/agent-chat/sessions", json=body)
        assert first.status_code == 201, first.text
        assert first.json()["lead"] is True
        second = client.post("/api/agent-chat/sessions", json={**body, "model": "second"})
        assert second.json()["session_id"] == first.json()["session_id"]
        assert second.json()["model"] == "second"
        sid = first.json()["session_id"]
        refused = client.delete(f"/api/agent-chat/sessions/{sid}")
        assert refused.status_code == 409
        # Coding chats keep their own sessions.
        coding = client.post(
            "/api/agent-chat/sessions", json={**body, "surface": "agent", "provider": "openai"}
        )
        assert coding.json()["session_id"] != sid


def test_memory_search_finds_what_was_said_in_the_conversation(tmp_path: Path) -> None:
    from dodaios.plugins.tool.memory_vault import MemorySearchTool
    from dodaios.society.conversation import ConversationArchive

    class _Runtime:
        def __init__(self, svc: AgentChatService) -> None:
            self.conversations = ConversationArchive(tmp_path / "archive.db")
            self._svc = svc

        def chat_service(self) -> AgentChatService:
            return self._svc

    async def scenario() -> None:
        svc = _service(tmp_path)
        svc.store.save_chat_selection(ChatSelection("openai", "m", "low"))
        sid = svc.lead_session().session_id
        await svc.import_voice_turn(
            sid, "My sister's wedding is in Lisbon in June", "Noted, Lisbon in June."
        )
        await svc.import_voice_turn(sid, "What's the weather?", "Sunny.")
        from dodaios.society import runtime as society_runtime

        previous = society_runtime.current_runtime()
        society_runtime.set_current_runtime(_Runtime(svc))  # type: ignore[arg-type]
        try:
            rows = lead.search_conversation("wedding Lisbon")
            assert rows and rows[0]["date"]
            assert any("Lisbon" in r["text"] and r["who"] == "user" for r in rows)
            result = await MemorySearchTool().execute({"query": "wedding Lisbon"}, None)  # type: ignore[arg-type]
            assert result.success
            assert any("Lisbon" in r["text"] for r in result.output["conversation"])
        finally:
            society_runtime.set_current_runtime(previous)

    asyncio.run(scenario())


def test_learned_memories_appear_in_the_conversation(tmp_path: Path) -> None:
    from dodaios.memory.vault import reconcile
    from dodaios.memory.vault.store import MemoryVault

    class _Runtime:
        def __init__(self, svc: AgentChatService) -> None:
            self._svc = svc

        def chat_service(self) -> AgentChatService:
            return self._svc

    async def scenario() -> None:
        svc = _service(tmp_path)
        svc.store.save_chat_selection(ChatSelection("openai", "m", "low"))
        sid = svc.lead_session().session_id
        vault = MemoryVault(tmp_path / "vault.db")
        receipts: list[dict[str, str]] = []
        op = reconcile.Op(
            op="add",
            text="Sister's wedding is in Lisbon in June",
            kind="relationship",
            evidence="wedding is in Lisbon",
        )
        anchors = [{"user": "My sister's wedding is in Lisbon in June.", "message_seq": 5}]
        assert (
            reconcile.apply(vault, [op], source={"via": "test"}, receipts=receipts, anchors=anchors)
            == 1
        )
        assert receipts[0]["op"] == "added" and receipts[0]["id"]
        from dodaios.society import runtime as society_runtime

        previous = society_runtime.current_runtime()
        society_runtime.set_current_runtime(_Runtime(svc))  # type: ignore[arg-type]
        try:
            await lead.post_learned(receipts)
        finally:
            society_runtime.set_current_runtime(previous)
        notices = [e for e in svc.store.list_events(sid) if e["kind"] == "notice"]
        assert notices[-1]["payload"]["kind"] == "memory_learned"
        assert "Lisbon" in notices[-1]["payload"]["items"][0]["text"]
        # The notice links back to the message the memory was learned from.
        assert notices[-1]["payload"]["items"][0]["message_seq"] == 5
        assert notices[-1]["payload"]["items"][0]["evidence"] == "wedding is in Lisbon"

    asyncio.run(scenario())


def test_fresh_start_drops_earlier_history_but_keeps_the_thread(tmp_path: Path) -> None:
    from dodaios.society.conversation import ConversationArchive

    class _Runtime:
        def __init__(self, svc: AgentChatService) -> None:
            self.conversations = ConversationArchive(tmp_path / "archive.db")
            self._svc = svc

        def chat_service(self) -> AgentChatService:
            return self._svc

    async def scenario() -> None:
        svc = _service(tmp_path)
        svc.store.save_chat_selection(ChatSelection("openai", "m", "low"))
        sid = svc.lead_session().session_id
        await svc.import_voice_turn(sid, "old question", "old answer")
        from dodaios.society import runtime as society_runtime

        previous = society_runtime.current_runtime()
        society_runtime.set_current_runtime(_Runtime(svc))  # type: ignore[arg-type]
        try:
            through = lead.fresh_start(svc)
            assert through and through >= 4
            await svc.import_voice_turn(sid, "new question", "new answer")
            history = lead.voice_history(sid, svc.store.list_events(sid))
            texts = [m.content for m in history]
            assert "old question" not in texts
            assert "new question" in texts
            assert lead.FRESH_START_SUMMARY in texts[0]
            # The thread itself still holds everything.
            assert len(svc.store.list_events(sid)) == 8
        finally:
            society_runtime.set_current_runtime(previous)

    asyncio.run(scenario())


def test_answer_in_lead_returns_the_reply_of_its_own_turn(tmp_path: Path, monkeypatch) -> None:
    async def scenario() -> None:
        svc = _service(tmp_path)
        svc.store.save_chat_selection(ChatSelection("openai", "m", "low"))
        sid = svc.lead_session().session_id

        async def fake_send(svc_, session_id, text, attachments=None, *, tool_choices=None):
            async def run() -> None:
                from dodaios.agent_chat.events import make_event

                await asyncio.sleep(0.01)
                await svc._emit(session_id, make_event("user_message", {"text": text}))  # noqa: SLF001
                await svc._emit(session_id, make_event("turn_started", {"turn_id": "t9"}))  # noqa: SLF001
                await svc._emit(  # noqa: SLF001
                    session_id,
                    make_event("assistant_text", {"turn_id": "t9", "text": "Hello back"}),
                )
                await svc._emit(  # noqa: SLF001
                    session_id, make_event("turn_finished", {"turn_id": "t9", "status": "done"})
                )

            asyncio.get_running_loop().create_task(run())
            return "", "queued-1"

        monkeypatch.setattr("dodaios.agent_chat.send_queue.send_or_queue", fake_send)
        answer = await lead.answer_in_lead(svc, "Hello", source="telegram", timeout_s=5)
        assert answer == "Hello back"
        assert sid

    asyncio.run(scenario())
