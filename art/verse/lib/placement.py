"""`verse.placement/1` documents: ids, canonical form and validation.

Pure Python (no bpy, no unreal), shared by the Blender export, the static
check `scripts/unreal/check_art_text.py` and pytest. The format is defined in
docs/verse/unreal/contracts/art-pipeline.md section 4; the JSON Schema is
`art/verse/schema/placement.schema.json`. This module adds the rules a schema
cannot express: unique ids, origins inside the zone box, unit quaternions,
room references, level and data-layer names that match the deck, and the
destructible and mobility rules of sections 4.2 and 5.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA_ID = "verse.placement/1"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "placement.schema.json"

ID_SNAP_CM = 15.0
ID_SNAP_DEG = 1.0
LOCATION_DIGITS = 3  # 0.001 cm
QUAT_DIGITS = 7
SCALE_DIGITS = 6
MAX_FILE_BYTES = 2 * 1024 * 1024  # art-pipeline 10.4
UNIT_QUAT_TOLERANCE = 1e-4

#: Destructible proxy states every destructible must provide (art-pipeline 5).
REQUIRED_PROXY_STATES = ("Intact", "Holed", "Breached", "Destroyed")
#: Data layers allowed outside `DL_<Deck>_Base` (VerseDecks day/arena switch).
HANGAR_LAYERS = ("DL_Hangar_Day", "DL_Hangar_Arena")

_ID_SAFE = re.compile(r"[^a-z0-9_]+")


def deck_title(deck: str) -> str:
    """`engineering` -> `Engineering`; `ops_deck` -> `OpsDeck` (folder and level case)."""
    return "".join(part.capitalize() for part in deck.split("_"))


def level_path(deck: str) -> str:
    title = deck_title(deck)
    return f"/Game/Verse/Decks/{title}/LV_{title}"


def base_layer(deck: str) -> str:
    return f"DL_{deck_title(deck)}_Base"


def asset_name_of(object_path: str) -> str:
    """`/Game/Verse/Kit/SM_Wall_480.SM_Wall_480` -> `SM_Wall_480`."""
    return object_path.rsplit("/", 1)[-1].split(".", 1)[0]


def sanitize_id(raw: str) -> str:
    """Builder ids become placement ids: lower case, `[a-z0-9_]` only."""
    cleaned = _ID_SAFE.sub("_", raw.lower()).strip("_")
    if not cleaned:
        raise ValueError(f"id {raw!r} has no usable characters")
    return cleaned


def _id_number(value: float) -> str:
    n = int(round(value))
    return f"m{-n}" if n < 0 else str(n)


def auto_id(piece: str, location_cm: Sequence[float], yaw_deg: float) -> str:
    """`<piece lower>_<x>_<y>_<z>_<yaw>`, snapped to 15 cm and 1 degree.

    Negative numbers are written `m<n>` because ids allow `[a-z0-9_]` only.
    """
    snapped = [ID_SNAP_CM * round(float(v) / ID_SNAP_CM) for v in location_cm]
    yaw = (ID_SNAP_DEG * round(float(yaw_deg) / ID_SNAP_DEG)) % 360.0
    parts = [sanitize_id(piece), *(_id_number(v) for v in snapped), _id_number(yaw) or "0"]
    return "_".join(parts)


def unique_ids(ids: Iterable[str]) -> list[str]:
    """Duplicates get `_2`, `_3`, ... in order of appearance."""
    seen: dict[str, int] = {}
    taken = set()
    out = []
    for raw in ids:
        count = seen.get(raw, 0) + 1
        seen[raw] = count
        candidate = raw if count == 1 else f"{raw}_{count}"
        while candidate in taken:
            count += 1
            seen[raw] = count
            candidate = f"{raw}_{count}"
        taken.add(candidate)
        out.append(candidate)
    return out


def yaw_from_quat_xyzw(quat: Sequence[float]) -> float:
    """Yaw in degrees of an [x, y, z, w] quaternion (rotation about Z part)."""
    x, y, z, w = (float(v) for v in quat)
    return math.degrees(math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z)))


def _round_list(values: Sequence[float], digits: int) -> list[float]:
    out = []
    for value in values:
        rounded = round(float(value), digits)
        out.append(0.0 if rounded == 0 else rounded)
    return out


def canonical(doc: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy with rounded numbers and arrays in stable order (by id)."""
    out = json.loads(json.dumps(doc))
    for item in out.get("placements", []):
        item["location"] = _round_list(item["location"], LOCATION_DIGITS)
        item["rotation"] = _round_list(item["rotation"], QUAT_DIGITS)
        item["scale"] = _round_list(item["scale"], SCALE_DIGITS)
        if "tags" in item:
            item["tags"] = sorted(item["tags"])
    for item in out.get("sockets", []):
        item["location"] = _round_list(item["location"], LOCATION_DIGITS)
        item["rotation"] = _round_list(item["rotation"], QUAT_DIGITS)
    for room in out.get("rooms", []):
        room["polygon_cm"] = [_round_list(p, LOCATION_DIGITS) for p in room["polygon_cm"]]
    bounds = out.get("bounds_cm")
    if isinstance(bounds, dict):
        for key in ("min", "max"):
            if key in bounds:
                bounds[key] = _round_list(bounds[key], LOCATION_DIGITS)
    for key in ("placements", "sockets", "rooms"):
        if isinstance(out.get(key), list):
            out[key].sort(key=lambda entry: str(entry.get("id", "")))
    return out


