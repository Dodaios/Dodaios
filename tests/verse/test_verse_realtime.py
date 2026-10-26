"""Gate for the realtime (eye-level) export pieces that run without Blender:
lightmap packing, gap filling, denoising, the rgbm2 encoding, the GLB writer
and the validator's realtime checks (docs/verse/realtime.md)."""

from __future__ import annotations

import importlib.util
import json
import shutil
import struct
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "scripts" / "verse"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


lightmap = _load("verse_lightmap_test", REPO_ROOT / "art" / "verse" / "lib" / "lightmap.py")
package_realtime = _load("verse_package_realtime", TOOLS / "package_realtime.py")
validate = _load("verse_validate_rt", TOOLS / "validate.py")

REALTIME_DECKS = sorted(
    p
    for p in (validate.PUBLIC_VERSE / "decks").glob("*")
    if (p / "manifest.json").is_file()
    and "realtime" in json.loads((p / "manifest.json").read_text(encoding="utf-8"))
)


# ---------------------------------------------------------------- packing


def test_packing_keeps_rectangles_apart_and_on_their_page() -> None:
    rng = np.random.default_rng(3)
    sizes = [(float(w), float(h)) for w, h in rng.integers(4, 300, size=(400, 2))]
    groups = [int(g) for g in rng.integers(0, 4, size=400)]
    pad = 7
    placements = lightmap.pack_skyline(sizes, groups, 1024, pad)
    boxes = {}
    for (w, h), place in zip(sizes, placements, strict=True):
        w, h = int(np.ceil(w * place.scale)), int(np.ceil(h * place.scale))
        assert place.x >= pad and place.y >= pad
        assert place.x + w <= 1024 - pad + 1 and place.y + h <= 1024 - pad + 1
        boxes.setdefault(place.page, []).append(
            (place.x - pad, place.y - pad, w + 2 * pad, h + 2 * pad)
        )
    for page in boxes.values():
        for i, (ax, ay, aw, ah) in enumerate(page):
            for bx, by, bw, bh in page[i + 1 :]:
                assert ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay


def test_packing_keeps_a_room_together() -> None:
    sizes = [(100.0, 100.0)] * 6
    placements = lightmap.pack_skyline(sizes, [0, 1, 0, 1, 0, 1], 512, 2)
    rows = {}
    for group, place in zip([0, 1, 0, 1, 0, 1], placements, strict=True):
        rows.setdefault(group, []).append((place.page, place.y, place.x))
    # Group 0 is placed before group 1 starts.
    assert max(rows[0]) < min(rows[1])


def test_oversized_rectangles_shrink_to_fit_a_page() -> None:
    (place,) = lightmap.pack_skyline([(5000.0, 100.0)], [0], 1024, 4)
    assert place.scale < 1 and 5000 * place.scale <= 1024 - 8 + 1


def test_packing_fills_most_of_a_page_with_mixed_sizes() -> None:
    # A few floors and walls a third of a page wide among hundreds of props.
    rng = np.random.default_rng(5)
    big = [(float(w), float(h)) for w, h in rng.integers(150, 450, size=(6, 2))]
    small = [(float(w), float(h)) for w, h in rng.integers(4, 90, size=(300, 2))]
    sizes = big + small
    placements = lightmap.pack_skyline(sizes, [0] * len(sizes), 1024, 3)
    assert max(p.page for p in placements) == 1
    pairs = zip(sizes, placements, strict=True)
    first = sum((w + 6) * (h + 6) for (w, h), p in pairs if p.page == 0)
    assert first / (1024 * 1024) > 0.8  # the full first page (shelves: about half)


# ---------------------------------------------------------------- filtering


def test_fill_gaps_keeps_covered_texels_and_fills_the_rest() -> None:
    image = np.zeros((32, 32, 3), np.float32)
    covered = np.zeros((32, 32), bool)
    image[4:10, 4:10] = (1.0, 2.0, 3.0)
    covered[4:10, 4:10] = True
    filled = lightmap.fill_gaps(image, covered)
    assert np.allclose(filled[covered], image[covered])
    assert np.isfinite(filled).all()
    assert np.allclose(filled[20, 20], (1.0, 2.0, 3.0), atol=1e-4)


