"""Game settings: the catalog, the sensitivity maths, the profile store, the API."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.games import sensitivity
from dodaios.games.catalog import SECTION_IDS, SETTING_TYPES, get_game, list_games
from dodaios.games.store import GameProfileStore, UnknownGameError

# --------------------------------------------------------------------------- catalog


def test_catalog_covers_the_big_shooters() -> None:
    ids = {g["id"] for g in list_games()}
    assert {"fortnite", "cod_bo6", "r6_siege_x", "valorant", "cs2", "apex"} <= ids


@pytest.mark.parametrize("game", list_games(), ids=lambda g: g["id"])
def test_every_game_is_well_formed(game: dict) -> None:
    assert [s["id"] for s in game["sections"]] == list(SECTION_IDS)
    keys = [s["key"] for section in game["sections"] for s in section["settings"]]
    assert len(keys) == len(set(keys)), "setting keys must be unique per game"
    for section in game["sections"]:
        for setting in section["settings"]:
            assert setting["type"] in SETTING_TYPES
            if setting["type"] == "select":
                assert len(setting["options"]) >= 2
                assert setting["default"] in (None, *setting["options"])
            if setting["type"] == "slider":
                assert setting["min"] < setting["max"]
    bind_ids = [k["id"] for k in game["keybinds"]]
    assert len(bind_ids) == len(set(bind_ids))
    assert len(bind_ids) >= 10
    if game["yaw"]:
        assert game["sens_key"] in keys
    else:
        assert game["sens_key"] is None


# --------------------------------------------------------------------------- maths


def test_cm_per_360_matches_known_values() -> None:
    # CS2 at 2.0 / 400 DPI is the classic 51.95 cm/360.
    assert sensitivity.cm_per_360(0.022, 2.0, 400) == pytest.approx(51.95, abs=0.01)


def test_convert_cs2_to_valorant_is_the_well_known_ratio() -> None:
    # Valorant = CS / 3.1818...
    assert sensitivity.convert(1.0, 0.022, 0.07, 800) == pytest.approx(0.3143, abs=1e-4)


def test_convert_keeps_cm_per_360_across_dpi() -> None:
    target = sensitivity.convert(6.4, 0.005555, 0.0066, 800, 1600)
    assert sensitivity.cm_per_360(0.005555, 6.4, 800) == pytest.approx(
        sensitivity.cm_per_360(0.0066, target, 1600)
    )


def test_sens_for_cm_inverts_cm_per_360() -> None:
    sens = sensitivity.sens_for_cm(30, 0.07, 800)
    assert sensitivity.cm_per_360(0.07, sens, 800) == pytest.approx(30)


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf")])
def test_maths_refuses_non_positive_input(bad: float) -> None:
    with pytest.raises(ValueError):
        sensitivity.cm_per_360(0.022, bad, 800)


# --------------------------------------------------------------------------- store


@pytest.fixture
def store(tmp_path) -> GameProfileStore:
    return GameProfileStore(tmp_path / "games" / "profiles.json")


def test_update_merges_and_persists(store: GameProfileStore) -> None:
    store.update("valorant", values={"aim_sens": 0.35}, keybinds={"jump": "Mouse Wheel Down"})
    store.update("valorant", values={"scoped_mult": 1.0}, dpi=1600, notes="0.35 @ 1600")
    profile = store.profile("valorant")
    assert profile["values"] == {"aim_sens": 0.35, "scoped_mult": 1.0}
    assert profile["keybinds"] == {"jump": "Mouse Wheel Down"}
    assert profile["dpi"] == 1600
    assert profile["notes"] == "0.35 @ 1600"
    on_disk = json.loads(store.path.read_text(encoding="utf-8"))
    assert on_disk["games"]["valorant"]["values"]["aim_sens"] == 0.35


def test_none_removes_a_value_and_dpi_none_follows_default(store: GameProfileStore) -> None:
    store.update("cs2", values={"sensitivity": 1.1}, dpi=400)
    store.update("cs2", values={"sensitivity": None}, dpi=None)
    profile = store.profile("cs2")
    assert profile["values"] == {}
    assert profile["dpi"] is None


def test_leaving_dpi_out_keeps_it(store: GameProfileStore) -> None:
    store.update("cs2", dpi=400)
    store.update("cs2", values={"sensitivity": 1.0})
    assert store.profile("cs2")["dpi"] == 400


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"nope": 1}, "Unknown setting"),
        ({"aim_sens": 999}, "at most"),
        ({"aim_sens": "fast"}, "expected a number"),
        ({"aim_sens": True}, "expected a number"),
        ({"raw_input_buffer": 1}, "on or off"),
    ],
)
def test_bad_values_are_refused_and_nothing_is_written(
    store: GameProfileStore, values: dict, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        store.update("valorant", values=values)
    assert not store.path.exists()


def test_select_values_must_be_an_option(store: GameProfileStore) -> None:
    game = get_game("r6_siege_x")
    select = next(s for sec in game["sections"] for s in sec["settings"] if s["type"] == "select")
    store.update("r6_siege_x", values={select["key"]: select["options"][0]})
    with pytest.raises(ValueError, match="options"):
        store.update("r6_siege_x", values={select["key"]: "Ultra Mega"})


def test_unknown_game_and_keybind(store: GameProfileStore) -> None:
    with pytest.raises(UnknownGameError):
        store.update("tetris", values={})
    with pytest.raises(ValueError, match="Unknown keybind"):
        store.update("cs2", keybinds={"fly": "F"})


def test_reset_forgets_the_profile(store: GameProfileStore) -> None:
    store.update("apex", values={"mouse_sens": 1.5})
    assert store.reset("apex") is True
    assert store.reset("apex") is False
    assert store.profile("apex")["values"] == {}


def test_corrupt_file_reads_as_empty(store: GameProfileStore) -> None:
    store.path.parent.mkdir(parents=True)
    store.path.write_text("{not json", encoding="utf-8")
    assert store.snapshot()["games"] == {}


def test_default_dpi_bounds(store: GameProfileStore) -> None:
    assert store.set_default_dpi(1600) == 1600
    assert store.snapshot()["dpi"] == 1600
    with pytest.raises(ValueError):
        store.set_default_dpi(10)


# --------------------------------------------------------------------------- API


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    from dodaios.core import config
    from dodaios.ui.web.games_routes import router

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_index_lists_games_and_default_dpi(client: TestClient) -> None:
    body = client.get("/api/games").json()
    assert body["dpi"] == 800
    fortnite = next(g for g in body["games"] if g["id"] == "fortnite")
    assert fortnite == {
        "id": "fortnite",
        "name": "Fortnite",
        "publisher": "Epic Games",
        "convertible": True,
        "has_profile": False,
        "updated_at": None,
    }


def test_profile_round_trip(client: TestClient) -> None:
    response = client.put(
        "/api/games/fortnite/profile",
        json={"values": {"mouse_sens_x": 6.4}, "keybinds": {"jump": "Space"}, "dpi": 1600},
    )
    assert response.status_code == 200
    detail = client.get("/api/games/fortnite").json()
    assert detail["profile"]["values"] == {"mouse_sens_x": 6.4}
    assert detail["profile"]["dpi"] == 1600
    assert detail["game"]["name"] == "Fortnite"
    assert next(g for g in client.get("/api/games").json()["games"] if g["id"] == "fortnite")[
        "has_profile"
    ]
    reset = client.put("/api/games/fortnite/profile", json={"reset_dpi": True})
    assert reset.json()["profile"]["dpi"] is None
    assert client.delete("/api/games/fortnite/profile").json() == {"removed": True}


def test_profile_errors(client: TestClient) -> None:
    assert client.get("/api/games/tetris").status_code == 404
    assert client.put("/api/games/tetris/profile", json={}).status_code == 404
    bad = client.put("/api/games/cs2/profile", json={"values": {"sensitivity": 50}})
    assert bad.status_code == 400
    assert "at most" in bad.json()["detail"]


def test_convert_lists_every_other_linear_game(client: TestClient) -> None:
    payload = {"game_id": "cs2", "sens": 1.0, "dpi": 800}
    body = client.post("/api/games/convert", json=payload).json()
    assert body["cm_per_360"] == pytest.approx(51.95, abs=0.01)
    assert body["edpi"] == 800
    by_id = {row["id"]: row for row in body["results"]}
    assert "cs2" not in by_id
    assert "battlefield6" not in by_id  # not linear
    assert by_id["valorant"]["sens"] == pytest.approx(0.3143, abs=1e-4)
    assert by_id["apex"]["sens"] == pytest.approx(1.0)
    assert by_id["valorant"]["sens_key"] == "aim_sens"


def test_convert_uses_the_saved_default_dpi(client: TestClient) -> None:
    client.put("/api/games/dpi", json={"dpi": 400})
    body = client.post("/api/games/convert", json={"game_id": "cs2", "sens": 2.0}).json()
    assert body["dpi"] == 400
    assert body["cm_per_360"] == pytest.approx(51.95, abs=0.01)


def test_convert_refuses_non_linear_games_and_bad_input(client: TestClient) -> None:
    pubg = client.post("/api/games/convert", json={"game_id": "pubg", "sens": 50})
    assert pubg.status_code == 400
    assert client.post("/api/games/convert", json={"game_id": "cs2", "sens": 0}).status_code == 400
    assert client.post("/api/games/convert", json={"game_id": "x", "sens": 1}).status_code == 404
    assert client.put("/api/games/dpi", json={"dpi": 1}).status_code == 400
