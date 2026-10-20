"""Shared building blocks for the command props (consoles, tables, seats, crew fittings).

Runs inside Blender. Every builder here works in piece-local space (kit
conventions, BRIEF section 4): Blender X = screen right, -Y = toward the plate
camera, Z = up, floor at Z = 0. A seated operator sits on the -Y side of a
console and faces +Y, so the console's screens face the camera.

Placement anchor (applied by :func:`anchor` at the end of every builder):

* ``"centre"``: the piece is centred on its footprint in X and Y.
* ``"wall"``: centred in X, the back face sits on local Y = 0 (the room face
  of a wall piece) and the prop extends toward -Y into the room.

Materials are referenced by role constants below. :func:`material` asks
``lib.materials.get`` first and falls back to a clearly named ``TMP_`` local
stand-in, so the props render before the shared library exists.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from contextlib import contextmanager

import bmesh
import bpy
from lib import kit
from mathutils import Matrix, Vector

# --------------------------------------------------------------------------
# Material roles
# --------------------------------------------------------------------------

BODY = "M_Console_Body"  # console carcasses, dark satin paint (library)
BODY_LIGHT = "M_Console_Deck"  # mid-grey desk tops and control decks (library)
STEEL = "M_Struct_Gunmetal"  # structure, plinths, frames (library)
GLOSS = "M_Lacquer_BlackGloss"  # piano-black table tops
SATIN = "M_Plastic_BlackSatin"  # keyboards, bezels, shells
VINYL = "M_Seat_Upholstery"  # black synthetic leather (library)
CHROME = "M_Trim_BrushedSteel"  # bright metal fittings (library)
SCREEN = "M_Screen"  # dark glass, quiet read-out (library)
LAMP_OFF = "M_Plastic_LampOff"  # unlit indicator caps
LAMP_RED = "M_Indicator_Red"
LAMP_GREEN = "M_Indicator_Green"
LAMP_AMBER = "M_Indicator_Amber"
LAMP_WHITE = "M_Indicator_White"
LAMP_BLUE = "M_Indicator_Blue"
BACKLIT = "M_Emit_BacklitPanel"  # translucent white instrument slats
HOLO_LENS = "M_Glass_HoloLens"
FABRIC = "M_Fabric_BunkGrey"
MED_WHITE = "M_Plastic_MedWhite"
RUBBER = "M_Rubber_Black"
GLASS = "M_Glass_Clear"
MIRROR = "M_Glass_Mirror"
LINEN = "M_Fabric_Linen"  # pillows, folded sheets
UNIFORM_CLOTH = "M_Fabric_UniformOlive"  # folded tunics on the quartermaster's counter
BLANKET = "M_Fabric_BlanketSlate"  # bunk blankets: charcoal with a slate-blue tone, no warm hue
RANK_BLUE = "M_Paint_RankBlue"
RANK_RED = "M_Paint_RankRed"
RANK_GOLD = "M_Metal_RankGold"
ACCENT_RED = "M_Paint_TrimRed"  # the thin red trim on console tops (art direction 4)
DARK_PANEL = "M_Wall_PaintedDark"  # dark panelling: locker doors, bunk backs (library)

DESK_H = 0.74  # seated work surface
SEAT_H = 0.46  # seat cushion top, the SOCKET_seat height
STAND_DESK_H = 1.02  # standing work surface

_WARNED: set[str] = set()


def material(name: str) -> bpy.types.Material:
    """Shared library material if available, else a ``TMP_`` stand-in."""
    try:
        from lib import materials as shared  # owned by kit-artist
    except ImportError:
        shared = None
    if shared is not None:
        try:
            found = shared.get(name)
        except KeyError:  # the library does not know this role yet
            found = None
            if name not in _WARNED:
                _WARNED.add(name)
                print(f"[props-command] {name} not in lib.materials; using TMP_{name}")
        if found is not None:
            return found
    return _fallback(name)


# Linear RGB. Values chosen against the style brief: restrained greys and
# blacks, colour only on lamps and screens.
_SPECS: dict[str, dict] = {
    BODY: dict(base=(0.050, 0.053, 0.057), rough=0.46, var=0.10, grime=0.45, wear=0.10),
    BODY_LIGHT: dict(base=(0.135, 0.140, 0.146), rough=0.40, var=0.10, grime=0.45, wear=0.06),
    STEEL: dict(base=(0.16, 0.16, 0.165), metal=0.85, rough=0.36, var=0.10, grime=0.5),
    GLOSS: dict(base=(0.003, 0.003, 0.0035), rough=0.05, var=0.02, coat=1.0, coat_rough=0.012),
    SATIN: dict(base=(0.014, 0.014, 0.015), rough=0.48, var=0.08, grime=0.3),
    VINYL: dict(base=(0.010, 0.010, 0.011), rough=0.30, var=0.08, bump=0.15),
    CHROME: dict(base=(0.62, 0.62, 0.63), metal=1.0, rough=0.20, var=0.06),
    LAMP_OFF: dict(base=(0.06, 0.06, 0.062), rough=0.25, var=0.02),
    LAMP_RED: dict(base=(0.30, 0.02, 0.015), rough=0.25, emit=(1.0, 0.07, 0.04), strength=9.0),
    LAMP_GREEN: dict(base=(0.03, 0.25, 0.06), rough=0.25, emit=(0.15, 1.0, 0.25), strength=6.0),
    LAMP_AMBER: dict(base=(0.30, 0.12, 0.01), rough=0.25, emit=(1.0, 0.42, 0.05), strength=7.0),
    LAMP_WHITE: dict(base=(0.30, 0.30, 0.30), rough=0.25, emit=(1.0, 0.96, 0.90), strength=5.0),
    LAMP_BLUE: dict(base=(0.03, 0.08, 0.30), rough=0.25, emit=(0.20, 0.45, 1.0), strength=6.0),
    BACKLIT: dict(base=(0.40, 0.40, 0.40), rough=0.30, emit=(0.95, 0.96, 1.0), strength=2.6),
    HOLO_LENS: dict(
        base=(0.01, 0.015, 0.02),
        rough=0.04,
        emit=(0.30, 0.62, 1.0),
        strength=3.0,
        coat=1.0,
        coat_rough=0.02,
    ),
    FABRIC: dict(base=(0.055, 0.058, 0.062), rough=0.92, var=0.04, sheen=0.5, bump=0.25),
    MED_WHITE: dict(base=(0.40, 0.415, 0.43), rough=0.34, var=0.08, grime=0.35),
    RUBBER: dict(base=(0.009, 0.009, 0.009), rough=0.82, var=0.06),
    GLASS: dict(kind="glass"),
    MIRROR: dict(base=(0.90, 0.90, 0.92), metal=1.0, rough=0.02, var=0.0),
    SCREEN: dict(kind="screen"),
    LINEN: dict(base=(0.40, 0.41, 0.43), rough=0.88, var=0.05, sheen=0.4, bump=0.2),
    BLANKET: dict(base=(0.026, 0.032, 0.046), rough=0.9, var=0.05, sheen=0.35, bump=0.25),
    UNIFORM_CLOTH: dict(base=(0.045, 0.048, 0.038), rough=0.85, var=0.06, sheen=0.4, bump=0.2),
    RANK_BLUE: dict(base=(0.015, 0.05, 0.22), rough=0.35, var=0.05),
    RANK_RED: dict(base=(0.30, 0.015, 0.012), rough=0.35, var=0.05),
    ACCENT_RED: dict(base=(0.26, 0.012, 0.010), rough=0.38, var=0.06),
    RANK_GOLD: dict(base=(0.80, 0.56, 0.22), metal=1.0, rough=0.28, var=0.06),
    "M_Floor_GlossBlack": dict(
        base=(0.006, 0.006, 0.0065), rough=0.07, var=0.04, coat=0.6, coat_rough=0.03
    ),
}


def _fallback(name: str) -> bpy.types.Material:
    tmp = f"TMP_{name}"
    mat = bpy.data.materials.get(tmp)
    if mat is not None:
        return mat
    spec = _SPECS.get(name)
    if spec is None:
        print(f"[props-command] no spec for {name}; neutral grey TMP_ material")
        spec = dict(base=(0.1, 0.1, 0.1), rough=0.5)
    mat = bpy.data.materials.new(tmp)
    if getattr(mat, "node_tree", None) is None:
        mat.use_nodes = True
    tree = mat.node_tree
    tree.nodes.clear()
    kind = spec.get("kind", "pbr")
    if kind == "glass":
        _glass_nodes(tree)
    elif kind == "screen":
        _screen_nodes(tree)
    else:
        _pbr_nodes(tree, spec)
    mat["tmp_stand_in"] = True
    return mat


def _node(tree, kind: str, x: float, y: float, **attrs):
    node = tree.nodes.new(kind)
    node.location = (x, y)
    for key, value in attrs.items():
        setattr(node, key, value)
    return node


def _pbr_nodes(tree, spec: dict) -> None:
    out = _node(tree, "ShaderNodeOutputMaterial", 900, 0)
    bsdf = _node(tree, "ShaderNodeBsdfPrincipled", 600, 0)
    tree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    base = spec.get("base", (0.1, 0.1, 0.1))
    bsdf.inputs["Base Color"].default_value = (*base, 1.0)
    bsdf.inputs["Metallic"].default_value = spec.get("metal", 0.0)
    rough = spec.get("rough", 0.5)
    var = spec.get("var", 0.0)
    coords = _node(tree, "ShaderNodeTexCoord", -900, 0)

    if var > 0:
        noise = _node(tree, "ShaderNodeTexNoise", -600, 200)
        noise.inputs["Scale"].default_value = 3.5
        noise.inputs["Detail"].default_value = 6.0
        tree.links.new(coords.outputs["Object"], noise.inputs["Vector"])
        remap = _node(tree, "ShaderNodeMapRange", -300, 200)
        remap.inputs["From Min"].default_value = 0.3
        remap.inputs["From Max"].default_value = 0.7
        remap.inputs["To Min"].default_value = max(0.0, rough - var)
        remap.inputs["To Max"].default_value = min(1.0, rough + var)
        tree.links.new(noise.outputs["Fac"], remap.inputs["Value"])
        tree.links.new(remap.outputs["Result"], bsdf.inputs["Roughness"])
    else:
        bsdf.inputs["Roughness"].default_value = rough

    grime = spec.get("grime", 0.0)
    wear = spec.get("wear", 0.0)
    color_socket = None
    if grime > 0 or wear > 0:
        rgb = _node(tree, "ShaderNodeRGB", -600, -150)
        rgb.outputs[0].default_value = (*base, 1.0)
        color_socket = rgb.outputs[0]
    if grime > 0:
        ao = _node(tree, "ShaderNodeAmbientOcclusion", -600, -350, samples=8)
        ao.inputs["Distance"].default_value = 0.06
        dim = _node(tree, "ShaderNodeMapRange", -300, -350)
        dim.inputs["From Min"].default_value = 0.2
        dim.inputs["From Max"].default_value = 1.0
        dim.inputs["To Min"].default_value = 1.0 - grime
        dim.inputs["To Max"].default_value = 1.0
        tree.links.new(ao.outputs["AO"], dim.inputs["Value"])
        scale = _node(tree, "ShaderNodeVectorMath", 0, -200, operation="SCALE")
        tree.links.new(color_socket, scale.inputs[0])
        tree.links.new(dim.outputs["Result"], scale.inputs["Scale"])
        color_socket = scale.outputs["Vector"]
    if wear > 0:
        edge = _node(tree, "ShaderNodeAmbientOcclusion", -600, -600, samples=8, inside=True)
        edge.inputs["Distance"].default_value = 0.012
        inv = _node(tree, "ShaderNodeMapRange", -300, -600)
        inv.inputs["From Min"].default_value = 0.35
        inv.inputs["From Max"].default_value = 0.9
        inv.inputs["To Min"].default_value = wear
        inv.inputs["To Max"].default_value = 0.0
        tree.links.new(edge.outputs["AO"], inv.inputs["Value"])
        add = _node(tree, "ShaderNodeVectorMath", 250, -400, operation="ADD")
        tree.links.new(color_socket, add.inputs[0])
        tree.links.new(inv.outputs["Result"], add.inputs[1])
        color_socket = add.outputs["Vector"]
    if color_socket is not None:
        tree.links.new(color_socket, bsdf.inputs["Base Color"])

    if spec.get("coat"):
        bsdf.inputs["Coat Weight"].default_value = spec["coat"]
        bsdf.inputs["Coat Roughness"].default_value = spec.get("coat_rough", 0.03)
    if spec.get("sheen"):
        bsdf.inputs["Sheen Weight"].default_value = spec["sheen"]
    if spec.get("emit"):
        bsdf.inputs["Emission Color"].default_value = (*spec["emit"], 1.0)
        bsdf.inputs["Emission Strength"].default_value = spec.get("strength", 5.0)
    if spec.get("bump"):
        fine = _node(tree, "ShaderNodeTexNoise", -600, -850)
        fine.inputs["Scale"].default_value = 180.0
        fine.inputs["Detail"].default_value = 4.0
        tree.links.new(coords.outputs["Object"], fine.inputs["Vector"])
        bump = _node(tree, "ShaderNodeBump", 300, -700)
        bump.inputs["Strength"].default_value = spec["bump"]
        bump.inputs["Distance"].default_value = 0.002
        tree.links.new(fine.outputs["Fac"], bump.inputs["Height"])
        tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def _glass_nodes(tree) -> None:
    out = _node(tree, "ShaderNodeOutputMaterial", 600, 0)
    bsdf = _node(tree, "ShaderNodeBsdfPrincipled", 300, 0)
    bsdf.inputs["Base Color"].default_value = (0.92, 0.95, 0.96, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.02
    bsdf.inputs["IOR"].default_value = 1.45
    bsdf.inputs["Transmission Weight"].default_value = 1.0
    tree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])


def _screen_nodes(tree) -> None:
    """Dark glass showing a dim, monochrome standby read-out.

    UV space of the screen quad: rows of short bars (brick texture), a thin
    frame and a header band. The runtime draws live content over the
    SOCKET_screen; this only has to read as a lit screen in the plate.
    """
    out = _node(tree, "ShaderNodeOutputMaterial", 1300, 0)
    bsdf = _node(tree, "ShaderNodeBsdfPrincipled", 1000, 0)
    bsdf.inputs["Base Color"].default_value = (0.004, 0.006, 0.008, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.06
    bsdf.inputs["Coat Weight"].default_value = 1.0
    bsdf.inputs["Coat Roughness"].default_value = 0.02
    tree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    coords = _node(tree, "ShaderNodeTexCoord", -1200, 0)
    info = _node(tree, "ShaderNodeObjectInfo", -1200, -250)
    mapping = _node(tree, "ShaderNodeMapping", -950, 0)
    tree.links.new(coords.outputs["UV"], mapping.inputs["Vector"])
    shift = _node(tree, "ShaderNodeVectorMath", -1000, -250, operation="SCALE")
    tree.links.new(info.outputs["Random"], shift.inputs[0])
    shift.inputs["Scale"].default_value = 7.0
    tree.links.new(shift.outputs["Vector"], mapping.inputs["Location"])

    brick = _node(tree, "ShaderNodeTexBrick", -650, 100, offset=0.37, squash_frequency=1)
    brick.inputs["Color1"].default_value = (1, 1, 1, 1)
    brick.inputs["Color2"].default_value = (0, 0, 0, 1)
    brick.inputs["Mortar"].default_value = (0, 0, 0, 1)
    brick.inputs["Scale"].default_value = 6.0
    brick.inputs["Mortar Size"].default_value = 0.012
    brick.inputs["Bias"].default_value = -0.2
    brick.inputs["Brick Width"].default_value = 0.30
    brick.inputs["Row Height"].default_value = 0.055
    tree.links.new(mapping.outputs["Vector"], brick.inputs["Vector"])
    bars = _node(tree, "ShaderNodeMath", -400, 100, operation="GREATER_THAN")
    tree.links.new(brick.outputs["Color"], bars.inputs[0])
    bars.inputs[1].default_value = 0.55

    # Frame: distance to the UV border.
    sep = _node(tree, "ShaderNodeSeparateXYZ", -950, -500)
    tree.links.new(coords.outputs["UV"], sep.inputs["Vector"])
    edge_terms = []
    for axis in ("X", "Y"):
        flip = _node(
            tree, "ShaderNodeMath", -750, -450 if axis == "X" else -650, operation="SUBTRACT"
        )
        flip.inputs[0].default_value = 1.0
        tree.links.new(sep.outputs[axis], flip.inputs[1])
        low = _node(
            tree, "ShaderNodeMath", -600, -450 if axis == "X" else -650, operation="MINIMUM"
        )
        tree.links.new(sep.outputs[axis], low.inputs[0])
        tree.links.new(flip.outputs["Value"], low.inputs[1])
        edge_terms.append(low)
    nearest = _node(tree, "ShaderNodeMath", -450, -550, operation="MINIMUM")
    tree.links.new(edge_terms[0].outputs["Value"], nearest.inputs[0])
    tree.links.new(edge_terms[1].outputs["Value"], nearest.inputs[1])
    frame_line = _node(tree, "ShaderNodeMath", -300, -550, operation="LESS_THAN")
    tree.links.new(nearest.outputs["Value"], frame_line.inputs[0])
    frame_line.inputs[1].default_value = 0.025
    inner = _node(tree, "ShaderNodeMath", -300, -350, operation="GREATER_THAN")
    tree.links.new(nearest.outputs["Value"], inner.inputs[0])
    inner.inputs[1].default_value = 0.07
    content = _node(tree, "ShaderNodeMath", -150, 0, operation="MULTIPLY")
    tree.links.new(bars.outputs["Value"], content.inputs[0])
    tree.links.new(inner.outputs["Value"], content.inputs[1])
    lit = _node(tree, "ShaderNodeMath", 50, -100, operation="MAXIMUM")
    tree.links.new(content.outputs["Value"], lit.inputs[0])
    tree.links.new(frame_line.outputs["Value"], lit.inputs[1])
    glow = _node(tree, "ShaderNodeMapRange", 250, -100)
    glow.inputs["From Min"].default_value = 0.0
    glow.inputs["From Max"].default_value = 1.0
    glow.inputs["To Min"].default_value = 0.10  # standby floor glow
    glow.inputs["To Max"].default_value = 1.6
    tree.links.new(lit.outputs["Value"], glow.inputs["Value"])
    bsdf.inputs["Emission Color"].default_value = (0.55, 0.80, 1.0, 1.0)
    tree.links.new(glow.outputs["Result"], bsdf.inputs["Emission Strength"])


# --------------------------------------------------------------------------
# Mesh finishing
# --------------------------------------------------------------------------


def finish(
    mb: kit.MeshBuilder,
    name: str,
    *,
    bevel_width: float = 0.006,
    segments: int = 2,
    angle_deg: float = 30.0,
    **props,
) -> bpy.types.Object | None:
    """Like ``MeshBuilder.build`` but resolves materials through :func:`material`."""
    if mb.is_empty():
        mb.bm.free()
        return None
    bmesh.ops.recalc_face_normals(mb.bm, faces=list(mb.bm.faces))
    mesh = bpy.data.meshes.new(name)
    mb.bm.to_mesh(mesh)
    mb.bm.free()
    for mat_name in mb.materials:
        mesh.materials.append(material(mat_name))
    obj = bpy.data.objects.new(name, mesh)
    kit.link(obj)
    if bevel_width > 0:
        kit.bevel(obj, bevel_width, segments, angle_deg)
    else:
        mesh.shade_flat()
    kit.tag(obj, **props)
    return obj


@contextmanager
def xform(mb: kit.MeshBuilder, matrix: Matrix):
    """Build the block's geometry through an extra local transform."""
    old = mb.matrix
    mb.matrix = old @ matrix
    try:
        yield mb
    finally:
        mb.matrix = old