def test_denoise_smooths_noise_but_not_across_a_corner() -> None:
    rng = np.random.default_rng(1)
    h, w = 64, 64
    irradiance = np.ones((h, w, 3), np.float32)
    irradiance[:, 32:] = 5.0
    noisy = irradiance * (1 + 0.3 * rng.standard_normal((h, w, 1)).astype(np.float32))
    normal = np.zeros((h, w, 3), np.float32)
    normal[:, :32] = (0, 0, 1)
    normal[:, 32:] = (1, 0, 0)  # a corner between the two halves
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32) * 0.03
    position = np.stack([xx, yy, np.zeros_like(xx)], axis=2)
    covered = np.ones((h, w), bool)
    out = lightmap.denoise(noisy, normal, position, covered, texel_m=0.03, passes=3)
    assert np.std(out[:, 4:28]) < 0.5 * np.std(noisy[:, 4:28])
    # No light bleeds over the corner: the dim side stays dim right next to it.
    assert abs(float(out[:, 31].mean()) - 1.0) < 0.15
    assert abs(float(out[:, 32].mean()) - 5.0) < 0.6


# ---------------------------------------------------------------- rgbm2


@pytest.mark.parametrize("value", [0.0005, 0.01, 0.3, 1.0, 7.5, 31.0])
def test_rgbm2_round_trips_within_one_percent(value: float) -> None:
    radiance = np.array([[[value, value * 0.5, value * 0.25]]], np.float32)
    span = lightmap.rgbm_range(32.0)
    back = lightmap.rgbm_decode(lightmap.rgbm_encode(radiance, span), span)
    assert np.allclose(back[..., 0], value, rtol=0.012, atol=2e-6)
    assert np.allclose(back[..., 2], value * 0.25, rtol=0.03, atol=2e-5)


def test_rgbm2_range_is_a_power_of_two_capped_at_64() -> None:
    assert lightmap.rgbm_range(0.3) == 1.0
    assert lightmap.rgbm_range(24.0) == 32.0
    assert lightmap.rgbm_range(500.0) == 64.0


def test_rgbm2_webp_keeps_its_alpha_exactly(tmp_path: Path) -> None:
    rng = np.random.default_rng(5)
    radiance = (rng.random((64, 64, 3)) ** 4 * 20).astype(np.float32)
    path = tmp_path / "page.webp"
    package_realtime.write_rgbm_webp(radiance, path, 32.0, 90)
    with Image.open(path) as image:
        assert image.mode == "RGBA"
        decoded = np.asarray(image)
    assert np.array_equal(decoded[..., 3], lightmap.rgbm_encode(radiance, 32.0)[..., 3])


# ---------------------------------------------------------------- glTF


