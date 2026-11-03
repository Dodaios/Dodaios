#!/usr/bin/env python3
"""Static check of the Verse art text, no engine and no LFS content (art-pipeline 10.3, 14).

Runs in the `unreal-static` lane and in `scripts/ci/run_gates.py`. It fails on:

* placement JSON (`unreal/Verse/Art/Placements/<deck>/<zone>.placement.json`)
  that breaks the `verse.placement/1` schema or its rules (`lib/placement.py`),
  or names an asset without an import record;
* import records (`Art/Import/**/<Name>.import.json`) that break `verse.import/1`,
  have no asset, break the naming rules of section 3, exceed a cap of 6.2,
  6.4 or 10.4, cite an unknown ledger row (section 11) or name the wrong owner
  for their content folder (section 9);
* MI recipes (`Art/Materials/MI_*.mi.json`) that break `verse.mi/1` or use a
  banned colour (section 8.3);
* a `.uasset` of an imported kind under `Content/Verse/` with no record (test
  placeholders under `Content/Verse/Test/` are built in the editor and exempt), any
  asset name outside section 3, engine sample content (section 11), and
  banned folder names under `unreal/` and `art/verse/` (section 10.1);
* a `space_vectors.json` that disagrees with `art/verse/lib/ue_space.py`.

    python scripts/unreal/check_art_text.py           # the repository
    python scripts/unreal/check_art_text.py --root D  # another checkout (tests)
"""

from __future__ import annotations

import argparse
import colorsys
import json
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# --------------------------------------------------------------------------
# Rules from the contract
# --------------------------------------------------------------------------

NAME_MAX = 64
OBJECT_PATH_MAX = 180

#: Section 3 prefixes of assets under /Game/Verse.
ASSET_PREFIXES = (
    "SM_", "GC_", "SK_", "SKEL_", "PHYS_", "IKRig_", "RTG_", "A_", "AM_", "BS_", "ABP_",
    "M_", "MF_", "MI_", "T_", "SW_", "MS_", "NS_", "DA_", "LV_", "DL_", "BP_",
)  # fmt: skip
TEXTURE_SUFFIXES = ("_BC", "_N", "_ORM", "_E", "_M")
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9][A-Za-z0-9_]*$")

#: Import record kind -> name rule.
KIND_NAMES = {
    "static_mesh": re.compile(r"^SM_[A-Za-z0-9_]+$"),
    "proxy_mesh": re.compile(
        r"^SM_[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*_Proxy_(Intact|Holed|Breached|Destroyed)$"
    ),
    "skeletal_mesh": re.compile(r"^SK_[A-Za-z0-9_]+$"),
    "skeleton": re.compile(r"^SKEL_[A-Za-z0-9_]+$"),
    "physics_asset": re.compile(r"^PHYS_[A-Za-z0-9_]+$"),
    "animation": re.compile(r"^A_[A-Za-z0-9_]+$"),
    "texture": re.compile(rf"^T_[A-Za-z0-9_]+(?:{'|'.join(TEXTURE_SUFFIXES)})$"),
    "geometry_collection": re.compile(r"^GC_[A-Za-z0-9_]+$"),
}
#: Prefixes whose assets come from an import record (a .uasset needs one).
IMPORTED_PREFIXES = ("SM_", "SK_", "SKEL_", "PHYS_", "A_", "T_", "GC_")

#: Folders whose assets are built inside the editor by test code (the G0 test human,
#: per-package placeholders), not imported from an export: no import record needed.
EDITOR_BUILT_FOLDERS = ("/Game/Verse/Test/",)

#: Triangle caps of section 6.2, first matching rule wins: (path prefix, name test, cap).
TRIANGLE_CAPS: tuple[tuple[str, str, int], ...] = (
    ("/Game/Verse/Kit/Architecture/", "", 500_000),
    ("/Game/Verse/Weapons/", "SK_Weapon_", 60_000),
    ("/Game/Verse/Weapons/", "SM_Weapon_", 150_000),
    ("/Game/Verse/Characters/", "SK_", 80_000),
    ("", "GC_", 300_000),
    ("", "_Proxy_", 2_000),
    ("", "SM_", 200_000),
)
TEXTURE_MAX = 2048
TEXTURE_MAX_FIRST_PERSON = 4096
MAX_BONES = {"character": 200, "weapon": 24}