def tr(
    x: float = 0.0, y: float = 0.0, z: float = 0.0, rz_deg: float = 0.0, rx_deg: float = 0.0
) -> Matrix:
    """Translation, then rotation about Z, then rotation about X (local)."""
    m = Matrix.Translation((x, y, z))
    if rz_deg:
        m = m @ Matrix.Rotation(math.radians(rz_deg), 4, "Z")
    if rx_deg:
        m = m @ Matrix.Rotation(math.radians(rx_deg), 4, "X")
    return m


def frame_on_slope(origin: Sequence[float], tilt_back_deg: float, rz_deg: float = 0.0) -> Matrix:
    """Panel frame: X right, Y up the panel, Z out of the panel.

    ``tilt_back_deg`` = 0 is a vertical panel facing -Y (the camera / the
    operator); 90 is a horizontal panel facing up.
    """
    m = Matrix.Translation(Vector(origin))
    if rz_deg:
        m = m @ Matrix.Rotation(math.radians(rz_deg), 4, "Z")
    # Start from a panel facing -Y (normal -Y, up +Z), then tilt about X.
    base = Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
    tilt = Matrix.Rotation(math.radians(-tilt_back_deg), 4, "X")
    return m @ tilt @ base


# --------------------------------------------------------------------------
# Outlines and solids
# --------------------------------------------------------------------------

