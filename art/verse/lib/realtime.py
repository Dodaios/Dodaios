"""Realtime export of a deck, Blender side: the deck as an eye-level 3D scene.

The plate cook photographs a deck from one fixed angle. The realtime export
turns the same scene into geometry a browser can walk through at eye level:

1. every mesh instance of Architecture, Props and Ceiling (the ceiling ghosts
   included, now as normal geometry that casts shadows) is realised into its
   own object, so it can own a unique lightmap layout;
2. a second UV set (``LM``) is unwrapped per object and packed into square
   atlas pages, at a texel density weighted by how close people get to the
   surface (floors and consoles high, hull voids and ceilings low);
3. Cycles bakes per page the diffuse irradiance (direct and indirect), the
   diffuse albedo, the emission, and the world normal and position used to
   denoise the irradiance; the page stores the view-independent outgoing
   radiance ``albedo * irradiance + emission`` (scene linear, HDR);
4. a box-projected reflection panorama is rendered per room;
5. the triangles are grouped by (material, room, page) into chunks with
   world positions, normals and the lightmap UV.

`scripts/verse/package.py` (outside Blender) encodes the pages and panoramas
(RGBM WebP), writes the meshopt-compressed glTF and the manifest's
``realtime`` block. Format and runtime: docs/verse/realtime.md.

Raw outputs (all in `out_dir`):
    lm_<page>.npy        float16 (h, w, 3) radiance per page, gaps filled
    probe_<room>.npy     float16 (h, w, 3) equirect radiance, three.js layout
    geometry.npz         chunk arrays: <i>_pos, <i>_nrm (float32), <i>_uv, <i>_idx
    realtime.json        chunks, pages, probes, materials, stats
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Vector

from lib import cook, lightmap, scene

UV_NAME = "LM"
ROLES = ("Architecture", "Props", "Ceiling", "Lights")
# Faces never exported: the plate's section caps (a drawing convention),
# decals cut out by their alpha (worn-through paint, stencils; they need an
# alpha bake, docs/verse/realtime.md "Open work") and volume-only haze. A
# material whose node tree is volume-only or alpha-cut is recognised as well
# (`_unexportable`), so a deck's own decals and hazes need no entry here.
EXCLUDED_MATERIALS = frozenset(
    {
        "M_Section_Cap",
        "M_Deck_Hazard",
        "M_Deck_Marking_White",
        "M_Deck_Marking_Amber",
        "M_Deck_Marking_Red",
        "M_Deck_Marking_Dark",
        "M_TMP_PropsInd_StencilAmber",
        "M_TMP_PropsInd_StencilDark",
        "M_TMP_PropsInd_StencilRed",
        "M_TMP_PropsInd_StencilWhite",
        "M_Haze_Volume",
        "M_TMP_PropsInd_Haze",
        "M_Eng_ShaftHaze",
        "M_Hangar_WellFog",
    }
)


@dataclass(frozen=True)
class Preset:
    page_px: int
    density: float  # lightmap texels per metre at weight 1
    max_pages: int
    samples: int  # irradiance bake samples
    probe_size: tuple[int, int]
    probe_samples: int
    margin_px: int
    denoise_passes: int


PRESETS = {
    "final": Preset(4096, 48.0, 4, 512, (1024, 512), 256, 6, 4),
    "preview": Preset(1024, 10.0, 2, 48, (256, 128), 48, 3, 2),
}

# How close people get to a surface: lightmap density relative to the base.
DENSITY_WEIGHT = {
    "M_Hull_Structure": 0.3,
    "M_Hull_Pipe": 0.35,
    "M_Hull_PipeInsulated": 0.35,
    "M_Ceiling_Panel": 0.45,
    "M_Recess_Dark": 0.4,
    "M_Starfield": 0.6,
    "M_Floor_GlossBlack": 0.75,
    "M_Floor_SatinDark": 0.75,
    "M_Floor_Grating": 0.75,
    "M_Light_CeilingPanel": 0.5,
    # Operations deck
    "M_Ops_Floor_Satin": 0.75,
    "M_Ops_Floor_SatinGrey": 0.75,
    "M_Ops_Floor_WashTile": 0.75,
    "M_Ops_Floor_WhiteTile": 0.75,
    "M_Ops_Starfield": 0.6,
    "M_Ops_Light_Corridor": 0.5,
    "M_Ops_Light_Dim": 0.5,
    "M_Ops_Light_Warm": 0.5,
    "M_Ops_Light_MessCool": 0.5,
    "M_Ops_Light_Night": 0.5,
    "M_Ops_Light_Ring": 0.5,
    "M_Ops_Light_Med": 0.5,
    # Hangar deck: 4 200 m2 of flight deck, seen from 1.7 m
    "M_Hangar_Deck": 0.6,
    "M_Hangar_BankPanel": 0.4,
    "M_Hangar_RoomStrip": 0.5,
}


@dataclass(frozen=True)
class RtMaterial:
    """What the runtime needs on top of the baked radiance: the specular layer.

    The bake carries all diffuse light (and the diffuse albedo in it), so the
    runtime material draws ``radiance + specular``. ``color`` is the specular
    tint of metals (linear RGB); ``specular`` is Blender's Specular IOR Level
    (0.5 = F0 4 %). ``detail`` picks a runtime close-up layer (see
    docs/verse/realtime.md); ``collide`` says whether the camera stops at it.
    """

    roughness: float = 0.5
    metalness: float = 0.0
    color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    clearcoat: float = 0.0
    clearcoat_roughness: float = 0.05
    specular: float = 0.5
    detail: str = "none"
    transparent: bool = False
    opacity: float = 1.0
    collide: bool = True


_GLASS = RtMaterial(roughness=0.02, specular=0.5, transparent=True, opacity=0.06, collide=False)
_LAMP = RtMaterial(roughness=0.25, clearcoat=1.0, clearcoat_roughness=0.02, collide=False)
_EMITTER = RtMaterial(roughness=0.6, specular=0.25, collide=False)

MATERIALS: dict[str, RtMaterial] = {
    "M_Floor_GlossBlack": RtMaterial(
        roughness=0.3, clearcoat=1.0, clearcoat_roughness=0.06, specular=0.12, detail="deck_plates"
    ),
    "M_Floor_SatinDark": RtMaterial(
        roughness=0.3, clearcoat=0.35, clearcoat_roughness=0.06, detail="deck_plates"
    ),
    "M_Floor_Grating": RtMaterial(roughness=0.46, metalness=1.0, color=(0.32, 0.33, 0.34)),
    "M_Wall_PaintedLight": RtMaterial(
        roughness=0.28, clearcoat=0.2, clearcoat_roughness=0.12, detail="painted"
    ),
    "M_Wall_PaintedMid": RtMaterial(roughness=0.41, detail="painted"),
    "M_Wall_PaintedDark": RtMaterial(roughness=0.39, detail="painted"),
    "M_Wall_Charcoal": RtMaterial(
        roughness=0.32, clearcoat=0.25, clearcoat_roughness=0.12, detail="painted"
    ),
    "M_Struct_Gunmetal": RtMaterial(
        roughness=0.38, metalness=1.0, color=(0.16, 0.165, 0.175), detail="metal"
    ),
    "M_Trim_BrushedSteel": RtMaterial(
        roughness=0.22, metalness=1.0, color=(0.56, 0.565, 0.575), detail="metal"
    ),
    "M_Trim_Chrome": RtMaterial(roughness=0.07, metalness=1.0, color=(0.82, 0.83, 0.84)),
    "M_Rubber_Black": RtMaterial(roughness=0.72, specular=0.35),
    "M_Recess_Dark": RtMaterial(roughness=0.7),
    "M_Ceiling_Panel": RtMaterial(roughness=0.47, detail="painted"),
    "M_Console_Body": RtMaterial(
        roughness=0.36, clearcoat=0.15, clearcoat_roughness=0.12, detail="painted"
    ),
    "M_Console_Deck": RtMaterial(roughness=0.43, detail="painted"),
    "M_Console_Keys": RtMaterial(roughness=0.5),
    "M_Screen": RtMaterial(roughness=0.3, clearcoat=1.0, clearcoat_roughness=0.03),
    "M_Glass_Viewport": _GLASS,
    "M_Glass_Clear": RtMaterial(
        roughness=0.01, specular=0.5, transparent=True, opacity=0.04, collide=False
    ),
    "M_Starfield": RtMaterial(roughness=1.0, specular=0.0, collide=False),
    "M_Plastic_BlackSatin": RtMaterial(roughness=0.48),
    "M_Plastic_LampOff": RtMaterial(roughness=0.25, clearcoat=0.5, clearcoat_roughness=0.05),
    "M_Plastic_MedWhite": RtMaterial(roughness=0.36),
    "M_Fabric_BunkGrey": RtMaterial(roughness=0.9, specular=0.3),
    "M_Paint_TrimRed": RtMaterial(roughness=0.3),
    "M_Lacquer_BlackGloss": RtMaterial(roughness=0.07, clearcoat=1.0, clearcoat_roughness=0.03),
    "M_Seat_Upholstery": RtMaterial(roughness=0.4),
    "M_Crate_Paint": RtMaterial(roughness=0.46, detail="painted"),
    "M_Hull_Structure": RtMaterial(roughness=0.5, metalness=0.75, color=(0.07, 0.075, 0.085)),
    "M_Hull_Pipe": RtMaterial(roughness=0.41),
    "M_Hull_PipeInsulated": RtMaterial(roughness=0.69),
    "M_Section_Cap": RtMaterial(roughness=0.5),
    "M_Light_CeilingPanel": _EMITTER,
    "M_Light_WallStrip": _EMITTER,
    "M_Light_Backlit": _EMITTER,
    "M_Light_RedTrim": _EMITTER,
    "M_Light_FloorInlay": _EMITTER,
    "M_Light_Maint_Red": _EMITTER,
    "M_Light_Maint_Amber": _EMITTER,
    "M_Emit_BacklitPanel": _EMITTER,
    "M_Indicator_Red": _LAMP,
    "M_Indicator_Green": _LAMP,
    "M_Indicator_Amber": _LAMP,
    "M_Indicator_Blue": _LAMP,
    "M_Indicator_White": _LAMP,
    "M_Light_Warm": _EMITTER,
    "M_Light_Flood": _EMITTER,
    "M_Light_DimCold": _EMITTER,
    "M_Light_CabinWarm": _EMITTER,
    # Industrial kit stand-ins (temp names while lib.materials lacks them)
    "M_TMP_PropsInd_LampFlood": _EMITTER,
    "M_TMP_PropsInd_LampDim": _EMITTER,
    "M_TMP_PropsInd_CabinGlow": _EMITTER,
    "M_TMP_PropsInd_CoreHot": _EMITTER,
    "M_TMP_PropsInd_ContainerGrey": RtMaterial(roughness=0.5, detail="painted"),
    "M_TMP_PropsInd_ContainerGunmetal": RtMaterial(roughness=0.46, detail="painted"),
    "M_TMP_PropsInd_ContainerOlive": RtMaterial(roughness=0.5, detail="painted"),
    "M_TMP_PropsInd_HullPaint": RtMaterial(roughness=0.42, detail="painted"),
    "M_TMP_PropsInd_GlassDark": RtMaterial(roughness=0.04, clearcoat=0.6, clearcoat_roughness=0.03),
    "M_TMP_PropsInd_Tread": RtMaterial(
        roughness=0.36, metalness=1.0, color=(0.3, 0.305, 0.31), detail="metal"
    ),
    "M_Container_Paint_Grey": RtMaterial(roughness=0.5, detail="painted"),
    "M_Container_Paint_Gunmetal": RtMaterial(roughness=0.46, detail="painted"),
    "M_Container_Paint_Olive": RtMaterial(roughness=0.5, detail="painted"),
    "M_Hull_PaintWhite": RtMaterial(roughness=0.42, detail="painted"),
    "M_Glass_Canopy": RtMaterial(roughness=0.04, clearcoat=0.6, clearcoat_roughness=0.03),
    # Hologram projector lenses (bridge): small, glossy, never in the camera's way.
    "TMP_M_Glass_HoloLens": RtMaterial(
        roughness=0.04, clearcoat=1.0, clearcoat_roughness=0.02, collide=False
    ),
    "M_Glass_HoloLens": RtMaterial(
        roughness=0.04, clearcoat=1.0, clearcoat_roughness=0.02, collide=False
    ),
    "M_Metal_TreadPlate": RtMaterial(
        roughness=0.36, metalness=1.0, color=(0.3, 0.305, 0.31), detail="metal"
    ),
    "M_Reactor_CoreHot": _EMITTER,
    "M_Eng_CoreHot": _EMITTER,
    # Operations deck
    "M_Ops_Floor_Satin": RtMaterial(
        roughness=0.3, clearcoat=0.45, clearcoat_roughness=0.08, detail="deck_plates"
    ),
    "M_Ops_Floor_SatinGrey": RtMaterial(roughness=0.4, detail="painted"),
    "M_Ops_Floor_WashTile": RtMaterial(roughness=0.26, clearcoat=0.3, clearcoat_roughness=0.08),
    "M_Ops_Floor_WhiteTile": RtMaterial(roughness=0.3, clearcoat=0.2, clearcoat_roughness=0.1),
    "M_Ops_Table_Top": RtMaterial(roughness=0.16, clearcoat=1.0, clearcoat_roughness=0.05),
    "M_Ops_Table_Grey": RtMaterial(roughness=0.4, detail="painted"),
    "M_Ops_Wall_White": RtMaterial(roughness=0.35, detail="painted"),
    "M_Ops_Glass_Case": RtMaterial(
        roughness=0.03, specular=0.5, transparent=True, opacity=0.05, collide=False
    ),
    "M_Ops_Glass_Slit": RtMaterial(
        roughness=0.02, specular=0.15, transparent=True, opacity=0.04, collide=False
    ),
    "M_Ops_Starfield": RtMaterial(roughness=1.0, specular=0.0, collide=False),
    "M_Ops_Light_Pip": _LAMP,
    "M_Ops_Lamp_Warm": _LAMP,
    "M_Ops_Light_Warm": _EMITTER,
    "M_Ops_Light_Dim": _EMITTER,
    "M_Ops_Light_Reading": _EMITTER,
    "M_Ops_Light_Hatch": _EMITTER,
    "M_Ops_Light_Ring": _EMITTER,
    "M_Ops_Light_Med": _EMITTER,
    "M_Ops_Light_Maint": _EMITTER,
    "M_Ops_Light_SimBar": _EMITTER,
    "M_Ops_Light_Corridor": _EMITTER,
    "M_Ops_Light_Night": _EMITTER,
    "M_Ops_Light_MessCool": _EMITTER,
    "M_Ops_Fabric_Blanket": RtMaterial(roughness=0.92, specular=0.3),
    "M_Ops_Fabric_Sheet": RtMaterial(roughness=0.88, specular=0.3),
    "M_Fabric_Linen": RtMaterial(roughness=0.9, specular=0.3),
    "M_Fabric_BlanketSlate": RtMaterial(roughness=0.92, specular=0.3),
    "M_Fabric_UniformOlive": RtMaterial(roughness=0.9, specular=0.3),
    "M_Ops_Enamel_Steel": RtMaterial(roughness=0.3, clearcoat=0.4, clearcoat_roughness=0.08),
    "M_Ops_Enamel_Blue": RtMaterial(roughness=0.3, clearcoat=0.4, clearcoat_roughness=0.08),
    "M_Ops_Enamel_Red": RtMaterial(roughness=0.3, clearcoat=0.4, clearcoat_roughness=0.08),
    "M_Ops_Enamel_Gold": RtMaterial(roughness=0.3, clearcoat=0.4, clearcoat_roughness=0.08),
    "TMP_M_Metal_RankGold": RtMaterial(roughness=0.3, metalness=1.0, color=(0.8, 0.56, 0.22)),
    "TMP_M_Paint_RankBlue": RtMaterial(roughness=0.35),
    "TMP_M_Paint_RankRed": RtMaterial(roughness=0.35),
    "M_Metal_RankGold": RtMaterial(roughness=0.3, metalness=1.0, color=(0.8, 0.56, 0.22)),
    "M_Paint_RankBlue": RtMaterial(roughness=0.35),
    "M_Paint_RankRed": RtMaterial(roughness=0.35),
    # Hangar deck
    "M_Hangar_Deck": RtMaterial(
        roughness=0.42, clearcoat=0.8, clearcoat_roughness=0.06, specular=0.3, detail="painted"
    ),
    "M_Hangar_BankPanel": _EMITTER,
    "M_Hangar_RoomStrip": _EMITTER,
    "M_Hangar_PierLight": _EMITTER,
    "M_Hangar_FloodLens": _EMITTER,
    "M_Hangar_DoorGlow": _EMITTER,
    "M_Hangar_SignBacklit": _EMITTER,
    "M_Hangar_ShaftLamp": _EMITTER,
    "M_Hangar_FloorLamp": _LAMP,
    # The launch well's containment field: a faint emissive sheet that dims
    # what lies below it to about half (its transparent colour ~0.5).
    "M_Hangar_FieldBlue": RtMaterial(
        roughness=0.08, specular=0.2, transparent=True, opacity=0.48, collide=False
    ),
}


class RealtimeError(RuntimeError):
    """The deck scene cannot be exported for the realtime view."""


@dataclass
class Item:
    """One realised mesh object of the export."""

    obj: bpy.types.Object
    weight: float
    area: float  # world surface area, m2
    centre: tuple[float, float, float]
    room: str | None = None
    page: int = -1
    z_range: tuple[float, float] = (0.0, 0.0)  # world height of its lowest and highest point


@dataclass
class Stats:
    timings: dict[str, float] = field(default_factory=dict)
    objects: int = 0
    triangles: int = 0
    vertices: int = 0
    chunks: int = 0
    area_m2: float = 0.0
    page_density: list[float] = field(default_factory=list)
    hidden_objects: int = 0
    hidden_area_m2: float = 0.0
    far_split: int = 0
    far_decimated_triangles: int = 0


def export_realtime(deck_id: str, out_dir: Path, quality: str = "final") -> dict:
    """Export deck `deck_id` (the current scene) for the realtime view into `out_dir`."""
    if quality not in PRESETS:
        raise ValueError(f"quality must be one of {sorted(PRESETS)}")
    preset = PRESETS[quality]
    info = scene.deck_info()
    if info["deck_id"] != deck_id:
        raise RealtimeError(f"scene holds deck {info['deck_id']!r}, not {deck_id!r}")
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    bpy.context.view_layer.update()
    stats = Stats()
    rooms = cook._rooms()
    with cook._stage("realise", stats.timings):
        items = _realise()
        _assign_rooms(items, rooms)
        items = _split_tall(items, rooms, stats)
        _weigh_by_distance(items, rooms, stats)
    with cook._stage("visibility", stats.timings):
        unseen = _unseen(items, rooms)
    # Never seen from where people walk: still lit and casting light in the
    # bake, never exported (no lightmap texels, no triangles).
    hidden_area = sum(items[i].area for i in unseen)
    items = [item for i, item in enumerate(items) if i not in unseen]
    stats.objects = len(items)
    stats.area_m2 = round(sum(item.area for item in items), 1)
    stats.hidden_objects = len(unseen)
    stats.hidden_area_m2 = round(hidden_area, 1)
    print(
        f"[verse] realtime {deck_id}: {len(items)} objects, {stats.area_m2} m2 "
        f"({len(unseen)} objects, {hidden_area:.0f} m2 never seen from the rooms)",
        flush=True,
    )
    with cook._stage("unwrap", stats.timings):
        pages, density = _unwrap(items, preset)
    with cook._stage("join", stats.timings):
        _keep_object_space(items)
        joined = _join_pages(items)
        _patch_materials({m for _, obj in joined for m in obj.data.materials if m is not None})
    with cook._stage("bake", stats.timings):
        page_info = []
        for page in range(pages):
            objects = [obj for p, obj in joined if p == page]
            radiance = _bake_page(page, objects, density, preset)
            np.save(out_dir / f"lm_{page}.npy", radiance.astype(np.float16))
            page_info.append(
                {
                    "file": f"lm_{page}.npy",
                    "size": preset.page_px,
                    "density": round(density, 2),
                    "max": round(float(radiance.max()), 3),
                }
            )
            stats.page_density.append(round(density, 2))
    with cook._stage("probes", stats.timings):
        probes = [_reflection_probe(room, preset, out_dir) for room in rooms]
    with cook._stage("geometry", stats.timings):
        chunks = _export_geometry(joined, out_dir / "geometry.npz", stats)
    used = sorted({chunk["material"] for chunk in chunks})
    result = {
        "id": deck_id,
        "quality": quality,
        "pages": page_info,
        "probes": probes,
        "chunks": chunks,
        "materials": {name: _material_json(name) for name in used},
        "stats": {
            "objects": stats.objects,
            "triangles": stats.triangles,
            "vertices": stats.vertices,
            "chunks": stats.chunks,
            "area_m2": stats.area_m2,
            "hidden_objects": stats.hidden_objects,
            "hidden_area_m2": stats.hidden_area_m2,
            "far_split": stats.far_split,
            "far_decimated_triangles": stats.far_decimated_triangles,
            "density": stats.page_density,
            "samples": preset.samples,
            "blender": bpy.app.version_string,
            **{key: round(value, 2) for key, value in stats.timings.items()},
        },
    }
    (out_dir / "realtime.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


# ---------------------------------------------------------------- realise


def _realise() -> list[Item]:
    """Every mesh instance of the deck as its own single-user object (modifiers
    applied, materials kept, ghosts turned into normal shadow-casting geometry)
    in a fresh collection; the original deck collections leave the render."""
    roles = cook._deck_roles()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    pending = []
    for instance in depsgraph.object_instances:
        obj = instance.object
        if obj.type != "MESH":
            continue
        owner = (
            instance.parent.original if instance.is_instance and instance.parent else obj.original
        )
        if roles.get(owner.name) not in ROLES:
            continue
        mesh = bpy.data.meshes.new_from_object(
            obj, preserve_all_data_layers=True, depsgraph=depsgraph
        )
        original = obj.original
        slots = [slot.material for slot in original.material_slots]
        pending.append((original.name, mesh, instance.matrix_world.copy(), slots, original))
    _exclude_originals()
    target = bpy.data.collections.new("RT_realtime")
    bpy.context.scene.collection.children.link(target)
    items = []
    for name, mesh, matrix, slots, original in pending:
        # The evaluated mesh carries the object's materials in slot order; set
        # them in place (clearing the list would reset every face to slot 0).
        before = _faces_per_material(mesh)
        for index, material in enumerate(slots):
            if index < len(mesh.materials):
                mesh.materials[index] = material
            else:
                mesh.materials.append(material)
        if _faces_per_material(mesh) != before:
            raise RealtimeError(f"{name}: realising changed which faces carry which material")
        if not _drop_excluded_faces(mesh) or not _finite(mesh, name):
            bpy.data.meshes.remove(mesh)
            continue
        obj = bpy.data.objects.new(f"RT_{name}", mesh)
        obj.matrix_world = matrix
        target.objects.link(obj)
        ghost = bool(original.get("ceiling_ghost"))
        obj.visible_camera = True
        obj.visible_shadow = ghost or original.visible_shadow
        obj.visible_diffuse = ghost or original.visible_diffuse
        obj.visible_glossy = ghost or original.visible_glossy
        obj.visible_transmission = ghost or original.visible_transmission
        items.append(_item(obj))
    if not items:
        raise RealtimeError("deck has no mesh geometry to export")
    bpy.context.view_layer.update()
    return items


def _exclude_originals() -> None:
    root = scene.deck_root()
    layer = _layer_collection(bpy.context.view_layer.layer_collection, root.name)
    if layer is None:
        raise RealtimeError(f"collection {root.name} is not in the view layer")
    for child in layer.children:
        if child.name in ("Architecture", "Props", "Ceiling"):
            child.exclude = True
    for obj in scene.objects_in("Lights"):
        if obj.type == "MESH":
            obj.hide_render = True


def _layer_collection(layer, name: str):
    if layer.collection.name == name:
        return layer
    for child in layer.children:
        found = _layer_collection(child, name)
        if found is not None:
            return found
    return None


_UNEXPORTABLE: dict[str, str | None] = {}


def _unexportable(material: bpy.types.Material | None) -> str | None:
    """Why a material's faces stay out of the export, or None.

    Listed in `EXCLUDED_MATERIALS`; volume-only (haze, fog: no surface to
    bake); or cut out by alpha (decals and stencils: a Principled BSDF with a
    linked or partial Alpha, or one mixed with a Transparent BSDF), which
    would bake as opaque quads with black where the paint is missing.
    """
    if material is None:
        return None
    if material.name in _UNEXPORTABLE:
        return _UNEXPORTABLE[material.name]
    reason = None
    if _base_name(material.name) in EXCLUDED_MATERIALS:
        reason = "excluded"
    elif material.node_tree is not None:
        output = _material_output(material.node_tree)
        if output is not None:
            surface = output.inputs["Surface"].links
            if not surface:
                reason = "volume" if output.inputs["Volume"].links else None
            else:
                nodes = _upstream(surface[0].from_node)
                types = {node.type for node in nodes}
                for node in nodes:
                    alpha = node.inputs.get("Alpha") if node.type == "BSDF_PRINCIPLED" else None
                    if alpha is not None and (alpha.is_linked or alpha.default_value < 0.999):
                        reason = "alpha cut-out"
                if {"BSDF_TRANSPARENT", "MIX_SHADER", "BSDF_PRINCIPLED"} <= types:
                    reason = "alpha cut-out"
    _UNEXPORTABLE[material.name] = reason
    return reason


def _material_output(tree: bpy.types.NodeTree):
    outputs = [node for node in tree.nodes if node.type == "OUTPUT_MATERIAL"]
    active = [node for node in outputs if node.is_active_output]
    return (active or outputs or [None])[0]


def _upstream(node) -> list:
    """`node` and every node feeding it."""
    seen, stack = [], [node]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.append(current)
        for socket in current.inputs:
            stack.extend(link.from_node for link in socket.links)
    return seen


def _drop_excluded_faces(mesh: bpy.types.Mesh) -> bool:
    """Remove faces of unexportable materials; False when nothing is left."""
    excluded = {
        index
        for index, material in enumerate(mesh.materials)
        if _unexportable(material) is not None
    }
    if excluded:
        bm = bmesh.new()
        bm.from_mesh(mesh)
        doomed = [face for face in bm.faces if face.material_index in excluded]
        bmesh.ops.delete(bm, geom=doomed, context="FACES")
        bm.to_mesh(mesh)
        bm.free()
    return len(mesh.polygons) > 0


def _finite(mesh: bpy.types.Mesh, name: str) -> bool:
    co = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", co)
    if not np.isfinite(co).all():
        print(f"[verse] realtime: skipping {name} (non-finite vertices)", flush=True)
        return False
    return True


def _faces_per_material(mesh: bpy.types.Mesh) -> dict[str, int]:
    """Face count per material name (the realise step must keep it)."""
    indices = np.empty(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get("material_index", indices)
    names = [m.name if m is not None else "" for m in mesh.materials] or [""]
    counts: dict[str, int] = {}
    for index, count in zip(*np.unique(indices, return_counts=True), strict=True):
        key = names[min(int(index), len(names) - 1)]
        counts[key] = counts.get(key, 0) + int(count)
    return counts


def _base_name(name: str) -> str:
    return name.split(".")[0]


def _item(obj: bpy.types.Object) -> Item:
    mesh = obj.data
    matrix = np.array(obj.matrix_world, dtype=np.float64)
    co = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    world = co.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3]
    mesh.calc_loop_triangles()
    tris = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", tris)
    tris = tris.reshape(-1, 3)
    a, b, c = world[tris[:, 0]], world[tris[:, 1]], world[tris[:, 2]]
    area = float(0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1).sum())
    weights = [DENSITY_WEIGHT.get(_base_name(m.name), 1.0) for m in mesh.materials if m is not None]
    centre = world.mean(axis=0)
    return Item(
        obj=obj,
        weight=max(weights, default=1.0),
        area=area,
        centre=(float(centre[0]), float(centre[1]), float(centre[2])),
        z_range=(float(world[:, 2].min()), float(world[:, 2].max())),
    )


def _assign_rooms(items: list[Item], rooms: list[cook.Room]) -> None:
    """The room each object belongs to (by its centre), for page grouping."""
    for item in items:
        x, y, z = item.centre
        item.room = cook._room_at(x, y, rooms, z) or _nearest_room(x, y, rooms)


def _nearest_room(x: float, y: float, rooms: list[cook.Room]) -> str:
    return min(rooms, key=lambda r: (r.centre[0] - x) ** 2 + (r.centre[1] - y) ** 2).id


# ---------------------------------------------------------------- distance

# People walk on the room floors with their eyes at 1.7 m: surfaces far above
# (the upper walls of a 12 m hall, a 21 m hangar ceiling) or far below (a 52 m
# reactor shaft) are only ever seen from a distance. Tall objects are split
# into height bands, each band's lightmap density falls with its distance
# from the eye band and far bands lose triangles.
EYE_BAND_M = (-1.0, 4.0)  # heights above the room floor seen up close
TALL_M = 8.0  # objects taller than this (and big) are split into bands
TALL_AREA_M2 = 150.0
BAND_EDGES_M = (-24.0, -10.0, -3.0, 6.0, 12.0)  # band limits above the room floor
FAR_FALLOFF_M = 4.0  # density halves this far beyond the eye band
FAR_DECIMATE_M = 4.0  # bands further than this lose triangles
FAR_DECIMATE_RATE_M = 3.0  # and keep 1 / (1 + beyond / this) of them
FAR_MIN_RATIO = 0.1
FAR_MIN_TRIANGLES = 2000


def _distance_beyond_eye_band(item: Item, floor: float) -> float:
    low, high = item.z_range
    return max(0.0, low - (floor + EYE_BAND_M[1]), (floor + EYE_BAND_M[0]) - high)


def _split_tall(items: list[Item], rooms: list[cook.Room], stats: Stats) -> list[Item]:
    """Split tall, big objects into height bands so each band can get its own
    density and triangle budget (faces are first cut at the band limits)."""
    floors = {room.id: room.z for room in rooms}
    out = []
    for item in items:
        low, high = item.z_range
        if high - low <= TALL_M or item.area < TALL_AREA_M2:
            out.append(item)
            continue
        floor = floors.get(item.room or "", 0.0)
        edges = [floor + edge for edge in BAND_EDGES_M]
        _cut_at_heights(item.obj, [h for h in edges if low < h < high])
        bands = _face_bands(item.obj, edges)
        if len(bands) < 2:
            out.append(item)
            continue
        first = min(bands)
        copies = {band: item.obj if band == first else _copy_object(item.obj) for band in bands}
        for band, faces in bands.items():
            obj = copies[band]
            _keep_faces(obj.data, faces)
            part = _item(obj)
            part.weight = item.weight
            part.room = item.room
            out.append(part)
        stats.far_split += 1
    return out


def _face_bands(obj: bpy.types.Object, edges: list[float]) -> dict[int, np.ndarray]:
    """Face indices per height band (band k lies between edges k-1 and k)."""
    mesh = obj.data
    centres = np.empty(len(mesh.polygons) * 3, dtype=np.float64)
    mesh.polygons.foreach_get("center", centres)
    matrix = np.array(obj.matrix_world, dtype=np.float64)
    z = (centres.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3])[:, 2]
    band = np.searchsorted(np.asarray(edges), z)
    return {int(b): np.flatnonzero(band == b) for b in np.unique(band)}


def _copy_object(obj: bpy.types.Object) -> bpy.types.Object:
    copy = obj.copy()
    copy.data = obj.data.copy()
    for collection in obj.users_collection:
        collection.objects.link(copy)
    return copy


def _cut_at_heights(obj: bpy.types.Object, heights: list[float]) -> None:
    """Cut the object's faces along horizontal world planes (nothing removed)."""
    if not heights:
        return
    inverse = obj.matrix_world.inverted()
    normal = (obj.matrix_world.to_3x3().transposed() @ Vector((0.0, 0.0, 1.0))).normalized()
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    for height in heights:
        geom = [*bm.verts, *bm.edges, *bm.faces]
        bmesh.ops.bisect_plane(
            bm, geom=geom, plane_co=inverse @ Vector((0.0, 0.0, height)), plane_no=normal, dist=1e-5
        )
    bm.to_mesh(obj.data)
    bm.free()


