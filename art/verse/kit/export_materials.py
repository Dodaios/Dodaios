"""Blender side of the WP12 material handling for the Unreal export (art-pipeline 7).

Used by `kit_export_blender.py` and `deck_export_blender.py`, inside Blender only:

* `rename_stand_ins()` gives the builders' stand-in materials their Unreal names
  (`kit/material_names.py`) for this Blender session, so the FBX slots and the import
  records carry them;
* `tints(materials)` reads what an MI recipe needs from each material: the base colour,
  emission, opacity, metalness and roughness of its Principled BSDF when those inputs
  are plain values, else the viewport colour. `kit/mi_recipes.py` turns them into
  recipes for the materials that are not in `lib/materials.py`.
"""

from __future__ import annotations

import bpy
from lib import unreal_export

from kit import material_names


def rename_stand_ins() -> int:
    """Rename every stand-in material in the file; returns how many changed."""
    changed = 0
    for material in list(bpy.data.materials):
        base = unreal_export.strip_suffix(material.name)
        target = material_names.unreal_name(base)
        if target == base:
            continue
        existing = bpy.data.materials.get(target)
        if existing is not None and existing != material:
            material.user_remap(existing)
        else:
            material.name = target
        changed += 1
    return changed


def _value(node, *names):
    for name in names:
        socket = node.inputs.get(name)
        if socket is not None and not socket.is_linked:
            return socket.default_value
    return None


def _rgb(value) -> list[float]:
    return [round(float(value[i]), 6) for i in range(3)]


def tint(material) -> dict:
    """`{"base": [r, g, b], "emission": [r, g, b], "strength": s, "alpha": a, ...}`, linear."""
    out = {"base": _rgb(material.diffuse_color), "source": "viewport"}
    tree = getattr(material, "node_tree", None)
    nodes = tree.nodes if tree is not None else []
    bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is not None:
        base = _value(bsdf, "Base Color")
        if base is not None:
            out["base"] = _rgb(base)
            out["source"] = "bsdf"
        for key, names in (
            ("metallic", ("Metallic",)),
            ("roughness", ("Roughness",)),
            ("alpha", ("Alpha",)),
            ("transmission", ("Transmission Weight", "Transmission")),
            ("strength", ("Emission Strength",)),
        ):
            value = _value(bsdf, *names)
            if value is not None:
                out[key] = round(float(value), 6)
        emission = _value(bsdf, "Emission Color", "Emission")
        if emission is not None:
            out["emission"] = _rgb(emission)
    emit = next((n for n in nodes if n.type == "EMISSION"), None)
    if emit is not None:
        colour = _value(emit, "Color")
        strength = _value(emit, "Strength")
        if colour is not None:
            out["emission"] = _rgb(colour)
        if strength is not None:
            out["strength"] = max(float(strength), out.get("strength", 0.0))
    if any(n.type == "BSDF_GLASS" for n in nodes):
        out["transmission"] = 1.0
    return out


def tints(materials) -> dict[str, dict]:
    out = {}
    for material in materials:
        if material is None:
            continue
        out[unreal_export.strip_suffix(material.name)] = tint(material)
    return out
