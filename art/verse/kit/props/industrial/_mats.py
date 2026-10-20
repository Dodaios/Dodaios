"""Material roles of the industrial props, with temporary local fallbacks.

Builders never hard-code a material name. They ask for a *role* with
:func:`m` ("gunmetal", "hull_paint", "core_hot", ...). A role resolves to the
kit material owned by kit-artist (``lib/materials.py``) when that material
exists, and otherwise to a clearly named temporary material
``M_TMP_PropsInd_<Role>`` built here, so the props render today and switch to
the shared library automatically as it grows.

Only materials that are specific to these props (reactor core, containment
field, haze, hull paint, stencils...) are meant to stay local for long; the
general ones (gunmetal, painted panels, floor) are placeholders.
"""

from __future__ import annotations

import os

import bpy

# Crevice grime and edge wear use the Cycles AO node (extra rays per shade).
USE_AO = os.environ.get("VERSE_PI_NO_AO") != "1"
AO_SAMPLES = int(os.environ.get("VERSE_PI_AO_SAMPLES", "4"))

# role -> kit material names to try first (kit-artist's library), in order.
PREFERRED: dict[str, tuple[str, ...]] = {
    "gunmetal": ("M_Struct_Gunmetal",),
    "dark_steel": ("M_Hull_Structure",),
    "panel_light": ("M_Wall_PaintedLight",),
    "panel_dark": ("M_Wall_PaintedDark",),
    "floor": ("M_Floor_GlossBlack",),
    "floor_engineering": ("M_Floor_SatinDark",),
    "grating": ("M_Floor_Grating",),
    "tread": ("M_Metal_TreadPlate",),
    "hull_paint": ("M_Hull_PaintWhite",),
    "container_charcoal": ("M_Crate_Paint",),
    "container_gunmetal": ("M_Container_Paint_Gunmetal",),
    "container_olive": ("M_Container_Paint_Olive",),
    "container_grey": ("M_Container_Paint_Grey",),
    "stencil_white": ("M_Deck_Marking_White",),
    "stencil_red": ("M_Deck_Marking_Red",),
    "stencil_amber": ("M_Deck_Marking_Amber",),
    "stencil_dark": ("M_Deck_Marking_Dark",),
    "hazard": ("M_Deck_Hazard",),
    "rubber": ("M_Rubber_Black",),
    "insulation": ("M_Hull_PipeInsulated",),
    "glass_dark": ("M_Glass_Canopy",),
    "core_hot": ("M_Reactor_CoreHot",),
    "field_blue": ("M_Reactor_ContainmentField",),
    "haze": ("M_Haze_Volume",),
    "lamp_white": ("M_Indicator_White",),
    "lamp_flood": ("M_Light_Flood",),
    "lamp_dim": ("M_Light_DimCold",),
    "lamp_band": ("M_Light_WallStrip",),
    "lamp_maint_red": ("M_Light_Maint_Red",),
    "lamp_warm": ("M_Light_Warm",),
    "lamp_red": ("M_Indicator_Red",),
    "lamp_green": ("M_Indicator_Green",),
    "lamp_amber": ("M_Indicator_Amber",),
    "void_black": ("M_Recess_Dark",),
    "cabin_glow": ("M_Light_CabinWarm",),
    "screen_dim": ("M_Screen",),
    "section_cap": ("M_Section_Cap",),
}

TMP_PREFIX = "M_TMP_PropsInd_"


def m(role: str) -> str:
    """Material name for ``role``: the kit's own if it exists, else a temp one."""
    for name in PREFERRED.get(role, ()):
        if _kit_has(name):
            return name
    return _tmp(role)


def _kit_has(name: str) -> bool:
    try:
        from lib import materials
    except ImportError:
        return False
    has = getattr(materials, "has", None)
    if callable(has):
        return bool(has(name))
    listed = getattr(materials, "names", None)
    if callable(listed):
        return name in listed()
    names = getattr(materials, "NAMES", None) or getattr(materials, "REGISTRY", None)
    if names is not None:
        return name in names
    return False