Outline = list[tuple[Vector, Vector]]  # (point, outward normal) in XY, CCW from above


def rounded_rect(w: float, d: float, r: float, seg: int = 6, cx=0.0, cy=0.0) -> Outline:
    r = max(1e-4, min(r, w / 2 - 1e-4, d / 2 - 1e-4))
    pts: Outline = []
    corners = (
        (w / 2 - r, d / 2 - r, 0),
        (-w / 2 + r, d / 2 - r, 90),
        (-w / 2 + r, -d / 2 + r, 180),
        (w / 2 - r, -d / 2 + r, 270),
    )
    for ccx, ccy, a0 in corners:
        for i in range(seg + 1):
            a = math.radians(a0 + 90 * i / seg)
            n = Vector((math.cos(a), math.sin(a)))
            pts.append((Vector((cx + ccx, cy + ccy)) + n * r, n))
    return pts


def superellipse(
    a: float, b: float, exponent: float = 2.6, count: int = 72, cx=0.0, cy=0.0
) -> Outline:
    pts: Outline = []
    e = exponent
    for i in range(count):
        t = 2 * math.pi * i / count
        c, s = math.cos(t), math.sin(t)
        x = a * math.copysign(abs(c) ** (2 / e), c)
        y = b * math.copysign(abs(s) ** (2 / e), s)
        gx = math.copysign(abs(x / a) ** (e - 1), x) / a
        gy = math.copysign(abs(y / b) ** (e - 1), y) / b
        n = Vector((gx, gy))
        n = n.normalized() if n.length > 1e-9 else Vector((c, s))
        pts.append((Vector((cx + x, cy + y)), n))
    return pts


