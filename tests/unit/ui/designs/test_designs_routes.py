"""REST contract of the designs (``dodaios/ui/web/designs_routes.py``, docs/designs.md).

Runs against the real store pointed at a tmp data directory; the bus is a
hand-written recorder.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.core import config as config_module
from dodaios.core.events import UiDesignChanged
from dodaios.ui.designs import store
from dodaios.ui.web.designs_routes import router

DARK = {"background": "#0b1020", "foreground": "#e8ecf8", "accent": "#7c9cff"}
LIGHT = {"background": "#f6f7fb", "foreground": "#141a2e", "accent": "#3a5bd9"}


class _Bus:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def publish(self, event: Any) -> None:
        self.events.append(event)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.setattr(config_module, "DATA_DIR", tmp_path)
    app = FastAPI()
    bus = _Bus()
    app.state.bus = bus
    app.include_router(router)
    return SimpleNamespace(client=TestClient(app), bus=bus, path=tmp_path / store.FILE_NAME)


def test_list_starts_on_the_standard_look_with_the_built_in_designs(env: SimpleNamespace) -> None:
    body = env.client.get("/api/designs").json()
    assert body["active"] == "standard"
    assert body["standard_id"] == "standard"
    ids = [d["id"] for d in body["designs"]]
    assert {"deep-sea", "ember", "forest", "night-sky", "dusk", "paper"} <= set(ids)
    assert all(d["builtin"] for d in body["designs"])
    assert body["schema"]["required_keys"] == ["background", "foreground", "accent"]
    assert "glow" in body["schema"]["background_styles"]
    assert not env.path.exists()


def test_save_makes_a_design_switches_to_it_and_announces_it(env: SimpleNamespace) -> None:
    resp = env.client.post(
        "/api/designs",
        json={
            "name": "Midnight Blue",
            "description": "dark blue with a slow glow",
            "dark": DARK,
            "light": {**LIGHT, "accent": "#3A5BD9"},
            "background": {
                "style": "glow",
                "colors": ["#1d3b8f", "#5a2a8a"],
                "speed": "slow",
                "strength": 0.4,
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["design"]["id"] == "midnight-blue"
    assert body["active"] == "midnight-blue"
    assert body["applied"] is True
    assert body["design"]["light"]["accent"] == "#3a5bd9"
    assert [type(e) for e in env.bus.events] == [UiDesignChanged]
    assert env.bus.events[0].active == "midnight-blue"
    saved = json.loads(env.path.read_text())
    assert saved["active"] == "midnight-blue"
    assert [d["id"] for d in saved["designs"]] == ["midnight-blue"]
    assert "builtin" not in saved["designs"][0]


def test_apply_false_only_saves(env: SimpleNamespace) -> None:
    body = env.client.post(
        "/api/designs", json={"name": "Quiet", "dark": DARK, "apply": False}
    ).json()
    assert body["active"] == "standard"
    assert body["applied"] is False


def test_a_change_keeps_what_was_not_sent(env: SimpleNamespace) -> None:
    env.client.post("/api/designs", json={"name": "Calm", "dark": DARK, "light": LIGHT})
    resp = env.client.post("/api/designs", json={"id": "calm", "dark": {"accent": "#ff8a3d"}})
    assert resp.status_code == 200, resp.text
    design = resp.json()["design"]
    assert design["dark"] == {**DARK, "accent": "#ff8a3d"}
    assert design["light"] == LIGHT
    assert design["name"] == "Calm"


def test_two_designs_with_one_name_get_two_ids(env: SimpleNamespace) -> None:
    first = env.client.post("/api/designs", json={"name": "Calm", "dark": DARK}).json()["design"][
        "id"
    ]
    second = env.client.post("/api/designs", json={"name": "Calm", "dark": DARK}).json()["design"][
        "id"
    ]
    assert (first, second) == ("calm", "calm-2")


def test_a_name_like_a_built_in_design_does_not_take_its_id(env: SimpleNamespace) -> None:
    body = env.client.post("/api/designs", json={"name": "Deep Sea", "dark": DARK}).json()
    assert body["design"]["id"] == "deep-sea-2"


@pytest.mark.parametrize(
    ("payload", "needle"),
    [
        ({"name": "X", "dark": {"background": "#000", "foreground": "#fff"}}, "needs accent"),
        ({"name": "X", "dark": {**DARK, "glitter": "#fff"}}, "unknown colour glitter"),
        ({"name": "X", "dark": {**DARK, "accent": "blue"}}, "is not a colour"),
        ({"name": "X"}, "needs colours"),
        ({"dark": DARK}, "name"),
        (
            {"name": "X", "dark": DARK, "background": {"style": "lava", "colors": ["#fff"]}},
            "background.style",
        ),
        ({"name": "X", "dark": DARK, "background": {"style": "glow"}}, "at least one colour"),
        (
            {"name": "X", "dark": DARK, "background": {"style": "glow", "colors": ["#fff"] * 6}},
            "at most 5",
        ),
    ],
)
def test_a_design_that_cannot_work_is_refused_with_the_reason(
    env: SimpleNamespace, payload: dict[str, Any], needle: str
) -> None:
    resp = env.client.post("/api/designs", json=payload)
    assert resp.status_code == 400
    assert needle in resp.json()["detail"]
    assert env.bus.events == []


def test_strength_is_clamped_into_zero_to_one(env: SimpleNamespace) -> None:
    body = env.client.post(
        "/api/designs",
        json={
            "name": "Loud",
            "dark": DARK,
            "background": {"style": "stars", "colors": ["#ffffff"], "strength": 3},
        },
    ).json()
    assert body["design"]["background"]["strength"] == 1.0


def test_built_in_designs_cannot_be_changed_or_deleted(env: SimpleNamespace) -> None:
    change = env.client.post("/api/designs", json={"id": "ember", "dark": {"accent": "#ffffff"}})
    assert change.status_code == 400
    assert "built-in" in change.json()["detail"]
    delete = env.client.delete("/api/designs/ember")
    assert delete.status_code == 400


def test_changing_a_design_that_does_not_exist_is_404(env: SimpleNamespace) -> None:
    assert env.client.post("/api/designs", json={"id": "ghost", "dark": DARK}).status_code == 404


def test_switch_reset_and_delete(env: SimpleNamespace) -> None:
    env.client.post("/api/designs", json={"name": "Mine", "dark": DARK})
    assert env.client.put("/api/designs/active", json={"id": "forest"}).json()["active"] == "forest"
    assert env.client.put("/api/designs/active", json={"id": "nope"}).status_code == 404
    assert env.client.post("/api/designs/reset").json()["active"] == "standard"
    assert env.client.put("/api/designs/active", json={"id": "mine"}).json()["active"] == "mine"
    body = env.client.delete("/api/designs/mine").json()
    assert body["active"] == "standard"
    assert "mine" not in [d["id"] for d in body["state"]["designs"]]
    assert env.client.delete("/api/designs/mine").status_code == 404
    assert [e.active for e in env.bus.events] == ["mine", "forest", "standard", "mine", "standard"]


def test_a_broken_file_falls_back_to_the_standard_look(env: SimpleNamespace) -> None:
    env.path.write_text("{not json")
    assert env.client.get("/api/designs").json()["active"] == "standard"


def test_a_broken_entry_is_skipped_and_the_rest_stays(env: SimpleNamespace) -> None:
    env.path.write_text(
        json.dumps(
            {
                "version": 1,
                "active": "good",
                "designs": [
                    {"id": "good", "name": "Good", "dark": DARK},
                    {"id": "bad", "name": "Bad", "dark": {"background": "red"}},
                ],
            }
        )
    )
    body = env.client.get("/api/designs").json()
    assert body["active"] == "good"
    own = [d["id"] for d in body["designs"] if not d["builtin"]]
    assert own == ["good"]


def test_an_active_id_that_is_gone_reads_as_standard(env: SimpleNamespace) -> None:
    env.path.write_text(json.dumps({"version": 1, "active": "vanished", "designs": []}))
    assert env.client.get("/api/designs").json()["active"] == "standard"


def test_every_built_in_design_passes_the_checks() -> None:
    from dodaios.ui.designs.presets import builtin_designs

    for design in builtin_designs():
        assert store.check_palette(design["dark"], side="dark") == design["dark"]
        assert store.check_palette(design["light"], side="light") == design["light"]
        assert store.check_background(design["background"]) == design["background"]
