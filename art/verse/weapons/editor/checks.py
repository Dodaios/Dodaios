"""A14.2 and the palette bans on weapon MIs (WP14.1, art-pipeline 7 and 8.3).

`weapon_colour_errors` is pure: the base colours a weapon MI can show after
the clamps of its master must stay black (linear luminance at most 0.06, no
coloured trim), and a weapon MI may glow only as the sight reticle
(art-pipeline 7). Weapon VFX MIs (`MI_Weapon_Vfx_*`) are exempt from the
emissive rule; they are bolts, flashes and sparks, not weapon surfaces.
`check_materials` runs the checks on the imported MIs inside the editor.
"""

from __future__ import annotations

import sys

from verse_pipeline import REPO_ROOT

#: Linear luminance cap of A14.2 for the base colour of every weapon material.
WEAPON_LUMINANCE_CAP = 0.06
WEAPON_MI_FOLDER = "/Game/Verse/Materials/Instances/Weapons/"
#: The weapon master clamps its tints in the shader (masters.WEAPON_*_CAP).
WEAPON_CAPS = {"BaseTint": (0.0103, 0.0103, 0.0109), "EdgeTint": (0.0437, 0.0497, 0.0630)}
EMISSIVE_MASTERS = ("M_Verse_Emissive", "M_Verse_Screen")
#: The only weapon surface allowed to glow (art-pipeline 7).
RETICLE_MI = "MI_Weapon_Reticle"
VFX_PREFIX = "MI_Weapon_Vfx_"


def luminance(rgb) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def _master(parent: str) -> str:
    return parent.rsplit(".", 1)[-1]


def weapon_base_colours(parent: str, vectors: dict) -> dict[str, tuple]:
    """The base colours a weapon MI can show, after the clamps of its master. Pure.

    Emissive masters have a black base; glass shows `BaseTint`; the weapon
    master shows `BaseTint` and `EdgeTint`, each clamped per channel.
    """
    name = _master(parent)
    if name in EMISSIVE_MASTERS:
        return {}
    keys = ("BaseTint", "EdgeTint") if name == "M_Verse_Weapon" else ("BaseTint",)
    out = {}
    for key in keys:
        value = tuple(vectors.get(key, (0.0, 0.0, 0.0, 1.0))[:3])
        if name == "M_Verse_Weapon":
            value = tuple(min(v, c) for v, c in zip(value, WEAPON_CAPS[key], strict=True))
        out[key] = value
    return out


def weapon_colour_errors(name: str, parent: str, vectors: dict) -> list[str]:
    """A14.2 on one weapon MI: black base, no coloured trim, glow only on the reticle. Pure."""
    errors = []
    if _master(parent) in EMISSIVE_MASTERS and name != RETICLE_MI and not name.startswith(VFX_PREFIX):
        errors.append(
            f"{name}: emissive weapon trim, only {RETICLE_MI} may glow (art-pipeline 7, A14.2)"
        )
    for key, rgb in weapon_base_colours(parent, vectors).items():
        lum = luminance(rgb)
        if lum > WEAPON_LUMINANCE_CAP:
            errors.append(f"{name}: {key} luminance {lum:.4f} > {WEAPON_LUMINANCE_CAP}")
        if max(rgb) > 0 and (max(rgb) - min(rgb)) / max(rgb) > 0.35:
            errors.append(f"{name}: {key} is coloured, weapons are black (A14.2)")
    return errors


#: Masters with a translucent blend mode; Nanite does not render them (art-pipeline 6.2).
TRANSLUCENT_MASTERS = frozenset({"M_Verse_Glass"})


def recipe_parents() -> dict[str, str]:
    """MI object path -> master name, from every MI recipe."""
    from verse_pipeline import materials

    return {
        materials.instance_path(r): r["parent"].rsplit(".", 1)[-1]
        for r in materials.load_recipes()
    }


def translucent_nanite_errors(record: dict, parents: dict[str, str]) -> list[str]:
    """A mesh record with Nanite on and a translucent slot (glass rule, art-pipeline 6.2). Pure."""
    if not record.get("nanite", {}).get("enabled"):
        return []
    bad = [
        s["slot"]
        for s in record.get("mesh", {}).get("material_slots", [])
        if parents.get(s.get("mi", "")) in TRANSLUCENT_MASTERS
    ]
    if not bad:
        return []
    return [f"{record['name']}: Nanite on with translucent slots {bad}; glass is Nanite off"]


def _colour_bans():
    path = str(REPO_ROOT / "scripts" / "unreal")
    if path not in sys.path:
        sys.path.insert(0, path)
    import check_art_text

    return check_art_text.colour_bans


def _mi_vectors(unreal, mi) -> dict:
    mel = unreal.MaterialEditingLibrary
    out = {}
    for name in mel.get_vector_parameter_names(mi):
        c = mel.get_material_instance_vector_parameter_value(mi, name)
        out[str(name)] = (c.r, c.g, c.b, c.a)
    return out


def check_materials(only: list[str]) -> tuple[list[str], list[str]]:
    """Palette bans (art-pipeline 8.3) on every MI from a recipe, A14.2 on weapon MIs."""
    import unreal

    from verse_pipeline import materials

    errors, checked = [], []
    bans = _colour_bans()
    allow = REPO_ROOT / "art" / "verse" / "gold_allowlist.txt"
    gold_ok = set(allow.read_text(encoding="utf-8").split()) if allow.is_file() else set()
    for recipe in materials.load_recipes():
        if only and recipe["name"] not in only:
            continue
        path = materials.instance_path(recipe)
        mi = unreal.load_asset(path)
        if mi is None:
            errors.append(f"{recipe['name']}: {path} does not exist")
            continue
        parent = mi.get_editor_property("parent")
        if parent is None or parent.get_path_name() != recipe["parent"]:
            errors.append(f"{recipe['name']}: parent is not {recipe['parent']}")
        vectors = _mi_vectors(unreal, mi)
        gold = recipe["name"] in gold_ok
        for param, value in sorted(vectors.items()):
            errors += bans(f"{recipe['name']}.{param}", list(value), gold_allowed=gold)
        if path.startswith(WEAPON_MI_FOLDER):
            errors += weapon_colour_errors(recipe["name"], recipe["parent"], vectors)
        checked.append(recipe["name"])
    return errors, checked
