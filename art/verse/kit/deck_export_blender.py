"""Blender side of the deck geometry export for Unreal (WP12.4 to WP12.7).

Run by `art/verse/kit/deck_import.py geometry <deck>` through `scripts/verse/blender.py`:

    argv: <deck> --zones ZONES.json --out DIR --result FILE

It builds the deck with its builder (`art/verse/decks/<deck>/build.py`, the same
scene the three.js cook used), then splits it for Unreal:

* every top-level kit placement (a collection instance of a kit master, or a
  realised one) becomes a placement of that piece (contracts/art-pipeline.md 4.2);
* every other mesh (the deck's bespoke hull, floors, walls and ceilings, ghosts
  included: Unreal has no plate camera to hide them from) is joined per zone into
  one shell mesh `SM_<Deck>_<Zone>_Shell`, exported as FBX with `fbx-ue/1`, its
  origin on the zone's floor centre;
* the zone's ceilings, their fixtures, ghosts and everything that starts higher than
  `UPPER_M` above the zone floor (upper hull, plenums) go into a separate
  `SM_<Deck>_<Zone>_Ceiling`, which the deck camera hides in the overview (cutaway);
* the deck bounds of `kit/deck_bounds.py` (floors and walls from today's nav grid) become
  hidden proxy meshes `SM_<Deck>_<Zone>_Bounds[<n>]` of at most 16 boxes each: every box
  is both the render geometry and a `UECOL_` primitive. The shells carry no collision.

Stand-in materials get their Unreal names first (`kit/export_materials.py`), and each
result lists the tint of every material slot for `kit/mi_recipes.py`.

`ZONES.json` maps each zone to its room polygons in Blender metres
(`{"zones": {zone: {"rooms": [[[x, y], ...], ...], "centre": [x, y, z], "bounds": [box]}},
"strict": bool}`, a box being `{"kind", "centre", "size", "yaw_deg"}`). An object belongs
to the zone whose room holds its centre, else (unless `strict`, used on the hangar where
WP11 owns the other zones) the nearest.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from lib import kit, unreal_export
from mathutils import Matrix, Vector

from kit import cap_fit, export_materials

KIT_MODULES = ("kit.architecture", "kit.props.command", "kit.props.industrial")
SKIP_PREFIXES = ("SOCKET_", "ROOM_", "UCX_", "UBX_", "USP_", "UCP_", "RT_")
SKIP_COLLECTIONS = ("Occluders", "Sockets", "NavOnly")
MIN_FACE_AREA = 1e-7  # m2; below any visible face, above the exporter check


def _inside(point, polygon) -> bool:
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _distance(point, polygon) -> float:
    if _inside(point, polygon):
        return 0.0
    best = math.inf
    for i in range(len(polygon)):
        ax, ay = polygon[i]
        bx, by = polygon[(i + 1) % len(polygon)]
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        along = ((point[0] - ax) * dx + (point[1] - ay) * dy) / length2 if length2 else 0.0
        t = max(0.0, min(1.0, along))
        best = min(best, math.hypot(point[0] - (ax + t * dx), point[1] - (ay + t * dy)))
    return best


class ZoneMap:
    def __init__(self, spec: dict):
        self.zones = spec["zones"]
        self.strict = bool(spec.get("strict"))

    def zone_of(self, point_xy) -> str | None:
        best = None
        for zone, data in self.zones.items():
            for polygon in data["rooms"]:
                distance = _distance(point_xy, polygon)
                if distance == 0.0:
                    return zone
                if best is None or distance < best[0]:
                    best = (distance, zone)
        if self.strict or best is None:
            return None
        return best[1]


def _skip(obj) -> bool:
    name = unreal_export.strip_suffix(obj.name)
    if name.startswith(SKIP_PREFIXES):
        return True
    return any(unreal_export.strip_suffix(c.name) in SKIP_COLLECTIONS for c in obj.users_collection)


def _kit_root(obj, registry):
    """The top-level kit placement this object belongs to, or None."""
    node = obj
    while node is not None:
        piece = node.get("piece")
        if piece in registry and not _in_master(node):
            return node
        node = node.parent
    return None


def _in_master(obj) -> bool:
    prefixes = ("SM_", kit.MASTER_ROOT)
    names = (unreal_export.strip_suffix(c.name) for c in obj.users_collection)
    return any(name.startswith(prefixes) for name in names)


def _clean(mesh: bpy.types.Mesh) -> None:
    bm = bmesh.new()
    bm.from_mesh(mesh)
    # Triangles first: a twisted n-gon can have area by one measure and none by another.
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 3])
    bad = [f for f in bm.faces if f.calc_area() < MIN_FACE_AREA]
    if bad:
        bmesh.ops.delete(bm, geom=bad, context="FACES")
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bm.to_mesh(mesh)
    bm.free()


#: Bespoke geometry that starts this high above the zone floor belongs to the ceiling mesh.
UPPER_M = 3.0
#: Material of the hidden bounds meshes (never seen in game).
BOUNDS_MATERIAL = "M_Section_Cap"


def _box_mesh(name: str, box: dict, offset: Vector) -> bpy.types.Mesh:
    """A unit cube scaled, turned and moved to one bounds box (zone-local metres)."""
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(mesh)
    bm.free()
    centre = Vector(box["centre"]) + offset
    turn = Matrix.Rotation(math.radians(box["yaw_deg"]), 4, "Z")
    mesh.transform(Matrix.Translation(centre) @ turn @ Matrix.Diagonal((*box["size"], 1.0)))
    return mesh


def _bounds_collections(zone_title: str, boxes: list[dict], offset: Vector):
    """(name suffix, collection) per group of at most MAX_PRIMITIVES boxes."""
    material = bpy.data.materials.get(BOUNDS_MATERIAL) or bpy.data.materials.new(BOUNDS_MATERIAL)
    cap = unreal_export.MAX_PRIMITIVES
    for index in range(0, len(boxes), cap):
        group = boxes[index : index + cap]
        number = index // cap + 1
        collection = bpy.data.collections.new(f"WP12_{zone_title}_bounds_{number}")
        for nn, box in enumerate(group):
            axis_aligned = abs(math.remainder(box["yaw_deg"], 90.0)) < 1e-6
            kind = "Box" if axis_aligned else "Convex"
            render = _box_mesh(f"WP12_bounds_{nn:02d}", box, offset)
            render.materials.append(material)
            collection.objects.link(bpy.data.objects.new(f"WP12_bounds_{nn:02d}", render))
            proxy = _box_mesh(f"UECOL_{kind}_{nn:02d}", box, offset)
            collection.objects.link(bpy.data.objects.new(f"UECOL_{kind}_{nn:02d}", proxy))
        yield number, collection


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="deck_export_blender")
    parser.add_argument("deck")
    parser.add_argument("--zones", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    options = parser.parse_args(argv)
    zones = ZoneMap(json.loads(options.zones.read_text(encoding="utf-8")))

    for name in KIT_MODULES:
        module = importlib.import_module(name)
        if callable(getattr(module, "load_all", None)):
            module.load_all()
    builder = importlib.import_module(f"decks.{options.deck}.build")
    builder.build()
    export_materials.rename_stand_ins()
    registry = kit.registry()
    bpy.context.view_layer.update()

    # 1. Kit placements: the top-level placement roots.
    placements = []
    roots = set()
    for obj in bpy.context.scene.objects:
        if _skip(obj) or _in_master(obj):
            continue
        piece = obj.get("piece")
        if piece not in registry or (obj.parent is not None and _kit_root(obj.parent, registry)):
            continue
        roots.add(obj.name)
        loc, rot, scale = obj.matrix_world.decompose()
        zone = zones.zone_of((loc.x, loc.y))
        if zone is None:
            continue
        placements.append(
            {
                "zone": zone,
                "blender_name": obj.name,
                "piece": piece,
                "location_m": list(loc),
                "quat_wxyz": list(rot),
                "scale": list(scale),
                "room": obj.get("room"),
                "nav": obj.get("nav") or registry[piece].nav,
                "station": obj.get("station"),
                "station_kind": obj.get("station_kind"),
            }
        )

    # 2. Bespoke geometry: every mesh instance not owned by a kit placement, by zone.
    depsgraph = bpy.context.evaluated_depsgraph_get()
    per_zone: dict[str, list] = {}
    for instance in depsgraph.object_instances:
        obj = instance.object
        if obj.type != "MESH":
            continue
        original = obj.original
        owner = instance.parent.original if instance.is_instance and instance.parent else original
        if _skip(original) or _skip(owner) or owner.name in roots or _kit_root(owner, registry):
            continue
        if _in_master(owner):
            continue
        mesh = bpy.data.meshes.new_from_object(
            obj, preserve_all_data_layers=True, depsgraph=depsgraph
        )
        if not mesh.polygons:
            bpy.data.meshes.remove(mesh)
            continue
        slots = [slot.material for slot in original.material_slots]
        for index, material in enumerate(slots):
            if index < len(mesh.materials):
                mesh.materials[index] = material
            else:
                mesh.materials.append(material)
        matrix = instance.matrix_world.copy()
        mesh.transform(matrix)
        if matrix.determinant() < 0:
            mesh.flip_normals()
        _clean(mesh)
        if not mesh.polygons:
            bpy.data.meshes.remove(mesh)
            continue
        centre = sum((v.co for v in mesh.vertices), Vector()) / len(mesh.vertices)
        zone = zones.zone_of((centre.x, centre.y))
        if zone is None:
            bpy.data.meshes.remove(mesh)
            continue
        # Ceilings, their fixtures and ghosts are hidden from today's plate camera; in Unreal they
        # are a separate mesh the deck camera hides in the overview (the cutaway). So is what
        # starts above head height (upper hull, plenums): today's plate cut it away too.
        lowest = min(v.co.z for v in mesh.vertices)
        ceiling = (
            not original.visible_camera
            or bool(original.get("ceiling_ghost"))
            or "Ceiling" in {unreal_export.strip_suffix(c.name) for c in original.users_collection}
            or lowest >= zones.zones[zone]["centre"][2] + UPPER_M
        )
        per_zone.setdefault(zone, []).append((original.name, mesh, ceiling))

    shells = []
    options.out.mkdir(parents=True, exist_ok=True)
    title = "".join(part.capitalize() for part in options.deck.split("_"))
    for zone, meshes in sorted(per_zone.items()):
        cx, cy, cz = zones.zones[zone]["centre"]
        offset = Matrix.Translation(Vector((-cx, -cy, -cz)))
        zone_title = "".join(p.capitalize() for p in zone.split("_"))
        for kind in ("shell", "ceiling"):
            want = kind == "ceiling"
            parts = [(source, mesh) for source, mesh, ceiling in meshes if ceiling == want]
            if kind == "ceiling" and not parts:
                continue
            collection = bpy.data.collections.new(f"WP12_{zone}_{kind}")
            linked = 0
            for source, mesh in parts:
                mesh.transform(offset)
                _clean(mesh)  # after the last transform: float rounding can collapse tiny faces
                if not mesh.polygons:
                    continue
                item = bpy.data.objects.new(f"{unreal_export.strip_suffix(source)}_part", mesh)
                collection.objects.link(item)
                linked += 1
            if kind == "ceiling" and not linked:
                continue
            name = f"SM_{title}_{zone_title}_{kind.capitalize()}"
            result = cap_fit.export(name, collection, options.out, cap=cap_fit.DEFAULT_CAP)
            entry = result.as_dict()
            entry["zone"] = zone
            entry["kind"] = kind
            entry["origin_m"] = [cx, cy, cz]
            entry["parts"] = len(parts)
            entry["material_tints"] = export_materials.tints(
                bpy.data.materials.get(slot["slot"]) for slot in entry["material_slots"]
            )
            shells.append(entry)
            tris = entry["triangles"]
            print(f"[verse] {options.deck}/{zone}: {kind} {name}, {tris} tris, {len(parts)} parts")

    for zone, spec in sorted(zones.zones.items()):
        boxes = spec.get("bounds", [])
        if not boxes:
            continue
        cx, cy, cz = spec["centre"]
        zone_title = "".join(p.capitalize() for p in zone.split("_"))
        offset = Vector((-cx, -cy, -cz))
        for number, collection in _bounds_collections(zone_title, boxes, offset):
            suffix = "" if number == 1 else str(number)
            name = f"SM_{title}_{zone_title}_Bounds{suffix}"
            result = unreal_export.export_static_mesh(name, collection, options.out)
            entry = result.as_dict()
            entry.update(zone=zone, kind="bounds", index=number, origin_m=[cx, cy, cz], parts=0)
            shells.append(entry)
        print(f"[verse] {options.deck}/{zone}: {len(boxes)} bounds boxes")

    options.result.parent.mkdir(parents=True, exist_ok=True)
    options.result.write_text(
        json.dumps({"deck": options.deck, "placements": placements, "shells": shells}, indent=1),
        encoding="utf-8",
    )
    print(f"[verse] {options.deck}: {len(placements)} kit placements, {len(shells)} shells")


main(sys.argv[1:])
