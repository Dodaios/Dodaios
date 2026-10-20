"""Gate for the cooked Verse content (no Blender): schema, files, names, budgets."""

from __future__ import annotations

import importlib.util
import json
import math
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "scripts" / "verse"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


validate = _load("verse_validate", TOOLS / "validate.py")
naming = validate.naming

DECKS = sorted(
    p for p in (validate.PUBLIC_VERSE / "decks").glob("*") if (p / "manifest.json").is_file()
)


def test_schema_is_a_valid_json_schema() -> None:
    validate.schema_validator()


def test_cooked_verse_tree_is_valid() -> None:
    assert validate.validate_all() == []


def test_cooked_verse_fits_the_total_budget() -> None:
    root = validate.PUBLIC_VERSE
    if root.is_dir():
        assert validate.total_bytes(root) <= validate.BUDGET_TOTAL


@pytest.mark.parametrize("deck_dir", DECKS, ids=[p.name for p in DECKS])
def test_screen_corners_lie_on_the_plate(deck_dir: Path) -> None:
    manifest = json.loads((deck_dir / "manifest.json").read_text(encoding="utf-8"))
    camera = manifest["camera"]
    for socket in manifest["sockets"]:
        for corner in socket.get("corners", []):
            x, y = validate.world_to_plate_px(camera, corner)
            assert 0 <= x <= camera["plate_w_px"] and 0 <= y <= camera["plate_h_px"]


def test_naming_round_trips() -> None:
    assert naming.socket_name("screen", "bridge_01") == "SOCKET_screen_bridge_01"
    parsed = naming.parse_socket("SOCKET_seat_pit_p_3.001")
    assert parsed == naming.SocketName(kind="seat", id="pit_p_3")
    assert naming.parse_socket("SOCKET_teleporter_x") is None
    assert naming.parse_room("ROOM_mess_hall") == "mess_hall"
    assert naming.is_occluder("UCX_wall_north")
    assert not naming.is_occluder("SM_Wall_1")
    with pytest.raises(ValueError):
        naming.level_name("Bridge")


def test_world_to_plate_matches_the_brief() -> None:
    pitch = math.radians(60)
    camera = {
        "centre": [0.0, 0.0, -1.0],
        "right": [1.0, 0.0, 0.0],
        "up": [0.0, math.cos(pitch), -math.sin(pitch)],
        "px_per_m": 96,
        "plate_w_px": 1920,
        "plate_h_px": 960,
    }
    assert validate.world_to_plate_px(camera, [0.0, 0.0, -1.0]) == (960.0, 480.0)
    x, y = validate.world_to_plate_px(camera, [1.0, 2.0, -1.0])
    assert x == pytest.approx(1056.0)
    assert y == pytest.approx(480.0 - 2 * math.cos(pitch) * 96)


