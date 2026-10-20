"""Physically based Cycles material library for the Verse kit.

``get("M_Floor_GlossBlack")`` creates a material once per file and returns it.
Names are stable: deck builders, the kit and the cook refer to them.

Every surface material has three layers of detail so nothing reads as
computer-clean: a macro roughness/value variation (smudges, wear), micro
normal detail (orange peel, scratches), and grime or wear where it physically
collects (crevices via ray-traced AO, convex edges via the Bevel node).

Texture space: no kit mesh has UVs. Surfaces use object-space coordinates
(rotation-proof for instances, real metres at scale 1) offset per instance by
Object Info > Random, so repeated pieces never share the same smudges. Deck
floors use world space instead so plate seams run on one global 1.2 m grid
across every module. CC0 roughness/height maps from Poly Haven (see
``lookdev/fetch_textures.py`` and LICENSES.md) are box-projected at their real
size; when a file is missing the procedural layers carry the detail alone.

Light units. Cycles emission strength is the emitter's radiance in scene
units: at exposure 0 a surface of strength 1 renders with pixel value 1.
Values below are luminance ratios anchored to real fixtures, assuming the
plate exposure maps ~250 cd/m2 to pixel value 1 (``lib.scene`` exposure 0):

==========================  ========  =================================
fixture                     strength  real-world anchor (cd/m2)
==========================  ========  =================================
ceiling diffuser panel      16        LED troffer, ~4 000
wall light strip (opal)     24        linear LED in opal lens, ~6 000
pit / step floor inlay      10        floor wash strip, ~2 500
console screen content      0.8-1.6   monitor at 50 %, ~200-400
indicator lamp              6-10      panel LED behind a lens, ~2 000
maintenance lamp            4         dim service light, ~1 000
star field (inside glass)   0.6-3     points only, background ~0.002
==========================  ========  =================================

The ``VERSE_MATERIAL_QUALITY=preview`` environment variable drops the
ray-traced AO and Bevel nodes for fast interactive work.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import bpy

VERSE_ROOT = Path(__file__).resolve().parents[1]
TEXTURE_CACHE = VERSE_ROOT / ".cache" / "textures"
LIBRARY_VERSION = 11
_PREVIEW = os.environ.get("VERSE_MATERIAL_QUALITY", "final").lower() == "preview"

# Real-world size (metres) of each Poly Haven texture, from its metadata.
TEXTURE_SIZE_M = {
    "blue_metal_plate": 2.5,
    "metal_plate_02": 2.0,
    "green_metal_rust": 1.0,
    "painted_concrete_02": 4.0,
}

_BUILDERS: dict[str, Callable[[_Graph], None]] = {}
_VIEWPORT_COLOUR: dict[str, tuple[float, float, float, float]] = {}

Socket = bpy.types.NodeSocket


def material(name: str, viewport=(0.5, 0.5, 0.5)):
    """Register a material builder under ``name``."""

    def register(fn: Callable[[_Graph], None]):
        _BUILDERS[name] = fn
        _VIEWPORT_COLOUR[name] = (*viewport, 1.0)
        return fn

    return register


def names() -> list[str]:
    return sorted(_BUILDERS)


def get(name: str) -> bpy.types.Material:
    """Return material ``name``, building it on first use in this file."""
    mat = bpy.data.materials.get(name)
    if mat is not None and mat.get("verse_lib") == LIBRARY_VERSION:
        return mat
    builder = _BUILDERS.get(name)
    if builder is None:
        raise KeyError(f"unknown material {name!r}; known: {', '.join(names())}")
    if mat is None:
        mat = bpy.data.materials.new(name)
    graph = _Graph(mat)
    builder(graph)
    mat["verse_lib"] = LIBRARY_VERSION
    mat.diffuse_color = _VIEWPORT_COLOUR[name]
    return mat


def build_all() -> list[bpy.types.Material]:
    return [get(n) for n in names()]


# --------------------------------------------------------------------------
# Node graph helper
# --------------------------------------------------------------------------


class _Graph:
    """Thin wrapper over a material node tree with the operations we use."""

    def __init__(self, mat: bpy.types.Material):
        self.mat = mat
        self.nt = mat.node_tree
        self.nt.nodes.clear()
        self.out = self.new("ShaderNodeOutputMaterial")
        self.out.location = (900, 0)
        self._count = 0
        self._cache: dict[str, Socket] = {}

    # -- plumbing ----------------------------------------------------------

    def new(self, type_: str, inputs: dict | None = None, **attrs):
        node = self.nt.nodes.new(type_)
        self._count = getattr(self, "_count", 0) + 1
        node.location = (-200 * (self._count % 7), -180 * (self._count // 7))
        for key, value in attrs.items():
            setattr(node, key, value)
        for key, value in (inputs or {}).items():
            self.set(node.inputs[key], value)
        return node

    def set(self, sock: Socket, value) -> None:
        if isinstance(value, bpy.types.NodeSocket):
            self.nt.links.new(value, sock)
        elif value is not None:
            if sock.type == "RGBA" and len(value) == 3:
                value = (*value, 1.0)
            sock.default_value = value

    def output(self, shader: Socket) -> None:
        self.set(self.out.inputs["Surface"], shader)

    # -- math --------------------------------------------------------------

    def math(self, op: str, a, b=0.0, c=None, clamp: bool = False) -> Socket:
        node = self.new("ShaderNodeMath", operation=op, use_clamp=clamp)
        self.set(node.inputs[0], a)
        self.set(node.inputs[1], b)
        if c is not None:
            self.set(node.inputs[2], c)
        return node.outputs[0]

    def add(self, *terms) -> Socket:
        acc = terms[0]
        for t in terms[1:]:
            acc = self.math("ADD", acc, t)
        return acc

    def mul(self, a, b) -> Socket:
        return self.math("MULTIPLY", a, b)

    def vmath(self, op: str, a, b=None, scale=None, out: str = "Vector") -> Socket:
        node = self.new("ShaderNodeVectorMath", operation=op)
        self.set(node.inputs[0], a)
        if b is not None:
            self.set(node.inputs[1], b)
        if scale is not None:
            self.set(node.inputs[3], scale)
        return node.outputs[out]

    def remap(self, x, f0, f1, t0=0.0, t1=1.0, smooth: bool = False, clamp: bool = True) -> Socket:
        node = self.new(
            "ShaderNodeMapRange",
            interpolation_type="SMOOTHSTEP" if smooth else "LINEAR",
            clamp=clamp,
        )
        for i, v in enumerate((x, f0, f1, t0, t1)):
            self.set(node.inputs[i], v)
        return node.outputs[0]

    def lerp(self, t, a, b) -> Socket:
        return self.remap(t, 0.0, 1.0, a, b)

    def mix_color(self, t, a, b, blend: str = "MIX") -> Socket:
        node = self.new("ShaderNodeMix", data_type="RGBA", blend_type=blend, clamp_result=False)
        self.set(node.inputs[0], t)
        self.set(node.inputs[6], a)
        self.set(node.inputs[7], b)
        return node.outputs[2]

    def separate(self, vec) -> tuple[Socket, Socket, Socket]:
        node = self.new("ShaderNodeSeparateXYZ")
        self.set(node.inputs[0], vec)
        return node.outputs[0], node.outputs[1], node.outputs[2]

    def combine(self, x=0.0, y=0.0, z=0.0) -> Socket:
        node = self.new("ShaderNodeCombineXYZ")
        for i, v in enumerate((x, y, z)):
            self.set(node.inputs[i], v)
        return node.outputs[0]

    # -- coordinates and textures -----------------------------------------

    def coord(self, space: str = "object", per_instance: bool = True) -> Socket:
        """Texture coordinates in metres: "object" (instance-local) or "world"."""
        key = f"coord:{space}:{per_instance}"
        if key in self._cache:
            return self._cache[key]
        if space == "world":
            co = self.new("ShaderNodeNewGeometry").outputs["Position"]
        else:
            co = self.new("ShaderNodeTexCoord").outputs["Object"]
        if per_instance:
            rnd = self.new("ShaderNodeObjectInfo").outputs["Random"]
            offset = self.vmath("SCALE", (17.31, 31.17, 7.73), scale=self.mul(rnd, 97.0))
            co = self.vmath("ADD", co, offset)
        self._cache[key] = co
        return co

    def noise(self, vec, scale: float, detail: float = 2.0, rough: float = 0.5, distortion=0.0):
        node = self.new(
            "ShaderNodeTexNoise",
            inputs={"Scale": scale, "Detail": detail, "Roughness": rough, "Distortion": distortion},
            noise_dimensions="3D",
        )
        self.set(node.inputs["Vector"], vec)
        return node.outputs["Fac"]

    def white(self, vec) -> Socket:
        node = self.new("ShaderNodeTexWhiteNoise", noise_dimensions="3D")
        self.set(node.inputs["Vector"], vec)
        return node.outputs["Value"]

    def image(self, asset: str, key: str, vec, blend: float = 0.3) -> Socket | None:
        """Box-projected CC0 map (``key`` = "rough" or "disp") at real size."""
        path = _texture_path(asset, key)
        if path is None:
            return None
        img = bpy.data.images.load(str(path), check_existing=True)
        img.colorspace_settings.name = "Non-Color"
        size = TEXTURE_SIZE_M.get(asset, 2.0)
        node = self.new(
            "ShaderNodeTexImage",
            image=img,
            projection="BOX",
            projection_blend=blend,
            interpolation="Cubic" if key == "disp" else "Linear",
        )
        self.set(node.inputs["Vector"], self.vmath("SCALE", vec, scale=1.0 / size))
        return node.outputs["Color"]

    def bump(self, height, strength: float, distance: float, normal=None) -> Socket:
        node = self.new("ShaderNodeBump", inputs={"Strength": strength, "Distance": distance})
        self.set(node.inputs["Height"], height)
        if normal is not None:
            self.set(node.inputs["Normal"], normal)
        return node.outputs["Normal"]

    # -- physically placed wear -------------------------------------------

    def edge_mask(self, radius: float = 0.012, lo: float = 0.02, hi: float = 0.18) -> Socket:
        """~1 on convex/concave edges, 0 on flat faces (Bevel node trick)."""
        if _PREVIEW:
            return self.math("ADD", 0.0, 0.0)
        bev = self.new("ShaderNodeBevel", samples=6, inputs={"Radius": radius})
        geo = self.new("ShaderNodeNewGeometry")
        dot = self.vmath(
            "DOT_PRODUCT", bev.outputs["Normal"], geo.outputs["True Normal"], out="Value"
        )
        return self.remap(self.math("SUBTRACT", 1.0, dot), lo, hi, smooth=True)

    def cavity(self, distance: float = 0.12) -> Socket:
        """~1 in crevices and corners where grime collects (local AO)."""
        if _PREVIEW:
            return self.math("ADD", 0.0, 0.0)
        ao = self.new("ShaderNodeAmbientOcclusion", samples=8, only_local=True)
        self.set(ao.inputs["Distance"], distance)
        return self.remap(ao.outputs["AO"], 0.95, 0.35, smooth=True)

    # -- shaders -----------------------------------------------------------

    def principled(self, **inputs) -> bpy.types.Node:
        node = self.new("ShaderNodeBsdfPrincipled")
        for key, value in inputs.items():
            self.set(node.inputs[key.replace("_", " ")], value)
        return node

    def blackbody(self, kelvin: float) -> Socket:
        return self.new("ShaderNodeBlackbody", inputs={"Temperature": kelvin}).outputs["Color"]


def _set_emission_sampling(mat: bpy.types.Material, mode: str) -> None:
    """ "FRONT" lets the light tree sample a fixture; "NONE" keeps faint or
    tiny emitters (screens, keys, stars) out of light sampling."""
    settings = getattr(mat, "cycles", None)
    if settings is not None and hasattr(settings, "emission_sampling"):
        settings.emission_sampling = mode


def _texture_path(asset: str, key: str) -> Path | None:
    folder = TEXTURE_CACHE / asset
    if not folder.is_dir():
        return None
    for candidate in sorted(folder.glob(f"{asset}_{key}_*")):
        if candidate.suffix.lower() in (".jpg", ".png", ".exr"):
            return candidate
    return None


# --------------------------------------------------------------------------
# Shared recipes
# --------------------------------------------------------------------------


def _scratches(g: _Graph, co, contrast=(0.42, 0.72)) -> Socket:
    """0..1 scratch/scuff mask from a real scratched-steel roughness scan."""
    img = g.image("blue_metal_plate", "rough", co)
    if img is None:
        img = g.noise(co, 22.0, detail=8, rough=0.7, distortion=0.6)
    return g.remap(img, contrast[0], contrast[1], smooth=True)


def _painted_metal(
    g: _Graph,
    color: tuple[float, float, float],
    *,
    rough: tuple[float, float] = (0.34, 0.48),
    chip_to: tuple[float, float, float] | None = (0.42, 0.42, 0.43),
    chip: float = 0.35,
    grime: float = 0.45,
    scratch: float = 0.5,
    sheen_coat: float = 0.0,
    macro_scale: float = 0.55,
    space: str = "object",
    extra_height=None,
) -> bpy.types.Node:
    """Satin paint on steel: smudges, scratches, chipped edges, crevice grime."""
    co = g.coord(space)
    macro = g.noise(co, macro_scale, detail=4, rough=0.6)
    blotch = g.noise(co, 3.1, detail=3, rough=0.55)
    scr = _scratches(g, co)
    cav = g.cavity()
    edge = g.edge_mask()
    chip_noise = g.remap(g.noise(co, 9.0, detail=6, rough=0.75), 0.48, 0.62, smooth=True)
    chip_mask = g.mul(g.mul(edge, chip_noise), chip)

    island = g.new("ShaderNodeNewGeometry").outputs["Random Per Island"]
    shade = g.add(0.84, g.mul(macro, 0.16), g.mul(blotch, 0.05), g.mul(island, 0.12))
    base = g.mix_color(shade, (0, 0, 0), color)
    base = g.mix_color(g.mul(cav, grime), base, g.mix_color(0.55, base, (0.012, 0.011, 0.01)))
    if chip_to is not None:
        base = g.mix_color(chip_mask, base, chip_to)

    rough_v = g.add(
        g.lerp(macro, rough[0], rough[1]),
        g.mul(scr, 0.16 * scratch),
        g.mul(cav, 0.18 * grime),
        g.mul(island, 0.08),
        -0.04,
    )
    if chip_to is not None:
        rough_v = g.lerp(chip_mask, rough_v, 0.24)
    metal = chip_mask if chip_to is not None else 0.0

    height = g.add(
        g.mul(g.noise(co, 140.0, detail=2, rough=0.5), 0.25),
        g.mul(scr, -0.4 * scratch),
        g.mul(chip_mask, -1.2),
    )
    disp = g.image("blue_metal_plate", "disp", co)
    if disp is not None:
        height = g.add(height, g.mul(disp, 0.5))
    if extra_height is not None:
        height = g.add(height, extra_height)
    normal = g.bump(height, 0.06, 0.002)

    bsdf = g.principled(
        Base_Color=base,
        Roughness=rough_v,
        Metallic=metal,
        Normal=normal,
        Coat_Weight=sheen_coat,
        Coat_Roughness=0.12,
    )
    g.output(bsdf.outputs[0])
    return bsdf


def _bare_metal(
    g: _Graph,
    color: tuple[float, float, float],
    *,
    rough: tuple[float, float] = (0.28, 0.42),
    polish_edges: float = 0.5,
    grime: float = 0.5,
    texture: str = "metal_plate_02",
    texture_weight: float = 0.35,
    brushed_axis: str | None = None,
    space: str = "object",
) -> bpy.types.Node:
    """Raw or blued steel: tool marks, polished edges, oily crevices."""
    co = g.coord(space)
    macro = g.noise(co, 0.8, detail=4, rough=0.6)
    scan = g.image(texture, "rough", co)
    scan = g.remap(scan, 0.2, 0.8) if scan is not None else g.noise(co, 12.0, detail=6)
    cav = g.cavity(0.1)
    edge = g.edge_mask(0.01)

    island = g.new("ShaderNodeNewGeometry").outputs["Random Per Island"]
    shade = g.add(0.8, g.mul(macro, 0.22), g.mul(island, 0.1))
    base = g.mix_color(shade, (0, 0, 0), color)
    base = g.mix_color(g.mul(edge, polish_edges), base, g.mix_color(0.5, color, (0.75, 0.75, 0.76)))
    base = g.mix_color(g.mul(cav, grime), base, g.mix_color(0.7, base, (0.01, 0.01, 0.009)))
    rough_v = g.add(
        g.lerp(macro, rough[0], rough[1]),
        g.mul(scan, texture_weight * 0.3),
        g.mul(cav, 0.2 * grime),
        g.mul(edge, -0.12 * polish_edges),
    )
    if brushed_axis:
        stretch = {"X": (0.4, 90.0, 90.0), "Y": (90.0, 0.4, 90.0), "Z": (90.0, 90.0, 0.4)}
        streak_co = g.vmath("MULTIPLY", co, stretch[brushed_axis])
        streaks = g.noise(streak_co, 1.0, detail=3, rough=0.6)
        height = g.mul(streaks, 0.6)
        rough_v = g.add(rough_v, g.mul(streaks, 0.08))
    else:
        height = g.mul(g.noise(co, 90.0, detail=3), 0.2)
    disp = g.image(texture, "disp", co)
    if disp is not None:
        height = g.add(height, g.mul(disp, 0.6 * texture_weight))
    bsdf = g.principled(
        Base_Color=base,
        Metallic=1.0,
        Roughness=rough_v,
        Normal=g.bump(height, 0.05, 0.002),
    )
    g.output(bsdf.outputs[0])
    return bsdf


def _emitter(
    g: _Graph,
    strength: float,
    *,
    kelvin: float | None = 6200.0,
    color: tuple[float, float, float] | None = None,
    falloff: float = 0.06,
    sampling: str = "FRONT",
) -> None:
    """Diffuser or lamp face: a fixture, never a glowing line for its own sake."""
    co = g.coord("object")
    unevenness = g.remap(g.noise(co, 1.7, detail=2), 0.3, 0.7, 1.0 - falloff, 1.0)
    tint = g.blackbody(kelvin) if color is None else color
    node = g.new("ShaderNodeEmission")
    g.set(node.inputs["Color"], tint)
    g.set(node.inputs["Strength"], g.mul(unevenness, strength))
    g.output(node.outputs[0])
    _set_emission_sampling(g.mat, sampling)


def _lamp(g: _Graph, color, strength: float) -> None:
    """Indicator lamp: emissive core behind a glossy lens."""
    bsdf = g.principled(
        Base_Color=(0.02, 0.02, 0.02),
        Roughness=0.25,
        Coat_Weight=1.0,
        Coat_Roughness=0.02,
        Emission_Color=color,
        Emission_Strength=strength,
    )
    g.output(bsdf.outputs[0])
    _set_emission_sampling(g.mat, "NONE")


# --------------------------------------------------------------------------
# Floors
# --------------------------------------------------------------------------

PLATE_X = 2.4  # deck plate length along the ship (m)
PLATE_Y = 1.2  # deck plate width across the ship (m)


def _plate_fields(g: _Graph, plate_x: float = PLATE_X, plate_y: float = PLATE_Y):
    """World-space deck-plate layout: seam mask, bolt mask, per-plate random."""
    pos = g.coord("world", per_instance=False)
    x, y, _ = g.separate(pos)
    u, v = g.math("DIVIDE", x, plate_x), g.math("DIVIDE", y, plate_y)
    fu, fv = g.math("FRACT", u), g.math("FRACT", v)
    du = g.mul(g.math("MINIMUM", fu, g.math("SUBTRACT", 1.0, fu)), plate_x)
    dv = g.mul(g.math("MINIMUM", fv, g.math("SUBTRACT", 1.0, fv)), plate_y)
    seam_d = g.math("MINIMUM", du, dv)
    seam = g.remap(seam_d, 0.0018, 0.0032, 1.0, 0.0, smooth=True)
    bevel_band = g.remap(seam_d, 0.0035, 0.0075, 1.0, 0.0, smooth=True)
    bx, by = (
        g.math("ABSOLUTE", g.math("SUBTRACT", du, 0.05)),
        g.math("ABSOLUTE", g.math("SUBTRACT", dv, 0.05)),
    )
    bolt_r = g.vmath("LENGTH", g.combine(bx, by, 0.0), out="Value")
    bolt = g.remap(bolt_r, 0.0075, 0.0095, 1.0, 0.0, smooth=True)
    cell = g.combine(g.math("FLOOR", u), g.math("FLOOR", v), 0.0)
    rnd = g.white(cell)
    return pos, seam, bevel_band, bolt, rnd


@material("M_Floor_GlossBlack", viewport=(0.02, 0.02, 0.022))
def _floor_gloss_black(g: _Graph) -> None:
    """Polished black deck plating (ART_DIRECTION 3 and "no clipped
    reflections"): one lacquer coat carries the reflection (~4.5 % at the
    camera's 30 degrees from the normal, so a 16-strength ceiling panel
    mirrors at ~0.7 scene-linear, inside AgX's gradient range rather than on
    its shoulder). Coat roughness 0.035-0.2 varies with smudges, wipe marks
    and micro-scratches, so every reflection has soft streaks and falls off
    at its edges and blurs more the farther the source is above the deck.
    The base under it is near-black with a faint broad sheen (a halo, not a
    second mirror). Plate seams are fine satin-steel joint strips."""
    pos, seam, bevel_band, bolt, rnd = _plate_fields(g)
    smudge = g.remap(g.noise(pos, 0.7, detail=6, rough=0.62), 0.42, 0.78, smooth=True)
    wipe_co = g.vmath("MULTIPLY", pos, (1.0, 7.0, 1.0))
    wipe = g.remap(g.noise(wipe_co, 2.2, detail=4, rough=0.5), 0.52, 0.76)
    streak = g.noise(g.vmath("MULTIPLY", pos, (0.6, 9.0, 1.0)), 3.0, detail=3)
    scuff = _scratches(g, pos, contrast=(0.55, 0.85))
    joint = g.math("MAXIMUM", seam, bolt)
    dust = g.mul(g.cavity(0.35), g.remap(g.noise(pos, 6.0, detail=4), 0.35, 0.65))

    tint = g.add(0.85, g.mul(rnd, 0.3))
    base = g.mix_color(tint, (0, 0, 0), (0.0085, 0.009, 0.01))
    base = g.mix_color(g.mul(dust, 0.6), base, (0.03, 0.03, 0.029))
    base = g.mix_color(joint, base, (0.2, 0.2, 0.205))

    rough = g.add(0.3, g.mul(smudge, 0.1), g.mul(dust, 0.2))
    rough = g.lerp(joint, rough, 0.32)
    film = g.math("MAXIMUM", g.mul(smudge, 0.85), g.mul(wipe, 0.75))
    coat_rough = g.add(
        0.035,
        g.mul(rnd, 0.015),
        g.mul(smudge, 0.05),
        g.mul(wipe, 0.07),
        g.mul(scuff, 0.07),
        g.mul(dust, 0.25),
    )
    # A greasy film both blurs and dims the mirror: 0.6-1.0 of the clean coat.
    coat = g.mul(g.lerp(joint, 1.0, 0.0), g.lerp(film, 1.0, 0.6))

    height = g.add(
        g.mul(bevel_band, -0.6),
        g.mul(bolt, 0.3),
        g.mul(g.noise(pos, 60.0, detail=2), 0.02),
        g.mul(scuff, -0.04),
    )
    normal = g.bump(height, 0.3, 0.003)
    coat_height = g.add(
        g.mul(streak, 0.5), g.mul(g.noise(pos, 7.0, detail=2), 0.2), g.mul(scuff, -0.3)
    )
    coat_normal = g.bump(coat_height, 0.03, 0.002)
    bsdf = g.principled(
        Base_Color=base,
        Roughness=rough,
        Metallic=joint,
        Specular_IOR_Level=g.lerp(joint, 0.12, 0.5),
        Normal=normal,
        Coat_Weight=coat,
        Coat_Roughness=coat_rough,
        Coat_Normal=coat_normal,
    )
    g.output(bsdf.outputs[0])


@material("M_Floor_SatinDark", viewport=(0.05, 0.05, 0.055))
def _floor_satin_dark(g: _Graph) -> None:
    """Secondary decks (hangar, engineering): dark grey plate, less mirror."""
    pos, seam, bevel_band, bolt, rnd = _plate_fields(g)
    smudge = g.remap(g.noise(pos, 0.35, detail=5, rough=0.62), 0.3, 0.75, smooth=True)
    scuff = _scratches(g, pos, contrast=(0.45, 0.75))
    base = g.mix_color(g.add(0.82, g.mul(rnd, 0.36)), (0, 0, 0), (0.035, 0.036, 0.039))
    base = g.mix_color(g.mul(scuff, 0.5), base, (0.07, 0.07, 0.072))
    base = g.mix_color(seam, base, (0.004, 0.004, 0.004))
    rough = g.add(0.22, g.mul(smudge, 0.16), g.mul(scuff, 0.14), g.mul(seam, 0.4))
    normal = g.bump(g.add(g.mul(bevel_band, -1.0), g.mul(bolt, 0.35)), 0.35, 0.003)
    bsdf = g.principled(
        Base_Color=base,
        Roughness=rough,
        Metallic=g.mul(bolt, 1.0),
        Normal=normal,
        Coat_Weight=g.lerp(smudge, 0.5, 0.2),
        Coat_Roughness=0.06,
    )
    g.output(bsdf.outputs[0])


@material("M_Floor_Grating", viewport=(0.2, 0.2, 0.21))
def _floor_grating(g: _Graph) -> None:
    """Galvanised steel bar grating: dull zinc, boot-polished top edges."""
    _bare_metal(
        g,
        (0.32, 0.33, 0.34),
        rough=(0.38, 0.55),
        polish_edges=0.8,
        grime=0.8,
        texture="metal_plate_02",
        texture_weight=0.5,
    )


# --------------------------------------------------------------------------
# Walls, structure, trims
# --------------------------------------------------------------------------


@material("M_Wall_PaintedLight", viewport=(0.45, 0.46, 0.47))
def _wall_painted_light(g: _Graph) -> None:
    """Light-grey semi-gloss panelling, #9EA3A8 (secondary wall finish)."""
    _painted_metal(
        g,
        (0.342, 0.366, 0.392),
        rough=(0.22, 0.34),
        chip=0.18,
        grime=0.5,
        scratch=0.45,
        sheen_coat=0.2,
    )


