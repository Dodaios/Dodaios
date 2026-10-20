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
package = _load("verse_package", TOOLS / "package.py")
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


def test_plate_levels_follow_the_manifest_contract() -> None:
    plate = package.plate_levels(19392, 12256)  # a 101 x 63.8 m deck at 192 px/m
    assert (plate["tile_px"], plate["cols"], plate["rows"]) == (2048, 10, 6)
    assert plate["tile_url"] == "plate/L0_{col}_{row}.avif"
    assert plate["mips"] == [
        {
            "divisor": 2,
            "w_px": 9696,
            "h_px": 6128,
            "cols": 5,
            "rows": 3,
            "tile_url": "plate/M2_{col}_{row}.avif",
        },
        {
            "divisor": 4,
            "w_px": 4848,
            "h_px": 3064,
            "cols": 3,
            "rows": 2,
            "tile_url": "plate/M4_{col}_{row}.avif",
        },
    ]
    assert (plate["l1_url"], plate["l1_w_px"], plate["l1_h_px"]) == ("plate/L1.avif", 2424, 1532)
    validate.schema_validator()  # the block must stay valid against the schema
    schema = json.loads(validate.SCHEMA_PATH.read_text(encoding="utf-8"))
    from jsonschema import Draft202012Validator

    Draft202012Validator(schema["properties"]["plate"]).validate(plate)


def _package_small_plate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict]:
    """Encode a 640 x 320 test plate with 256 px tiles; return the deck dir and manifest."""
    import numpy as np
    from PIL import Image

    monkeypatch.setattr(package, "TILE_PX", 256)
    rng = np.random.default_rng(1)
    pixels = rng.integers(0, 255, (320, 640, 3), dtype=np.uint8)
    deck = tmp_path / "deck"
    plate = package._encode_plate(Image.fromarray(pixels, mode="RGB"), deck)
    manifest = {"plate": plate, "camera": {"plate_w_px": 640, "plate_h_px": 320}}
    return deck, manifest


def test_packager_writes_every_level_the_validator_expects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deck, manifest = _package_small_plate(tmp_path, monkeypatch)
    plate = manifest["plate"]
    assert (plate["cols"], plate["rows"]) == (3, 2)
    assert [(m["w_px"], m["h_px"], m["cols"], m["rows"]) for m in plate["mips"]] == [
        (320, 160, 2, 1),
        (160, 80, 1, 1),
    ]
    assert (plate["l1_w_px"], plate["l1_h_px"]) == (80, 40)
    names = sorted(p.name for p in (deck / "plate").iterdir())
    assert names == [
        "L0_0_0.avif", "L0_0_1.avif", "L0_1_0.avif", "L0_1_1.avif", "L0_2_0.avif", "L0_2_1.avif",
        "L1.avif", "M2_0_0.avif", "M2_1_0.avif", "M4_0_0.avif",
    ]  # fmt: skip
    assert validate.avif_size(deck / "plate" / "M2_1_0.avif") == (64, 160)  # edge tile
    assert validate._check_plate("deck", deck, manifest) == []


def test_validator_catches_broken_mip_levels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deck, manifest = _package_small_plate(tmp_path, monkeypatch)
    (deck / "plate" / "M4_0_0.avif").unlink()
    (deck / "plate" / "M8_0_0.avif").write_bytes(b"")
    manifest["plate"]["mips"][0]["w_px"] = 321
    problems = " | ".join(validate._check_plate("deck", deck, manifest))
    assert "missing tile plate/M4_0_0.avif" in problems
    assert "stray files in the plate folder: ['M8_0_0.avif']" in problems
    assert "mip /2 is 321x160, expected 320x160" in problems

    del manifest["plate"]["mips"]
    assert any("plate.mips missing" in p for p in validate._check_plate("deck", deck, manifest))


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