@pytest.mark.skipif(not DECKS, reason="no cooked deck yet")
def test_validator_catches_broken_decks(tmp_path: Path) -> None:
    deck = tmp_path / DECKS[0].name
    shutil.copytree(DECKS[0], deck)
    manifest_path = deck / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sockets"].append(
        {"id": "far", "kind": "spawn", "position": [5000.0, 0.0, 0.0], "yaw_deg": 0, "room": None}
    )
    manifest["sockets"].append(
        {
            "id": "x",
            "kind": "seat",
            "position": [0, 0, 0],
            "yaw_deg": 0,
            "room": None,
            "station": "nope",
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (deck / "plate" / "L1.avif").unlink()
    problems = "\n".join(validate.validate_deck_dir(deck))
    assert "spawn_far is outside the plate" in problems
    assert "unknown station 'nope'" in problems
    assert "missing plate/L1.avif" in problems

    manifest["schema"] = "verse.deck/0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert any("schema" in p for p in validate.validate_deck_dir(deck))


navgrid = _load("verse_navgrid", REPO_ROOT / "art" / "verse" / "lib" / "navgrid.py")


def test_clearance_reaches_the_eight_neighbours_for_a_quarter_metre_body() -> None:
    offsets = navgrid.clearance_offsets(0.2, 0.25)
    assert sorted(offsets) == sorted(
        (di, dj) for di in (-1, 0, 1) for dj in (-1, 0, 1) if (di, dj) != (0, 0)
    )


def test_erosion_keeps_bodies_off_walls_and_drops_but_allows_steps() -> None:
    import numpy as np

    heights = np.zeros((7, 9))
    heights[:, 0] = np.nan  # wall on the left edge
    heights[:, 6:] = 0.2  # a 0.2 m step: still connected
    heights[0, :] = 1.0  # a 1 m platform along the top row
    eroded = navgrid.erode(heights)
    assert np.isnan(eroded[3, 1])  # touches the wall
    assert not np.isnan(eroded[3, 2])
    assert not np.isnan(eroded[3, 5]) and not np.isnan(eroded[3, 6])  # across the step
    assert np.isnan(eroded[1, 4])  # next to the 1 m drop


def test_samples_reduce_to_cells_and_encode() -> None:
    import numpy as np

    samples = np.zeros((6, 6))
    samples[0, 0] = np.nan  # one blocked sample blocks its cell
    samples[3:, 3:] = 0.6
    samples[5, 5] = 1.2  # 0.6 m spread inside one cell blocks it
    cells = navgrid.reduce_samples(samples, 3)
    assert np.isnan(cells[0, 0]) and np.isnan(cells[1, 1])
    assert cells[0, 1] == 0.0
    codes = navgrid.encode(np.array([[np.nan, 0.0, 0.6, -0.8]]))
    assert codes.tolist() == [[0, 128, 152, 96]]


plate_post = _load("verse_plate_post", REPO_ROOT / "art" / "verse" / "lib" / "plate_post.py")


@pytest.mark.parametrize("size", [(2592, 1696), (9696, 5616), (4096, 4096), (3968, 400)])
def test_plate_regions_cover_the_frame_once_within_the_size_limit(size: tuple[int, int]) -> None:
    import numpy as np

    width, height = size
    plan = plate_post.regions(width, height)
    coverage = np.zeros((height, width), dtype=np.int32)
    for region in plan:
        assert region.row1 - region.row0 <= plate_post.REGION_MAX_PX
        assert region.col1 - region.col0 <= plate_post.REGION_MAX_PX
        assert region.inner_row0 % 16 == 0 and region.inner_col0 % 16 == 0
        coverage[region.inner_row0 : region.inner_row1, region.inner_col0 : region.inner_col1] += 1
    assert (coverage == 1).all()


def test_region_wise_glow_equals_whole_image_bloom() -> None:
    import numpy as np

    rng = np.random.default_rng(0)
    linear = rng.random((96, 160, 3), dtype=np.float32) * 0.5
    linear[40:44, 70:90] = 20.0  # a light panel
    whole = plate_post.bloom(linear, px_per_m=96)
    factor = plate_post.GLOW_FACTOR
    plan = plate_post.regions(160, 96, max_px=64, overlap=8)
    small = np.zeros((96 // factor, 160 // factor, 3), dtype=np.float32)
    for r in plan:
        inner = linear[r.inner_row0 : r.inner_row1, r.inner_col0 : r.inner_col1]
        rows = slice(r.inner_row0 // factor, r.inner_row1 // factor)
        cols = slice(r.inner_col0 // factor, r.inner_col1 // factor)
        small[rows, cols] = plate_post.downsample(plate_post.bright(inner), factor)
    glow = plate_post.glow(small, 96 / factor)
    for r in plan:
        part = linear[r.inner_row0 : r.inner_row1, r.inner_col0 : r.inner_col1]
        part = part + plate_post.BLOOM_STRENGTH * plate_post.upsample_window(
            glow, factor, r.inner_row0, r.inner_row1, r.inner_col0, r.inner_col1
        )
        np.testing.assert_allclose(
            part, whole[r.inner_row0 : r.inner_row1, r.inner_col0 : r.inner_col1], atol=1e-5
        )
    added = (whole - linear).sum(axis=2)
    assert added[30, 80] > added[5, 5] > 0  # glow spills around the panel and falls off


@pytest.mark.skipif(not DECKS, reason="no cooked deck yet")
def test_validator_rejects_a_nav_grid_without_walkable_cells(tmp_path: Path) -> None:
    from PIL import Image

    deck = tmp_path / DECKS[0].name
    shutil.copytree(DECKS[0], deck)
    manifest = json.loads((deck / "manifest.json").read_text(encoding="utf-8"))
    nav = manifest["nav"]
    Image.new("L", (nav["w"], nav["h"]), 0).save(deck / nav["url"])
    assert any("walkable cells" in p for p in validate.validate_deck_dir(deck))
    manifest["nav"]["walkable_cells"] = 0
    (deck / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert any("walkable_cells" in p for p in validate.validate_deck_dir(deck))