@material("M_Wall_PaintedMid", viewport=(0.22, 0.23, 0.24))
def _wall_painted_mid(g: _Graph) -> None:
    """Mid grey for upper panels, ceilings seen in reflections and soffits."""
    _painted_metal(g, (0.17, 0.175, 0.18), rough=(0.34, 0.48), chip=0.15, grime=0.45)


@material("M_Wall_PaintedDark", viewport=(0.06, 0.065, 0.07))
def _wall_painted_dark(g: _Graph) -> None:
    """Dark wall panelling, kick plates, door leaves."""
    _painted_metal(
        g, (0.045, 0.047, 0.05), rough=(0.32, 0.46), chip_to=(0.3, 0.3, 0.31), chip=0.3, grime=0.3
    )


@material("M_Wall_Charcoal", viewport=(0.035, 0.036, 0.04))
def _wall_charcoal(g: _Graph) -> None:
    """Hero wall panelling (ART_DIRECTION 2): charcoal semi-gloss enamel."""
    _painted_metal(
        g,
        (0.03, 0.031, 0.034),
        rough=(0.26, 0.38),
        chip_to=(0.28, 0.28, 0.29),
        chip=0.15,
        grime=0.35,
        scratch=0.6,
        sheen_coat=0.25,
    )


@material("M_Struct_Gunmetal", viewport=(0.16, 0.165, 0.17))
def _struct_gunmetal(g: _Graph) -> None:
    """Blued structural steel: frames, ribs, pillars, door frames."""
    _bare_metal(g, (0.16, 0.165, 0.175), rough=(0.3, 0.46), polish_edges=0.45, grime=0.55)


