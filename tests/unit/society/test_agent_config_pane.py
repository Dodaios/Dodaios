"""The agent pane's configuration and learning review, headless.

* every field the pane edits round-trips through ``PATCH /api/society/agents/{id}``
  and the roster validators, and a bad value is refused rather than stored;
* a tool change on a Hermes or OpenClaw agent reaches its very next tool call,
  because the CLI/ACP tool filter re-reads the roster row every time;
* the review queue lists real proposal, knowledge-share and memory rows, and
  approve / reject act on them through the existing resolve paths.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agent_chat.store import AgentChatStore
from dodaios.society.runtime import SocietyRuntime
from dodaios.society.surface import tools_for_cli_session
from dodaios.ui.web.society_routes import router
from tests.fakes.fake_agent_chat import FakeChatService


def _tool(name: str, desc: str) -> SimpleNamespace:
    return SimpleNamespace(
        name=name, description=desc, risk_tier="monitor", parameters={}, schema={}
    )


TOOLS = {
    "gmail": _tool("gmail", "Read and send mail."),
    "google_calendar": _tool("google_calendar", "Read the calendar."),
    "cli_gh": _tool("cli_gh", "GitHub CLI."),
}


def _app(tmp_path: Path) -> tuple[FastAPI, SocietyRuntime]:
    runtime = SocietyRuntime(tmp_path, seed_starter_team=False, brain_tools=lambda: TOOLS)
    app = FastAPI()
    app.include_router(router)
    app.state.society_factory = lambda: runtime
    return app, runtime


# ------------------------------------------------------------------ PATCH


def test_every_pane_field_round_trips_through_patch(tmp_path: Path) -> None:
    app, _ = _app(tmp_path)
    with TestClient(app) as c:
        c.post("/api/society/agents", json={"name": "Mailbox", "description": "Handle my mail."})
        body = {
            "grant_mode": "allowlist",
            "grants": ["plugin:gmail", "cli:gh"],
            "focus": ["plugin:gmail"],
            "denies": ["plugin:google_calendar"],
            "permission_ceiling": "ask",
            "approval_rules": {"require_approval": ["plugin:gmail:send"], "always_allow": []},
            "daily_budget_usd": 7.5,
            "max_concurrent_runs": 3,
            "browser_mode": "attach",
            "browser_allowed_domains": ["Mail.Google.com", "mail.google.com"],
        }
        response = c.patch("/api/society/agents/mailbox", json=body)
        assert response.status_code == 200, response.text
        agent = c.get("/api/society/agents/mailbox").json()["agent"]
        assert agent["grant_mode"] == "allowlist"
        assert agent["grants"] == ["cli:gh", "plugin:gmail"]
        assert agent["focus"] == ["plugin:gmail"]
        assert agent["denies"] == ["plugin:google_calendar"]
        assert agent["permission_ceiling"] == "ask"
        assert agent["approval_rules"] == {
            "require_approval": ["plugin:gmail:send"],
            "always_allow": [],
        }
        assert agent["daily_budget_usd"] == 7.5
        assert agent["max_concurrent_runs"] == 3
        assert agent["browser_mode"] == "attach"
        assert agent["browser_allowed_domains"] == ["mail.google.com"]
        # Nothing the pane did not send moved: the instructions stay as written.
        assert agent["description"] == "Handle my mail."

        renamed = c.patch("/api/society/agents/mailbox", json={"name": "Inbox", "title": "Mail"})
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["agent"]["name"] == "Inbox"
        assert renamed.json()["agent"]["title"] == "Mail"


@pytest.mark.parametrize(
    "body",
    [
        {"browser_mode": "everywhere"},
        {"grant_mode": "some"},
        {"permission_ceiling": "block"},
        {"max_concurrent_runs": 11},
        {"daily_budget_usd": -1},
        {"approval_rules": {"require_approval": "plugin:gmail"}},
        {"name": "a/b"},
    ],
)
def test_a_bad_value_is_refused_and_nothing_is_stored(tmp_path: Path, body: dict) -> None:
    app, _ = _app(tmp_path)
    with TestClient(app) as c:
        c.post("/api/society/agents", json={"name": "Mailbox"})
        before = c.get("/api/society/agents/mailbox").json()["agent"]
        response = c.patch("/api/society/agents/mailbox", json=body)
        assert 400 <= response.status_code < 500, response.text
        after = c.get("/api/society/agents/mailbox").json()["agent"]
        assert {k: after[k] for k in before if k != "stats"} == {
            k: before[k] for k in before if k != "stats"
        }


# ------------------------------------------------- per-turn tool filtering


@pytest.mark.parametrize("runtime", ["hermes", "openclaw"])
async def test_a_tool_change_reaches_the_runtime_on_its_next_call(
    tmp_path: Path, runtime: str
) -> None:
    chat_store = AgentChatStore(tmp_path / "chat.db")
    service = FakeChatService(chat_store)
    cfg = SimpleNamespace(memory=SimpleNamespace(data_dir=str(tmp_path)))
    rt = SocietyRuntime(
        tmp_path, seed_starter_team=False, chat_service=lambda: service, cfg=lambda: cfg
    )
    await rt.ensure_started()
    try:
        agent, _ = await rt.roster.create(name="Remote", runtime=runtime, provider="openai")
        chat_store.create_session(
            session_id=agent.session_id,
            surface="society",
            provider="openai",
            model="test-model",
            effort="medium",
            cwd=str(tmp_path / "workspace"),
            permission_mode="bypass",
            runtime=runtime,
        )
        brain = SimpleNamespace(_tools={}, _config=cfg)

        async def names() -> list[str]:
            picked = await tools_for_cli_session(agent.session_id, dict(TOOLS), brain)
            assert picked is not None
            # The agent's own hands (society_*, its folder tools) always stay.
            return [n for n in picked if n in TOOLS]

        assert {"gmail", "cli_gh", "google_calendar"} <= set(await names())

        await rt.roster.update(agent.agent_id, {"denies": ["plugin:gmail"]})
        assert "gmail" not in await names()

        await rt.roster.update(
            agent.agent_id,
            {"denies": [], "grant_mode": "allowlist", "grants": ["cli:gh"], "focus": ["cli:gh"]},
        )
        assert await names() == ["cli_gh"]
    finally:
        await rt.close()
        chat_store.close()


# ----------------------------------------------------------- review queue


def test_the_review_queue_decides_real_proposals(tmp_path: Path) -> None:
    app, _ = _app(tmp_path)
    with TestClient(app) as c:
        c.post("/api/society/agents", json={"name": "Mailbox", "description": "Handle my mail."})
        c.post("/api/society/agents", json={"name": "Other"})

        def park(agent_id: str, text: str) -> str:
            return c.post(
                "/api/society/approvals",
                json={
                    "agent_id": agent_id,
                    "capability": "core:config:rule",
                    "action": {"kind": "rule", "payload": {"text": text}, "reason": "asked"},
                    "summary": f"Add a standing rule: {text}",
                },
            ).json()["approval"]["id"]

        keep = park("mailbox", "Be brief.")
        drop = park("mailbox", "Use emoji.")
        park("other", "Not mine.")

        queue = c.get("/api/society/agents/mailbox/review-queue").json()
        ids = {item["id"] for item in queue["items"]}
        assert ids == {f"proposal:{keep}", f"proposal:{drop}"}
        assert queue["counts"]["proposal"] == 2
        item = next(i for i in queue["items"] if i["id"] == f"proposal:{keep}")
        assert item["proposal_kind"] == "rule"
        assert item["preview"] == ["+ Be brief."]

        approved = c.post(f"/api/society/agents/mailbox/review/proposal:{keep}/approve")
        assert approved.status_code == 200, approved.text
        assert approved.json()["outcome"] == "applied"
        rejected = c.post(f"/api/society/agents/mailbox/review/proposal:{drop}/reject")
        assert rejected.json()["outcome"] == "rejected"

        agent = c.get("/api/society/agents/mailbox").json()["agent"]
        assert agent["description"] == "Handle my mail.\n\nBe brief."
        assert c.get("/api/society/agents/mailbox/review-queue").json()["total"] == 0

        again = c.post(f"/api/society/agents/mailbox/review/proposal:{keep}/approve")
        assert again.status_code == 409
        foreign = park("other", "Still not mine.")
        foreign_url = f"/api/society/agents/mailbox/review/proposal:{foreign}/approve"
        assert c.post(foreign_url).status_code == 404
        assert c.post("/api/society/agents/mailbox/review/nonsense/approve").status_code == 404
        assert c.post("/api/society/agents/mailbox/review/proposal:x/maybe").status_code == 422


def test_a_focus_proposal_previews_as_a_diff(tmp_path: Path) -> None:
    app, _ = _app(tmp_path)
    with TestClient(app) as c:
        c.post("/api/society/agents", json={"name": "Mailbox", "focus": ["plugin:gmail"]})
        c.post(
            "/api/society/approvals",
            json={
                "agent_id": "mailbox",
                "capability": "core:config:focus",
                "action": {"kind": "focus", "payload": {"focus": ["cli:gh"]}, "reason": ""},
                "summary": "Reach first for: cli:gh",
            },
        )
        item = c.get("/api/society/agents/mailbox/review-queue").json()["items"][0]
        assert item["preview"] == ["- plugin:gmail", "+ cli:gh"]


async def test_memory_writes_are_kept_or_forgotten(tmp_path: Path) -> None:
    from dodaios.society import learning_review

    rt = SocietyRuntime(tmp_path, seed_starter_team=False)
    await rt.ensure_started()
    try:
        agent, _ = await rt.roster.create(name="Scout")
        await rt.memory.remember(agent, "The user prefers short replies.", target="user")
        await rt.memory.remember(agent, "The weekly report goes out on Friday.", target="memory")
        await rt.memory.remember(agent, "I asked for this myself.", target="memory", origin="user")

        queue = await learning_review.queue(rt, agent)
        memory = [i for i in queue["items"] if i["kind"] == "memory"]
        # The person's own write never needs review.
        assert sorted(i["summary"] for i in memory) == [
            "The user prefers short replies.",
            "The weekly report goes out on Friday.",
        ]
        keep = next(i for i in memory if "Friday" in i["summary"])
        forget = next(i for i in memory if "short replies" in i["summary"])
        assert forget["book"] == "USER.md"

        kept = await learning_review.decide(rt, agent, keep["id"], approve=True)
        assert kept["outcome"] == "applied"
        gone = await learning_review.decide(rt, agent, forget["id"], approve=False)
        assert gone["outcome"] == "rejected"

        texts = [e.text for e in rt.memory.entries(agent)]
        assert "The weekly report goes out on Friday." in texts
        assert "The user prefers short replies." not in texts
        after = await learning_review.queue(rt, agent)
        assert [i for i in after["items"] if i["kind"] == "memory"] == []
        with pytest.raises(learning_review.ReviewRefused):
            await learning_review.decide(rt, agent, keep["id"], approve=True)
    finally:
        await rt.close()


async def test_a_knowledge_share_is_promoted_or_kept_private(tmp_path: Path) -> None:
    from dodaios.society import learning_review

    rt = SocietyRuntime(tmp_path, seed_starter_team=False)
    await rt.ensure_started()
    try:
        agent, _ = await rt.roster.create(name="Scout")
        shared = await rt.memory.propose_shared(agent, "Office hours", "Mon to Fri, 9 to 5.")
        private = await rt.memory.propose_shared(agent, "Draft idea", "Not ready yet.")
        queue = await learning_review.queue(rt, agent)
        shares = {i["id"] for i in queue["items"] if i["kind"] == "memory_share"}
        assert shares == {f"share:{shared['approval_id']}", f"share:{private['approval_id']}"}

        promoted = await learning_review.decide(
            rt, agent, f"share:{shared['approval_id']}", approve=True
        )
        assert promoted["outcome"] == "applied"
        assert promoted["detail"].startswith("society/shared/")
        kept = await learning_review.decide(
            rt, agent, f"share:{private['approval_id']}", approve=False
        )
        assert kept["outcome"] == "rejected"
        left = (await learning_review.queue(rt, agent))["items"]
        assert not [i for i in left if i["kind"] == "memory_share"]
    finally:
        await rt.close()
