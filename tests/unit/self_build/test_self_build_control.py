"""Control over the self-building loop: settings, provenance and the stop."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.core import config_writer
from dodaios.core.config import SelfBuildConfig
from dodaios.self_build import Kind, SelfBuild, State


def _client(tmp_path: Path, cfg: object) -> tuple[TestClient, SelfBuild]:
    from dodaios.ui.web.self_build_routes import router

    svc = SelfBuild(tmp_path, lambda: cfg)
    app = FastAPI()
    app.state.self_build = svc
    app.state.config = cfg
    app.include_router(router)
    return TestClient(app), svc


def _live(svc: SelfBuild, kind: Kind, signature: str, artefact: dict[str, str]) -> str:
    record = svc.ledger.open_case(kind, signature, f"Built {signature}")
    svc.ledger.attach_artefact(record.id, artefact, {})
    svc.ledger.set_state(record.id, State.TRIAL, "proved")
    return record.id


# ------------------------------------------------------------------ provenance


def test_provenance_lists_live_and_archived_artefacts_only(tmp_path: Path) -> None:
    cfg = SimpleNamespace(self_build=SelfBuildConfig(silent_days=0))
    client, svc = _client(tmp_path, cfg)
    skill = _live(svc, Kind.SKILL, "s1", {"type": "skill", "id": "weekly-report"})
    routine = _live(svc, Kind.ROUTINE, "r1", {"type": "routine", "id": "task-7"})
    svc.ledger.set_state(routine, State.ARCHIVED, "unused")
    gone = _live(svc, Kind.AGENT, "a1", {"type": "agent", "id": "agent-3"})
    svc.ledger.set_state(gone, State.UNDONE, "undone")
    svc.ledger.open_case(Kind.SKILL, "p1", "Still building")  # no artefact yet

    items = client.get("/api/self-build/provenance").json()["items"]
    assert set(items) == {"skill:weekly-report", "routine:task-7"}
    assert items["skill:weekly-report"]["build_id"] == skill
    assert items["routine:task-7"]["state"] == "archived"

    only_skills = client.get("/api/self-build/provenance", params={"type": "skill"}).json()
    assert set(only_skills["items"]) == {"skill:weekly-report"}
    svc.ledger.close()


def test_provenance_is_empty_without_the_ledger() -> None:
    from dodaios.ui.web.self_build_routes import router

    app = FastAPI()
    app.state.self_build = None
    app.include_router(router)
    assert TestClient(app).get("/api/self-build/provenance").json() == {"items": {}}


# ------------------------------------------------------------------ settings


def test_settings_round_trip_writes_toml_and_applies_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml = tmp_path / "jarvis.toml"
    toml.write_text("# the person's comment\n[memory]\ndata_dir = 'x'\n", encoding="utf-8")
    real = config_writer.set_self_build_settings
    monkeypatch.setattr(
        config_writer,
        "set_self_build_settings",
        lambda values: real(values, path=toml),
    )
    cfg = SimpleNamespace(self_build=SelfBuildConfig(silent_days=0))
    client, svc = _client(tmp_path, cfg)

    got = client.get("/api/self-build/settings").json()
    # Only the limits: no master switch, no stage per kind, no levels.
    assert set(got["settings"]) == set(config_writer.SELF_BUILD_SETTING_KEYS)
    assert "levels" not in got
    assert got["bounds"]["max_builds_per_day"] == {"min": 0, "max": 50}

    put = client.put("/api/self-build/settings", json={"max_builds_per_day": 5})
    assert put.status_code == 200, put.text
    assert put.json()["settings"]["max_builds_per_day"] == 5
    # Hot-applied: the running loop reads the new cap through its getter.
    assert cfg.self_build.max_builds_per_day == 5
    text = toml.read_text(encoding="utf-8")
    assert "# the person's comment" in text
    assert "[self_build]" in text and "max_builds_per_day = 5" in text
    svc.ledger.close()


@pytest.mark.parametrize(
    "body",
    [
        {"enabled": False},
        {"skill": "trial"},
        {"memory": "off"},
        {"routine": "suggest"},
        {"agent": "full"},
        {"code": "full"},
        {"code": "full", "max_builds_per_day": 5},
    ],
)
def test_settings_take_no_switch_and_no_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: dict[str, object]
) -> None:
    real = config_writer.set_self_build_settings
    writes: list[dict[str, object]] = []
    monkeypatch.setattr(config_writer, "set_self_build_settings", writes.append)
    cfg = SimpleNamespace(self_build=SelfBuildConfig())
    client, svc = _client(tmp_path, cfg)
    assert client.put("/api/self-build/settings", json=body).status_code == 422
    assert writes == []
    for key in ("enabled", "memory", "skill", "routine", "agent", "code"):
        with pytest.raises(ValueError, match="unknown self_build"):
            real({key: "full"}, path=tmp_path / "x.toml")
    svc.ledger.close()


def test_status_tells_the_fixed_autonomy_whatever_the_file_says(tmp_path: Path) -> None:
    old = SelfBuildConfig(enabled=False, memory="off", skill="suggest", code="full")
    client, svc = _client(tmp_path, SimpleNamespace(self_build=old))
    status = client.get("/api/self-build").json()["status"]
    assert "enabled" not in status
    assert status["autonomy"] == {
        "memory": "full",
        "skill": "full",
        "routine": "full",
        "agent": "full",
        "code": "watch",
    }
    svc.ledger.close()


def test_settings_reject_out_of_range_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writes: list[dict[str, object]] = []
    monkeypatch.setattr(config_writer, "set_self_build_settings", writes.append)
    cfg = SimpleNamespace(self_build=SelfBuildConfig())
    client, svc = _client(tmp_path, cfg)

    assert client.put("/api/self-build/settings", json={"trial_days": 0}).status_code == 400
    assert client.put("/api/self-build/settings", json={"trial_days": "x"}).status_code == 422
    assert client.put("/api/self-build/settings", json={}).status_code == 400
    assert writes == []
    assert cfg.self_build.trial_days == 14
    svc.ledger.close()


def test_writer_refuses_unknown_keys(tmp_path: Path) -> None:
    toml = tmp_path / "jarvis.toml"
    toml.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown self_build"):
        config_writer.set_self_build_settings({"judge": "me"}, path=toml)


# ------------------------------------------------------------------ who may change it


def test_the_brain_cannot_loosen_the_loop() -> None:
    from dodaios.app_actions.catalog import is_excluded
    from dodaios.core.self_mod.forbidden import is_forbidden

    assert is_excluded("/api/self-build/settings")
    assert is_excluded("/api/self-build/pause")
    # Seeing what was built, and undoing it, stay reachable when asked.
    assert not is_excluded("/api/self-build")
    assert not is_excluded("/api/self-build/{build_id}/undo")
    assert is_forbidden("self_build.skill")
    assert is_forbidden("self_build.enabled")


def test_society_kill_switch_pauses_the_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dodaios.self_build import service as service_module
    from dodaios.society import runtime

    svc = SelfBuild(tmp_path, lambda: SimpleNamespace(self_build=SelfBuildConfig()))
    monkeypatch.setattr(service_module, "_current", svc)
    assert runtime._pause_self_build() is True
    assert svc.status()["paused"] is True
    svc.ledger.close()

    monkeypatch.setattr(service_module, "_current", None)
    assert runtime._pause_self_build() is False


def test_land_repos_are_cleaned_and_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml = tmp_path / "jarvis.toml"
    toml.write_text("", encoding="utf-8")
    real = config_writer.set_self_build_settings
    monkeypatch.setattr(
        config_writer, "set_self_build_settings", lambda values: real(values, path=toml)
    )
    cfg = SimpleNamespace(self_build=SelfBuildConfig())
    client, svc = _client(tmp_path, cfg)
    put = client.put(
        "/api/self-build/settings",
        json={"code_land_repos": [" octo/app ", "https://github.com/Octo/App.git", "", "me/tool"]},
    )
    assert put.status_code == 200, put.text
    assert put.json()["settings"]["code_land_repos"] == ["octo/app", "me/tool"]
    assert cfg.self_build.code_land_repos == ["octo/app", "me/tool"]
    assert 'code_land_repos = ["octo/app", "me/tool"]' in toml.read_text(encoding="utf-8")
    bad = client.put("/api/self-build/settings", json={"code_land_repos": ["not a repo"]})
    assert bad.status_code == 400
    assert cfg.self_build.code_land_repos == ["octo/app", "me/tool"]
    svc.ledger.close()