@material("M_Trim_BrushedSteel", viewport=(0.6, 0.6, 0.62))
def _trim_brushed(g: _Graph) -> None:
    """Brushed stainless trims and rails (grain along the piece's X)."""
    _bare_metal(
        g,
        (0.56, 0.565, 0.575),
        rough=(0.18, 0.26),
        polish_edges=0.3,
        grime=0.35,
        texture_weight=0.15,
        brushed_axis="X",
    )


@material("M_Trim_Chrome", viewport=(0.85, 0.85, 0.87))
def _trim_chrome(g: _Graph) -> None:
    """Polished chrome accents: handrails, door tracks."""
    co = g.coord()
    smudge = g.remap(g.noise(co, 2.0, detail=4), 0.4, 0.75, smooth=True)
    bsdf = g.principled(
        Base_Color=(0.82, 0.83, 0.84),
        Metallic=1.0,
        Roughness=g.add(0.04, g.mul(smudge, 0.1)),
    )
    g.output(bsdf.outputs[0])


@material("M_Rubber_Black", viewport=(0.025, 0.025, 0.025))
def _rubber_black(g: _Graph) -> None:
    """Matte black rubber: seals, door gaskets, cable jackets, step nosing."""
    co = g.coord()
    macro = g.noise(co, 1.5, detail=3)
    bsdf = g.principled(
        Base_Color=g.mix_color(g.add(0.8, g.mul(macro, 0.4)), (0, 0, 0), (0.022, 0.022, 0.023)),
        Roughness=g.lerp(macro, 0.62, 0.82),
        Specular_IOR_Level=0.35,
        Normal=g.bump(g.noise(co, 220.0, detail=2), 0.15, 0.001),
    )
    g.output(bsdf.outputs[0])