def _keep_faces(mesh: bpy.types.Mesh, keep: np.ndarray) -> None:
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.index_update()
    wanted = {int(i) for i in keep}
    doomed = [face for face in bm.faces if face.index not in wanted]
    bmesh.ops.delete(bm, geom=doomed, context="FACES")
    loose = [vert for vert in bm.verts if not vert.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bm.to_mesh(mesh)
    bm.free()


def _weigh_by_distance(items: list[Item], rooms: list[cook.Room], stats: Stats) -> None:
    """Lower the density of far objects and decimate the far heavy ones."""
    floors = {room.id: room.z for room in rooms}
    for item in items:
        distance = _distance_beyond_eye_band(item, floors.get(item.room or "", 0.0))
        if distance <= 0.0:
            continue
        item.weight *= 1.0 / (1.0 + distance / FAR_FALLOFF_M)
        if distance <= FAR_DECIMATE_M:
            continue
        mesh = item.obj.data
        mesh.calc_loop_triangles()
        before = len(mesh.loop_triangles)
        if before < FAR_MIN_TRIANGLES:
            continue
        ratio = max(FAR_MIN_RATIO, 1.0 / (1.0 + (distance - FAR_DECIMATE_M) / FAR_DECIMATE_RATE_M))
        modifier = item.obj.modifiers.new("RT_far", "DECIMATE")
        modifier.decimate_type = "COLLAPSE"
        modifier.ratio = ratio
        depsgraph = bpy.context.evaluated_depsgraph_get()
        reduced = bpy.data.meshes.new_from_object(
            item.obj.evaluated_get(depsgraph), preserve_all_data_layers=True, depsgraph=depsgraph
        )
        item.obj.modifiers.remove(modifier)
        old = item.obj.data
        item.obj.data = reduced
        bpy.data.meshes.remove(old)
        reduced.calc_loop_triangles()
        stats.far_decimated_triangles += before - len(reduced.loop_triangles)
        refreshed = _item(item.obj)
        item.area, item.centre, item.z_range = refreshed.area, refreshed.centre, refreshed.z_range
    print(
        f"[verse] realtime: {stats.far_split} tall objects split into height bands, "
        f"{stats.far_decimated_triangles} triangles decimated far from the eye band",
        flush=True,
    )


# ---------------------------------------------------------------- visibility

VIEW_GRID_M = 1.2  # eye points on this grid inside every room
VIEW_HEIGHTS_M = (0.9, 1.7, 2.5)  # above the room's floor: a crouch, the head, the camera
VIEW_RAYS = 256


def _unseen(items: list[Item], rooms: list[cook.Room]) -> set[int]:
    """Indices of objects no ray from any eye point in the rooms reaches.

    Eye points sit on a grid inside every room polygon at a few heights; rays
    go out in evenly spread directions and the first surface each hits counts
    as seen. Hull voids behind full walls never are.
    """
    from mathutils.bvhtree import BVHTree

    vertex_chunks, triangle_chunks, owner_chunks, offset = [], [], [], 0
    for index, item in enumerate(items):
        mesh = item.obj.data
        matrix = np.array(item.obj.matrix_world, dtype=np.float64)
        co = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
        mesh.vertices.foreach_get("co", co)
        mesh.calc_loop_triangles()
        tris = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
        mesh.loop_triangles.foreach_get("vertices", tris)
        vertex_chunks.append(co.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3])
        triangle_chunks.append(tris.reshape(-1, 3) + offset)
        owner_chunks.append(np.full(len(tris) // 3, index, dtype=np.int32))
        offset += len(mesh.vertices)
    vertices = np.concatenate(vertex_chunks)
    triangles = np.concatenate(triangle_chunks)
    owner = np.concatenate(owner_chunks)
    tree = BVHTree.FromPolygons(vertices.tolist(), triangles.tolist(), all_triangles=True)
    golden = math.pi * (3.0 - math.sqrt(5.0))
    directions = []
    for k in range(VIEW_RAYS):
        y = 1.0 - 2.0 * (k + 0.5) / VIEW_RAYS
        r = math.sqrt(max(0.0, 1.0 - y * y))
        directions.append(Vector((math.cos(golden * k) * r, math.sin(golden * k) * r, y)))
    seen = np.zeros(len(items), dtype=bool)
    for room in rooms:
        xs = [p[0] for p in room.polygon]
        ys = [p[1] for p in room.polygon]
        gx = np.arange(min(xs) + VIEW_GRID_M / 2, max(xs), VIEW_GRID_M)
        gy = np.arange(min(ys) + VIEW_GRID_M / 2, max(ys), VIEW_GRID_M)
        px, py = np.meshgrid(gx, gy)
        px, py = px.ravel(), py.ravel()
        inside = _points_in_polygon(px, py, room.polygon)
        for x, y in zip(px[inside], py[inside], strict=True):
            for height in VIEW_HEIGHTS_M:
                origin = Vector((float(x), float(y), room.z + height))
                for direction in directions:
                    _, _, index, _ = tree.ray_cast(origin, direction, 200.0)
                    if index is not None:
                        seen[owner[index]] = True
    return {i for i in range(len(items)) if not seen[i]}


# ---------------------------------------------------------------- lightmap UVs


PAGE_FILL = 0.75  # share of a page the skyline packer fills (rectangles of mixed sizes)
# Texels between the islands inside one object: enough for bilinear
# filtering and the first mip levels. Objects of panels and greebles have
# thousands of islands; the full page padding (`margin_px`) on each would
# leave them a few percent of their own rectangle. The rectangles keep the
# full padding from each other.
ISLAND_GAP_TEXELS = 2.5
# Smart UV's island margin (a fraction of the object's own square) never
# exceeds this: an object only a few texels wide keeps its islands touching.
MAX_ISLAND_MARGIN = 0.03
# An object whose islands cover less of its square than this (thousands of
# slivers, all margins) is sized as if they covered this much: it gets fewer
# texels per metre instead of taking a page of margins from everyone else.
MIN_LAYOUT_FILL = 0.3


@dataclass(frozen=True)
class Layout:
    bbox: tuple[float, float, float, float]  # u0, v0, u1, v1 of the object's own layout
    uv_area: float


def _unwrap(items: list[Item], preset: Preset) -> tuple[int, float]:
    """Unwrap every object's LM UVs and pack them into pages.

    Returns (page count, texels per metre at weight 1). Every object gets its
    own Smart UV Project layout with island margins sized for the expected
    density, and goes whole, as one rectangle, onto skyline-packed pages
    (`lightmap.pack_skyline`, room by room). Rectangles are sized by the
    object's weighted area; when they do not fit into `max_pages` pages the
    density steps down until they do.

    (Packing every island of a page with Blender's Pack Islands instead
    wasted most of each page: a decimated shaft wall or a beveled key bank
    has thousands of islands, each paying a full margin, so Pack Islands
    shrank whole pages to 2-18 % coverage.)
    """
    size = preset.page_px
    pad = preset.margin_px + 1
    weighted = sum(item.area * item.weight**2 for item in items)
    estimate = min(
        preset.density, math.sqrt(preset.max_pages * size * size * PAGE_FILL / max(weighted, 1e-9))
    )
    layouts = [_project(item, estimate) for item in items]
    rooms = sorted({item.room or "" for item in items})
    groups = [rooms.index(item.room or "") for item in items]
    density = preset.density
    while True:
        sizes = [_rect(item, layout, density) for item, layout in zip(items, layouts, strict=True)]
        placements = lightmap.pack_skyline(sizes, groups, size, pad)
        pages = max((p.page for p in placements), default=-1) + 1
        if pages <= preset.max_pages:
            break
        density *= 0.97
    used = sum(w * h for w, h in sizes) / (pages * size * size)
    print(
        f"[verse] realtime: {pages} page(s) at {density:.1f} px/m, {len(items)} objects, "
        f"{used:.0%} of the pages in rectangles",
        flush=True,
    )
    for item, layout, (w, h), place in zip(items, layouts, sizes, placements, strict=True):
        item.page = place.page
        _place_layout(item.obj, layout.bbox, w, h, place, size)
    return pages, density


def _rect(item: Item, layout: Layout, density: float) -> tuple[float, float]:
    """Size in texels of an object's whole layout at its weighted density."""
    u0, v0, u1, v1 = layout.bbox
    covered = max(layout.uv_area, MIN_LAYOUT_FILL * (u1 - u0) * (v1 - v0), 1e-12)
    k = density * item.weight * math.sqrt(item.area / covered)
    return (u1 - u0) * k, (v1 - v0) * k


def _place_layout(
    obj: bpy.types.Object,
    bbox: tuple[float, float, float, float],
    w: float,
    h: float,
    place: lightmap.Placement,
    size: int,
) -> None:
    """Move an object's whole layout into its page rectangle."""
    layer = obj.data.uv_layers[UV_NAME]
    uv = np.empty(len(layer.data) * 2, dtype=np.float64)
    layer.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    bw, bh = max(bbox[2] - bbox[0], 1e-9), max(bbox[3] - bbox[1], 1e-9)
    # Blender UV: v grows upward; the packer counts rows from the top.
    u = (place.x + (uv[:, 0] - bbox[0]) / bw * w * place.scale) / size
    top = place.y + h * place.scale
    v = 1.0 - (top - (uv[:, 1] - bbox[1]) / bh * h * place.scale) / size
    layer.data.foreach_set("uv", np.stack([u, v], axis=1).ravel().astype(np.float32))


def _project(item: Item, density: float) -> Layout:
    """Smart UV Project of one object into its own unit square, islands
    `ISLAND_GAP_TEXELS` apart at `density` (Smart UV packs them itself)."""
    obj = item.obj
    mesh = obj.data
    layer = mesh.uv_layers.get(UV_NAME) or mesh.uv_layers.new(name=UV_NAME)
    mesh.uv_layers.active = layer  # an existing render UV map (screens) stays active_render
    expected = math.sqrt(item.area) * density * item.weight  # texels across the square
    margin = min(MAX_ISLAND_MARGIN, ISLAND_GAP_TEXELS / max(expected, 1.0))
    if expected < 8.0 * ISLAND_GAP_TEXELS:
        margin = 0.0  # a few texels wide: islands touch, the rectangle's padding keeps it apart
    _edit_objects([obj])
    try:
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(
            angle_limit=math.radians(66.0),
            margin_method="FRACTION",
            island_margin=margin,
            area_weight=0.0,
            correct_aspect=True,
            scale_to_bounds=False,
        )
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    layer = mesh.uv_layers[UV_NAME]  # edit mode reallocated the layers
    uv = np.empty(len(layer.data) * 2, dtype=np.float64)
    layer.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    mesh.calc_loop_triangles()
    loops = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("loops", loops)
    tri = uv[loops].reshape(-1, 3, 2)
    e1, e2 = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
    area = float(0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]).sum())
    bbox = (
        float(uv[:, 0].min()),
        float(uv[:, 1].min()),
        float(uv[:, 0].max()),
        float(uv[:, 1].max()),
    )
    return Layout(bbox=bbox, uv_area=area)