#: Content folder ownership of section 9, longest prefix first.
FOLDER_OWNERS: tuple[tuple[str, str], ...] = (
    ("/Game/Verse/Materials/Master/", "WP14"),
    ("/Game/Verse/Materials/Instances/Weapons/", "WP14"),
    ("/Game/Verse/Materials/Instances/Characters/", "WP13"),
    ("/Game/Verse/Materials/Instances/Screens/", "WP16"),
    ("/Game/Verse/Materials/Instances/", "WP12"),
    ("/Game/Verse/Kit/", "WP12"),
    ("/Game/Verse/Characters/", "WP13"),
    ("/Game/Verse/Animations/", "WP13"),
    ("/Game/Verse/Weapons/", "WP14"),
    ("/Game/Verse/VFX/Weapons/", "WP14"),
    ("/Game/Verse/PostProcess/", "WP14"),
    ("/Game/Verse/Combat/Abilities/", "WP02"),
    ("/Game/Verse/Combat/Finisher/", "WP04"),
    ("/Game/Verse/Movement/", "WP01"),
    ("/Game/Verse/Destruction/_Holes/", "WP03"),
    ("/Game/Verse/Destruction/", "WP06"),
    ("/Game/Verse/Gore/", "WP05"),
    ("/Game/Verse/Bot/Tiers/", "WP09"),
    ("/Game/Verse/Bot/", "WP08"),
    ("/Game/Verse/Crew/", "WP15"),
    ("/Game/Verse/Screens/", "WP16"),
    ("/Game/Verse/UI/Stations/", "WP16"),
    ("/Game/Verse/UI/ServiceRecord/", "WP21"),
    ("/Game/Verse/UI/", "WP18"),
    ("/Game/Verse/Audio/", "WP19"),
)
_TEST_FOLDER = re.compile(r"^/Game/Verse/Test/(WP\d{2})/")

#: Folder names that may not appear under unreal/ or art/verse/ (section 10.1).
BANNED_FOLDERS = {
    "build", "models", "env", "logs", "dist", "secrets", "credentials", "traces",
    "blobs", "video", "videos", "film", "films", "renders", "evidence", "recordings",
    "screenshots",
}  # fmt: skip
ALLOWED_FOLDERS = {"unreal/Verse/Build"}

#: Engine sample content (section 11, "Scan").
ENGINE_CONTENT = re.compile(
    r"/Game/StarterContent|/Game/Characters/Mannequins|SKM_Manny|SKM_Quinn|SK_Mannequin",
    re.IGNORECASE,
)

#: Banned hues for MI vector parameters (section 8.3): (label, lo, hi, min sat, emissive only).
HUE_BANS = (
    ("cyan", 160.0, 210.0, 0.35, False),
    ("violet/purple/magenta", 250.0, 330.0, 0.2, False),
    ("saturated green light", 90.0, 160.0, 0.5, True),
    ("info blue light", 210.0, 250.0, 0.4, True),
)
GOLD_SRGB = (0xC8, 0xA2, 0x4A)
GOLD_DELTA_E = 6.0


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _art_lib(root: Path):
    art = str(root / "art" / "verse")
    if art not in sys.path:
        sys.path.insert(0, art)
    from lib import placement, ue_space

    return placement, ue_space


def _validator(schema_path: Path):
    import jsonschema

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _schema_errors(validator, doc) -> list[str]:
    out = []
    for error in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in error.absolute_path) or "<root>"
        out.append(f"{where}: {error.message}")
    return out


def _load_json(path: Path) -> tuple[object | None, list[str]]:
    raw = path.read_bytes()
    errors = ["line endings must be LF"] if b"\r\n" in raw else []
    try:
        return json.loads(raw.decode("utf-8")), errors
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return None, [*errors, f"not valid JSON: {error}"]


def asset_name(object_path: str) -> str:
    return object_path.rsplit("/", 1)[-1].split(".", 1)[0]


def folder_owner(object_path: str) -> str | None:
    test = _TEST_FOLDER.match(object_path)
    if test:
        return test.group(1)
    deck_zone = re.match(r"^/Game/Verse/Decks/[^/]+/(?!DataLayers/)([^/]+)/", object_path)
    if deck_zone:
        return None  # zone folders: owner from work-packages.md section 3, checked by owner field
    for prefix, owner in FOLDER_OWNERS:
        if object_path.startswith(prefix):
            return owner
    return None