@material("M_Recess_Dark", viewport=(0.015, 0.015, 0.016))
def _recess_dark(g: _Graph) -> None:
    """Shadow gap and recess backs: near-black matte."""
    bsdf = g.principled(Base_Color=(0.012, 0.012, 0.013), Roughness=0.7)
    g.output(bsdf.outputs[0])


@material("M_Section_Cap", viewport=(0.07, 0.07, 0.075))
def _section_cap(g: _Graph) -> None:
    """Cut face of a sectioned wall (BRIEF section 5): dark steel with faint
    45-degree hatching. A cut plane is a drawing convention, not a lit
    surface (caps at ceiling height get no light at all), so it carries a
    faint constant poche tone (emission 0.035, not sampled as a light) on
    top of normal shading, and never reads as a hole."""
    pos = g.coord("world", per_instance=False)
    x, y, _ = g.separate(pos)
    diag = g.math("FRACT", g.math("DIVIDE", g.add(x, y), 0.06))
    line = g.remap(g.math("ABSOLUTE", g.math("SUBTRACT", diag, 0.5)), 0.44, 0.47, 0.0, 1.0)
    macro = g.noise(pos, 1.3, detail=3)
    base = g.mix_color(line, (0.05, 0.051, 0.055), (0.085, 0.086, 0.09))
    base = g.mix_color(g.mul(macro, 0.25), base, (0.0, 0.0, 0.0))
    poche = g.add(0.03, g.mul(line, 0.025))
    bsdf = g.principled(
        Base_Color=base,
        Metallic=0.3,
        Roughness=g.add(0.5, g.mul(macro, 0.1)),
        Normal=g.bump(g.mul(line, 0.3), 0.08, 0.001),
        Emission_Color=(0.8, 0.82, 0.85),
        Emission_Strength=poche,
    )
    g.output(bsdf.outputs[0])
    _set_emission_sampling(g.mat, "NONE")


