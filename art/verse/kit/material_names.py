"""Unreal-facing names of the stand-in materials some builders create (art-pipeline 3, 7).

Pure Python, no bpy. Two prop families build their own materials when the kit
library has no match, under names that are not Verse material names:

* `kit/props/industrial/_mats.py` makes `M_TMP_PropsInd_<Role>`;
* `kit/props/command/_base.py` makes `TMP_M_<Name>`.

Today's three.js cook keys its realtime tables by those names, so the builders keep
them. Only the Unreal export renames them, in its own Blender session, so every slot
lands on a PascalCase instance with a recipe: `M_PropsInd_<Role>` and `M_<Name>`.
"""

from __future__ import annotations

import re

_INDUSTRIAL = re.compile(r"^M_TMP_PropsInd_(?P<role>[A-Za-z0-9]+)$")
_COMMAND = re.compile(r"^TMP_(?P<name>M_[A-Za-z0-9][A-Za-z0-9_]*)$")


def unreal_name(blender_name: str) -> str:
    """The material name the Unreal export writes for `blender_name` (unchanged when fine)."""
    match = _INDUSTRIAL.match(blender_name)
    if match:
        return f"M_PropsInd_{match['role']}"
    match = _COMMAND.match(blender_name)
    if match:
        return match["name"]
    return blender_name


def is_stand_in(blender_name: str) -> bool:
    return unreal_name(blender_name) != blender_name
