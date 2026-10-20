"""The team-thread REST surface and the choice of a default team."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agent_chat.team import TeamThreads, TeamThreadStore
from dodaios.ui.web import team_thread_routes
from dodaios.ui.web.team_thread_routes import default_team, router
from tests.fakes.fake_team_turns import FakeTurns, FakeWorkspace, object_to


def _seat(provider: str, family: str, *, agent: str = "", ready: bool = True, **extra) -> dict:
    return {
        "provider": provider,
        "label": provider.title(),
        "family": family,
        "runner": f"{agent}-cli" if agent else "api",
        "agent": agent,
        "model": "",
        "models": [],
        "ready": ready,
        "local": False,
        "fallback": "",
        **extra,
    }


ROWS = [
    _seat("openai", "openai"),
    _seat("claude-api", "claude", agent="claude"),
    _seat("openai-codex", "openai", agent="codex"),
    _seat("antigravity", "antigravity", agent="antigravity"),
    _seat("gemini", "gemini"),
    _seat("grok-build", "xai", agent="grok-build", ready=False),
    _seat("ollama", "ollama", local=True),
]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def seats() -> list[dict]:
        return [dict(row) for row in ROWS]

    monkeypatch.setattr(team_thread_routes, "_seats", seats)
    app = FastAPI()
    app.include_router(router)
    app.state.turns = FakeTurns()
    app.state.team_threads = TeamThreads(
        TeamThreadStore(":memory:"), app.state.turns, workspace=FakeWorkspace()
    )
    with TestClient(app) as test_client:
        yield test_client


def _providers(team: list[dict]) -> list[str]:
    return [seat["provider"] for seat in team]


def test_the_default_team_crosses_three_families_on_their_coding_agents() -> None:
    assert _providers(default_team(ROWS)) == ["claude-api", "openai-codex", "antigravity"]


def test_the_default_team_degrades_to_what_is_ready() -> None:
    def only(*ready: str) -> list[dict]:
        return [{**row, "ready": row["provider"] in ready} for row in ROWS]

    # Two families: two members. A family with only an API key still sits in.
    assert _providers(default_team(only("claude-api", "gemini"))) == ["claude-api", "gemini"]
    # One family with two rows: both, rather than a team of one.
    assert _providers(default_team(only("openai", "openai-codex"))) == ["openai-codex", "openai"]
    # One key at all: the same seat twice still plans blind and reviews.
    assert _providers(default_team(only("gemini"))) == ["gemini", "gemini"]
    # Local hardware only counts when nothing else is there.
    assert _providers(default_team(only("ollama"))) == ["ollama", "ollama"]
    assert default_team(only()) == []


def test_a_seat_knows_a_model_its_account_lists() -> None:
    live = {"codex-cli": [{"id": "gpt-luna"}, {"id": "gpt-terra"}]}
    fallback = team_thread_routes._seat_fallback

    # The CLI's configured default may be a model the account cannot use.
    assert fallback({"runner": "codex-cli"}, live) == "gpt-luna"
    assert fallback({"runner": "claude-cli"}, live) == ""


def test_listing_builds_nothing_for_someone_who_never_used_it(tmp_path: Path) -> None:
    class Memory:
        data_dir = str(tmp_path)

    class Config:
        memory = Memory()

    app = FastAPI()
    app.include_router(router)
    app.state.team_threads = None
    app.state.config = Config()
    with TestClient(app) as bare:
        assert bare.get("/api/team-threads").json() == {"threads": []}
    assert app.state.team_threads is None
    assert not (tmp_path / "team_threads.db").exists()


def test_seats_lists_what_can_sit_in_a_team(client: TestClient) -> None:
    body = client.get("/api/team-threads/seats").json()

    assert [s["provider"] for s in body["default"]] == [
        "claude-api", "openai-codex", "antigravity",
    ]
    assert body["min_members"] == 2
    assert body["max_members"] == 8
    assert len(body["seats"]) == len(ROWS)


def test_one_prompt_starts_the_default_team_and_ends_in_one_thread(
    client: TestClient, tmp_path: Path
) -> None:
    started = client.post(
        "/api/team-threads", json={"task": "Add a retry to the uploader", "cwd": str(tmp_path)}
    )
    assert started.status_code == 201, started.text
    team_id = started.json()["team_id"]
    assert [m["name"] for m in started.json()["members"]] == [
        "Claude-Api", "Openai-Codex", "Antigravity",
    ]

    client.portal.call(client.app.state.team_threads.settled, team_id)
    thread = client.get(f"/api/team-threads/{team_id}").json()
    assert thread["state"] == "done"
    assert thread["entries"][0] == {
        **thread["entries"][0], "kind": "user", "payload": {"text": "Add a retry to the uploader"},
    }
    listed = client.get("/api/team-threads").json()["threads"]
    assert [(row["team_id"], row["state"]) for row in listed] == [(team_id, "done")]
    # Only what is new since the reader's last entry.
    last = thread["entries"][-1]["seq"]
    assert client.get(f"/api/team-threads/{team_id}?after={last}").json()["entries"] == []


def test_the_person_picks_the_members_and_the_bounds(client: TestClient, tmp_path: Path) -> None:
    started = client.post(
        "/api/team-threads",
        json={
            "task": "Fix the flaky test",
            "cwd": str(tmp_path),
            "seats": [{"provider": "gemini"}, {"provider": "openai", "model": "gpt-x"}],
            "limits": {"max_minutes": 20, "plan_rounds": 1},
        },
    ).json()

    assert [m["provider"] for m in started["members"]] == ["gemini", "openai"]
    assert started["members"][1]["name"] == "Openai · gpt-x"
    assert started["limits"]["max_minutes"] == 20
    assert started["limits"]["plan_rounds"] == 1
    assert started["limits"]["review_rounds"] == 3


def test_a_disagreement_is_settled_over_the_api(client: TestClient, tmp_path: Path) -> None:
    client.app.state.turns.script = lambda provider, step, nth: (
        object_to("No rollback.") if step == "vote" and provider == "openai-codex" else None
    )
    team_id = client.post(
        "/api/team-threads",
        json={"task": "Migrate the table", "cwd": str(tmp_path), "limits": {"plan_rounds": 1}},
    ).json()["team_id"]
    client.portal.call(client.app.state.team_threads.settled, team_id)
    waiting = client.get(f"/api/team-threads/{team_id}").json()
    assert (waiting["state"], waiting["reason"]) == ("needs_input", "plan_disagreement")
    assert waiting["issues"][0]["issue"] == "No rollback."

    assert client.post(f"/api/team-threads/{team_id}/accept").status_code == 200
    client.portal.call(client.app.state.team_threads.settled, team_id)
    assert client.get(f"/api/team-threads/{team_id}").json()["state"] == "done"


def test_requests_a_thread_cannot_take_are_refused(client: TestClient, tmp_path: Path) -> None:
    assert client.get("/api/team-threads/nope").status_code == 404
    assert client.post("/api/team-threads/nope/pause").status_code == 404
    missing = client.post("/api/team-threads", json={"task": "x", "cwd": str(tmp_path / "gone")})
    assert missing.status_code == 400
    unknown = client.post(
        "/api/team-threads",
        json={"task": "x", "cwd": str(tmp_path), "seats": [{"provider": "a"}, {"provider": "b"}]},
    )
    assert unknown.status_code == 400
    alone = client.post(
        "/api/team-threads",
        json={"task": "x", "cwd": str(tmp_path), "seats": [{"provider": "gemini"}]},
    )
    assert alone.status_code == 422
    missing_cli = client.post(
        "/api/team-threads",
        json={"task": "x", "cwd": str(tmp_path),
              "seats": [{"provider": "gemini"}, {"provider": "grok-build"}]},
    )
    assert missing_cli.status_code == 409
    assert "not connected" in missing_cli.json()["detail"]

    team_id = client.post("/api/team-threads", json={"task": "x", "cwd": str(tmp_path)}).json()[
        "team_id"
    ]
    client.portal.call(client.app.state.team_threads.settled, team_id)
    assert client.post(f"/api/team-threads/{team_id}/pause").status_code == 409
    late = client.post(f"/api/team-threads/{team_id}/message", json={"text": "hi"})
    assert late.status_code == 409
    assert client.delete(f"/api/team-threads/{team_id}").json() == {"deleted": True}
    assert client.get(f"/api/team-threads/{team_id}").status_code == 404


def test_every_route_says_whether_it_changes_anything() -> None:
    for route in router.routes:
        extra = getattr(route, "openapi_extra", None) or {}
        reads = route.methods == {"GET"}  # type: ignore[attr-defined]
        assert extra.get("x-jarvis-readonly" if reads else "x-jarvis-dangerous") is True, route.path  # type: ignore[attr-defined]


def test_a_planner_and_builder_team_starts_with_its_roles(
    client: TestClient, tmp_path: Path
) -> None:
    started = client.post(
        "/api/team-threads",
        json={
            "task": "Add a retry to the uploader",
            "cwd": str(tmp_path),
            "mode": "planner_builder",
            "seats": [
                {"provider": "gemini", "role": "builder"},
                {"provider": "claude-api", "role": "planner"},
            ],
        },
    )
    assert started.status_code == 201, started.text
    body = started.json()
    assert (body["mode"], body["phase"]) == ("planner_builder", "planning")
    assert [m["role"] for m in body["members"]] == ["builder", "planner"]

    client.portal.call(client.app.state.team_threads.settled, body["team_id"])
    thread = client.get(f"/api/team-threads/{body['team_id']}").json()
    assert thread["state"] == "done"
    assert [s["status"] for s in thread["plan"]["steps"]] == ["accepted", "accepted"]
    listed = client.get("/api/team-threads").json()["threads"]
    assert listed[0]["mode"] == "planner_builder"


def test_a_mode_or_role_the_team_does_not_know_is_refused(
    client: TestClient, tmp_path: Path
) -> None:
    def start(**extra) -> int:
        return client.post(
            "/api/team-threads", json={"task": "x", "cwd": str(tmp_path), **extra}
        ).status_code

    assert start(mode="solo") == 422
    assert start(mode="planner_builder", seats=[
        {"provider": "gemini", "role": "boss"}, {"provider": "openai"},
    ]) == 422
    # Two builders and no planner: nobody would plan, and nobody check the plan.
    assert start(mode="planner_builder", seats=[
        {"provider": "gemini", "role": "builder"}, {"provider": "openai", "role": "builder"},
    ]) == 409