@material("M_Ceiling_Panel", viewport=(0.12, 0.12, 0.125))
def _ceiling_panel(g: _Graph) -> None:
    """Ceiling plating: only ever seen mirrored in the floor."""
    _painted_metal(g, (0.09, 0.092, 0.095), rough=(0.4, 0.55), chip=0.0, chip_to=None, grime=0.3)


# --------------------------------------------------------------------------
# Lights (fixtures)
# --------------------------------------------------------------------------


@material("M_Light_CeilingPanel", viewport=(1.0, 1.0, 1.0))
def _light_ceiling_panel(g: _Graph) -> None:
    """Ceiling diffuser panel, 6 200 K (see the module table for units)."""
    _emitter(g, 16.0, kelvin=6200.0)


@material("M_Light_WallStrip", viewport=(1.0, 1.0, 1.0))
def _light_wall_strip(g: _Graph) -> None:
    """Recessed opal light strip in wall panelling, 6 000 K."""
    _emitter(g, 24.0, kelvin=6000.0, falloff=0.04)


@material("M_Light_Backlit", viewport=(0.95, 0.97, 1.0))
def _light_backlit(g: _Graph) -> None:
    """Backlit opal rectangles stacked in wall light columns, 6 500 K.
    Each rectangle (object instance) varies a few percent, as real tubes do."""
    rnd = g.new("ShaderNodeObjectInfo").outputs["Random"]
    co = g.coord("object")
    cell = g.white(g.vmath("FLOOR", g.vmath("SCALE", co, scale=8.0)))
    vary = g.add(0.9, g.mul(cell, 0.12), g.mul(rnd, 0.06))
    node = g.new("ShaderNodeEmission")
    g.set(node.inputs["Color"], g.blackbody(6500.0))
    g.set(node.inputs["Strength"], g.mul(vary, 9.0))
    g.output(node.outputs[0])
    _set_emission_sampling(g.mat, "FRONT")


@material("M_Light_RedTrim", viewport=(0.9, 0.05, 0.04))
def _light_red_trim(g: _Graph) -> None:
    """Thin red light trim on console tops and step edges (accent only)."""
    _emitter(g, 5.0, kelvin=None, color=(1.0, 0.035, 0.03), falloff=0.08, sampling="NONE")


@material("M_Light_FloorInlay", viewport=(0.95, 0.95, 1.0))
def _light_floor_inlay(g: _Graph) -> None:
    """Walkway edge / pit step inlay strip, 6 500 K."""
    _emitter(g, 10.0, kelvin=6500.0, falloff=0.05)


@material("M_Light_Maint_Red", viewport=(0.8, 0.05, 0.03))
def _light_maint_red(g: _Graph) -> None:
    """Dim red service lamp in hull structure."""
    _emitter(g, 4.0, kelvin=None, color=(1.0, 0.06, 0.025), sampling="AUTO")


@material("M_Light_Maint_Amber", viewport=(0.9, 0.45, 0.1))
def _light_maint_amber(g: _Graph) -> None:
    """Dim amber service lamp in hull structure."""
    _emitter(g, 4.0, kelvin=None, color=(1.0, 0.42, 0.08), sampling="AUTO")


@material("M_Indicator_Red", viewport=(1.0, 0.05, 0.03))
def _ind_red(g: _Graph) -> None:
    _lamp(g, (1.0, 0.045, 0.02), 9.0)


