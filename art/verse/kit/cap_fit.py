"""Fit an exported static mesh under its triangle cap (art-pipeline 6.2), inside Blender.

`export` exports once; when the measured count is over the cap it adds a planar
dissolve (flat hard-surface faces merge without changing the silhouette) to every
render mesh of the collection and exports again, then a collapse at the ratio that
is still needed. Collision primitives (`UECOL_*`) and sockets are never touched.
The FBX and the result come from the last export, so the record carries the real
count and hash.
"""

from __future__ import annotations

import math
from collections.abc import Iterator

import bpy
from lib import unreal_export

#: Triangle caps of art-pipeline 6.2 for the assets WP12 exports.
ARCHITECTURE_CAP = 500_000
DEFAULT_CAP = 200_000
#: Head room under the cap, so a rebuild that adds a few faces stays legal.
MARGIN = 0.95
DISSOLVE_ANGLE_DEG = 1.0
_KEEP_PREFIXES = ("UECOL_", "UESOCKET_", "SOCKET_", "ROOM_")


def cap_for(builder_path: str) -> int:
    """Architecture pieces are built under `kit/architecture/`; everything else is a prop cap."""
    return ARCHITECTURE_CAP if "/kit/architecture/" in f"/{builder_path}" else DEFAULT_CAP


def _render_objects(
    collection: bpy.types.Collection, depth: int = 0
) -> Iterator[bpy.types.Object]:
    if depth > 16:
        return
    for obj in collection.all_objects:
        kept = unreal_export.strip_suffix(obj.name).startswith(_KEEP_PREFIXES)
        if obj.type == "MESH" and not kept:
            yield obj
        if obj.instance_type == "COLLECTION" and obj.instance_collection is not None:
            yield from _render_objects(obj.instance_collection, depth + 1)


def _add(collection: bpy.types.Collection, kind: str, ratio: float = 1.0) -> int:
    seen: set[str] = set()
    for obj in _render_objects(collection):
        if obj.name in seen:
            continue
        seen.add(obj.name)
        mod = obj.modifiers.new(name=f"WP12_cap_{kind}", type="DECIMATE")
        if kind == "dissolve":
            mod.decimate_type = "DISSOLVE"
            mod.angle_limit = math.radians(DISSOLVE_ANGLE_DEG)
            mod.delimit = {"MATERIAL"}
        else:
            mod.decimate_type = "COLLAPSE"
            mod.ratio = ratio
    return len(seen)


def export(name: str, collection: bpy.types.Collection, out_dir, *, cap: int, **kwargs):
    """`unreal_export.export_static_mesh` that ends under `cap`; raises if it cannot."""
    target = int(cap * MARGIN)
    result = unreal_export.export_static_mesh(name, collection, out_dir, **kwargs)
    first = result.triangles
    if first <= target:
        return result
    _add(collection, "dissolve")
    result = unreal_export.export_static_mesh(name, collection, out_dir, **kwargs)
    if result.triangles > target:
        ratio = max(0.02, target / result.triangles * 0.97)
        _add(collection, "collapse", ratio)
        result = unreal_export.export_static_mesh(name, collection, out_dir, **kwargs)
    print(f"[verse] {name}: {first} -> {result.triangles} tris (cap {cap})", flush=True)
    if result.triangles > cap:
        count = result.triangles
        raise unreal_export.ExportError(f"{name}: {count} triangles after fitting, cap {cap}")
    return result
