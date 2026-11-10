"""The lead conversation's one-time introduction after setup.

Pins: it is due only when setup completes with this build (an install that
finished setup before never sees it), it ends once answered or skipped, a
replayed first run makes it due again, and the route rejects unknown outcomes.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.setup import state as st
from dodaios.ui.web import onboarding_routes


def test_due_after_setup_completes(tmp_path) -> None:
    p = tmp_path / "s.json"
    assert st.is_first_conversation_due(p) is False
    st.mark_onboarding_complete(p)
    assert st.is_first_conversation_due(p) is True
    st.finish_first_conversation("skipped", p)
    assert st.is_first_conversation_due(p) is False
    assert st.load_setup_state(p)["first_conversation_outcome"] == "skipped"


def test_existing_install_never_sees_it(tmp_path) -> None:
    p = tmp_path / "s.json"
    # Setup finished with an older build: completed, but no due marker.
    p.write_text(json.dumps({"onboarding_completed_at": "2026-01-01T00:00:00+00:00"}), "utf-8")
    assert st.is_onboarding_complete(p) is True
    assert st.is_first_conversation_due(p) is False


def test_finished_introduction_is_not_made_due_again_by_a_second_completion(tmp_path) -> None:
    p = tmp_path / "s.json"
    st.mark_onboarding_complete(p)
    st.finish_first_conversation("done", p)
    st.mark_onboarding_complete(p)
    assert st.is_first_conversation_due(p) is False


def test_reset_replays_it(tmp_path) -> None:
    p = tmp_path / "s.json"
    st.mark_onboarding_complete(p)
    st.finish_first_conversation("done", p)
    removed = st.reset_onboarding(p)
    assert "first_conversation_done_at" in removed
    st.mark_onboarding_complete(p)
    assert st.is_first_conversation_due(p) is True


def test_unknown_outcome_is_refused(tmp_path) -> None:
    with pytest.raises(ValueError):
        st.finish_first_conversation("later", tmp_path / "s.json")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(onboarding_routes, "_STATE_PATH_OVERRIDE", tmp_path / "s.json")
    monkeypatch.delenv("JARVIS_FORCE_ONBOARDING", raising=False)
    app = FastAPI()
    app.include_router(onboarding_routes.router)
    return TestClient(app, headers={"Origin": "http://testserver"})


def test_state_payload_and_route(client, tmp_path) -> None:
    assert client.get("/api/onboarding/state").json()["first_conversation_due"] is False
    st.mark_onboarding_complete(tmp_path / "s.json")
    assert client.get("/api/onboarding/state").json()["first_conversation_due"] is True

    bad = client.post("/api/onboarding/first-conversation", json={"outcome": "later"})
    assert bad.status_code == 422
    ok = client.post("/api/onboarding/first-conversation", json={"outcome": "done"})
    assert ok.json() == {"ok": True, "outcome": "done"}
    assert client.get("/api/onboarding/state").json()["first_conversation_due"] is False