def dumps(doc: Mapping[str, Any]) -> str:
    """Canonical text: sorted keys, 2-space indent, LF, trailing newline."""
    return json.dumps(canonical(doc), indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def write(path: Path, doc: Mapping[str, Any]) -> bool:
    """Write `doc` canonically; return True when the file changed."""
    text = dumps(doc)
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return True


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def _schema_validator():
    import jsonschema

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _path_of(error) -> str:
    parts = [str(p) for p in error.absolute_path]
    return "/".join(parts) or "<root>"


def schema_errors(doc: Any) -> list[str]:
    validator = _schema_validator()
    return [
        f"{_path_of(e)}: {e.message}"
        for e in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    ]


def _inside(point: Sequence[float], lo: Sequence[float], hi: Sequence[float]) -> bool:
    return all(a - 1e-6 <= p <= b + 1e-6 for p, a, b in zip(point, lo, hi, strict=True))


def _dupes(values: Sequence[str]) -> list[str]:
    return sorted({v for v in values if values.count(v) > 1})


def _quat_norm_error(quat: Sequence[float]) -> float:
    return abs(math.sqrt(sum(float(v) * float(v) for v in quat)) - 1.0)


def semantic_errors(
    doc: Mapping[str, Any],
    *,
    path: Path | None = None,
    known_assets: set[str] | None = None,
) -> list[str]:
    """Rules beyond the schema. Assumes `schema_errors(doc)` is empty."""
    errors: list[str] = []
    deck, zone = doc["deck"], doc["zone"]
    if path is not None:
        if path.name != f"{zone}.placement.json":
            errors.append(f"file name must be {zone}.placement.json")
        if path.parent.name != deck:
            errors.append(f"file must live in Placements/{deck}/")
        size = path.stat().st_size if path.is_file() else 0
        if size > MAX_FILE_BYTES:
            errors.append(f"file is {size} bytes, budget {MAX_FILE_BYTES} (art-pipeline 10.4)")
    if doc["level"] != level_path(deck):
        errors.append(f"level must be {level_path(deck)}")
    lo, hi = doc["bounds_cm"]["min"], doc["bounds_cm"]["max"]
    if not all(a < b for a, b in zip(lo, hi, strict=True)):
        errors.append("bounds_cm: min must be below max on every axis")

    rooms = [room["id"] for room in doc["rooms"]]
    errors += [f"rooms: duplicate id {rid!r}" for rid in _dupes(rooms)]
    room_set = set(rooms)
    allowed_layers = {base_layer(deck)}
    if deck == "hangar":
        allowed_layers.update(HANGAR_LAYERS)

    ids = [p["id"] for p in doc["placements"]]
    errors += [f"placements: duplicate id {i!r}" for i in _dupes(ids)]
    for item in doc["placements"]:
        where = f"placements/{item['id']}"
        if asset_name_of(item["asset"]) != item["piece"]:
            errors.append(f"{where}: asset {item['asset']} is not the piece {item['piece']}")
        object_name = item["asset"].rsplit(".", 1)[-1]
        if object_name != item["piece"]:
            errors.append(f"{where}: object path must end in .{item['piece']}")
        if known_assets is not None and item["asset"] not in known_assets:
            errors.append(f"{where}: unknown asset {item['asset']} (no import record)")
        if not _inside(item["location"], lo, hi):
            errors.append(f"{where}: origin {item['location']} outside bounds_cm")
        if _quat_norm_error(item["rotation"]) > UNIT_QUAT_TOLERANCE:
            errors.append(f"{where}: rotation is not a unit quaternion")
        if item["room"] is not None and item["room"] not in room_set:
            errors.append(f"{where}: room {item['room']!r} is not in rooms[]")
        if item["data_layer"] not in allowed_layers:
            layers = sorted(allowed_layers)
            errors.append(f"{where}: data_layer {item['data_layer']} not in {layers}")
        destructible = item["destructible"]
        if destructible is not None:
            if item["mobility"] != "movable":
                errors.append(f"{where}: a destructible must be movable")
            if item["collision"] != "Verse_Destructible":
                errors.append(f"{where}: a destructible uses collision Verse_Destructible")
            missing = [s for s in REQUIRED_PROXY_STATES if s not in destructible["proxies"]]
            if missing:
                errors.append(f"{where}: destructible proxies missing {missing}")
            states = set(destructible["states"])
            for state in REQUIRED_PROXY_STATES:
                if state not in states:
                    errors.append(f"{where}: destructible states missing {state}")
        elif item["collision"] == "Verse_Destructible":
            errors.append(f"{where}: collision Verse_Destructible needs a destructible block")
        if item["piece"].startswith("GC_") and destructible is None:
            errors.append(f"{where}: a geometry collection placement must be destructible")

    socket_ids = [s["id"] for s in doc["sockets"]]
    errors += [f"sockets: duplicate id {i!r}" for i in _dupes(socket_ids)]
    for socket in doc["sockets"]:
        where = f"sockets/{socket['id']}"
        if not _inside(socket["location"], lo, hi):
            errors.append(f"{where}: location outside bounds_cm")
        if _quat_norm_error(socket["rotation"]) > UNIT_QUAT_TOLERANCE:
            errors.append(f"{where}: rotation is not a unit quaternion")
        if socket["room"] is not None and socket["room"] not in room_set:
            errors.append(f"{where}: room {socket['room']!r} is not in rooms[]")
    return errors


def validate(
    doc: Any, *, path: Path | None = None, known_assets: set[str] | None = None
) -> list[str]:
    """All errors of one placement document (schema first, then semantics)."""
    errors = schema_errors(doc)
    if errors:
        return errors
    return semantic_errors(doc, path=path, known_assets=known_assets)


def validate_file(path: Path, *, known_assets: set[str] | None = None) -> list[str]:
    raw = path.read_bytes()
    errors: list[str] = []
    if b"\r\n" in raw:
        errors.append("line endings must be LF")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return [f"not valid JSON: {error}"]
    errors += validate(doc, path=path, known_assets=known_assets)
    if not errors and raw.decode("utf-8") != dumps(doc):
        errors.append(
            "not in canonical form (sorted keys, 2-space indent, arrays by id);"
            " rewrite it with lib.placement.write"
        )
    return errors
