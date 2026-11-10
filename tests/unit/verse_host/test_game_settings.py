"""The Verse game settings catalogue, its store and the app's settings routes.

Bridge-protocol 3.2 / 14: ``welcome.settings.game`` carries every catalogue
setting, ``settings.set`` and ``PATCH /api/verse/settings`` validate against
the catalogue, and a running Verse gets each change as ``settings.changed``.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from dodaios.ui.web import verse_routes
from dodaios.verse_host import game_settings as G
from dodaios.verse_host.settings_store import SettingsError, SettingsStore
from tests.unit.verse_host._support import close, connect, make_host

REPO = Path(__file__).resolve().parents[3]


def _app(host) -> FastAPI:
    app = FastAPI()
    app.include_router(verse_routes.router)
    app.state.verse_host = host
    return app


def test_catalogue_is_well_formed() -> None:
    ids = [s.id for s in G.CATALOGUE]
    assert len(ids) == len(set(ids))
    for s in G.CATALOGUE:
        assert s.tab in G.TABS
        assert G.check_value(s, s.default) == s.default
        if s.kind == "range":
            assert s.min <= s.default <= s.max
    data = G.catalogue_json()
    assert data["tabs"] == list(G.TABS)
    assert set(data["preset_groups"]) <= set(ids)
    json.dumps(data)  # serialisable for the route


def test_keybinds_match_the_unreal_key_file() -> None:
    keys = REPO / "unreal" / "Verse" / "Data" / "ui" / "keys.json"
    if not keys.is_file():
        pytest.skip("Unreal project not in this checkout")
    actions = json.loads(keys.read_text(encoding="utf-8"))["actions"]
    assert {a["action"]: a["key"] for a in actions} == {a: k for a, k, _ in G.KEYBINDS}


def test_unreal_catalogue_file_matches() -> None:
    """VerseUI reads Data/ui/game_settings.json; it must be catalogue_json() exactly."""
    path = REPO / G.UNREAL_CATALOGUE
    if not path.is_file():
        pytest.skip("Unreal project not in this checkout")
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert text == G.unreal_catalogue_text(), "run: python -m dodaios.verse_host.game_settings"


def test_locale_has_every_setting() -> None:
    en = json.loads(
        (REPO / "dodaios/ui/web/frontend/src/i18n/locales/verse_settings/en.json").read_text(
            encoding="utf-8"
        )
    )["verse_settings"]
    for s in G.CATALOGUE:
        head, _, name = s.id.partition(".")
        assert en["s"][head][name]["label"], s.id
        for option in s.options:
            if s.id in ("display.resolution", "display.frame_limit") and option not in (
                "native",
                "unlimited",
            ):
                continue
            assert option in en["o"], (s.id, option)
    assert set(en["tabs"]) == set(G.TABS)
    assert {s.section for s in G.CATALOGUE} <= set(en["sections"])


def test_store_defaults_validation_and_key_conflicts(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    settings = store.settings()
    assert settings["game"]["graphics.shadows"] == "high"
    assert "audio.master" not in settings["game"]  # lives at view.volume
    after = store.update({"game": {"graphics.shadows": "low", "keybinds.jump": "C"}})
    assert after["game"]["graphics.shadows"] == "low"
    assert after["game"]["keybinds.jump"] == "C"
    assert SettingsStore(tmp_path / "settings.json").settings()["game"]["keybinds.jump"] == "C"
    for bad in (
        {"game": {"graphics.shadows": "ultra"}},
        {"game": {"nope": 1}},
        {"game": {"audio.master": 0.5}},  # legacy path, write view.volume
        {"game": {"controls.fov_duel": 200}},
        {"game": {"keybinds.fire": "Escape"}},
        {"game": {"keybinds.fire": "W"}},  # W is move_forward
        {"return_key": "W"},
    ):
        with pytest.raises(SettingsError):
            store.update(bad)
    assert store.settings()["game"]["keybinds.fire"] == "LeftMouseButton"
    # A swap in one patch is fine.
    swap = {"keybinds.fire": "W", "keybinds.move_forward": "LeftMouseButton"}
    swapped = store.update({"game": swap})
    assert swapped["game"]["keybinds.fire"] == "W"


async def test_patch_route_writes_and_pushes_to_verse(tmp_path: Path) -> None:
    host, _ = make_host(tmp_path)
    t, task = await connect(host)
    welcome = t.of_type("welcome")[0]["data"]
    assert "game_settings" in welcome["features"]
    assert welcome["settings"]["game"]["display.window_mode"] == "borderless"
    transport = httpx.ASGITransport(app=_app(host))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as c:
        cat = (await c.get("/api/verse/settings/catalogue")).json()
        assert cat["schema"] == "verse.settings.catalogue/1"
        res = await c.patch(
            "/api/verse/settings",
            json={"game": {"graphics.preset": "low"}, "view": {"volume": 0.4}},
        )
        assert res.status_code == 200
        assert res.json()["settings"]["view"]["volume"] == 0.4
        bad = await c.patch("/api/verse/settings", json={"game": {"graphics.preset": "ultra"}})
        assert bad.status_code == 422
    changed = await t.wait_for(lambda f: f["type"] == "settings.changed")
    assert changed["data"]["game"] == {"graphics.preset": "low"}
    assert changed["data"]["view"]["volume"] == 0.4
    await close(t, task)


async def test_settings_set_from_verse_sends_only_the_changed_game_keys(tmp_path: Path) -> None:
    host, _ = make_host(tmp_path)
    t, task = await connect(host)
    t.push(
        {
            "type": "settings.set",
            "id": "c-1",
            "ts": 1.0,
            "data": {"game": {"hud.crosshair_color": "cyan"}},
        }
    )
    reply = await t.reply_to("c-1")
    assert reply["data"]["result"]["settings"]["game"]["hud.crosshair_color"] == "cyan"
    changed = await t.wait_for(lambda f: f["type"] == "settings.changed")
    assert changed["data"] == {"game": {"hud.crosshair_color": "cyan"}}
    await close(t, task)
