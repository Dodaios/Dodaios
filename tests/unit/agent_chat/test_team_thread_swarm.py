"""Teams the person sets member by member: one seat twice, and swarms of up to eight."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agent_chat.team import SeatPick, TeamError, TeamThreads, TeamThreadStore, prompts
from dodaios.agent_chat.team.engine import MAX_MEMBERS
from dodaios.ui.web import team_thread_routes
from dodaios.ui.web.team_thread_routes import router, short_model_label
from tests.fakes.fake_team_turns import FakeTurns, FakeWorkspace, changes

CLAUDE_MODELS = [
    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5", "efforts": []},
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "efforts": []},
]

SWARM = [
    SeatPick(f"seat{n}", name=f"Seat {n}", family=f"family{n}") for n in range(1, MAX_MEMBERS + 1)
]


def _engine(turns: FakeTurns) -> TeamThreads:
    return TeamThreads(TeamThreadStore(":memory:"), turns, workspace=FakeWorkspace())


async def _run(engine: TeamThreads, tmp_path: Path, **kwargs) -> dict:
    snap = await engine.start(task="Add a retry to the uploader", cwd=str(tmp_path), **kwargs)
    await engine.settled(snap["team_id"])
    return engine.snapshot(snap["team_id"])


def _authors(snap: dict, kind: str) -> list[str]:
    return [e["author"] for e in snap["entries"] if e["kind"] == kind]


# ------------------------------------------------------------------ engine


async def test_one_seat_can_sit_in_the_team_twice_as_separate_members(tmp_path: Path) -> None:
    turns = FakeTurns()
    seats = [
        SeatPick(
            "claude", name="Anthropic Claude", family="claude", model="opus", model_label="Opus 5.5"
        ),
        SeatPick(
            "claude",
            name="Anthropic Claude",
            family="claude",
            model="sonnet",
            model_label="Sonnet 5.5",
        ),
        SeatPick("codex", name="OpenAI Codex", family="openai"),
    ]
    snap = await _run(_engine(turns), tmp_path, seats=seats)

    assert snap["state"] == "done"
    assert [m["name"] for m in snap["members"]] == [
        "Anthropic Claude · Opus 5.5",
        "Anthropic Claude · Sonnet 5.5",
        "OpenAI Codex",
    ]
    # Each member is a session of its own, on its own model.
    assert len({m["session_id"] for m in snap["members"]}) == 3
    assert [m["model"] for m in snap["members"]] == ["opus", "sonnet", ""]
    assert sorted(_authors(snap, "draft")) == ["m1", "m2", "m3"]
    # Each member reads the other's plan under the other's name.
    challenge = next(
        p for p in turns.prompts("claude", "critique") if "You are Anthropic Claude · Opus 5.5" in p
    )
    assert "<plan by Anthropic Claude · Sonnet 5.5>" in challenge
    assert "<plan by Anthropic Claude · Opus 5.5>" not in challenge


async def test_members_on_one_seat_and_one_model_are_numbered(tmp_path: Path) -> None:
    seats = [
        SeatPick("claude", name="Anthropic Claude", family="claude"),
        SeatPick("claude", name="Anthropic Claude", family="claude"),
        SeatPick(
            "claude", name="Anthropic Claude", family="claude", model="opus", model_label="Opus 5.5"
        ),
        SeatPick(
            "claude", name="Anthropic Claude", family="claude", model="opus", model_label="Opus 5.5"
        ),
    ]
    snap = await _run(_engine(FakeTurns()), tmp_path, seats=seats)

    assert [m["name"] for m in snap["members"]] == [
        "Anthropic Claude 1",
        "Anthropic Claude 2",
        "Anthropic Claude · Opus 5.5 1",
        "Anthropic Claude · Opus 5.5 2",
    ]
    assert "same_family" in [e["payload"]["code"] for e in snap["entries"] if e["kind"] == "notice"]


async def test_a_swarm_of_eight_peers_plans_builds_and_reviews(tmp_path: Path) -> None:
    turns = FakeTurns()
    snap = await _run(_engine(turns), tmp_path, seats=SWARM)

    assert snap["state"] == "done"
    assert len(snap["members"]) == 8
    assert len(_authors(snap, "draft")) == 8
    assert len(_authors(snap, "critique")) == 8
    assert len(_authors(snap, "vote")) == 7
    assert len(_authors(snap, "review")) == 7
    # A bigger team gets a bigger default turn bound.
    assert snap["limits"]["max_turns"] == 80
    assert snap["usage"]["turns"] == 8 + 8 + 1 + 7 + 1 + 7


async def test_more_members_than_the_cap_are_refused(tmp_path: Path) -> None:
    extra = [*SWARM, SeatPick("seat9", name="Seat 9", family="family9")]
    with pytest.raises(TeamError):
        await _engine(FakeTurns()).start(task="x", cwd=str(tmp_path), seats=extra)


async def test_a_swarm_reviews_every_step_and_converges(tmp_path: Path) -> None:
    def script(provider: str, step: str, nth: int):
        # One of six reviewers holds the first step back once.
        if provider == "seat5" and step == "step_review" and nth == 0:
            return changes("The retry never stops.")
        return None

    turns = FakeTurns(script)
    snap = await _run(_engine(turns), tmp_path, seats=SWARM, mode="planner_builder")

    assert snap["state"] == "done"
    roles = [m["role"] for m in snap["members"]]
    assert roles == ["planner", "builder"] + ["reviewer"] * 6
    reviews = [e for e in snap["entries"] if e["kind"] == "step_review"]
    builds = [e for e in snap["entries"] if e["kind"] == "step_build"]
    # Step 1 was built twice; each round of it was read by all six reviewers.
    assert [b["payload"]["number"] for b in builds] == [1, 1, 2]
    first = [r for r in reviews if r["payload"]["number"] == 1]
    assert len(first) == 12
    assert all(r["payload"]["approve"] for r in first[6:])
    assert len([r for r in reviews if r["payload"]["number"] == 2]) == 6
    # Every reviewer reads the plan.
    assert _authors(snap, "plan_review") == ["m3", "m4", "m5", "m6", "m7", "m8"]
    assert snap["plan"]["steps"][0]["rounds"] == 2


# ------------------------------------------------------------------ prompts


def test_a_few_contributions_are_passed_on_whole() -> None:
    texts = [("plan by A", "a" * 9_000), ("plan by B", "b" * 11_000)]
    assert prompts.share([len(text) for _, text in texts]) == prompts.MAX_QUOTE
    assert [len(block) for block in prompts.quotes(texts)] == [
        len(prompts.quote(label, text)) for label, text in texts
    ]


def test_many_contributions_share_one_budget_and_short_ones_stay_whole() -> None:
    lengths = [500, 800] + [12_000] * 6
    limit = prompts.share(lengths)
    assert limit < prompts.MAX_QUOTE
    assert 500 + 800 + 6 * limit <= prompts.MAX_MATERIAL
    # Never below the floor, however many there are.
    assert prompts.share([12_000] * 40) == prompts.MIN_QUOTE


def test_a_swarm_challenge_stays_within_the_material_budget() -> None:
    drafts = {f"Seat {n}": f"plan {n} " + "x" * 20_000 for n in range(2, 9)}
    prompt = prompts.challenge(
        name="Seat 1",
        roster=[f"Seat {n}" for n in range(1, 9)],
        cwd="/repo",
        drafts=drafts,
        notes=[],
    )
    assert len(prompt) < prompts.MAX_MATERIAL + 3_000
    assert prompt.count("[shortened]") == 7
    for n in range(2, 9):
        assert f"<plan by Seat {n}>\nplan {n} " in prompt


def test_a_swarm_master_plan_shares_the_budget_between_plans_and_challenges() -> None:
    roster = [f"Seat {n}" for n in range(1, 9)]
    long = "y" * 15_000
    prompt = prompts.master_plan(
        name="Seat 1",
        roster=roster,
        cwd="/repo",
        drafts={name: long for name in roster},
        critiques={name: long for name in roster},
        previous="",
        objections={},
        notes=[],
    )
    assert len(prompt) < prompts.MAX_MATERIAL + 4_000
    assert prompt.count("<plan by ") == 8
    assert prompt.count("<challenge by ") == 8


# ------------------------------------------------------------------ routes


def _row(provider: str, label: str, family: str, **extra) -> dict:
    return {
        "provider": provider,
        "label": label,
        "family": family,
        "runner": "api",
        "agent": "",
        "model": "",
        "models": [],
        "model_options": [],
        "efforts": [],
        "ready": True,
        "local": False,
        "fallback": "",
        **extra,
    }


ROWS = [
    _row(
        "claude-api",
        "Anthropic Claude",
        "claude",
        agent="claude",
        runner="claude-cli",
        models=[m["id"] for m in CLAUDE_MODELS],
        model_options=CLAUDE_MODELS,
        efforts=["low", "medium", "high"],
        fallback="claude-sonnet-5-5",
    ),
    _row("openai-codex", "OpenAI Codex", "openai", agent="codex", runner="codex-cli"),
    *[_row(f"api{n}", f"Api {n}", f"family{n}") for n in range(1, 8)],
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


def test_seats_offer_up_to_eight_members_and_the_turn_bound_per_size(client: TestClient) -> None:
    body = client.get("/api/team-threads/seats").json()

    assert body["max_members"] == 8
    assert body["max_turns"] == {
        "2": 40,
        "3": 40,
        "4": 40,
        "5": 50,
        "6": 60,
        "7": 70,
        "8": 80,
    }


def test_two_claude_members_on_different_models_start_over_the_api(
    client: TestClient, tmp_path: Path
) -> None:
    started = client.post(
        "/api/team-threads",
        json={
            "task": "Fix the flaky test",
            "cwd": str(tmp_path),
            "seats": [
                {"provider": "claude-api", "model": "claude-opus-5-5", "effort": "high"},
                {"provider": "claude-api", "model": "claude-sonnet-5-5"},
                {"provider": "openai-codex"},
            ],
        },
    )
    assert started.status_code == 201, started.text
    members = started.json()["members"]
    assert [m["name"] for m in members] == [
        "Anthropic Claude · Opus 5.5",
        "Anthropic Claude · Sonnet 5.5",
        "OpenAI Codex",
    ]
    assert [m["model"] for m in members] == ["claude-opus-5-5", "claude-sonnet-5-5", ""]
    assert [m["effort"] for m in members] == ["high", "", ""]
    assert len({m["session_id"] for m in members}) == 3


def test_two_members_on_the_seats_default_are_numbered_over_the_api(
    client: TestClient, tmp_path: Path
) -> None:
    started = client.post(
        "/api/team-threads",
        json={
            "task": "Fix the flaky test",
            "cwd": str(tmp_path),
            "seats": [{"provider": "claude-api"}, {"provider": "claude-api"}],
        },
    ).json()
    assert [m["name"] for m in started["members"]] == ["Anthropic Claude 1", "Anthropic Claude 2"]


def test_a_team_of_eight_starts_and_a_ninth_member_is_refused(
    client: TestClient, tmp_path: Path
) -> None:
    eight = [{"provider": "claude-api"}, {"provider": "openai-codex"}] + [
        {"provider": f"api{n}"} for n in range(1, 7)
    ]
    started = client.post(
        "/api/team-threads",
        json={"task": "Swarm", "cwd": str(tmp_path), "seats": eight, "mode": "planner_builder"},
    )
    assert started.status_code == 201, started.text
    assert len(started.json()["members"]) == 8

    nine = client.post(
        "/api/team-threads",
        json={"task": "Swarm", "cwd": str(tmp_path), "seats": [*eight, {"provider": "api7"}]},
    )
    assert nine.status_code == 422


def test_an_effort_the_seat_does_not_offer_is_refused(client: TestClient, tmp_path: Path) -> None:
    refused = client.post(
        "/api/team-threads",
        json={
            "task": "x",
            "cwd": str(tmp_path),
            "seats": [{"provider": "claude-api", "effort": "ludicrous"}, {"provider": "api1"}],
        },
    )
    assert refused.status_code == 422
    assert "ludicrous" in refused.json()["detail"]


def test_a_seat_lists_its_models_without_the_hidden_ones() -> None:
    row = {
        "curated_models": [
            {"id": "a", "label": "Model A", "efforts": ["low", "", "high"]},
            {"id": "b", "label": "Model B"},
            {"id": "", "label": "nameless"},
        ],
        "hidden_models": ["b"],
    }
    assert team_thread_routes._model_options(row) == [
        {"id": "a", "label": "Model A", "efforts": ["low", "high"]},
    ]


def test_a_model_name_drops_what_the_seat_name_already_says() -> None:
    assert short_model_label("Anthropic Claude", "Claude Opus 5.5") == "Opus 5.5"
    assert short_model_label("OpenAI Codex", "GPT-6-Luna") == "GPT-6-Luna"
    assert short_model_label("Antigravity", "Claude Opus 5.5") == "Claude Opus 5.5"
    # A bare number would say nothing on its own.
    assert short_model_label("Grok Build", "Grok 4.7 Fast") == "Grok 4.7 Fast"
    assert short_model_label("Anthropic Claude", "Claude") == "Claude"