def circle(r: float, count: int = 64, cx=0.0, cy=0.0) -> Outline:
    out: Outline = []
    for i in range(count):
        a = 2 * math.pi * i / count
        n = Vector((math.cos(a), math.sin(a)))
        out.append((Vector((cx, cy)) + n * r, n))
    return out


def loft(
    mb: kit.MeshBuilder,
    outline: Outline,
    levels: Sequence[tuple[float, float]],
    mat: str,
    *,
    cap_bottom: bool = True,
    cap_top: bool = True,
) -> None:
    """Sweep ``outline`` through ``levels`` = [(outward offset, z), ...]."""
    n = len(outline)
    verts: list[Vector] = []
    for offset, z in levels:
        for p, nrm in outline:
            q = p + nrm * offset
            verts.append(Vector((q.x, q.y, z)))
    faces = []
    for row in range(len(levels) - 1):
        a, b = row * n, (row + 1) * n
        for i in range(n):
            j = (i + 1) % n
            faces.append((a + i, a + j, b + j, b + i))
    if cap_bottom:
        faces.append(tuple(reversed(range(n))))
    if cap_top:
        last = (len(levels) - 1) * n
        faces.append(tuple(range(last, last + n)))
    mb._add(verts, faces, mat)


def slab(
    mb: kit.MeshBuilder, outline: Outline, z0: float, z1: float, mat: str, chamfer: float = 0.0
) -> None:
    """Flat solid from an outline, optionally with chamfered top and bottom."""
    if chamfer <= 0:
        loft(mb, outline, ((0.0, z0), (0.0, z1)), mat)
        return
    c = min(chamfer, (z1 - z0) / 2.01)
    loft(mb, outline, ((-c, z0), (0.0, z0 + c), (0.0, z1 - c), (-c, z1)), mat)


