"""WP11 hangar arena: layout, spawns, flow and placements (work-packages.md WP11).

The geometry acceptance rows that need no engine run here on the design-time
model of `art/verse/decks/hangar/unreal_arena` (A11.1, A11.2, A11.5, the
structural half of A11.7); the Unreal automation tests `Verse.Combat.Deathmatch.*`
and `Verse.Decks.HangarSwitch.*` cover the rules and the switch.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "art" / "verse" / "decks" / "hangar"))
sys.path.insert(0, str(REPO / "art" / "verse"))

from lib import placement as placement_lib  # noqa: E402
from unreal_arena import flow, nav, placements  # noqa: E402
from unreal_arena import layout as L  # noqa: E402

pytest.importorskip("jsonschema")


@pytest.fixture(scope="module")
def lay() -> L.Layout:
    return L.build()


@pytest.fixture(scope="module")
def graph(lay) -> nav.NavGraph:
    return nav.build(lay)


@pytest.fixture(scope="module")
def docs(lay) -> dict[str, dict]:
    return placements.documents(lay)


# --- A11.1 arena geometry ---------------------------------------------------------


def test_walkable_bounds_fit_50_by_40(graph):
    x0, x1, z0, z1 = graph.extent()
    assert x1 - x0 <= 50.0 + 1e-6
    assert z1 - z0 <= 40.0 + 1e-6
    ax0, ax1, az0, az1 = L.ARENA
    assert ax0 >= L.HALL[0] and ax1 <= L.HALL[1] and az0 >= L.HALL[2] and az1 <= L.HALL[3]


def test_three_levels_each_at_least_15_percent(graph):
    shares = graph.level_shares()
    assert set(shares) == {"L0", "L1", "L2"}
    for name, share in shares.items():
        assert share >= 0.15, (name, share)


def test_nav_is_one_island(graph):
    assert graph.islands() == [graph.count]


def test_arena_is_sealed_from_the_hall(lay):
    """Built over the whole hall in arena mode, no walkable node outside the
    arena bounds may reach one inside (the perimeter is closed on all sides)."""
    hall = nav.build(lay, bounds=(2.5, 97.5, 1.5, 61.6))
    ax0, ax1, az0, az1 = L.ARENA
    inside = (hall.xs > ax0) & (hall.xs < ax1) & (hall.zs > az0) & (hall.zs < az1)
    assert inside.any() and (~inside).any()
    shared = set(hall.labels[inside].tolist()) & set(hall.labels[~inside].tolist())
    assert not shared, f"{int((~inside & np.isin(hall.labels, list(shared))).sum())} nodes leak"


def test_ceiling_is_21_m_and_floor_is_whole(lay):
    ceiling = next(b for b in lay.boxes if b.id == "ceiling")
    assert ceiling.h0 == pytest.approx(21.0)
    floors = [b for b in lay.boxes if b.family == "HangarFloor"]
    area = sum((b.x1 - b.x0) * (b.z1 - b.z0) for b in floors)
    wx0, wx1, wz0, wz1 = L.WELL
    assert area == pytest.approx(100 * 62 - (wx1 - wx0) * (wz1 - wz0))


# --- A11.2 spawns -------------------------------------------------------------------


def test_at_least_eight_spawns_20_m_apart_by_path(lay, graph):
    assert len(lay.spawns) >= 8
    spacing = flow.spawn_spacing(graph, lay)
    assert spacing["min_path_m"] >= 20.0, spacing["closest"]


def test_every_spawn_stands_on_the_nav(lay, graph):
    for s in lay.spawns:
        n = graph.nearest(s.x, s.z, s.h)
        assert abs(graph.xs[n] - s.x) <= 0.5 and abs(graph.zs[n] - s.z) <= 0.5, s.id
        assert abs(graph.hs[n] - s.h) <= 0.35, s.id


# --- A11.5 flow (design-time model; the bot runs replace the walker in phase 2) ------


def test_longest_unbroken_sightline_at_most_40_m(lay, graph):
    lines = flow.sightlines(graph, lay, spacing_m=1.5)
    assert lines["longest_m"] <= flow.SIGHT_CAP_M, lines["worst"]


def test_walker_time_to_contact_median_in_range(lay, graph):
    ttc = flow.time_to_contact(graph, lay, runs=30)
    lo, hi = flow.TTC_RANGE_S
    assert lo <= ttc["median_s"] <= hi, ttc


def test_sight_test_honours_glass_and_walls(lay):
    boxes = flow.sight_boxes(lay)
    # Across the canyon at eye height, through a container (walls block) ...
    a = np.array([[59.0, 14.0, 1.65]])
    b = np.array([[65.0, 14.0, 1.65]])
    assert not flow.clear(a, b, boxes)[0]
    # ... and through the booth's east glass (glass does not).
    a = np.array([[36.0, 37.5, 4.65]])
    b = np.array([[39.5, 37.5, 4.65]])
    assert flow.clear(a, b, boxes)[0]


def test_bot_log_is_read(tmp_path):
    log = tmp_path / "runs.jsonl"
    log.write_text(
        '{"run": 1, "t_contact_s": 7.5}\n\n{"run": 2, "t_contact_s": 9.5}\n', encoding="utf-8"
    )
    assert flow.summarize_contacts(flow.contacts_from_log(log)) == {"runs": 2, "median_s": 8.5}


# --- placements, destructibles, A11.7 floor ------------------------------------------


def test_placement_documents_validate(docs, tmp_path):
    assert set(docs) == set(L.ZONES)
    for zone, doc in docs.items():
        path = tmp_path / "hangar" / f"{zone}.placement.json"
        placement_lib.write(path, doc)
        assert placement_lib.validate_file(path) == [], zone
        assert {p["owner"] for p in doc["placements"]} == {"WP11"}


def test_arena_zones_live_in_the_arena_layer(docs):
    for zone in L.ARENA_ZONES:
        layers = {p["data_layer"] for p in docs[zone]["placements"]}
        assert layers <= {"DL_Hangar_Arena", "DL_Hangar_Base"}, zone
        assert "DL_Hangar_Arena" in layers, zone
    assert {p["data_layer"] for p in docs["armoury"]["placements"]} == {"DL_Hangar_Base"}


def test_hall_floor_never_breaks(docs):
    floors = [p for p in docs["shell"]["placements"] if p["piece"] == "SM_HangarFloor"]
    assert len(floors) == 4
    for p in floors:
        assert p["destructible"] is None
        assert p["collision"] == "Verse_Architecture"
        assert p["nav"] == "walk"
        assert "Verse.Material.concrete" in p["tags"]


def test_destructibles_are_solid_at_their_reference_thickness(lay):
    pieces = [b for b in lay.boxes if b.piece_class]
    assert {b.piece_class for b in pieces} == set(L.PIECE_CLASSES)
    for b in pieces:
        material = L.PIECE_CLASSES[b.piece_class][0]
        assert b.material == material, b.id
        ref = L.REF_THICKNESS_M[material]
        assert min(b.size) == pytest.approx(ref, rel=0.10), (b.id, b.size, ref)


def test_canyon_aisles_are_3_6_m(lay):
    rows = sorted(L.ROW_X0)
    gaps = [rows[i + 1] - (rows[i] + L.CONTAINER_W) for i in range(len(rows) - 1)]
    assert gaps == pytest.approx([3.6] * len(gaps))


def test_spawn_sockets_and_armoury_station(docs):
    spawns = [s for d in docs.values() for s in d["sockets"] if s["kind"] == "spawn"]
    assert len(spawns) >= 8
    assert all(s["spawn"] == {"team": "any", "duel": True} for s in spawns)
    stations = [p["station"] for p in docs["armoury"]["placements"] if p["station"]]
    assert {"id": "armoury", "kind": "armoury"} in stations


def test_lights_are_warm_work_lights(docs):
    lights = [s["light"] for d in docs.values() for s in d["sockets"] if s["kind"] == "light"]
    assert lights
    # art-pipeline 8.2: hard work lights at 4300-6500 K.
    assert all(4300 <= li["kelvin"] <= 6500 for li in lights)


def test_haze_is_neutral_volumetric_height_fog():
    # art-pipeline 8.2 "Haze" and 8.3 "Coloured fog" (saturation > 0.1 fails), 6.3 Lumen only.
    import colorsys

    assert L.HAZE["fog"] == "exponential_height" and L.HAZE["volumetric"] is True
    assert L.HAZE["fog_density"] > 0
    for key in ("fog_inscattering_rgb", "volumetric_albedo_rgb"):
        _, sat, _ = colorsys.rgb_to_hsv(*L.HAZE[key])
        assert sat <= 0.1, key
    assert L.POST["gi"] == "lumen" and L.POST["reflections"] == "lumen"


def test_placements_are_deterministic(lay):
    a = placements.documents(lay)
    b = placements.documents(L.build())
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# --- rules data -----------------------------------------------------------------------


def test_deathmatch_rules_start_values():
    doc = json.loads(
        (REPO / "unreal" / "Verse" / "Data" / "rules" / "deathmatch.json").read_text("utf-8")
    )
    assert doc["schema"] == "verse.rules/1"
    assert doc["ruleset"] == "endless/1"
    assert doc["respawn_delay_s"] == 3.0
    assert doc["spawn_protection_max_s"] == 2.0
    assert doc["kills_per_set"] == 10
    assert doc["health_regen_per_s"] == 0.0
    assert doc["max_armor"] == 0.0
    known = {
        "schema",
        "ruleset",
        "respawn_delay_s",
        "spawn_protection_max_s",
        "kills_per_set",
        "health_regen_per_s",
        "max_armor",
        "loadout",
        "notes",
    }
    assert set(doc) <= known
