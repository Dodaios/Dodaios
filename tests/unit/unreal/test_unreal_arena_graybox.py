"""arena_graybox.py: the runtime hangar arena the Verse builds from WP11's layout."""

from __future__ import annotations

import json

from scripts.unreal import arena_graybox


def test_committed_json_matches_the_layout():
    assert arena_graybox.main(["--check"]) == 0


def test_graybox_has_the_arena_spawns_inside_its_bounds():
    data = arena_graybox.build()
    x0, y0, x1, y1 = data["arenaBoundsCm"]
    assert data["schema"] == arena_graybox.SCHEMA
    assert len(data["spawns"]) >= 2
    for spawn in data["spawns"]:
        x, y, _ = spawn["location"]
        assert x0 <= x <= x1 and y0 <= y <= y1, spawn["id"]


def test_boxes_are_centre_and_size_in_centimetres_and_skip_the_day_layer():
    data = arena_graybox.build()
    assert data["boxes"], "no boxes"
    assert all(b["layer"] in ("base", "arena") for b in data["boxes"])
    floor = next(b for b in data["boxes"] if b["id"] == "floor_north")
    assert floor["size"][0] == 10000.0  # the 100 m hall


def test_ramps_run_from_their_low_to_their_high_edge():
    for ramp in arena_graybox.build()["ramps"]:
        assert ramp["start"] != ramp["end"], ramp["id"]
        assert ramp["widthCm"] > 0 and ramp["thicknessCm"] > 0


def test_render_is_stable_json():
    text = arena_graybox.render(arena_graybox.build())
    assert json.loads(text)["schema"] == arena_graybox.SCHEMA
    assert text.endswith("\n")


def test_lights_name_their_layer_so_the_deck_hall_lights_without_the_arena():
    # The hangar deck view builds the hall (layer "base") alone; the arena's practicals come with
    # the duel. Every light says which part it belongs to.
    data = arena_graybox.build()
    layers = {light["id"]: light["layer"] for light in data["lights"]}
    assert set(layers.values()) == {"base", "arena"}
    assert all(layers[i] == "base" for i in layers if i.startswith(("work_", "armoury_")))
    for light in data["lights"]:
        assert (light["layer"] == "arena") == light["zone"].startswith("arena"), light["id"]