def cushion(
    mb: kit.MeshBuilder,
    w: float,
    d: float,
    z0: float,
    h: float,
    mat: str,
    corner: float = 0.06,
    edge: float = 0.025,
    cx=0.0,
    cy=0.0,
    steps: int = 3,
) -> None:
    """Upholstered pad: rounded rectangle with rounded top and bottom edges."""
    edge = min(edge, h / 2.05)
    outline = rounded_rect(w, d, corner, 5, cx, cy)
    levels = []
    for i in range(steps + 1):
        t = math.radians(90 * i / steps)
        levels.append((-edge * (1 - math.sin(t)), z0 + edge * (1 - math.cos(t))))
    for i in range(steps + 1):
        t = math.radians(90 * i / steps)
        levels.append((-edge * (1 - math.cos(t)), z0 + h - edge + edge * math.sin(t)))
    loft(mb, outline, levels, mat)


def lathe(
    mb: kit.MeshBuilder,
    profile: Sequence[tuple[float, float]],
    mat: str,
    segments: int = 48,
    *,
    closed: bool = False,
    cx=0.0,
    cy=0.0,
) -> None:
    """Revolve an (r, z) profile around the local Z axis through (cx, cy)."""
    verts: list[Vector] = []
    rows: list[list[int]] = []
    for r, z in profile:
        if r <= 1e-6:
            rows.append([len(verts)])
            verts.append(Vector((cx, cy, z)))
            continue
        row = []
        for i in range(segments):
            a = 2 * math.pi * i / segments
            row.append(len(verts))
            verts.append(Vector((cx + r * math.cos(a), cy + r * math.sin(a), z)))
        rows.append(row)
    pairs = list(zip(rows[:-1], rows[1:], strict=True))
    if closed:
        pairs.append((rows[-1], rows[0]))
    faces = []
    n = segments
    for a, b in pairs:
        if len(a) == 1 and len(b) == 1:
            continue
        if len(a) == 1:
            faces += [(a[0], b[(i + 1) % n], b[i]) for i in range(n)]
        elif len(b) == 1:
            faces += [(a[i], a[(i + 1) % n], b[0]) for i in range(n)]
        else:
            faces += [(a[i], a[(i + 1) % n], b[(i + 1) % n], b[i]) for i in range(n)]
    mb._add(verts, faces, mat)