def name_errors(name: str) -> list[str]:
    errors = []
    if len(name) > NAME_MAX:
        errors.append(f"{name}: longer than {NAME_MAX} characters")
    if not name.isascii() or not NAME_RE.match(name):
        errors.append(f"{name}: not ASCII PascalCase segments joined by _ (art-pipeline 3)")
    if not name.startswith(ASSET_PREFIXES):
        errors.append(f"{name}: prefix not in art-pipeline section 3")
    if name.startswith("T_") and not name.endswith(TEXTURE_SUFFIXES):
        errors.append(f"{name}: texture needs a suffix {'/'.join(TEXTURE_SUFFIXES)}")
    return errors


def triangle_cap(record: dict) -> int | None:
    path, name = record["asset_path"], record["name"]
    for prefix, test, cap in TRIANGLE_CAPS:
        if path.startswith(prefix) and test in name:
            return cap
    return None


def ledger_hashes(root: Path) -> set[str]:
    path = root / "art" / "verse" / "LICENSES.md"
    if not path.is_file():
        return set()
    return set(re.findall(r"\b[0-9a-f]{64}\b", path.read_text(encoding="utf-8")))


def _srgb(linear: float) -> float:
    linear = max(0.0, linear)
    return 12.92 * linear if linear <= 0.0031308 else 1.055 * linear ** (1 / 2.4) - 0.055


def _lab(rgb: Iterable[float]) -> tuple[float, float, float]:
    """sRGB (0..1) -> CIE Lab (D65)."""

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def colour_bans(name: str, rgba_linear: list[float], *, gold_allowed: bool) -> list[str]:
    """Section 8.3 hue tests on one MI vector parameter (linear RGBA)."""
    r, g, b = (min(1.0, _srgb(c)) for c in rgba_linear[:3])
    hue, sat, _value = colorsys.rgb_to_hsv(r, g, b)
    hue *= 360.0
    emissive = "emissive" in name.lower() or "light" in name.lower()
    hits = []
    for label, lo, hi, min_sat, emissive_only in HUE_BANS:
        if emissive_only and not emissive:
            continue
        if lo <= hue <= hi and sat > min_sat:
            hits.append(f"{name}: banned colour ({label}, hue {hue:.0f}, sat {sat:.2f})")
    if not gold_allowed:
        gold = _lab(c / 255 for c in GOLD_SRGB)
        lab = _lab((r, g, b))
        if sum((p - q) ** 2 for p, q in zip(lab, gold, strict=True)) ** 0.5 <= GOLD_DELTA_E:
            hits.append(f"{name}: brand gold outside art/verse/gold_allowlist.txt")
    return hits


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------


