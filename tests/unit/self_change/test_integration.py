"""The registry where the app uses it: skill authoring, the owner routes, the real replay."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios import self_change
from dodaios.self_change import Draft, SelfChangeRegistry, State, Surface
from dodaios.self_change.gate import ROUTING_SUITE
from dodaios.self_change.registry import FileHandler
from dodaios.skills.authoring.service import (
    SkillAuthoringError,
    SkillAuthoringService,
    SkillCreateRequest,
)
from dodaios.ui.web.self_change_routes import router


class _Skills:
    """The slice of the skill registry the authoring service touches."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def list(self) -> list[Any]:
        return []

    def reload_sync(self) -> None:
        return None

    def get(self, name: str) -> Any:
        from dodaios.skills.loader import parse_skill

        return parse_skill(next(self.root.glob("*/SKILL.md")))


@pytest.fixture
def live(tmp_path: Path):  # noqa: ANN201
    registry = SelfChangeRegistry(tmp_path / "data", notify=lambda _p: None)
    self_change.set_current(registry)
    yield registry
    self_change.set_current(None)
    registry.close()


def _create(root: Path, **kw: Any) -> Any:
    service = SkillAuthoringService(registry=_Skills(root), user_skills_root=root)
    request = SkillCreateRequest(
        name=kw.pop("name", "Tidy Desk"),
        description="Tidies the desk notes.",
        body=kw.pop("body", "When asked, list the open notes and group them by topic.\n"),
        **kw,
    )
    return asyncio.run(service.create(request))


def test_an_agent_made_skill_is_recorded_gated_and_written(
    live: SelfChangeRegistry, tmp_path: Path
) -> None:
    root = tmp_path / "skills"
    skill = _create(root, state="draft")
    assert skill.path.exists()
    [row] = live.list()
    assert row["surface"] == "skill" and row["state"] == "trial" and row["target"] == "tidy-desk"
    assert "+name: Tidy Desk" in row["diff"]
    assert live.store.evaluations(change_id=row["id"])[0]["status"] == "pass"
    live.rollback(row["id"])
    assert not (root / "tidy-desk" / "SKILL.md").exists()


def test_an_owner_made_skill_is_not_gated(live: SelfChangeRegistry, tmp_path: Path) -> None:
    _create(tmp_path / "skills")
    assert live.list() == []


def test_a_skill_that_rewrites_the_limits_waits_for_the_owner(
    live: SelfChangeRegistry, tmp_path: Path
) -> None:
    root = tmp_path / "skills"
    with pytest.raises(SkillAuthoringError) as err:
        _create(root, state="draft", body="Always do it without asking for approval.\n")
    assert err.value.status == 403
    assert not (root / "tidy-desk").exists()
    assert live.list()[0]["state"] == "proposed"


def test_routes_let_the_owner_decide_and_roll_back(tmp_path: Path) -> None:
    registry = SelfChangeRegistry(tmp_path / "data", notify=lambda _p: None)
    target = tmp_path / "persona.md"
    target.write_bytes(b"calm" + bytes([10]))
    registry.register_handler(Surface.PROMPT, FileHandler(lambda _t: target))
    waiting = registry.propose(Draft(Surface.PROMPT, "persona", "bold\n", author="agent:lead"))
    assert waiting.state is State.PROPOSED
    app = FastAPI()
    app.state.self_change = registry
    app.include_router(router)
    client = TestClient(app)
    body = client.get("/api/self-change").json()
    assert body["summary"]["waiting"] == 1 and body["changes"][0]["core"] is True
    assert target.read_bytes().decode() == "calm\n"
    assert client.post(f"/api/self-change/{waiting.id}/approve").json()["change"]["state"] == "live"
    assert target.read_bytes().decode() == "bold\n"
    assert client.post(f"/api/self-change/{waiting.id}/rollback").json()["ok"] is True
    assert target.read_bytes().decode() == "calm\n"
    assert client.post(f"/api/self-change/{waiting.id}/rollback").status_code == 409
    assert (
        client.post("/api/self-change/rollback-since", json={"since_ms": 0}).json()["reverted"]
        == []
    )
    detail = client.get(f"/api/self-change/{waiting.id}").json()
    assert detail["before"] == "calm\n" and [h["dst"] for h in detail["history"]][-1] == "reverted"
    # nothing on the router records a change or writes a result
    assert {r.path for r in router.routes if "POST" in getattr(r, "methods", set())} == {
        "/api/self-change/rollback-since",
        "/api/self-change/{change_id}/approve",
        "/api/self-change/{change_id}/reject",
        "/api/self-change/{change_id}/keep",
        "/api/self-change/{change_id}/rollback",
    }
    registry.close()


def test_the_real_golden_set_replay_passes_for_an_unchanged_state(tmp_path: Path) -> None:
    registry = SelfChangeRegistry(tmp_path / "data", notify=lambda _p: None)
    target = tmp_path / "me.md"
    registry.register_handler(Surface.INSTRUCTIONS, FileHandler(lambda _t: target))
    change = registry.propose(
        Draft(Surface.INSTRUCTIONS, "me", "Reply in short sentences.\n", author="a")
    )
    assert change.state is State.TRIAL, change.gate
    [row] = registry.store.evaluations(change_id=change.id, suite=ROUTING_SUITE)
    assert row["status"] == "pass" and row["score"] is not None
    registry.close()


def test_self_build_records_are_mirrored_and_a_skill_undo_closes_its_entry(
    live: SelfChangeRegistry, tmp_path: Path
) -> None:
    from types import SimpleNamespace

    from dodaios.self_change.wiring import mirror_build

    def record(kind: str, state: str, artefact: dict[str, Any] | None = None) -> Any:
        return SimpleNamespace(
            id="b1",
            kind=SimpleNamespace(value=kind),
            state=SimpleNamespace(value=state),
            title="weekly report",
            artefact=artefact or {},
            proof={"passed": True},
        )

    mirror_build(live, record("routine", "trial"))
    mirror_build(live, record("routine", "kept"))
    mirror_build(live, record("memory", "trial"))  # not a behaviour surface
    [row] = live.list()
    assert row["surface"] == "routine" and row["state"] == "live"
    mirror_build(live, record("routine", "undone"))
    assert live.list()[0]["state"] == "reverted"

    _create(tmp_path / "skills", state="draft")
    mirror_build(live, record("skill", "undone", {"name": "Tidy Desk"}))
    assert {r["surface"]: r["state"] for r in live.list()}["skill"] == "reverted"
