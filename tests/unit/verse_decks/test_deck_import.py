"""WP12: today's deck manifests carried into Unreal zone placement JSON (A12.1, A12.6)."""

from __future__ import annotations

import colorsys
import importlib.util
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "art" / "verse"))

from lib import placement  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "verse_deck_import", ROOT / "art" / "verse" / "kit" / "deck_import.py"
)
assert _SPEC and _SPEC.loader
deck_import = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = deck_import
_SPEC.loader.exec_module(deck_import)

AGENT_DECKS = deck_import.AGENT_DECKS


def committed_docs(deck: str) -> list[dict]:
    """The committed zone files of `deck` that WP12 owns."""
    zones = [zone.id for zone in deck_import.zones_of(deck)]
    paths = [deck_import.zone_path(deck, zone) for zone in zones]
    return [json.loads(path.read_text(encoding="utf-8")) for path in paths]


def angle_gap(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def union(docs):
    rooms, sockets = {}, {}
    for doc in docs:
        for room in doc["rooms"]:
            assert room["id"] not in rooms, f"room {room['id']} in two zones"
            rooms[room["id"]] = room
        for socket in doc["sockets"]:
            key = deck_import.socket_key(socket["id"])
            assert key not in sockets, f"socket {key} in two zones"
            sockets[key] = socket
    return rooms, sockets


@pytest.mark.parametrize("deck", AGENT_DECKS)
def test_rooms_sockets_and_stations_match_the_manifest_by_id(deck):
    manifest = deck_import.load_manifest(deck)
    rooms, sockets = union(committed_docs(deck))
    assert set(rooms) == {r["id"] for r in manifest["rooms"]}
    assert set(sockets) == {(s["kind"], s["id"]) for s in manifest["sockets"]}
    stations = {
        s["station"]["id"]: s for s in sockets.values() if s["kind"] == "station" and s["station"]
    }
    assert set(stations) == {st["id"] for st in manifest["stations"]}
    for station in manifest["stations"]:
        socket = stations[station["id"]]
        assert socket["station"]["kind"] == station["kind"]
        for group, ids in station["sockets"].items():
            assert socket["props"][f"sockets.{group}"].split(",") == ids


def test_the_hangar_day_zones_carry_their_rooms_and_every_socket_in_them():
    manifest = deck_import.load_manifest("hangar")
    rooms, sockets = union(committed_docs("hangar"))
    assert set(rooms) == {"lift_lobby", "arrivals"}
    wanted = {(s["kind"], s["id"]) for s in manifest["sockets"] if s["room"] in rooms}
    assert set(sockets) == wanted
    stations = {s["station"]["id"]: s["station"]["kind"] for s in sockets.values() if s["station"]}
    assert stations == {"arrivals": "create_agent", "lift": "lift"}


@pytest.mark.parametrize("deck", (*AGENT_DECKS, "hangar"))
def test_positions_and_headings_round_trip_to_the_manifest(deck):
    manifest = deck_import.load_manifest(deck)
    _rooms, sockets = union(committed_docs(deck))
    raw = {(s["kind"], s["id"]): s for s in manifest["sockets"]}
    for key, socket in sockets.items():
        source = raw[key]
        x, y, z = socket["location"]
        back = [x / 100.0, z / 100.0, y / 100.0]
        assert back == pytest.approx(source["position"], abs=1e-5), key
        heading = deck_import.quat_yaw_deg(socket["rotation"])
        assert angle_gap(deck_import.three_yaw_deg(heading), source["yaw_deg"]) < 1e-4, key


def test_the_commander_spawn_lands_on_the_coordinates_golden_row():
    """contracts/coordinates.md 3.2: (70, 0, 54.2) yaw 0 -> (7000, 5420, 0), heading 90."""
    _rooms, sockets = union(committed_docs("hangar"))
    spawn = sockets[("spawn", "commander")]
    assert spawn["location"] == pytest.approx([7000.0, 5420.0, 0.0])
    assert deck_import.quat_yaw_deg(spawn["rotation"]) == pytest.approx(90.0)
    lift = sockets[("door", "lift_a")]
    assert lift["location"] == pytest.approx([6800.0, 5072.0, 0.0])


@pytest.mark.parametrize(
    ("three", "unreal"), [(0, 90), (90, 0), (-90, 180), (180, -90), (135, -45), (-135, -135)]
)
def test_heading_follows_the_coordinates_table(three, unreal):
    assert deck_import.heading_deg(three) == pytest.approx(unreal)


def test_every_zone_file_is_valid_canonical_and_up_to_date():
    files = sorted(deck_import.PLACEMENTS_ROOT.glob("*/*.placement.json"))
    mine = [
        p for p in files
        if p.parent.name in AGENT_DECKS or p.stem.split(".")[0] in deck_import.HANGAR_ZONES
    ]
    assert len(mine) >= 20
    for path in mine:
        assert placement.validate_file(path) == [], path
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["source"]["builder"].startswith("art/verse/decks/")
    assert deck_import.write_all(check=True) == []


def test_room_less_sockets_go_to_the_nearest_zone_and_stay_inside_its_box():
    for deck in AGENT_DECKS:
        for doc in deck_import.build_zone_docs(deck):
            lo, hi = doc["bounds_cm"]["min"], doc["bounds_cm"]["max"]
            for socket in doc["sockets"]:
                inside = zip(socket["location"], lo, hi, strict=True)
                assert all(a <= v <= b for v, a, b in inside), socket["id"]


def test_two_zones_claiming_one_room_is_an_error():
    zone = deck_import.Zone
    with pytest.raises(ValueError, match="claimed"):
        deck_import.assign_zones({"rooms": []}, [zone("a", ("x",)), zone("b", ("x",))])


def _hue_sat(hex_colour: str) -> tuple[float, float]:
    r, g, b = (int(hex_colour[i : i + 2], 16) / 255.0 for i in (1, 3, 5))
    h, s, _v = colorsys.rgb_to_hsv(r, g, b)
    return h * 360.0, s


def test_lights_are_noir_work_lights_or_allowed_accent_lamps():
    """art-pipeline 8.2/8.3: work lights 4300-6500 K; lamps never cyan, violet or info blue."""
    seen = defaultdict(int)
    for deck in (*AGENT_DECKS, "hangar"):
        for doc in committed_docs(deck):
            for socket in doc["sockets"]:
                if socket["kind"] != "light":
                    continue
                seen[deck] += 1
                light = socket["light"]
                assert light["shadows"] is True
                assert 4300 <= light["kelvin"] <= 6500, socket["id"]
                colour = socket["props"].get("colour")
                if colour:
                    hue, sat = _hue_sat(colour)
                    assert not (160 <= hue <= 210 and sat > 0.35), socket["id"]
                    assert not (250 <= hue <= 330 and sat > 0.2), socket["id"]
                    assert not (210 <= hue <= 250 and sat > 0.4), socket["id"]
    assert all(seen[deck] > 0 for deck in AGENT_DECKS)


def test_socket_ids_reverse_and_reject_bare_ids():
    assert deck_import.socket_key("station-lift") == ("station", "lift")
    assert deck_import.socket_key("seat-arrivals__arrival") == ("seat", "arrivals__arrival")
    with pytest.raises(ValueError):
        deck_import.socket_key("lift")
    assert math.isclose(deck_import.quat_yaw_deg(deck_import.yaw_quat_xyzw(-135.0)), -135.0)