def _glb_parts(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    magic, version, total = struct.unpack("<4sII", data[:12])
    assert magic == b"glTF" and version == 2 and total == len(data)
    length, kind = struct.unpack("<I4s", data[12:20])
    assert kind == b"JSON"
    gltf = json.loads(data[20 : 20 + length])
    bin_length, bin_kind = struct.unpack("<I4s", data[20 + length : 28 + length])
    assert bin_kind == b"BIN\0"
    return gltf, data[28 + length : 28 + length + bin_length]


@pytest.mark.skipif(shutil.which("node") is None, reason="node runs the meshopt encoder")
def test_glb_writer_emits_quantised_meshopt_chunks(tmp_path: Path) -> None:
    encoder = REPO_ROOT / "dodaios/ui/web/frontend/node_modules/meshoptimizer/meshopt_encoder.js"
    if not encoder.is_file():
        pytest.skip("frontend node_modules not installed")
    pos = np.array([[0, 0, 0], [2, 0, 0], [2, 0, 3], [0, 0, 3]], np.float32)
    arrays = {
        "0_pos": pos,
        "0_nrm": np.tile(np.array([[0, 1, 0]], np.float32), (4, 1)),
        "0_uv": np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32),
        "0_idx": np.array([0, 1, 2, 0, 2, 3], np.uint32),
    }
    chunks = [{"index": 0, "material": "M_Floor_GlossBlack", "room": "bridge", "page": 0}]
    stats = package_realtime.write_glb(chunks, arrays, tmp_path / "scene.glb", tmp_path)
    assert stats == {"vertices": 4, "triangles": 2, "chunks": 1}
    gltf, _ = _glb_parts(tmp_path / "scene.glb")
    assert set(gltf["extensionsRequired"]) == {"EXT_meshopt_compression", "KHR_mesh_quantization"}
    (node,) = gltf["nodes"]
    assert node["extras"] == {"material": "M_Floor_GlossBlack", "room": "bridge", "page": 0}
    # Dequantised positions reproduce the chunk: translation + scale * q.
    accessor = gltf["accessors"][gltf["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]
    lo = np.array(node["translation"]) + node["scale"][0] * np.array(accessor["min"])
    hi = np.array(node["translation"]) + node["scale"][0] * np.array(accessor["max"])
    assert np.allclose(lo, pos.min(axis=0), atol=1e-3)
    assert np.allclose(hi, pos.max(axis=0), atol=1e-3)
    for view in gltf["bufferViews"]:
        assert view["extensions"]["EXT_meshopt_compression"]["buffer"] == 0


# ---------------------------------------------------------------- validator


@pytest.mark.parametrize("deck_dir", REALTIME_DECKS, ids=[p.name for p in REALTIME_DECKS])
def test_realtime_export_fits_its_budget(deck_dir: Path) -> None:
    manifest = json.loads((deck_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["realtime"]["bytes"] <= validate.BUDGET_REALTIME


@pytest.mark.skipif(not REALTIME_DECKS, reason="no deck has a realtime export yet")
def test_validator_catches_broken_realtime_exports(tmp_path: Path) -> None:
    source = REALTIME_DECKS[0]
    deck = tmp_path / source.name
    shutil.copytree(source, deck)
    assert validate.validate_deck_dir(deck) == []
    manifest_path = deck / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["realtime"]["probes"][0]["room"] = "nowhere"
    manifest["realtime"]["scene"]["chunks"] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (deck / "realtime" / "stray.bin").write_bytes(b"x")
    (deck / manifest["realtime"]["lightmaps"]["pages"][0]["url"]).unlink()
    problems = "\n".join(validate.validate_deck_dir(deck))
    assert "unknown room 'nowhere'" in problems
    assert "chunks, the manifest says" in problems
    assert "stray files in realtime/" in problems
    assert "missing realtime/lm_0.webp" in problems
    del manifest["realtime"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert any("no realtime block" in p for p in validate.validate_deck_dir(deck))


package = _load("verse_package_rt", TOOLS / "package.py")


def test_a_plate_cook_keeps_the_realtime_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(package, "TILE_PX", 256)
    raw = tmp_path / "raw"
    raw.mkdir()
    np.save(raw / "plate_0.npy", np.zeros((320, 640, 3), np.uint8))
    np.save(raw / "nav.npy", np.full((4, 4), 128, np.uint8))
    (raw / "occluders.glb").write_bytes(b"glb")
    (raw / "env.hdr").write_bytes(b"#?RADIANCE")
    cook = {
        "id": "deck", "name": "Deck", "floor": 1, "quality": "preview",
        "camera": {"plate_w_px": 640, "plate_h_px": 320},
        "plate_parts": [{"file": "plate_0.npy", "row0": 0, "row1": 320, "col0": 0, "col1": 640}],
        "nav": {"w": 4, "h": 4}, "occluders": {"triangles": 1}, "env": {},
        "probes": [], "rooms": [], "sockets": [], "stations": [], "stats": {},
    }  # fmt: skip
    (raw / "cook.json").write_text(json.dumps(cook), encoding="utf-8")
    out = tmp_path / "deck"
    (out / "realtime").mkdir(parents=True)
    (out / "realtime" / "scene.glb").write_bytes(b"scene")
    block = {"version": 1, "bytes": 5}
    (out / "manifest.json").write_text(json.dumps({"realtime": block}), encoding="utf-8")
    manifest = package.package_deck(raw, out)
    assert manifest["realtime"] == block
    assert (out / "realtime" / "scene.glb").read_bytes() == b"scene"
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8"))["realtime"] == block