@material("M_Indicator_Green", viewport=(0.1, 1.0, 0.2))
def _ind_green(g: _Graph) -> None:
    _lamp(g, (0.12, 1.0, 0.22), 7.0)


@material("M_Indicator_Amber", viewport=(1.0, 0.45, 0.05))
def _ind_amber(g: _Graph) -> None:
    _lamp(g, (1.0, 0.38, 0.04), 8.0)


@material("M_Indicator_Blue", viewport=(0.15, 0.4, 1.0))
def _ind_blue(g: _Graph) -> None:
    _lamp(g, (0.12, 0.35, 1.0), 8.0)


@material("M_Indicator_White", viewport=(1.0, 1.0, 1.0))
def _ind_white(g: _Graph) -> None:
    _lamp(g, (1.0, 0.97, 0.92), 6.0)


# --------------------------------------------------------------------------
# Consoles, screens, glass
# --------------------------------------------------------------------------


@material("M_Console_Body", viewport=(0.05, 0.052, 0.055))
def _console_body(g: _Graph) -> None:
    """Dark satin console carcass; worn to steel on the corners hands touch."""
    _painted_metal(
        g,
        (0.04, 0.042, 0.046),
        rough=(0.3, 0.42),
        chip_to=(0.35, 0.35, 0.36),
        chip=0.45,
        grime=0.35,
        sheen_coat=0.15,
    )


@material("M_Console_Deck", viewport=(0.16, 0.165, 0.17))
def _console_deck(g: _Graph) -> None:
    """Mid-grey control deck surface around screens and keys."""
    _painted_metal(g, (0.13, 0.135, 0.14), rough=(0.36, 0.5), chip=0.25, grime=0.55, scratch=0.7)


@material("M_Console_Keys", viewport=(0.05, 0.05, 0.055))
def _console_keys(g: _Graph) -> None:
    """Key banks (ART_DIRECTION 7): dark caps in a grid; lit keys come in
    small groups, mostly cool white, rarely red, most of the bank dark."""
    co = g.coord()
    x, y, z = g.separate(co)
    v = g.add(y, z)
    kx, ky = 0.034, 0.022
    gx = g.math("FRACT", g.math("DIVIDE", x, kx))
    gy = g.math("FRACT", g.math("DIVIDE", v, ky))
    gap = g.math(
        "MAXIMUM",
        g.remap(g.math("ABSOLUTE", g.math("SUBTRACT", gx, 0.5)), 0.38, 0.44),
        g.remap(g.math("ABSOLUTE", g.math("SUBTRACT", gy, 0.5)), 0.32, 0.4),
    )
    cell = g.combine(
        g.math("FLOOR", g.math("DIVIDE", x, kx)), g.math("FLOOR", g.math("DIVIDE", v, ky))
    )
    group = g.combine(
        g.math("FLOOR", g.math("DIVIDE", x, kx * 3)), g.math("FLOOR", g.math("DIVIDE", v, ky * 2))
    )
    group_on = g.remap(g.white(group), 0.7, 0.71)
    key_on = g.mul(group_on, g.remap(g.white(cell), 0.25, 0.26))
    red = g.remap(g.white(g.vmath("ADD", group, (5.3, 1.1, 0.0))), 0.86, 0.87)
    lit_col = g.mix_color(red, (0.85, 0.9, 1.0), (1.0, 0.06, 0.04))
    bsdf = g.principled(
        Base_Color=g.mix_color(gap, (0.035, 0.036, 0.04), (0.004, 0.004, 0.004)),
        Roughness=g.lerp(gap, 0.35, 0.7),
        Emission_Color=lit_col,
        Emission_Strength=g.mul(g.mul(key_on, g.math("SUBTRACT", 1.0, gap)), 1.6),
        Normal=g.bump(g.mul(gap, -1.0), 0.4, 0.0015),
    )
    g.output(bsdf.outputs[0])
    _set_emission_sampling(g.mat, "NONE")


@material("M_Screen", viewport=(0.05, 0.12, 0.14))
def _screen(g: _Graph) -> None:
    """Console screen: dark backlit readouts under a glossy glass face.

    Content is deliberately quiet (the runtime overlays live screens on the
    SOCKET_screen_* planes); it reads as "on" without stealing the frame.
    """
    co = g.coord()
    x, y, z = g.separate(co)
    vert = g.add(y, z)  # screens stand in local XZ or lie in local XY
    rows = g.math("FRACT", g.math("DIVIDE", vert, 0.018))
    row_id = g.math("FLOOR", g.math("DIVIDE", vert, 0.018))
    line_len = g.white(g.combine(row_id, 1.7, 0.0))
    xr = g.math("FRACT", g.math("DIVIDE", g.add(x, 1.0), 0.6))
    text = g.mul(
        g.remap(g.math("ABSOLUTE", g.math("SUBTRACT", rows, 0.5)), 0.2, 0.12),
        g.math("LESS_THAN", xr, g.lerp(line_len, 0.15, 0.85)),
    )
    blocks = g.remap(g.noise(g.vmath("MULTIPLY", co, (6.0, 14.0, 14.0)), 1.0, detail=0), 0.62, 0.66)
    glow = g.add(0.05, g.mul(text, 0.8), g.mul(blocks, 0.18))
    accent = g.remap(g.white(g.combine(row_id, 9.1, 0.0)), 0.9, 0.91)
    tint = g.mix_color(accent, (0.22, 0.62, 0.72), (1.0, 0.2, 0.1))
    bsdf = g.principled(
        Base_Color=(0.004, 0.005, 0.006),
        Roughness=0.3,
        Coat_Weight=1.0,
        Coat_Roughness=g.add(0.015, g.mul(g.noise(co, 4.0, detail=3), 0.04)),
        Emission_Color=tint,
        Emission_Strength=g.mul(glow, 1.4),
    )
    g.output(bsdf.outputs[0])
    _set_emission_sampling(g.mat, "NONE")


@material("M_Glass_Viewport", viewport=(0.6, 0.65, 0.7))
def _glass_viewport(g: _Graph) -> None:
    """Thick viewport glazing modelled as one thin surface: Fresnel-weighted
    reflection over a slightly blue-grey transmission."""
    fres = g.new("ShaderNodeFresnel", inputs={"IOR": 1.52}).outputs[0]
    co = g.coord()
    smear = g.remap(g.noise(co, 1.2, detail=4), 0.45, 0.75, smooth=True)
    glossy = g.new("ShaderNodeBsdfGlossy", inputs={"Color": (1, 1, 1)})
    g.set(glossy.inputs["Roughness"], g.add(0.01, g.mul(smear, 0.04)))
    clear = g.new("ShaderNodeBsdfTransparent", inputs={"Color": (0.86, 0.9, 0.93)})
    mix = g.new("ShaderNodeMixShader")
    g.set(mix.inputs[0], g.add(fres, 0.02))
    g.set(mix.inputs[1], clear.outputs[0])
    g.set(mix.inputs[2], glossy.outputs[0])
    g.output(mix.outputs[0])