def _tmp(role: str) -> str:
    name = TMP_PREFIX + "".join(part.capitalize() for part in role.split("_"))
    if name not in bpy.data.materials:
        builder = _BUILDERS.get(role)
        if builder is None:
            raise KeyError(f"no temporary material for role {role!r}")
        mat = bpy.data.materials.new(name)
        builder(_Nodes(mat))
    return name


# --------------------------------------------------------------------------
# Small node-graph helper
# --------------------------------------------------------------------------


class _Nodes:
    def __init__(self, mat: bpy.types.Material):
        self.mat = mat
        try:
            mat.use_nodes = True
        except AttributeError:  # always on in newer Blender
            pass
        self.nt = mat.node_tree
        self.nt.nodes.clear()
        self.out = self.nt.nodes.new("ShaderNodeOutputMaterial")
        self.out.target = "ALL"

    def new(self, kind: str, **props):
        node = self.nt.nodes.new(kind)
        for key, value in props.items():
            setattr(node, key, value)
        return node

    def link(self, a, b):
        self.nt.links.new(a, b)

    @staticmethod
    def sock(node, identifier: str, *, output: bool = False):
        sockets = node.outputs if output else node.inputs
        for s in sockets:
            if s.identifier == identifier or s.name == identifier:
                return s
        raise KeyError(f"{node.bl_idname} has no socket {identifier!r}")

    def set(self, node, **values):
        for key, value in values.items():
            self.sock(node, key.replace("_", " ")).default_value = value
        return node

    # -- common sub-graphs ------------------------------------------------

    def coord(self, kind: str = "Object"):
        tc = self.new("ShaderNodeTexCoord")
        return self.sock(tc, kind, output=True)

    def noise(self, scale, detail=4.0, roughness=0.55, vector=None, dims="3D"):
        n = self.new("ShaderNodeTexNoise")
        n.noise_dimensions = dims
        self.set(n, Scale=scale, Detail=detail, Roughness=roughness)
        self.link(vector or self.coord(), n.inputs["Vector"])
        return n.outputs["Fac"]

    def map_range(self, value, a, b, c, d):
        mr = self.new("ShaderNodeMapRange")
        mr.clamp = True
        self.link(value, mr.inputs["Value"])
        mr.inputs["From Min"].default_value = a
        mr.inputs["From Max"].default_value = b
        mr.inputs["To Min"].default_value = c
        mr.inputs["To Max"].default_value = d
        return mr.outputs["Result"]

    def math(self, op, a, b=None, c=None):
        node = self.new("ShaderNodeMath", operation=op)
        node.use_clamp = False
        for i, v in enumerate((a, b, c)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                node.inputs[i].default_value = v
            else:
                self.link(v, node.inputs[i])
        return node.outputs[0]

    def mix_color(self, fac, a, b):
        node = self.new("ShaderNodeMix", data_type="RGBA")
        node.clamp_factor = True
        for ident, v in (("Factor_Float", fac), ("A_Color", a), ("B_Color", b)):
            s = self.sock(node, ident)
            if isinstance(v, (int, float, tuple)):
                s.default_value = v if not isinstance(v, tuple) else (*v[:3], 1.0)
            else:
                self.link(v, s)
        return self.sock(node, "Result_Color", output=True)

    def mul_color(self, color, factor):
        node = self.new("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
        self.sock(node, "Factor_Float").default_value = 1.0
        for ident, v in (("A_Color", color), ("B_Color", factor)):
            s = self.sock(node, ident)
            if isinstance(v, tuple):
                s.default_value = (*v[:3], 1.0)
            else:
                self.link(v, s)
        return self.sock(node, "Result_Color", output=True)

    def ao(self, distance=0.25, inside=False):
        if not USE_AO:
            v = self.new("ShaderNodeValue")
            v.outputs[0].default_value = 1.0
            return v.outputs[0]
        node = self.new(
            "ShaderNodeAmbientOcclusion", inside=inside, only_local=True, samples=AO_SAMPLES
        )
        node.inputs["Distance"].default_value = distance
        return node.outputs["AO"]

    def principled(self, color, roughness, metallic=0.0, **extra):
        bsdf = self.new("ShaderNodeBsdfPrincipled")
        for key, value in dict(
            {"Base Color": color, "Roughness": roughness, "Metallic": metallic}, **extra
        ).items():
            s = bsdf.inputs[key]
            if isinstance(value, (int, float)):
                s.default_value = value
            elif isinstance(value, tuple):
                s.default_value = (*value[:3], 1.0) if len(s.default_value) == 4 else value
            else:
                self.link(value, s)
        return bsdf

    def bump(self, height, strength=0.2, distance=0.01):
        b = self.new("ShaderNodeBump")
        b.inputs["Strength"].default_value = strength
        b.inputs["Distance"].default_value = distance
        self.link(height, b.inputs["Height"])
        return b.outputs["Normal"]

    def surface(self, shader_socket):
        self.link(shader_socket, self.out.inputs["Surface"])


# --------------------------------------------------------------------------
# Worn surfaces
# --------------------------------------------------------------------------


def _worn(
    nb: _Nodes,
    base,
    rough=(0.32, 0.55),
    metallic=0.0,
    grime=0.55,
    scale=1.0,
    edge_wear=None,
    streaks=False,
    bump=0.08,
):
    """Painted/bare surface with roughness breakup, crevice grime and
    optional edge wear (exposing ``edge_wear`` coloured metal)."""
    big = nb.noise(0.35 * scale, detail=3.0)
    fine = nb.noise(9.0 * scale, detail=6.0, roughness=0.65)
    rough_mix = nb.math("MULTIPLY_ADD", big, 0.6, fine)
    r = nb.map_range(rough_mix, 0.45, 1.15, rough[0], rough[1])
    # every separate plate/part (mesh island) gets its own tone and sheen
    geo = nb.new("ShaderNodeNewGeometry")
    island = nb.sock(geo, "Random Per Island", output=True)
    r = nb.math("ADD", r, nb.map_range(island, 0.0, 1.0, -0.07, 0.07))
    color = nb.mul_color(base, nb.map_range(island, 0.0, 1.0, 0.72, 1.22))

    occl = nb.ao(0.35)
    grime_mask = nb.map_range(occl, 0.35, 0.95, grime, 0.0)
    color = nb.mix_color(grime_mask, color, (0.02, 0.018, 0.016))
    if streaks:
        sv = nb.new("ShaderNodeMapping")
        sv.inputs["Scale"].default_value = (5.0 * scale, 5.0 * scale, 0.35 * scale)
        nb.link(nb.coord(), sv.inputs["Vector"])
        streak = nb.noise(1.0, detail=2.0, vector=sv.outputs["Vector"])
        smask = nb.map_range(streak, 0.5, 0.75, 0.0, 0.22)
        color = nb.mix_color(smask, color, (0.05, 0.045, 0.04))
    met = metallic
    if edge_wear is not None and USE_AO:
        # convex edges: where a bevelled shading normal leaves the true normal
        bev = nb.new("ShaderNodeBevel", samples=4)
        bev.inputs["Radius"].default_value = 0.015
        dot = nb.new("ShaderNodeVectorMath", operation="DOT_PRODUCT")
        nb.link(bev.outputs["Normal"], dot.inputs[0])
        nb.link(nb.sock(geo, "Normal", output=True), dot.inputs[1])
        edge = nb.map_range(nb.sock(dot, "Value", output=True), 0.96, 0.995, 1.0, 0.0)
        chip = nb.noise(14.0 * scale, detail=5.0, roughness=0.7)
        e = nb.math("MULTIPLY", edge, nb.map_range(chip, 0.42, 0.6, 0.0, 1.0))
        color = nb.mix_color(e, color, edge_wear)
        r = nb.math("ADD", r, nb.math("MULTIPLY", e, -0.15))
        met = nb.map_range(e, 0.0, 1.0, metallic, 1.0)
    normal = nb.bump(fine, strength=bump, distance=0.004)
    bsdf = nb.principled(color, r, met, Normal=normal)
    nb.surface(bsdf.outputs["BSDF"])
    return bsdf


def _gunmetal(nb):
    _worn(nb, (0.085, 0.09, 0.1), rough=(0.36, 0.62), metallic=0.9, grime=0.6)


def _dark_steel(nb):
    _worn(nb, (0.07, 0.072, 0.078), rough=(0.38, 0.6), metallic=0.85, grime=0.4)


def _panel_light(nb):
    _worn(nb, (0.42, 0.43, 0.44), rough=(0.32, 0.5), grime=0.5, edge_wear=(0.3, 0.31, 0.32))


def _panel_dark(nb):
    _worn(nb, (0.075, 0.078, 0.085), rough=(0.35, 0.55), grime=0.35, edge_wear=(0.25, 0.26, 0.27))


def _hull_paint(nb):
    _worn(
        nb,
        (0.36, 0.365, 0.36),
        rough=(0.32, 0.55),
        grime=0.6,
        streaks=True,
        edge_wear=(0.28, 0.29, 0.3),
        scale=0.6,
    )


def _container(color):
    def build(nb):
        _worn(nb, color, rough=(0.42, 0.68), grime=0.55, streaks=True, edge_wear=(0.22, 0.2, 0.18))

    return build


def _rubber(nb):
    _worn(nb, (0.018, 0.018, 0.019), rough=(0.5, 0.72), grime=0.2, bump=0.15)


def _insulation(nb):
    _worn(nb, (0.36, 0.36, 0.34), rough=(0.7, 0.9), grime=0.6, streaks=True, bump=0.3)


def _floor(nb):
    """Lookdev stand-in for the deck floor: polished black plates, 1.2 m seams."""
    co = nb.coord()
    sep = nb.new("ShaderNodeSeparateXYZ")
    nb.link(co, sep.inputs[0])
    seams = []
    for axis in ("X", "Y"):
        f = nb.math("FRACT", nb.math("DIVIDE", sep.outputs[axis], 1.2))
        d = nb.math("MINIMUM", f, nb.math("SUBTRACT", 1.0, f))
        seams.append(nb.math("LESS_THAN", d, 0.004))
    seam = nb.math("MAXIMUM", *seams)
    smudge = nb.noise(0.6, detail=5.0)
    r = nb.map_range(smudge, 0.35, 0.75, 0.06, 0.2)
    r = nb.math("MAXIMUM", r, nb.math("MULTIPLY", seam, 0.6))
    color = nb.mix_color(seam, (0.012, 0.012, 0.014), (0.002, 0.002, 0.002))
    bsdf = nb.principled(color, r, 0.0)
    nb.surface(bsdf.outputs["BSDF"])


def _grating(nb):
    """Catwalk plate: dark steel with a 5 cm bar grating read (no alpha)."""
    co = nb.coord()
    sep = nb.new("ShaderNodeSeparateXYZ")
    nb.link(co, sep.inputs[0])
    fx = nb.math("FRACT", nb.math("DIVIDE", sep.outputs["X"], 0.04))
    fy = nb.math("FRACT", nb.math("DIVIDE", sep.outputs["Y"], 0.12))
    bar_x = nb.math("LESS_THAN", fx, 0.28)
    bar_y = nb.math("LESS_THAN", fy, 0.1)
    bars = nb.math("MAXIMUM", bar_x, bar_y)
    wear = nb.noise(3.0, detail=4.0)
    base = nb.mix_color(bars, (0.004, 0.004, 0.005), (0.16, 0.165, 0.17))
    base = nb.mix_color(nb.map_range(wear, 0.55, 0.8, 0.0, 0.5), base, (0.3, 0.3, 0.3))
    r = nb.map_range(wear, 0.3, 0.8, 0.5, 0.3)
    normal = nb.bump(bars, strength=0.6, distance=0.01)
    bsdf = nb.principled(base, r, 0.9, Normal=normal)
    nb.surface(bsdf.outputs["BSDF"])


def _stencil(color):
    """Painted marking with worn-through patches (alpha) and dirt."""

    def build(nb):
        wear = nb.noise(6.0, detail=6.0, roughness=0.7)
        big = nb.noise(0.8, detail=3.0)
        alpha = nb.math(
            "MULTIPLY",
            nb.map_range(wear, 0.38, 0.52, 0.0, 1.0),
            nb.map_range(big, 0.3, 0.5, 0.55, 1.0),
        )
        dirt = nb.map_range(big, 0.4, 0.7, 0.0, 0.35)
        col = nb.mix_color(dirt, color, (0.05, 0.05, 0.05))
        bsdf = nb.principled(col, 0.62, 0.0, Alpha=alpha)
        nb.surface(bsdf.outputs["BSDF"])

    return build


def _hazard(nb):
    """Worn amber/black diagonal stripes, 0.2 m pitch, along object X+Z."""
    co = nb.coord()
    sep = nb.new("ShaderNodeSeparateXYZ")
    nb.link(co, sep.inputs[0])
    diag = nb.math("ADD", sep.outputs["X"], nb.math("ADD", sep.outputs["Y"], sep.outputs["Z"]))
    stripe = nb.math("LESS_THAN", nb.math("FRACT", nb.math("DIVIDE", diag, 0.4)), 0.5)
    wear = nb.noise(5.0, detail=6.0)
    worn = nb.math("MULTIPLY", stripe, nb.map_range(wear, 0.35, 0.5, 0.0, 1.0))
    col = nb.mix_color(worn, (0.02, 0.02, 0.02), (0.42, 0.3, 0.05))
    bsdf = nb.principled(col, nb.map_range(wear, 0.3, 0.7, 0.4, 0.65), 0.0)
    nb.surface(bsdf.outputs["BSDF"])


def _tread(nb):
    """Worn diamond tread plate: dark steel, raised lozenges polished by boots."""
    co = nb.coord()
    sep = nb.new("ShaderNodeSeparateXYZ")
    nb.link(co, sep.inputs[0])
    u = nb.math("ADD", sep.outputs["X"], sep.outputs["Y"])
    v = nb.math("SUBTRACT", sep.outputs["X"], sep.outputs["Y"])
    lozenge = []
    for axis, pitch in ((u, 0.05), (v, 0.05)):
        f = nb.math("FRACT", nb.math("DIVIDE", axis, pitch))
        lozenge.append(nb.math("ABSOLUTE", nb.math("SUBTRACT", f, 0.5)))
    d = nb.math("ADD", *lozenge)
    raised = nb.math("LESS_THAN", d, 0.28)
    wear = nb.noise(1.5, detail=5.0)
    polish = nb.math("MULTIPLY", raised, nb.map_range(wear, 0.35, 0.7, 0.0, 1.0))
    base = nb.mix_color(polish, (0.035, 0.037, 0.04), (0.16, 0.165, 0.17))
    occl = nb.ao(0.3)
    base = nb.mix_color(nb.map_range(occl, 0.4, 0.95, 0.6, 0.0), base, (0.01, 0.01, 0.01))
    rough = nb.map_range(polish, 0.0, 1.0, 0.55, 0.28)
    normal = nb.bump(raised, strength=0.35, distance=0.003)
    bsdf = nb.principled(base, rough, 0.85, Normal=normal)
    nb.surface(bsdf.outputs["BSDF"])


def _glass_dark(nb):
    bsdf = nb.principled((0.004, 0.005, 0.006), 0.04, 0.0, **{"Coat Weight": 0.6})
    nb.surface(bsdf.outputs["BSDF"])


def _emit(color=None, kelvin=None, strength=10.0):
    def build(nb):
        em = nb.new("ShaderNodeEmission")
        if kelvin is not None:
            bb = nb.new("ShaderNodeBlackbody")
            bb.inputs["Temperature"].default_value = kelvin
            nb.link(bb.outputs[0], em.inputs["Color"])
        else:
            em.inputs["Color"].default_value = (*color, 1.0)
        em.inputs["Strength"].default_value = strength
        nb.surface(em.outputs[0])

    return build


def _core_hot(nb):
    """Hot plasma column: whiter and brighter where it faces the viewer, oranger
    toward the limb (limb darkening), with slow vertical turbulence."""
    lw = nb.new("ShaderNodeLayerWeight")
    lw.inputs["Blend"].default_value = 0.35
    facing = nb.sock(lw, "Facing", output=True)
    centre = nb.math("SUBTRACT", 1.0, facing)
    mapping = nb.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (1.2, 1.2, 0.12)
    nb.link(nb.coord(), mapping.inputs["Vector"])
    flicker = nb.noise(1.0, detail=6.0, roughness=0.6, vector=mapping.outputs["Vector"])
    heat = nb.math("MULTIPLY", centre, nb.map_range(flicker, 0.3, 0.7, 0.75, 1.15))
    temp = nb.map_range(heat, 0.0, 1.0, 1900.0, 4300.0)
    bb = nb.new("ShaderNodeBlackbody")
    nb.link(temp, bb.inputs["Temperature"])
    strength = nb.map_range(heat, 0.0, 1.0, 0.25, 3.2)
    value = nb.new("ShaderNodeValue")
    value.name = value.label = "Strength"
    value.outputs[0].default_value = 1.0
    em = nb.new("ShaderNodeEmission")
    nb.link(bb.outputs[0], em.inputs["Color"])
    nb.link(nb.math("MULTIPLY", strength, value.outputs[0]), em.inputs["Strength"])
    nb.surface(em.outputs[0])


def _field_blue(nb):
    """Containment field over a launch opening: a faint translucent sheen.

    Object coordinates of the field mesh (centred on the opening, half-size
    ``FIELD_HALF``) give the distance to the rim in metres: a thin brighter
    glow within ~0.6 m of the projector rail, slow bands and fine scan lines
    elsewhere at strength ~0.01-0.04 (AgX lifts low values: a sheen, not a slab), so the dark well
    stays visible below.
    """
    sep = nb.new("ShaderNodeSeparateXYZ")
    nb.link(nb.coord("Object"), sep.inputs[0])
    dx = nb.math("SUBTRACT", FIELD_HALF[0], nb.math("ABSOLUTE", sep.outputs["X"]))
    dy = nb.math("SUBTRACT", FIELD_HALF[1], nb.math("ABSOLUTE", sep.outputs["Y"]))
    rim = nb.math("POWER", nb.map_range(nb.math("MINIMUM", dx, dy), 0.0, 0.6, 1.0, 0.0), 2.0)
    scan = nb.math("SINE", nb.math("MULTIPLY", sep.outputs["Y"], 2.0 * 3.14159265 / 0.35))
    scan = nb.math("POWER", nb.map_range(scan, -1.0, 1.0, 0.0, 1.0), 6.0)
    mapping = nb.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (0.12, 0.5, 1.0)
    nb.link(nb.coord("Object"), mapping.inputs["Vector"])
    bands = nb.map_range(
        nb.noise(1.0, detail=3.0, vector=mapping.outputs["Vector"]), 0.35, 0.65, 0.35, 1.0
    )
    body = nb.math("MULTIPLY", nb.math("ADD", 0.022, nb.math("MULTIPLY", scan, 0.018)), bands)
    strength = nb.math("ADD", body, nb.math("MULTIPLY", rim, 0.7))
    em = nb.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (0.16, 0.42, 1.0, 1.0)
    nb.link(strength, em.inputs["Strength"])
    tr = nb.new("ShaderNodeBsdfTransparent")
    add = nb.new("ShaderNodeAddShader")
    nb.link(tr.outputs[0], add.inputs[0])
    nb.link(em.outputs[0], add.inputs[1])
    nb.surface(add.outputs[0])


FIELD_HALF = (15.0, 6.0)  # half-size of the default launch well opening (m)


def _haze(nb):
    """Shaft haze: density rises with depth (object -Z), cool scatter."""
    sep = nb.new("ShaderNodeSeparateXYZ")
    nb.link(nb.coord("Object"), sep.inputs[0])
    depth = nb.map_range(sep.outputs["Z"], -3.0, -48.0, 0.0, 1.0)
    dens = nb.math("MULTIPLY", nb.math("POWER", depth, 1.6), 0.16)
    dens = nb.math("ADD", dens, 0.0015)
    vol = nb.new("ShaderNodeVolumePrincipled")
    vol.inputs["Color"].default_value = (0.22, 0.25, 0.3, 1.0)
    vol.inputs["Absorption Color"].default_value = (0.05, 0.06, 0.08, 1.0)
    vol.inputs["Anisotropy"].default_value = 0.45
    nb.link(dens, vol.inputs["Density"])
    nb.link(vol.outputs[0], nb.out.inputs["Volume"])


def _void_black(nb):
    bsdf = nb.principled((0.0, 0.0, 0.0), 1.0, 0.0, **{"Specular IOR Level": 0.0})
    nb.surface(bsdf.outputs["BSDF"])


def _screen_dim(nb):
    em = nb.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (0.25, 0.55, 0.75, 1.0)
    em.inputs["Strength"].default_value = 0.6
    glossy = nb.principled((0.01, 0.012, 0.015), 0.08, 0.0)
    add = nb.new("ShaderNodeAddShader")
    nb.link(glossy.outputs["BSDF"], add.inputs[0])
    nb.link(em.outputs[0], add.inputs[1])
    nb.surface(add.outputs[0])


_BUILDERS = {
    "gunmetal": _gunmetal,
    "dark_steel": _dark_steel,
    "panel_light": _panel_light,
    "panel_dark": _panel_dark,
    "floor": _floor,
    "grating": _grating,
    "hull_paint": _hull_paint,
    "container_charcoal": _container((0.045, 0.047, 0.05)),
    "container_gunmetal": _container((0.11, 0.12, 0.135)),
    "container_olive": _container((0.1, 0.105, 0.085)),
    "container_grey": _container((0.32, 0.33, 0.335)),
    "stencil_white": _stencil((0.62, 0.62, 0.6)),
    "stencil_red": _stencil((0.32, 0.03, 0.025)),
    "stencil_amber": _stencil((0.45, 0.3, 0.05)),
    "stencil_dark": _stencil((0.035, 0.037, 0.04)),
    "hazard": _hazard,
    "rubber": _rubber,
    "insulation": _insulation,
    "glass_dark": _glass_dark,
    "core_hot": _core_hot,
    "field_blue": _field_blue,
    "haze": _haze,
    "lamp_white": _emit(kelvin=6200.0, strength=12.0),
    "lamp_flood": _emit(kelvin=6500.0, strength=45.0),
    "lamp_dim": _emit(kelvin=6800.0, strength=3.0),
    "lamp_band": _emit(kelvin=6200.0, strength=20.0),
    "lamp_maint_red": _emit(color=(0.8, 0.03, 0.02), strength=4.0),
    "floor_engineering": _floor,
    "tread": _tread,
    "lamp_warm": _emit(kelvin=3600.0, strength=8.0),
    "lamp_red": _emit(color=(1.0, 0.04, 0.02), strength=14.0),
    "lamp_green": _emit(color=(0.1, 1.0, 0.25), strength=10.0),
    "lamp_amber": _emit(color=(1.0, 0.45, 0.05), strength=10.0),
    "void_black": _void_black,
    "cabin_glow": _emit(kelvin=4300.0, strength=3.0),
    "screen_dim": _screen_dim,
    "section_cap": _dark_steel,
}
