"""Blender material names to Unreal material instances (art-pipeline 7).

Pure Python. Each Blender `M_<Name>` of `lib/materials.py` maps to one
`MI_<Name>` in a group folder under `/Game/Verse/Materials/Instances/`; the
export writes that path into each mesh's material slot list, and the MI
recipe `unreal/Verse/Art/Materials/MI_<Name>.mi.json` (owned by the folder's
package, art-pipeline 9) describes the instance.
"""

from __future__ import annotations

import re

INSTANCES_ROOT = "/Game/Verse/Materials/Instances"

#: Blender name prefix (after `M_`) -> instance group folder. First match wins.
GROUPS: tuple[tuple[str, str], ...] = (
    ("Floor_", "Floors"),
    ("Deck_", "Markings"),
    ("Wall_", "Walls"),
    ("Ceiling_", "Walls"),
    ("Recess_", "Walls"),
    ("Section_", "Walls"),
    ("Struct_", "Metal"),
    ("Trim_", "Metal"),
    ("Rubber_", "Metal"),
    ("Hull_", "Hull"),
    ("Light_", "Lights"),
    ("Emit_", "Lights"),
    ("Indicator_", "Lights"),
    ("Console_", "Consoles"),
    ("Screen", "Screens"),
    ("Glass_", "Glass"),
    ("Weapon_", "Weapons"),
    ("Character_", "Characters"),
    ("Skin_", "Characters"),
)
DEFAULT_GROUP = "Props"

_BLENDER_NAME = re.compile(r"^M_(?P<name>[A-Za-z0-9][A-Za-z0-9_]*?)(?:\.\d{3})?$")


def instance_name(blender_material: str) -> str:
    """`M_Wall_Charcoal` (or `M_Wall_Charcoal.001`) -> `MI_Wall_Charcoal`."""
    match = _BLENDER_NAME.match(blender_material)
    if not match:
        raise ValueError(f"not a Verse material name: {blender_material!r}")
    return f"MI_{match['name']}"


def group_for(blender_material: str) -> str:
    name = instance_name(blender_material)[3:]
    for prefix, group in GROUPS:
        if name.startswith(prefix):
            return group
    return DEFAULT_GROUP


def instance_path(blender_material: str) -> str:
    """Object path of the MI that replaces `blender_material`."""
    mi = instance_name(blender_material)
    return f"{INSTANCES_ROOT}/{group_for(blender_material)}/{mi}.{mi}"