@material("M_Starfield", viewport=(0.0, 0.0, 0.01))
def _starfield(g: _Graph) -> None:
    """Dim star field on a plane behind viewport glass (never outside the hull)."""
    co = g.coord(per_instance=False)
    vor = g.new("ShaderNodeTexVoronoi", inputs={"Scale": 7.0, "Randomness": 1.0})
    g.set(vor.inputs["Vector"], co)
    star = g.remap(vor.outputs["Distance"], 0.05, 0.0, smooth=True)
    mag = g.math("POWER", g.white(vor.outputs["Position"]), 6.0)
    vor2 = g.new("ShaderNodeTexVoronoi", inputs={"Scale": 31.0, "Randomness": 1.0})
    g.set(vor2.inputs["Vector"], co)
    dust = g.mul(g.remap(vor2.outputs["Distance"], 0.03, 0.0, smooth=True), 0.25)
    neb = g.remap(g.noise(co, 0.12, detail=6, rough=0.65), 0.5, 0.8, smooth=True)
    strength = g.add(g.mul(star, g.add(0.6, g.mul(mag, 6.0))), dust, g.mul(neb, 0.02), 0.002)
    em = g.new("ShaderNodeEmission")
    g.set(em.inputs["Color"], g.mix_color(neb, (0.82, 0.88, 1.0), (0.75, 0.8, 1.0)))
    g.set(em.inputs["Strength"], strength)
    g.output(em.outputs[0])
    _set_emission_sampling(g.mat, "NONE")


# --------------------------------------------------------------------------
# Markings, crates, seats
# --------------------------------------------------------------------------


def paint_wear(g: _Graph, pos, amount: float = 1.0) -> tuple[Socket, Socket, Socket]:
    """Wear of floor paint that holds up at full plate density (5 mm pixels).

    Returns ``(keep, scuff, grime)``:

    * ``keep`` is 1 where the paint is intact and 0 where it is worn through,
      with an edge about one plate pixel wide, so wear reads as chipped and
      flaked patches with ragged edges. Never use a soft threshold here: a
      half-transparent paint layer over a dark deck renders as grey clouds.
    * ``scuff`` (0..1) marks fine scratches and boot scuffs, mostly along X,
      that darken and roughen the paint without removing it.
    * ``grime`` (0..1) is a faint broad dirt film for a slight tonal drift.

    Wear clusters: a broad zone noise moves the flake threshold, so some
    stretches of a line are almost pristine and others are well worn.
    ``amount`` scales how much paint is worn through (1 = deck traffic).
    """
    zone = g.remap(g.noise(pos, 0.35, detail=2, rough=0.5), 0.38, 0.62, smooth=True)
    flake = g.noise(pos, 6.0, detail=7, rough=0.62, distortion=0.3)
    threshold = g.lerp(zone, 0.74, 0.74 - 0.13 * amount)
    keep = g.remap(flake, g.math("SUBTRACT", threshold, 0.006), threshold, 1.0, 0.0)
    streak_co = g.vmath("MULTIPLY", pos, (1.0, 16.0, 16.0))
    streak = g.remap(g.noise(streak_co, 5.0, detail=3, rough=0.55), 0.7, 0.74)
    scan = g.image("blue_metal_plate", "rough", pos)
    if scan is not None:
        scratch = g.remap(scan, 0.4, 0.47)
    else:
        scratch = g.remap(g.noise(pos, 40.0, detail=6, rough=0.7), 0.7, 0.74)
    scuff = g.math("MAXIMUM", g.mul(streak, g.mul(zone, 0.8)), g.mul(scratch, 0.7))
    grime = g.remap(g.noise(pos, 1.2, detail=3, rough=0.5), 0.4, 0.7, smooth=True)
    return keep, scuff, grime


def _worn_paint(g: _Graph, color_a, color_b=None, stripe_m: float = 0.0) -> None:
    """Floor paint on a decal quad; worn-through chips reveal the deck."""
    pos = g.coord("world", per_instance=False)
    paint = color_a
    if color_b is not None and stripe_m > 0:
        x, y, _ = g.separate(pos)
        stripe = g.math(
            "GREATER_THAN", g.math("FRACT", g.math("DIVIDE", g.add(x, y), stripe_m)), 0.5
        )
        paint = g.mix_color(stripe, color_a, color_b)
    keep, scuff, grime = paint_wear(g, pos)
    paint = g.mix_color(g.add(g.mul(scuff, 0.45), g.mul(grime, 0.12)), paint, (0.03, 0.03, 0.03))
    bsdf = g.principled(
        Base_Color=paint,
        Roughness=g.add(0.45, g.mul(scuff, 0.2), g.mul(grime, 0.08)),
        Normal=g.bump(g.mul(scuff, -0.3), 0.1, 0.001),
    )
    clear = g.new("ShaderNodeBsdfTransparent")
    mix = g.new("ShaderNodeMixShader")
    g.set(mix.inputs[0], keep)
    g.set(mix.inputs[1], clear.outputs[0])
    g.set(mix.inputs[2], bsdf.outputs[0])
    g.output(mix.outputs[0])


@material("M_Deck_Marking_White", viewport=(0.6, 0.6, 0.58))
def _marking_white(g: _Graph) -> None:
    """Worn white deck paint: lane lines, landing marks, bay numbers."""
    _worn_paint(g, (0.55, 0.55, 0.53))


@material("M_Deck_Hazard", viewport=(0.5, 0.35, 0.02))
def _marking_hazard(g: _Graph) -> None:
    """Worn yellow/black hazard chevrons at edges, lifts and blast doors."""
    _worn_paint(g, (0.32, 0.2, 0.012), (0.015, 0.015, 0.015), stripe_m=0.2)


@material("M_Crate_Paint", viewport=(0.1, 0.1, 0.105))
def _crate_paint(g: _Graph) -> None:
    """Cargo crate enamel: dark fleet grey, chipped to steel on the corners."""
    _painted_metal(
        g, (0.075, 0.078, 0.082), rough=(0.38, 0.55), chip_to=(0.4, 0.4, 0.41), chip=0.8, grime=0.7
    )


@material("M_Seat_Upholstery", viewport=(0.02, 0.02, 0.022))
def _seat_upholstery(g: _Graph) -> None:
    """Black synthetic leather of crew seats."""
    co = g.coord()
    grain = g.noise(co, 380.0, detail=2)
    wear = g.remap(g.noise(co, 4.0, detail=3), 0.55, 0.75, smooth=True)
    bsdf = g.principled(
        Base_Color=g.mix_color(wear, (0.016, 0.016, 0.017), (0.04, 0.04, 0.042)),
        Roughness=g.add(g.lerp(wear, 0.42, 0.3), g.mul(grain, 0.1)),
        Sheen_Weight=0.15,
        Normal=g.bump(grain, 0.2, 0.0008),
    )
    g.output(bsdf.outputs[0])


# --------------------------------------------------------------------------
# Furniture finishes (shared with the props kits)
# --------------------------------------------------------------------------


