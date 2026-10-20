"""Validate cooked Verse content (no Blender needed; fast enough for CI).

    python scripts/verse/validate.py [--root dodaios/ui/web/frontend/public/verse]

Checks every deck manifest against art/verse/schema/deck.schema.json, file
existence and image sizes, naming, cross references, that every socket lies
inside the plate frame, and the content budgets.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import struct
import sys
from collections.abc import Iterable
from pathlib import Path

from jsonschema import Draft202012Validator
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "art" / "verse" / "schema" / "deck.schema.json"
PUBLIC_VERSE = REPO_ROOT / "dodaios" / "ui" / "web" / "frontend" / "public" / "verse"

MB = 1024 * 1024
BUDGET_TOTAL = 30 * MB
BUDGET_PLATE = 6 * MB
BUDGET_CHARACTER_GLB = 2 * MB
CHARACTER_PREFIXES = ("SK_", "SM_", "A_", "T_")


def _load_naming():
    path = REPO_ROOT / "art" / "verse" / "lib" / "naming.py"
    spec = importlib.util.spec_from_file_location("verse_naming", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


naming = _load_naming()


def schema_validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


# ---------------------------------------------------------------- file probes


def avif_size(path: Path) -> tuple[int, int]:
    """Width and height from the AVIF `ispe` box."""
    data = path.read_bytes()
    index = data.find(b"ispe")
    if data[4:8] != b"ftyp" or index < 0:
        raise ValueError(f"{path.name} is not an AVIF image")
    width, height = struct.unpack(">II", data[index + 8 : index + 16])
    return width, height


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path.name} is not a PNG image")
    return struct.unpack(">II", data[16:24])


def nav_walkable_cells(path: Path) -> int:
    """Number of non-zero (walkable) pixels in a nav PNG."""
    with Image.open(path) as image:
        return sum(count for value, count in enumerate(image.convert("L").histogram()) if value)


def glb_json(path: Path) -> dict:
    data = path.read_bytes()
    magic, version, _ = struct.unpack("<4sII", data[:12])
    if magic != b"glTF" or version != 2:
        raise ValueError(f"{path.name} is not a glTF 2.0 binary")
    length, kind = struct.unpack("<I4s", data[12:20])
    if kind != b"JSON":
        raise ValueError(f"{path.name}: first GLB chunk is not JSON")
    return json.loads(data[20 : 20 + length])


# ---------------------------------------------------------------- geometry


def world_to_plate_px(camera: dict, point: Iterable[float]) -> tuple[float, float]:
    """Plate pixel (L0, origin top-left) of a three.js world point. Mirrors manifest.ts."""
    offset = [p - c for p, c in zip(point, camera["centre"], strict=True)]
    u = sum(o * r for o, r in zip(offset, camera["right"], strict=True))
    v = sum(o * w for o, w in zip(offset, camera["up"], strict=True))
    scale = camera["px_per_m"]
    return camera["plate_w_px"] / 2 + u * scale, camera["plate_h_px"] / 2 - v * scale


# ---------------------------------------------------------------- deck checks


def validate_deck_dir(deck_dir: Path, validator: Draft202012Validator | None = None) -> list[str]:
    """Problems with one cooked deck directory (empty list = valid)."""
    validator = validator or schema_validator()
    where = deck_dir.name
    manifest_path = deck_dir / "manifest.json"
    if not manifest_path.is_file():
        return [f"{where}: manifest.json missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"{where}: manifest.json is not JSON ({error})"]
    problems = [
        f"{where}: schema: {'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
        for e in sorted(validator.iter_errors(manifest), key=lambda e: list(e.absolute_path))
    ]
    if problems:
        return problems
    if manifest["id"] != deck_dir.name:
        problems.append(f"{where}: manifest id {manifest['id']!r} differs from directory name")
    problems += _check_camera(where, manifest["camera"])
    problems += _check_plate(where, deck_dir, manifest)
    problems += _check_files(where, deck_dir, manifest)
    problems += _check_references(where, manifest)
    problems += _check_sockets_in_frame(where, manifest)
    return problems


def _check_camera(where: str, camera: dict) -> list[str]:
    problems = []
    pitch = math.radians(camera["pitch_deg"])
    expected_up = [0.0, math.cos(pitch), -math.sin(pitch)]
    if any(abs(a - b) > 1e-3 for a, b in zip(camera["up"], expected_up, strict=True)):
        problems.append(f"{where}: camera.up does not match pitch_deg")
    for axis, size_m, size_px in (
        ("w", camera["frame_w_m"], camera["plate_w_px"]),
        ("h", camera["frame_h_m"], camera["plate_h_px"]),
    ):
        if abs(size_m * camera["px_per_m"] - size_px) > 0.5:
            problems.append(f"{where}: frame_{axis}_m * px_per_m != plate_{axis}_px")
    return problems


def _check_plate(where: str, deck_dir: Path, manifest: dict) -> list[str]:
    problems = []
    plate, camera = manifest["plate"], manifest["camera"]
    tile = plate["tile_px"]
    width, height = camera["plate_w_px"], camera["plate_h_px"]
    if plate["cols"] != math.ceil(width / tile) or plate["rows"] != math.ceil(height / tile):
        problems.append(f"{where}: plate cols/rows do not cover {width}x{height} at {tile} px")
    expected_tiles = set()
    for row in range(plate["rows"]):
        for col in range(plate["cols"]):
            name = plate["tile_url"].format(col=col, row=row)
            expected_tiles.add(Path(name).name)
            path = deck_dir / name
            if not path.is_file():
                problems.append(f"{where}: missing tile {name}")
                continue
            expected = (min(tile, width - col * tile), min(tile, height - row * tile))
            if avif_size(path) != expected:
                problems.append(f"{where}: tile {name} is {avif_size(path)}, expected {expected}")
    l1 = deck_dir / plate["l1_url"]
    if not l1.is_file():
        problems.append(f"{where}: missing {plate['l1_url']}")
    elif avif_size(l1) != (plate["l1_w_px"], plate["l1_h_px"]):
        problems.append(f"{where}: L1 size differs from the manifest")
    tile_dir = (deck_dir / plate["tile_url"]).parent
    if tile_dir.is_dir():
        extra = {p.name for p in tile_dir.iterdir()} - expected_tiles - {Path(plate["l1_url"]).name}
        if extra:
            problems.append(f"{where}: stray files in the plate folder: {sorted(extra)}")
        plate_bytes = sum(p.stat().st_size for p in tile_dir.iterdir() if p.is_file())
        if plate_bytes > BUDGET_PLATE:
            problems.append(f"{where}: plate is {plate_bytes / MB:.2f} MB (budget 6 MB)")
    return problems


def _check_files(where: str, deck_dir: Path, manifest: dict) -> list[str]:
    problems = []
    nav = manifest["nav"]
    nav_path = deck_dir / nav["url"]
    if not nav_path.is_file():
        problems.append(f"{where}: missing {nav['url']}")
    elif png_size(nav_path) != (nav["w"], nav["h"]):
        problems.append(f"{where}: nav.png size differs from nav.w x nav.h")
    elif nav_walkable_cells(nav_path) != nav["walkable_cells"]:
        problems.append(f"{where}: nav.png walkable cells differ from nav.walkable_cells")
    occluders = deck_dir / manifest["occluders"]["url"]
    if not occluders.is_file():
        problems.append(f"{where}: missing {manifest['occluders']['url']}")
    else:
        gltf = glb_json(occluders)
        if gltf.get("materials"):
            problems.append(f"{where}: occluders.glb must not carry materials")
        names = [node.get("name", "") for node in gltf.get("nodes", [])]
        if not all(naming.is_occluder(name) for name in names):
            problems.append(f"{where}: occluder nodes must be named UCX_*: {names}")
    env = deck_dir / manifest["env"]["url"]
    if not env.is_file():
        problems.append(f"{where}: missing {manifest['env']['url']}")
    elif not env.read_bytes()[:10].startswith((b"#?RADIANCE", b"#?RGBE")):
        problems.append(f"{where}: env map is not a Radiance HDR file")
    return problems


def _check_references(where: str, manifest: dict) -> list[str]:
    problems = []
    rooms = [room["id"] for room in manifest["rooms"]]
    if len(set(rooms)) != len(rooms):
        problems.append(f"{where}: duplicate room ids")
    if sum(room["main"] for room in manifest["rooms"]) > 1:
        problems.append(f"{where}: more than one main room")
    keys = [(s["kind"], s["id"]) for s in manifest["sockets"]]
    if len(set(keys)) != len(keys):
        problems.append(f"{where}: duplicate socket kind/id pairs")
    stations = {station["id"] for station in manifest["stations"]}
    for socket in manifest["sockets"]:
        label = f"{where}: socket {socket['kind']}_{socket['id']}"
        if socket["room"] is not None and socket["room"] not in rooms:
            problems.append(f"{label} names unknown room {socket['room']!r}")
        if "station" in socket and socket["station"] not in stations:
            problems.append(f"{label} names unknown station {socket['station']!r}")
        if not naming.SOCKET_RE.match(f"SOCKET_{socket['kind']}_{socket['id']}"):
            problems.append(f"{label} does not form a valid SOCKET_ name")
    socket_keys = set(keys)
    for station in manifest["stations"]:
        for kind, ids in station["sockets"].items():
            missing = [i for i in ids if (kind, i) not in socket_keys]
            if missing:
                problems.append(f"{where}: station {station['id']} lists unknown {kind} {missing}")
    for probe in manifest["probes"]:
        if probe["room"] not in rooms:
            problems.append(f"{where}: probe for unknown room {probe['room']!r}")
    return problems


def _check_sockets_in_frame(where: str, manifest: dict) -> list[str]:
    camera = manifest["camera"]
    problems = []
    for socket in manifest["sockets"]:
        x, y = world_to_plate_px(camera, socket["position"])
        if not (0 <= x <= camera["plate_w_px"] and 0 <= y <= camera["plate_h_px"]):
            problems.append(f"{where}: socket {socket['kind']}_{socket['id']} is outside the plate")
    return problems


# ---------------------------------------------------------------- whole tree


def _check_characters(root: Path) -> list[str]:
    problems = []
    characters = root / "characters"
    if not characters.is_dir():
        return problems
    for path in sorted(characters.rglob("*.glb")):
        if not path.name.startswith(CHARACTER_PREFIXES):
            problems.append(f"characters: {path.name} lacks an SK_/SM_/A_/T_ prefix")
        if path.stat().st_size > BUDGET_CHARACTER_GLB:
            size = path.stat().st_size / MB
            problems.append(f"characters: {path.name} is {size:.2f} MB (budget 2 MB)")
        try:
            glb_json(path)
        except ValueError as error:
            problems.append(f"characters: {error}")
    return problems


def total_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def validate_all(root: Path = PUBLIC_VERSE) -> list[str]:
    """Problems with the whole cooked Verse tree under `root`."""
    if not root.is_dir():
        return []
    validator = schema_validator()
    problems = []
    decks = root / "decks"
    if decks.is_dir():
        for deck_dir in sorted(p for p in decks.iterdir() if p.is_dir()):
            if deck_dir.name.endswith(".staging"):
                problems.append(f"{deck_dir.name}: leftover staging directory")
                continue
            problems += validate_deck_dir(deck_dir, validator)
    problems += _check_characters(root)
    size = total_bytes(root)
    if size > BUDGET_TOTAL:
        problems.append(f"public/verse is {size / MB:.2f} MB (budget 30 MB)")
    return problems


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=PUBLIC_VERSE)
    options = parser.parse_args(argv)
    problems = validate_all(options.root)
    for problem in problems:
        print(f"FAIL {problem}")
    size = total_bytes(options.root) if options.root.is_dir() else 0
    print(f"[verse] {len(problems)} problem(s); public/verse = {size / MB:.2f} MB of 30 MB")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(_main())