def arc_segment(
    mb: kit.MeshBuilder,
    r0: float,
    r1: float,
    a0_deg: float,
    a1_deg: float,
    z0: float,
    z1: float,
    mat: str,
    steps: int = 16,
    cx=0.0,
    cy=0.0,
) -> None:
    """Annular sector solid (a curved desk or rim piece)."""
    outline: Outline = []
    for i in range(steps + 1):
        a = math.radians(a0_deg + (a1_deg - a0_deg) * i / steps)
        n = Vector((math.cos(a), math.sin(a)))
        outline.append((Vector((cx, cy)) + n * r1, n))
    for i in range(steps, -1, -1):
        a = math.radians(a0_deg + (a1_deg - a0_deg) * i / steps)
        n = Vector((math.cos(a), math.sin(a)))
        outline.append((Vector((cx, cy)) + n * r0, -n))
    loft(mb, outline, ((0.0, z0), (0.0, z1)), mat)


# --------------------------------------------------------------------------
# Instrument details
# --------------------------------------------------------------------------

# Indicator colours (ART_DIRECTION 4): red and white first, green for status,
# amber only as a rare warning.
LAMP_PALETTE_BRIDGE = ((LAMP_RED, 0.45), (LAMP_WHITE, 0.35), (LAMP_GREEN, 0.15), (LAMP_AMBER, 0.05))
LAMP_PALETTE_COOL = ((LAMP_WHITE, 0.4), (LAMP_RED, 0.3), (LAMP_BLUE, 0.2), (LAMP_GREEN, 0.1))
LAMP_PALETTE_ENGINE = ((LAMP_WHITE, 0.4), (LAMP_GREEN, 0.3), (LAMP_RED, 0.2), (LAMP_AMBER, 0.1))
# Key banks read as mostly dark keys with a few lit indicators, not a tile
# board (art director review): every requested lit share is scaled by this.
LIT_SHARE = 0.35


def _pick(rng: random.Random, palette) -> str:
    roll = rng.random() * sum(w for _, w in palette)
    for mat, weight in palette:
        roll -= weight
        if roll <= 0:
            return mat
    return palette[-1][0]


def button_bank(
    lamps: kit.MeshBuilder,
    keys: kit.MeshBuilder,
    frame: Matrix,
    cols: int,
    rows: int,
    pitch: tuple[float, float],
    size: tuple[float, float],
    seed: int,
    *,
    lit: float = 0.45,
    palette=LAMP_PALETTE_BRIDGE,
    height: float = 0.006,
    plate: str | None = SATIN,
) -> None:
    """Grid of push buttons on a panel plane (``frame``: XY = panel, +Z out).

    Lit caps go to ``lamps`` (emissive), dark caps and the backing plate to
    ``keys``. Deterministic for a given ``seed``.
    """
    rng = random.Random(seed)  # noqa: S311 - deterministic set dressing, not crypto
    px, py = pitch
    sx, sy = size
    w = (cols - 1) * px + sx
    h = (rows - 1) * py + sy
    if plate:
        with xform(keys, frame):
            keys.box(
                (-w / 2 - 0.012, -h / 2 - 0.012, 0.0), (w / 2 + 0.012, h / 2 + 0.012, 0.003), plate
            )
    for r in range(rows):
        for c in range(cols):
            x = -w / 2 + sx / 2 + c * px
            y = -h / 2 + sy / 2 + r * py
            is_lit = rng.random() < lit * LIT_SHARE
            target, mat = (lamps, _pick(rng, palette)) if is_lit else (keys, LAMP_OFF)
            with xform(target, frame):
                target.box(
                    (x - sx / 2, y - sy / 2, 0.003), (x + sx / 2, y + sy / 2, 0.003 + height), mat
                )


def slat_stack(
    lamps: kit.MeshBuilder,
    keys: kit.MeshBuilder,
    frame: Matrix,
    n: int,
    w: float,
    h: float,
    gap: float,
    *,
    frame_mat: str = SATIN,
    lit_mat: str = BACKLIT,
    seed: int = 0,
    lit: float = 1.0,
) -> None:
    """Stack of backlit horizontal instrument slats in a dark surround."""
    rng = random.Random(seed)  # noqa: S311 - deterministic set dressing, not crypto
    total = n * h + (n - 1) * gap
    with xform(keys, frame):
        keys.box(
            (-w / 2 - 0.015, -total / 2 - 0.015, 0.0),
            (w / 2 + 0.015, total / 2 + 0.015, 0.004),
            frame_mat,
        )
    for i in range(n):
        y = -total / 2 + i * (h + gap)
        target, mat = (lamps, lit_mat) if rng.random() < lit else (keys, LAMP_OFF)
        with xform(target, frame):
            target.box((-w / 2, y, 0.004), (w / 2, y + h, 0.007), mat)