class Checker:
    def __init__(self, root: Path):
        self.root = root
        self.project = root / "unreal" / "Verse"
        self.art = self.project / "Art"
        self.content = self.project / "Content" / "Verse"
        self.schemas = root / "art" / "verse" / "schema"
        self.errors: list[str] = []

    def fail(self, path: Path | str, message: str) -> None:
        where = path.relative_to(self.root).as_posix() if isinstance(path, Path) else path
        self.errors.append(f"{where}: {message}")

    # -- records ----------------------------------------------------------

    def records(self) -> dict[str, dict]:
        validator = _validator(self.schemas / "import.schema.json")
        ledger = ledger_hashes(self.root)
        out: dict[str, dict] = {}
        folder = self.art / "Import"
        for path in sorted(folder.rglob("*.json")) if folder.is_dir() else []:
            if not path.name.endswith(".import.json"):
                self.fail(path, "import records are named <Asset>.import.json")
                continue
            doc, errors = _load_json(path)
            errors += _schema_errors(validator, doc) if doc is not None else []
            if errors:
                for error in errors:
                    self.fail(path, error)
                continue
            self._record_rules(path, doc, ledger)
            if doc["asset_path"] in out:
                self.fail(path, f"second record for {doc['asset_path']}")
            out[doc["asset_path"]] = {**doc, "_file": path}
        return out

    def _record_rules(self, path: Path, doc: dict, ledger: set[str]) -> None:
        name, object_path = doc["name"], doc["asset_path"]
        if path.name != f"{name}.import.json":
            self.fail(path, f"file must be named {name}.import.json")
        if asset_name(object_path) != name or not object_path.endswith(f".{name}"):
            self.fail(path, f"asset_path {object_path} is not the asset {name}")
        if len(object_path) >= OBJECT_PATH_MAX:
            self.fail(path, f"object path longer than {OBJECT_PATH_MAX - 1} characters")
        for error in name_errors(name):
            self.fail(path, error)
        if not KIND_NAMES[doc["kind"]].match(name):
            self.fail(path, f"kind {doc['kind']} does not fit the name {name}")
        expected_owner = folder_owner(object_path)
        if expected_owner and doc["owner"] != expected_owner:
            self.fail(path, f"owner {doc['owner']}, the content folder belongs to {expected_owner}")
        mesh = doc.get("mesh")
        cap = triangle_cap(doc)
        override = doc.get("budget_override") or {}
        if mesh and cap and mesh["triangles"] > cap and override.get("field") != "triangles":
            self.fail(path, f"{mesh['triangles']} triangles, cap {cap} (art-pipeline 6.2)")
        if mesh and "bones" in mesh:
            limit = MAX_BONES["weapon" if "/Weapons/" in object_path else "character"]
            if len(mesh["bones"]) > limit and override.get("field") != "bones":
                self.fail(path, f"{len(mesh['bones'])} bones, cap {limit} (art-pipeline 10.4)")
        if doc["kind"] in ("static_mesh", "skeletal_mesh", "proxy_mesh") and not mesh:
            self.fail(path, "mesh records need a mesh block")
        texture = doc.get("texture")
        if doc["kind"] == "texture" and not texture:
            self.fail(path, "texture records need a texture block")
        if texture:
            limit = TEXTURE_MAX_FIRST_PERSON if texture["group"] == "Weapon" else TEXTURE_MAX
            if texture["max_size"] > limit and override.get("field") != "max_size":
                self.fail(path, f"texture max_size {texture['max_size']} > {limit}")
            if name.endswith("_N") and not texture["flip_green"]:
                self.fail(path, "normal maps flip green on import (art-pipeline 6.4)")
            if name.endswith(("_N", "_ORM", "_M")) and texture["srgb"]:
                self.fail(path, "_N, _ORM and _M textures are linear (srgb false)")
            if name.endswith(("_BC", "_E")) and not texture["srgb"]:
                self.fail(path, "_BC and _E textures are sRGB")
        license_ = doc["license"]
        if license_["kind"] == "ledger":
            cited = license_.get("ledger_sha256") or []
            if not cited:
                self.fail(path, "licence kind ledger needs ledger_sha256 rows")
            for digest in cited:
                if digest not in ledger:
                    self.fail(path, f"ledger row {digest[:12]}... not in art/verse/LICENSES.md")
        elif license_.get("ledger_sha256"):
            self.fail(path, "own work cites no ledger rows")
        if ENGINE_CONTENT.search(json.dumps(doc)):
            self.fail(path, "engine sample content is forbidden (art-pipeline 11)")

    # -- placements -------------------------------------------------------

    def placements(self, records: dict[str, dict]) -> None:
        placement, _ = _art_lib(self.root)
        folder = self.art / "Placements"
        for path in sorted(folder.rglob("*")) if folder.is_dir() else []:
            if path.is_dir():
                continue
            if not path.name.endswith(".placement.json"):
                self.fail(path, "only <zone>.placement.json files live under Placements/")
                continue
            for error in placement.validate_file(path, known_assets=set(records)):
                self.fail(path, error)
            text = path.read_text(encoding="utf-8", errors="replace")
            if ENGINE_CONTENT.search(text):
                self.fail(path, "engine sample content is forbidden (art-pipeline 11)")

    # -- material instances ---------------------------------------------

    def materials(self) -> None:
        validator = _validator(self.schemas / "mi.schema.json")
        allow = self.root / "art" / "verse" / "gold_allowlist.txt"
        gold_ok = set(allow.read_text(encoding="utf-8").split()) if allow.is_file() else set()
        folder = self.art / "Materials"
        for path in sorted(folder.rglob("*")) if folder.is_dir() else []:
            if path.is_dir():
                continue
            if not path.name.endswith(".mi.json"):
                self.fail(path, "only MI_<Name>.mi.json recipes live under Art/Materials/")
                continue
            doc, errors = _load_json(path)
            errors += _schema_errors(validator, doc) if doc is not None else []
            if errors:
                for error in errors:
                    self.fail(path, error)
                continue
            if path.name != f"{doc['name']}.mi.json":
                self.fail(path, f"file must be named {doc['name']}.mi.json")
            for param, value in sorted(doc["vectors"].items()):
                for hit in colour_bans(param, value, gold_allowed=doc["name"] in gold_ok):
                    self.fail(path, hit)

    # -- content tree ---------------------------------------------------

    def content_tree(self, records: dict[str, dict]) -> None:
        on_disk = set()
        if self.content.is_dir():
            for path in sorted(self.content.rglob("*")):
                if path.suffix not in (".uasset", ".umap"):
                    continue
                rel = path.relative_to(self.content).with_suffix("")
                name = rel.name
                object_path = f"/Game/Verse/{rel.as_posix()}.{name}"
                on_disk.add(object_path)
                for error in name_errors(name):
                    self.fail(path, error)
                needs_record = name.startswith(IMPORTED_PREFIXES) and not object_path.startswith(
                    EDITOR_BUILT_FOLDERS
                )
                if path.suffix == ".uasset" and needs_record:
                    if object_path not in records:
                        self.fail(path, "no import record in unreal/Verse/Art/Import/")
                if ENGINE_CONTENT.search(object_path):
                    self.fail(path, "engine sample content is forbidden (art-pipeline 11)")
        for object_path, record in sorted(records.items()):
            if object_path not in on_disk:
                self.fail(
                    record["_file"],
                    f"record has no asset (import it: python scripts/unreal/import_art.py"
                    f" assets --only {record['name']})",
                )

    def folders(self) -> None:
        for rel in _tracked(self.root, ("unreal", "art/verse")):
            parts = rel.split("/")[:-1]
            for depth, part in enumerate(parts):
                prefix = "/".join(parts[: depth + 1])
                if part.lower() in BANNED_FOLDERS and prefix not in ALLOWED_FOLDERS:
                    self.fail(rel, f"folder name {part!r} is banned (art-pipeline 10.1)")
                    break
            if ENGINE_CONTENT.search(rel):
                self.fail(rel, "engine sample content is forbidden (art-pipeline 11)")

    def space_vectors(self) -> None:
        path = self.art / "space_vectors.json"
        if not path.is_file():
            self.fail(path.relative_to(self.root).as_posix(), "missing")
            return
        _, ue_space = _art_lib(self.root)
        doc, errors = _load_json(path)
        for error in errors:
            self.fail(path, error)
        if doc is None:
            return
        for case in doc.get("blender_to_unreal", []):
            b, u = case["blender"], case["unreal"]
            got = ue_space.location_to_ue(b["location_m"])
            if any(abs(p - q) > 1e-6 for p, q in zip(got, u["location_cm"], strict=True)):
                self.fail(path, f"{case['name']}: location {got} != {u['location_cm']}")
            quat = ue_space.quat_to_ue(b["quat_wxyz"])
            if any(abs(p - q) > 1e-9 for p, q in zip(quat, u["quat_xyzw"], strict=True)):
                self.fail(path, f"{case['name']}: rotation {quat} != {u['quat_xyzw']}")
        for case in doc.get("yaw", []):
            if abs(ue_space.yaw_to_ue(case["blender_rot_z_deg"]) - case["unreal_yaw_deg"]) > 1e-9:
                self.fail(path, f"yaw {case['blender_rot_z_deg']} disagrees")
        for case in doc.get("three_to_unreal", []):
            got = ue_space.three_to_ue(case["three_m"])
            if any(abs(p - q) > 1e-6 for p, q in zip(got, case["unreal_cm"], strict=True)):
                self.fail(path, f"three {case['three_m']} -> {got} != {case['unreal_cm']}")

    def run(self) -> list[str]:
        records = self.records()
        self.placements(records)
        self.materials()
        self.content_tree(records)
        self.folders()
        self.space_vectors()
        return self.errors


def _tracked(root: Path, scopes: tuple[str, ...]) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard",
             "--", *scopes],
            capture_output=True, text=True, check=True,
        ).stdout  # fmt: skip
        return [line for line in out.splitlines() if line]
    except (OSError, subprocess.CalledProcessError):
        files = []
        for scope in scopes:
            base = root / scope
            if base.is_dir():
                files += [p.relative_to(root).as_posix() for p in base.rglob("*") if p.is_file()]
        return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    options = parser.parse_args(argv)
    errors = Checker(options.root.resolve()).run()
    for error in errors:
        print(f"check_art_text: {error}", file=sys.stderr)
    if errors:
        print(f"check_art_text: {len(errors)} problem(s)", file=sys.stderr)
        return 1
    print("check_art_text: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
