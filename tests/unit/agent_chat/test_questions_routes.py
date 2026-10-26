"""The question card's routes: reviewed submit, single-question skip, touch, chat reply."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agent_chat.questions import parse_questions
from dodaios.agent_chat.service import AgentChatService, _Running
from dodaios.agent_chat.store import AgentChatStore
from dodaios.ui.web.agent_chat_routes import router

_DB: dict[str, Any] = {
    "question": "Which database?",
    "options": [{"label": "SQLite"}, {"label": "Postgres"}],
}
_FEATURES: dict[str, Any] = {
    "question": "Which features?",
    "multi": True,
    "options": [{"label": "Search"}, {"label": "Export"}, {"label": "Sharing"}],
}


def test_the_card_routes_drive_a_live_card(tmp_path: Path) -> None:
    svc = AgentChatService(AgentChatStore(":memory:"))
    sid = svc.store.create_session(provider="p", model="m", effort="", cwd=str(tmp_path)).session_id

    async def open_cards() -> tuple[str, str]:
        run = _Running("t1", asyncio.Event())
        run.task = asyncio.ensure_future(asyncio.sleep(3600))
        svc._running[sid] = run
        first = await svc.open_questions(sid, parse_questions({"questions": [_DB, _FEATURES]}))
        second = await svc.open_questions(sid, parse_questions(_DB))
        return first, second

    app = FastAPI()
    app.include_router(router)
    app.state.agent_chat = svc
    with TestClient(app) as client:
        # The service's cards live on the client's loop.
        first, second = client.portal.call(open_cards)  # type: ignore[union-attr]
        base = f"/api/agent-chat/sessions/{sid}/questions"
        assert client.post(f"{base}/{first}/touch").json() == {"ok": True}
        bad = client.post(f"{base}/{first}/submit", json={"answers": [{"option_index": 9}, {}]})
        assert bad.status_code == 400
        assert client.post(f"{base}/{first}/skip", json={"index": 0}).status_code == 200
        picks = {"answers": [{}, {"option_indices": [0, 2]}]}
        ok = client.post(f"{base}/{first}/submit", json=picks)
        assert ok.status_code == 200
        assert client.post(f"{base}/{first}/submit", json={"answers": [{}, {}]}).status_code == 404
        reply = client.post(f"/api/agent-chat/sessions/{sid}/reply-to-question", json={"text": "a"})
        assert reply.json() == {"ok": True, "consumed": True, "question_id": second}
        assert svc.pending_questions(sid) == []
        answers = client.portal.call(svc.wait_questions, sid, first, 5)  # type: ignore[union-attr]
        assert [(a.answer, a.source) for a in answers] == [
            ("", "declined"),
            ("Search\nSharing", "person"),
        ]