@material("M_Lacquer_BlackGloss", viewport=(0.012, 0.012, 0.013))
def _lacquer_black_gloss(g: _Graph) -> None:
    """Piano-black lacquer for table tops: mirror coat over a black base,
    faint wipe marks and fingerprints in the coat roughness."""
    co = g.coord()
    smudge = g.remap(g.noise(co, 3.0, detail=5, rough=0.6), 0.55, 0.8, smooth=True)
    prints = g.remap(g.noise(co, 18.0, detail=3), 0.6, 0.75, smooth=True)
    bsdf = g.principled(
        Base_Color=(0.009, 0.009, 0.01),
        Roughness=g.add(0.05, g.mul(smudge, 0.05)),
        Coat_Weight=1.0,
        Coat_Roughness=g.add(0.01, g.mul(smudge, 0.03), g.mul(prints, 0.05)),
    )
    g.output(bsdf.outputs[0])


@material("M_Plastic_BlackSatin", viewport=(0.015, 0.015, 0.016))
def _plastic_black_satin(g: _Graph) -> None:
    """Moulded black satin plastic: bezels, keyboards, chair shells."""
    co = g.coord()
    macro = g.noise(co, 2.0, detail=3)
    bsdf = g.principled(
        Base_Color=g.mix_color(g.add(0.85, g.mul(macro, 0.3)), (0, 0, 0), (0.014, 0.014, 0.015)),
        Roughness=g.lerp(macro, 0.42, 0.54),
        Normal=g.bump(g.noise(co, 300.0, detail=2), 0.08, 0.0005),
    )
    g.output(bsdf.outputs[0])


@material("M_Plastic_LampOff", viewport=(0.06, 0.06, 0.062))
def _plastic_lamp_off(g: _Graph) -> None:
    """Unlit key caps and lamp lenses: smoked grey, glossy."""
    bsdf = g.principled(Base_Color=(0.055, 0.056, 0.06), Roughness=0.25, Coat_Weight=0.5)
    g.output(bsdf.outputs[0])


@material("M_Plastic_MedWhite", viewport=(0.4, 0.4, 0.4))
def _plastic_med_white(g: _Graph) -> None:
    """Off-white medical plastic (beds, cabinets)."""
    co = g.coord()
    grime = g.cavity(0.08)
    bsdf = g.principled(
        Base_Color=g.mix_color(g.mul(grime, 0.4), (0.4, 0.4, 0.39), (0.2, 0.2, 0.19)),
        Roughness=g.lerp(g.noise(co, 2.5, detail=3), 0.3, 0.42),
    )
    g.output(bsdf.outputs[0])


@material("M_Fabric_BunkGrey", viewport=(0.12, 0.12, 0.125))
def _fabric_bunk_grey(g: _Graph) -> None:
    """Grey wool-mix blanket and mattress cover."""
    co = g.coord()
    weave = g.noise(co, 900.0, detail=1)
    bsdf = g.principled(
        Base_Color=g.mix_color(g.noise(co, 3.0, detail=3), (0.1, 0.1, 0.105), (0.14, 0.14, 0.145)),
        Roughness=0.9,
        Sheen_Weight=0.4,
        Normal=g.bump(weave, 0.2, 0.0006),
    )
    g.output(bsdf.outputs[0])


@material("M_Paint_TrimRed", viewport=(0.3, 0.02, 0.02))
def _paint_trim_red(g: _Graph) -> None:
    """Deep signal-red enamel for thin console-top trims (unlit variant;
    the lit trim is M_Light_RedTrim)."""
    _painted_metal(g, (0.28, 0.012, 0.01), rough=(0.25, 0.35), chip_to=(0.3, 0.3, 0.31), chip=0.2)


@material("M_Emit_BacklitPanel", viewport=(0.9, 0.9, 0.85))
def _emit_backlit_panel(g: _Graph) -> None:
    """Instrument diffuser slats on consoles: dimmer than the wall columns."""
    _emitter(g, 2.6, kelvin=5600.0, falloff=0.1, sampling="NONE")


@material("M_Glass_Clear", viewport=(0.7, 0.75, 0.78))
def _glass_clear(g: _Graph) -> None:
    """Clear partition / display-case glass as one thin surface."""
    fres = g.new("ShaderNodeFresnel", inputs={"IOR": 1.52}).outputs[0]
    co = g.coord()
    smear = g.remap(g.noise(co, 2.0, detail=4), 0.5, 0.8, smooth=True)
    glossy = g.new("ShaderNodeBsdfGlossy", inputs={"Color": (1, 1, 1)})
    g.set(glossy.inputs["Roughness"], g.add(0.005, g.mul(smear, 0.03)))
    clear = g.new("ShaderNodeBsdfTransparent", inputs={"Color": (0.93, 0.96, 0.96)})
    mix = g.new("ShaderNodeMixShader")
    g.set(mix.inputs[0], g.add(fres, 0.01))
    g.set(mix.inputs[1], clear.outputs[0])
    g.set(mix.inputs[2], glossy.outputs[0])
    g.output(mix.outputs[0])


# --------------------------------------------------------------------------
# Hull structure (outside the rooms)
# --------------------------------------------------------------------------


@material("M_Hull_Structure", viewport=(0.03, 0.032, 0.035))
def _hull_structure(g: _Graph) -> None:
    """Dark, oily, functional frames and machinery between the rooms."""
    co = g.coord()
    scan = g.image("metal_plate_02", "rough", co)
    scan = g.remap(scan, 0.15, 0.85) if scan is not None else g.noise(co, 8.0, detail=6)
    oil = g.remap(g.noise(co, 0.9, detail=5, rough=0.65), 0.52, 0.66, smooth=True)
    cav = g.cavity(0.25)
    edge = g.edge_mask(0.015)
    base = g.mix_color(g.add(0.75, g.mul(scan, 0.5)), (0, 0, 0), (0.066, 0.072, 0.082))
    base = g.mix_color(g.mul(edge, 0.6), base, (0.14, 0.14, 0.145))
    base = g.mix_color(g.mul(cav, 0.8), base, (0.006, 0.006, 0.005))
    rough = g.add(g.lerp(scan, 0.35, 0.65), g.mul(oil, -0.25), g.mul(edge, -0.1))
    bsdf = g.principled(
        Base_Color=base,
        Metallic=g.lerp(g.math("MAXIMUM", oil, edge), 0.55, 0.95),
        Roughness=rough,
        Coat_Weight=g.mul(oil, 0.6),
        Coat_Roughness=0.08,
        Normal=g.bump(g.mul(scan, 0.5), 0.08, 0.002),
    )
    g.output(bsdf.outputs[0])


@material("M_Hull_Pipe", viewport=(0.06, 0.062, 0.065))
def _hull_pipe(g: _Graph) -> None:
    """Painted service pipes in hull voids."""
    _painted_metal(
        g, (0.05, 0.052, 0.056), rough=(0.32, 0.5), chip_to=(0.25, 0.25, 0.26), chip=0.6, grime=0.8
    )


@material("M_Hull_PipeInsulated", viewport=(0.18, 0.18, 0.17))
def _hull_pipe_insulated(g: _Graph) -> None:
    """Lagged coolant line: dull grey jacket, grimy."""
    _painted_metal(g, (0.13, 0.13, 0.125), rough=(0.6, 0.78), chip_to=None, grime=0.9, scratch=0.2)