def keyboard(
    keys: kit.MeshBuilder,
    frame: Matrix,
    w: float = 0.44,
    d: float = 0.15,
    cols: int = 15,
    rows: int = 5,
) -> None:
    """Low keyboard slab with a key grid (frame: XY = desk plane)."""
    with xform(keys, frame):
        keys.box((-w / 2, -d / 2, 0.0), (w / 2, d / 2, 0.016), SATIN)
        kx = (w - 0.03) / cols
        ky = (d - 0.03) / rows
        for r in range(rows):
            for c in range(cols):
                x0 = -w / 2 + 0.015 + c * kx
                y0 = -d / 2 + 0.015 + r * ky
                keys.box(
                    (x0 + 0.002, y0 + 0.002, 0.016),
                    (x0 + kx - 0.002, y0 + ky - 0.002, 0.024),
                    LAMP_OFF,
                )


def screen(
    name: str,
    frame: Matrix,
    w: float,
    h: float,
    bezel: kit.MeshBuilder | None = None,
    *,
    local_id: str = "",
    socket_on: bool = True,
    border: float = 0.025,
    depth: float = 0.02,
) -> bpy.types.Object:
    """Screen glass quad (with UVs) in a bezel, plus its SOCKET_screen.

    ``frame``: XY = screen plane centred on the glass, +Z = screen normal,
    +Y = screen up. The glass sits 4 mm behind the bezel lip.
    """
    if bezel is not None:
        b = border
        with xform(bezel, frame):
            bezel.box((-w / 2 - b, -h / 2 - b, -depth), (w / 2 + b, -h / 2, 0.006), SATIN)
            bezel.box((-w / 2 - b, h / 2, -depth), (w / 2 + b, h / 2 + b, 0.006), SATIN)
            bezel.box((-w / 2 - b, -h / 2, -depth), (-w / 2, h / 2, 0.006), SATIN)
            bezel.box((w / 2, -h / 2, -depth), (w / 2 + b, h / 2, 0.006), SATIN)
            bezel.box((-w / 2, -h / 2, -depth), (w / 2, h / 2, -0.004), SATIN)
    corners = [
        frame @ Vector((sx * w / 2, sy * h / 2, 0.002))
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))
    ]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(c) for c in corners], [], [(0, 1, 2, 3)])
    uv = mesh.uv_layers.new(name="UVMap")
    for loop, coord in zip(mesh.loops, ((0, 0), (1, 0), (1, 1), (0, 1)), strict=True):
        uv.data[loop.index].uv = coord
    mesh.materials.append(material(SCREEN))
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    kit.link(obj)
    if socket_on:
        kit.socket(
            "screen",
            local_id,
            frame @ Matrix.Translation((0, 0, 0.004)),
            size_w=round(w, 4),
            size_h=round(h, 4),
        )
    return obj


def lamp(lamps: kit.MeshBuilder, center: Sequence[float], size: Sequence[float], mat: str) -> None:
    lamps.box_c(center, size, mat)


# --------------------------------------------------------------------------
# Sockets
# --------------------------------------------------------------------------


def _facing_matrix(location, facing_deg: float):
    """+Z up and local -Y along the facing direction (the cook's convention:
    a socket faces its local -Y; ``lib.scene.add_socket`` does the same).

    ``facing_deg`` is measured in the piece's XY plane from +Y: 0 = facing +Y
    (away from the camera, e.g. an operator at a console), 180 = facing the
    camera, 90 = facing -X. In three.js yaw terms: yaw = 180 - facing_deg.
    """
    a = math.radians(facing_deg)
    facing = Vector((-math.sin(a), math.cos(a), 0.0))
    return kit.socket_matrix(location, (0, 0, 1), -facing)


def seat_socket(local_id: str, x: float, y: float, facing_deg: float, z: float = SEAT_H) -> None:
    """SOCKET_seat on the cushion top (hip point), facing ``facing_deg``."""
    kit.socket("seat", local_id, _facing_matrix((x, y, z), facing_deg))


def stand_socket(
    local_id: str,
    x: float,
    y: float,
    facing_deg: float,
    kind: str = "stand",
    z: float = 0.0,
    **props,
) -> None:
    """SOCKET_stand (or another floor-point kind, e.g. station) facing ``facing_deg``."""
    kit.socket(kind, local_id, _facing_matrix((x, y, z), facing_deg), **props)


def holo_socket(local_id: str, x: float, y: float, z: float, radius: float, height: float) -> None:
    """SOCKET_holo at the emitter lens; ``radius``/``height`` = projection volume."""
    kit.socket("holo", local_id, _facing_matrix((x, y, z), 180.0), radius=radius, height=height)


def bunk_socket(local_id: str, x: float, y: float, z: float, head_deg: float) -> None:
    """SOCKET_bunk on the mattress top centre; ``head_deg`` is where the head
    lies. Local -Y (the socket's yaw) points to the FOOT end: the character's
    root takes the socket yaw and the sleep clip lies with the head at the
    root's back (convention settled with pipeline, engine and deck-ops)."""
    kit.socket("bunk", local_id, _facing_matrix((x, y, z), head_deg + 180.0))


# --------------------------------------------------------------------------
# Anchoring
# --------------------------------------------------------------------------


