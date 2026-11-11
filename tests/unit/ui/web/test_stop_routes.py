"""The desk's stop, resume and the list of stops in force."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.orchestrator import jobs
from dodaios.safety.stop_hold import stop_holds
from dodaios.ui.web.trust_routes import router


@pytest.fixture
def client():
    ledger = jobs.JobLedger(":memory:")
    jobs.set_ledger(ledger)
    app = FastAPI()
    app.include_router(router)
    app.state.agent_chat = None
    try:
        yield TestClient(app)
    finally:
        jobs.set_ledger(None)
        ledger.close()


def test_stop_lists_resume_and_lift(client) -> None:
    jobs.get_ledger().create("mission", job_id="j1", title="m", state="running")
    body = client.post("/api/trust/stop-everything", params={"reason": "enough"}).json()
    assert body["ok"] and body["report"]["jobs"] == 1
    assert body["message"].startswith("Stopped.")
    listed = client.get("/api/trust/stop-holds").json()
    assert listed["everything"] and listed["holds"][0]["reason"] == "enough"
    assert listed["holds"][0]["source"] == "desk"

    stop_holds().hold("agent", "ada", reason="r")
    assert client.delete("/api/trust/stop-holds", params={"kind": "agent", "ref": "ada"}).json()["ok"]
    assert client.delete("/api/trust/stop-holds", params={"kind": "agent", "ref": "ada"}).status_code == 404
    assert client.delete("/api/trust/stop-holds", params={"kind": "planet", "ref": "x"}).status_code == 400

    resumed = client.post("/api/trust/resume-everything").json()
    assert resumed["was_held"] and "Resumed" in resumed["message"]
    assert client.get("/api/trust/stop-holds").json()["everything"] is False