def _edit_objects(objects: list[bpy.types.Object]) -> None:
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.mode_set(mode="EDIT")


# ---------------------------------------------------------------- join


OBJECT_SPACE_ATTR = "rt_orco"
RANDOM_ATTR = "rt_random"


def _keep_object_space(items: list[Item]) -> None:
    """Store each object's own texture space before the objects are joined.

    The kit's materials read Object coordinates and Object Info > Random;
    joined objects share one space, so the original local coordinates and a
    per-object random go into point attributes the patched materials read
    (`_patch_materials`).
    """
    for index, item in enumerate(items):
        mesh = item.obj.data
        co = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get("co", co)
        orco = mesh.attributes.new(OBJECT_SPACE_ATTR, "FLOAT_VECTOR", "POINT")
        orco.data.foreach_set("vector", co)
        rnd = mesh.attributes.new(RANDOM_ATTR, "FLOAT", "POINT")
        value = ((index * 2654435761) % 4294967296) / 4294967296.0
        rnd.data.foreach_set("value", np.full(len(mesh.vertices), value, dtype=np.float32))


def _join_pages(items: list[Item]) -> list[tuple[int, bpy.types.Object]]:
    """Join each page's objects into one object per set of ray visibility flags.

    Cycles syncs the whole scene for every object it bakes, so a page bakes
    as one or a few objects instead of hundreds.
    """
    groups: dict[tuple, list[bpy.types.Object]] = {}
    for item in items:
        obj = item.obj
        flags = (
            obj.visible_shadow,
            obj.visible_diffuse,
            obj.visible_glossy,
            obj.visible_transmission,
        )
        groups.setdefault((item.page, flags), []).append(obj)
    joined = []
    for (page, _), objects in sorted(groups.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        for obj in bpy.context.view_layer.objects:
            obj.select_set(False)
        for obj in objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = objects[0]
        if len(objects) > 1:
            bpy.ops.object.join()
        target = bpy.context.view_layer.objects.active
        target.name = f"RT_page{page}_{len(joined)}"
        mesh = target.data
        render_uv = mesh.uv_layers.get("UVMap")
        if render_uv is not None:
            render_uv.active_render = True
        mesh.uv_layers.active = mesh.uv_layers[UV_NAME]
        joined.append((page, target))
    return joined


def _patch_materials(materials: set[bpy.types.Material]) -> None:
    """Point Object coordinates and Object Info > Random at the stored
    attributes, and light the plate-only emitters (`light_glossy_emitters`)."""
    light_glossy_emitters(materials)
    for material in materials:
        tree = material.node_tree
        if tree is None:
            continue
        for link in list(tree.links):
            node, socket = link.from_node, link.from_socket.name
            if node.type == "TEX_COORD" and socket == "Object":
                attr = tree.nodes.new("ShaderNodeAttribute")
                attr.attribute_type = "GEOMETRY"
                attr.attribute_name = OBJECT_SPACE_ATTR
                tree.links.new(attr.outputs["Vector"], link.to_socket)
            elif node.type == "OBJECT_INFO" and socket == "Random":
                attr = tree.nodes.new("ShaderNodeAttribute")
                attr.attribute_type = "GEOMETRY"
                attr.attribute_name = RANDOM_ATTR
                tree.links.new(attr.outputs["Fac"], link.to_socket)


def light_glossy_emitters(materials) -> int:
    """Make emitters that only the plate's floor mirror shows visible at eye level.

    Some fixtures emit only for glossy (and camera) rays, so the plate shows
    them in the floor mirror while spot lights do the lighting. The bake, the
    probes and the eye-level camera must see them lit; the room's light must
    not change: "Is Glossy Ray" and "Is Camera Ray" become "not a diffuse
    ray". Returns how many links were rewired.
    """
    count = 0
    for material in materials:
        tree = material.node_tree
        if tree is None:
            continue
        for link in list(tree.links):
            node, socket = link.from_node, link.from_socket.name
            if node.type == "LIGHT_PATH" and socket in ("Is Glossy Ray", "Is Camera Ray"):
                lit = tree.nodes.new("ShaderNodeMath")
                lit.operation = "SUBTRACT"
                lit.inputs[0].default_value = 1.0
                tree.links.new(node.outputs["Is Diffuse Ray"], lit.inputs[1])
                tree.links.new(lit.outputs[0], link.to_socket)
                count += 1
    return count


# ---------------------------------------------------------------- bake


def _bake_page(
    page: int, objects: list[bpy.types.Object], density: float, preset: Preset
) -> np.ndarray:
    """Bake one page; returns its radiance (h, w, 3) float32, gaps filled."""
    size = preset.page_px
    image = bpy.data.images.new(f"LM_bake_{page}", size, size, alpha=True, float_buffer=True)
    image.colorspace_settings.name = "Non-Color"
    materials = {m for obj in objects for m in obj.data.materials if m is not None}
    nodes = []
    for material in materials:
        tree = material.node_tree
        if tree is None:
            continue
        node = tree.nodes.new("ShaderNodeTexImage")
        node.image = image
        node.select = True
        tree.nodes.active = node
        nodes.append((tree, node))
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy_scene = bpy.context.scene
    bake = bpy_scene.render.bake
    bake.target = "IMAGE_TEXTURES"
    bake.use_selected_to_active = False
    saved_samples = bpy_scene.cycles.samples
    margin = preset.margin_px
    try:
        passes = {}
        for name, kind, filters, samples, pad in (
            ("normal", "NORMAL", set(), 1, margin),
            ("position", "POSITION", set(), 1, margin),
            ("albedo", "DIFFUSE", {"COLOR"}, 16, margin),
            ("emit", "EMIT", set(), 16, margin),
            ("irradiance", "DIFFUSE", {"DIRECT", "INDIRECT"}, preset.samples, margin),
        ):
            started = time.monotonic()
            bpy_scene.cycles.samples = samples
            bpy.ops.object.bake(
                type=kind,
                pass_filter=filters,
                uv_layer=UV_NAME,
                margin=pad,
                margin_type="EXTEND",
                use_clear=True,
                normal_space="OBJECT",
                target="IMAGE_TEXTURES",
            )
            pixels = np.empty(size * size * 4, dtype=np.float32)
            image.pixels.foreach_get(pixels)
            passes[name] = pixels.reshape(size, size, 4)[::-1, :, :3].copy()
            print(
                f"[verse] realtime page {page}: {name} {time.monotonic() - started:.1f} s",
                flush=True,
            )
    finally:
        bpy_scene.cycles.samples = saved_samples
        for tree, node in nodes:
            tree.nodes.remove(node)
        bpy.data.images.remove(image)
    guided = np.abs(passes["normal"]).sum(axis=2) > 0.05
    normal = passes.pop("normal") * 2.0 - 1.0
    texel_m = 1.0 / density
    started = time.monotonic()
    irradiance = lightmap.denoise(
        passes.pop("irradiance"),
        normal,
        passes.pop("position"),
        guided,
        texel_m,
        preset.denoise_passes,
    )
    print(f"[verse] realtime page {page}: denoise {time.monotonic() - started:.1f} s", flush=True)
    radiance = passes["albedo"] * irradiance + passes["emit"]
    radiance = np.where(np.isfinite(radiance), np.maximum(radiance, 0.0), 0.0)
    return lightmap.fill_gaps(radiance, guided)


# ---------------------------------------------------------------- probes


def _reflection_probe(room: cook.Room, preset: Preset, out_dir: Path) -> dict:
    """An equirect panorama of the room at eye height and the box it is projected on."""
    position = cook._eye_point(room)
    path = out_dir / f"probe_{room.id}.exr"
    cook._render_panorama(
        bpy.context.scene, position, preset.probe_size, preset.probe_samples, path
    )
    radiance = cook._load_linear_rgb(path)
    path.unlink()
    np.save(out_dir / f"probe_{room.id}.npy", radiance.astype(np.float16))
    xs = [p[0] for p in room.polygon]
    ys = [p[1] for p in room.polygon]
    ceiling = _room_ceiling(room)
    box_min = scene.to_three((min(xs), max(ys), room.z))
    box_max = scene.to_three((max(xs), min(ys), ceiling))
    return {
        "room": room.id,
        "file": f"probe_{room.id}.npy",
        "w": preset.probe_size[0],
        "h": preset.probe_size[1],
        "position": scene.to_three(position),
        "box_min": box_min,
        "box_max": box_max,
    }


def _room_ceiling(room: cook.Room) -> float:
    """Height of the room's ceiling: the median of upward hits over a grid of
    points in the room (one ray at the probe point can find a fixture, a
    gantry or an opening instead)."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    xs = [p[0] for p in room.polygon]
    ys = [p[1] for p in room.polygon]
    gx = np.linspace(min(xs), max(xs), 9)[1:-1]
    gy = np.linspace(min(ys), max(ys), 9)[1:-1]
    px, py = (a.ravel() for a in np.meshgrid(gx, gy))
    inside = _points_in_polygon(px, py, room.polygon)
    heights = []
    for x, y in zip(px[inside], py[inside], strict=True):
        origin = Vector((float(x), float(y), room.z + 1.4))
        hit, location, *_ = bpy.context.scene.ray_cast(depsgraph, origin, Vector((0.0, 0.0, 1.0)))
        if hit:
            heights.append(float(location.z))
    return float(np.median(heights)) if heights else room.z + 4.0


# ---------------------------------------------------------------- geometry


def _export_geometry(
    joined: list[tuple[int, bpy.types.Object]], path: Path, stats: Stats
) -> list[dict]:
    """Group every triangle by (material, room, page) and write the chunks."""
    rooms = cook._rooms()
    corners: dict[tuple[str, str, int], list[tuple[np.ndarray, np.ndarray, np.ndarray]]] = {}
    for page, obj in joined:
        for key, arrays in _object_corners(obj, page, rooms).items():
            corners.setdefault(key, []).append(arrays)
    arrays: dict[str, np.ndarray] = {}
    chunks = []
    for index, key in enumerate(sorted(corners)):
        material, room, page = key
        pos = np.concatenate([c[0] for c in corners[key]])
        nrm = np.concatenate([c[1] for c in corners[key]])
        uv = np.concatenate([c[2] for c in corners[key]])
        vertices, indices = _weld(pos, nrm, uv)
        arrays[f"{index}_pos"] = vertices[:, 0:3].astype(np.float32)
        arrays[f"{index}_nrm"] = vertices[:, 3:6].astype(np.float32)
        arrays[f"{index}_uv"] = vertices[:, 6:8].astype(np.float32)
        arrays[f"{index}_idx"] = indices.astype(np.uint32)
        chunks.append(
            {
                "index": index,
                "material": material,
                "room": room,
                "page": page,
                "vertices": int(len(vertices)),
                "triangles": int(len(indices) // 3),
            }
        )
        stats.vertices += len(vertices)
        stats.triangles += len(indices) // 3
    stats.chunks = len(chunks)
    np.savez(path, **arrays)
    return chunks


def _object_corners(obj: bpy.types.Object, page: int, rooms: list[cook.Room]) -> dict:
    """Per (material, room, page): world positions, normals and LM UVs per triangle corner."""
    mesh = obj.data
    mesh.calc_loop_triangles()
    n = len(mesh.loop_triangles)
    if n == 0:
        return {}
    loops = np.empty(n * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("loops", loops)
    verts = np.empty(n * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", verts)
    mat_index = np.empty(n, dtype=np.int32)
    mesh.loop_triangles.foreach_get("material_index", mat_index)
    co = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    normals = np.empty(len(mesh.loops) * 3, dtype=np.float64)
    mesh.corner_normals.foreach_get("vector", normals)
    uv = np.empty(len(mesh.loops) * 2, dtype=np.float64)
    mesh.uv_layers[UV_NAME].data.foreach_get("uv", uv)
    matrix = np.array(obj.matrix_world, dtype=np.float64)
    linear = matrix[:3, :3]
    normal_matrix = np.linalg.inv(linear).T
    pos = co.reshape(-1, 3)[verts] @ linear.T + matrix[:3, 3]
    nrm = normals.reshape(-1, 3)[loops] @ normal_matrix.T
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
    tex = uv.reshape(-1, 2)[loops]
    # Room per triangle: the side its face looks into.
    tri = pos.reshape(n, 3, 3)
    face_n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    face_n /= np.maximum(np.linalg.norm(face_n, axis=1, keepdims=True), 1e-12)
    probe = tri.mean(axis=1) + face_n * 0.08
    room_of = _rooms_of(probe[:, 0], probe[:, 1], rooms, probe[:, 2])
    names = [_base_name(m.name) if m is not None else "M_Default" for m in mesh.materials]
    out: dict = {}
    for m in np.unique(mat_index):
        material = names[min(int(m), len(names) - 1)] if names else "M_Default"
        for room in np.unique(room_of[mat_index == m]):
            sel = np.repeat((mat_index == m) & (room_of == room), 3)
            key = (material, rooms[int(room)].id, page)
            out[key] = (_to_three(pos[sel]), _to_three(nrm[sel]), tex[sel])
    return out


def _to_three(v: np.ndarray) -> np.ndarray:
    """Blender (x, y, z) -> three.js (x, z, -y)."""
    return np.stack([v[:, 0], v[:, 2], -v[:, 1]], axis=1)


def _rooms_of(
    x: np.ndarray, y: np.ndarray, rooms: list[cook.Room], z: np.ndarray | None = None
) -> np.ndarray:
    """Index of the room containing each point (Blender XYZ); the nearest centre outside.

    A nested room wins over the room around it (smallest first); a room with
    a `ceiling` prop holds only points inside its height band.
    """
    result = np.full(len(x), -1, dtype=np.int32)
    for index in sorted(range(len(rooms)), key=lambda i: rooms[i].area):
        room = rooms[index]
        inside = _points_in_polygon(x, y, room.polygon)
        ceiling = room.props.get("ceiling")
        if z is not None and ceiling is not None:
            low = room.z - cook.ROOM_BAND_BELOW_M
            inside &= (z >= low) & (z <= room.z + float(ceiling))
        result[(result < 0) & inside] = index
    missing = result < 0
    if missing.any():
        centres = np.array([room.centre for room in rooms])
        d = (x[missing, None] - centres[None, :, 0]) ** 2 + (
            y[missing, None] - centres[None, :, 1]
        ) ** 2
        result[missing] = d.argmin(axis=1)
    return result


def _points_in_polygon(x: np.ndarray, y: np.ndarray, polygon) -> np.ndarray:
    inside = np.zeros(len(x), dtype=bool)
    pts = list(polygon)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1], strict=True):
        crosses = (y0 > y) != (y1 > y)
        with np.errstate(divide="ignore", invalid="ignore"):
            at = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
        inside ^= crosses & (x < at)
    return inside


def _weld(pos: np.ndarray, nrm: np.ndarray, uv: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Merge identical corners into shared vertices; returns (vertices (v, 8), indices)."""
    key = np.concatenate(
        [np.round(pos * 1e4), np.round(nrm * 1e3), np.round(uv * 2e6)], axis=1
    ).astype(np.int64)
    _, first, inverse = np.unique(key, axis=0, return_index=True, return_inverse=True)
    vertices = np.concatenate([pos, nrm, uv], axis=1)[first]
    return vertices, inverse.reshape(-1).astype(np.uint32)


# ---------------------------------------------------------------- materials


def _material_json(name: str) -> dict:
    material = MATERIALS.get(name)
    if material is None:
        material = _fallback_material(name)
        print(
            f"[verse] realtime: material {name} is not in MATERIALS; read off its nodes: "
            f"{material}",
            flush=True,
        )
    data = asdict(material)
    data["color"] = [round(c, 4) for c in data["color"]]
    return data


def _fallback_material(name: str) -> RtMaterial:
    """Specular parameters read off the material's nodes: an emission-only
    surface is an emitter, otherwise the Principled BSDF's defaults."""
    material = bpy.data.materials.get(name)
    tree = material.node_tree if material is not None else None
    output = _material_output(tree) if tree is not None else None
    surface = output.inputs["Surface"].links if output is not None else []
    if surface and surface[0].from_node.type == "EMISSION":
        return _EMITTER
    bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if tree else None
    if bsdf is None:
        return RtMaterial()

    def value(socket: str, default: float) -> float:
        inp = bsdf.inputs.get(socket)
        if inp is None or inp.is_linked:
            return default
        v = inp.default_value
        return float(v) if isinstance(v, float) else default

    metal = value("Metallic", 0.0)
    colour = bsdf.inputs["Base Color"].default_value
    transmission = value("Transmission Weight", 0.0)
    return RtMaterial(
        roughness=value("Roughness", 0.5),
        metalness=metal,
        color=(float(colour[0]), float(colour[1]), float(colour[2])) if metal > 0.5 else (0, 0, 0),
        clearcoat=value("Coat Weight", 0.0),
        clearcoat_roughness=value("Coat Roughness", 0.05),
        transparent=transmission > 0.5,
        opacity=0.1 if transmission > 0.5 else 1.0,
        collide=transmission <= 0.5,
    )