def anchor(mode: str = "centre", *, spin_deg: float = 0.0) -> tuple[float, float, float]:
    """Shift everything the active builder made so the piece obeys its anchor.

    Modes: ``centre`` (footprint centred in X and Y), ``wall`` (centred in X,
    back on local Y = 0), ``design`` (keep the builder's own origin, for pieces
    that match a deck contract). ``spin_deg`` first turns the whole piece
    about Z (for pieces a deck places at a fixed yaw). Must be the last call
    of a piece builder. Returns the measured dims.
    """
    col = kit.current_collection()
    pdef = kit._ACTIVE[-1]  # noqa: SLF001 - same package family, registry internals
    if spin_deg:
        spin = Matrix.Rotation(math.radians(spin_deg), 4, "Z")
        for obj in col.objects:
            obj.matrix_basis = spin @ obj.matrix_basis
        for spec in pdef.sockets:
            spec.matrix = spin @ spec.matrix
        for spec in pdef.occluders:
            spec.verts = [spin @ v for v in spec.verts]
    xs, ys, zs = [], [], []
    for obj in col.objects:
        if obj.type != "MESH":
            continue
        mw = obj.matrix_basis
        for v in obj.data.vertices:
            w = mw @ v.co
            xs.append(w.x)
            ys.append(w.y)
            zs.append(w.z)
    if not xs:
        return (0.0, 0.0, 0.0)
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2 if mode == "centre" else max(ys)
    if mode == "design":
        cx = cy = 0.0
    shift = Matrix.Translation((-cx, -cy, 0.0))
    for obj in col.objects:
        obj.matrix_basis = shift @ obj.matrix_basis
    for spec in pdef.sockets:
        spec.matrix = shift @ spec.matrix
    for spec in pdef.occluders:
        spec.verts = [shift @ v for v in spec.verts]
    dims = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    col["dims"] = [round(d, 3) for d in dims]
    col["anchor"] = mode
    return dims


def box_occluder(lo: Sequence[float], hi: Sequence[float], nav: str = "block") -> None:
    kit.occluder((tuple(lo), tuple(hi)), nav=nav)


def oriented_box_occluder(
    matrix: Matrix, lo: Sequence[float], hi: Sequence[float], nav: str = "block"
) -> None:
    """UCX box in a local frame (rotated chairs, angled console wings)."""
    verts, faces = kit._box_verts_faces(Vector(lo), Vector(hi))  # noqa: SLF001
    kit._ACTIVE[-1].occluders.append(  # noqa: SLF001
        kit.OccluderSpec([matrix @ v for v in verts], faces, {"nav": nav})
    )


def prism_occluder(
    points_xy: Sequence[Sequence[float]], z0: float, z1: float, nav: str = "block"
) -> None:
    """UCX prism from a convex XY polygon (round tables, plinths)."""
    n = len(points_xy)
    verts = [Vector((x, y, z0)) for x, y in points_xy] + [Vector((x, y, z1)) for x, y in points_xy]
    faces = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
    faces += [tuple(reversed(range(n))), tuple(range(n, 2 * n))]
    kit._ACTIVE[-1].occluders.append(kit.OccluderSpec(verts, faces, {"nav": nav}))  # noqa: SLF001


def pname() -> str:
    """Name of the piece whose builder is running."""
    return kit._ACTIVE[-1].name  # noqa: SLF001


def builders() -> dict[str, kit.MeshBuilder]:
    """The usual set of mesh builders for one piece."""
    return {
        "body": kit.MeshBuilder(),
        "trim": kit.MeshBuilder(),
        "detail": kit.MeshBuilder(),
        "lamps": kit.MeshBuilder(),
        "soft": kit.MeshBuilder(),
    }


_BEVEL = {"body": 0.008, "trim": 0.004, "detail": 0.0018, "lamps": 0.0008, "soft": 0.004}


def finish_all(mbs: dict[str, kit.MeshBuilder]) -> None:
    """Turn every builder of a piece into its own bevelled object."""
    base = pname()
    for key, mb in mbs.items():
        finish(
            mb,
            f"{base}_{key}",
            bevel_width=_BEVEL.get(key, 0.004),
            segments=1 if key in ("lamps", "detail") else 2,
        )


def edge_strip(
    mb: kit.MeshBuilder,
    points_yz: Sequence[Sequence[float]],
    x0: float,
    x1: float,
    mat: str = CHROME,
    t: float = 0.004,
) -> None:
    """Thin trim capping a profile's top edges (a polyline in YZ), across X.

    Brushed-steel caps on console cheeks catch the ceiling light as crisp
    lines, the "steel edge trim" of ART_DIRECTION 7.
    """
    for (y0, z0), (y1, z1) in zip(points_yz[:-1], points_yz[1:], strict=True):
        dy, dz = y1 - y0, z1 - z0
        length = math.hypot(dy, dz)
        if length < 1e-6:
            continue
        ny, nz = -dz / length, dy / length
        if nz < 0 or (abs(nz) < 1e-6 and ny > 0):
            ny, nz = -ny, -nz
        quad = ((y0, z0), (y1, z1), (y1 + ny * t, z1 + nz * t), (y0 + ny * t, z0 + nz * t))
        mb.prism_x(quad, x0, x1, mat)


def fasteners(
    mb: kit.MeshBuilder, frame: Matrix, w: float, h: float, inset: float = 0.018, r: float = 0.004
) -> None:
    """Four small screw heads at the corners of a panel (frame: XY = panel)."""
    with xform(mb, frame):
        for sx in (-1, 1):
            for sy in (-1, 1):
                x, y = sx * (w / 2 - inset), sy * (h / 2 - inset)
                mb.tube((x, y, 0.0), (x, y, 0.0025), r, CHROME, 8)
