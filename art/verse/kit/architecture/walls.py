"""Wall panel modules on the 1.2 m module.

Piece space: the wall runs along X (centred), its room face is the plane
Y = 0 facing -Y, the wall body extends to Y = +THICKNESS, floor at Z = 0.

Hero walls (ART_DIRECTION 2), widths 1.2 / 2.4 / 4.8 m:

* ``SM_Wall_<cm>`` - full height (4.5 m) charcoal panelling. Modules
  alternate between a *light column* (a recessed bay of stacked backlit opal
  rectangles between gunmetal ribs) and a *grille* (dark horizontal slats
  between ribs); a steel trim and a charcoal upper band 0.9 m below the top.
  The top face is a section cap (the ceiling plane cuts it).
* ``SM_Wall_<cm>_H540`` - the same, 5.4 m tall.
* ``SM_Wall_<cm>_Cut`` - cut at 1.1 m with a section cap and a ceiling ghost
  of the full wall above (see ``lib.kit.ghost``).

Secondary light-grey panelling (#9EA3A8 semi-gloss) for offices, briefing
and medical rooms:

* ``SM_WallLight_<cm>`` / ``_H540`` / ``_Cut`` - dark 0.6 m base band with a
  vent grille on every second module, light-grey panels with deep seams,
  an access hatch on every fourth module, and a light channel at 2.8 m whose
  fixture hides under the upper lip (only its glow on the channel shows).
* ``SM_WallLight_<cm>_Hatch`` - hatch on the first module.

Corner posts: ``SM_Wall_Corner`` / ``SM_Wall_Corner_Cut`` (0.3 x 0.3 m).

Other heights: ``kit.register_variant("SM_Wall_480_H1200", walls.build_wall,
width=4.8, height=12.0)`` (same for ``build_wall_light``).
"""

from __future__ import annotations

from lib import kit

THICKNESS = 0.3
HEIGHT = 4.5
TALL = 5.4
CUT_HEIGHT = 1.1
GAP = 0.006  # panel seam
PANEL_DEPTH = 0.04

# Light-grey wall bands (z0, z1).
BASE = (0.0, 0.6)
MAIN = (0.6, 2.78)
CHANNEL = (2.78, 3.02)
KICK = (0.0, 0.12)  # kept for pieces that reuse the old kick plate
LOWER = (0.12, 1.06)
STRIP = CHANNEL
UPPER = (3.02, HEIGHT)

# Hero wall bands.
PLINTH = 0.3
BAND_BELOW_TOP = 0.9  # charcoal upper band height
BAY_W = 0.36  # light column bay width
LIGHT_W, LIGHT_H, LIGHT_GAP = 0.26, 0.15, 0.05

WIDTHS = (1.2, 2.4, 4.8)


def module_spans(width: float, module: float = kit.MODULE) -> list[tuple[float, float]]:
    """(x0, x1) of each panel module across a centred piece of ``width``."""
    count = max(1, round(width / module))
    step = width / count
    x0 = -width / 2
    return [(x0 + i * step, x0 + (i + 1) * step) for i in range(count)]


def panel_row(mb: kit.MeshBuilder, width: float, z0: float, z1: float, material: str) -> None:
    for a, b in module_spans(width):
        mb.box((a + GAP / 2, 0.0, z0 + GAP / 2), (b - GAP / 2, PANEL_DEPTH, z1 - GAP / 2), material)


def backing(mb: kit.MeshBuilder, width: float, height: float, y0: float = 0.125) -> None:
    """Dark wall core behind every recess (light bays, strips, seams)."""
    mb.box((-width / 2, y0, 0.0), (width / 2, THICKNESS, height), "M_Recess_Dark")


def section_cap(mb: kit.MeshBuilder, width: float, z: float, thickness: float = THICKNESS) -> None:
    mb.box((-width / 2, -0.004, z - 0.02), (width / 2, thickness, z), "M_Section_Cap")


def light_strip(prefix: str, width: float, z0: float, z1: float) -> None:
    """Recessed opal strip between two brushed lips (a visible fixture)."""
    lips = kit.MeshBuilder()
    lips.box((-width / 2, 0.0, z0), (width / 2, PANEL_DEPTH, z0 + 0.03), "M_Trim_BrushedSteel")
    lips.box((-width / 2, 0.0, z1 - 0.03), (width / 2, PANEL_DEPTH, z1), "M_Trim_BrushedSteel")
    lips.box((-width / 2, 0.075, z0 + 0.03), (width / 2, 0.09, z1 - 0.03), "M_Recess_Dark")
    lips.build(f"{prefix}_strip_lips", bevel_width=0.002)
    kit.emissive_panel(
        f"{prefix}_strip_light",
        (0.0, 0.05, (z0 + z1) / 2),
        (width - 0.004, z1 - z0 - 0.07),
        "M_Light_WallStrip",
        normal="-Y",
    )


def light_channel(prefix: str, width: float, z0: float, z1: float) -> None:
    """Light channel with a hidden fixture: the emitter sits under the proud
    upper lip facing down, so the camera (always looking down) sees only its
    glow on the channel back and on the panels below."""
    mb = kit.MeshBuilder()
    mb.box((-width / 2, -0.02, z0), (width / 2, PANEL_DEPTH, z0 + 0.05), "M_Trim_BrushedSteel")
    mb.box((-width / 2, -0.06, z1 - 0.07), (width / 2, PANEL_DEPTH, z1), "M_Wall_PaintedMid")
    mb.box((-width / 2, 0.1, z0), (width / 2, 0.125, z1), "M_Wall_PaintedLight")
    mb.build(f"{prefix}_channel", bevel_width=0.003)
    kit.emissive_panel(
        f"{prefix}_channel_light",
        (0.0, -0.01, z1 - 0.0705),
        (width - 0.004, 0.08),
        "M_Light_WallStrip",
        normal="-Z",
    )


# ------------------------------------------------------------ hero walls


def _light_column(panels, ribs, lights: list, a: float, b: float, z1: float) -> None:
    """Charcoal side panels, a recessed bay with stacked backlit rectangles."""
    cx = (a + b) / 2
    side = (b - a - BAY_W) / 2
    panels.box((a + GAP / 2, 0.0, PLINTH), (a + side - 0.03, PANEL_DEPTH, z1), "M_Wall_Charcoal")
    panels.box((b - side + 0.03, 0.0, PLINTH), (b - GAP / 2, PANEL_DEPTH, z1), "M_Wall_Charcoal")
    for x in (cx - BAY_W / 2 - 0.015, cx + BAY_W / 2 + 0.015):
        ribs.box((x - 0.03, -0.02, PLINTH), (x + 0.03, 0.12, z1), "M_Struct_Gunmetal")
    z = PLINTH + 0.1
    slot = 0
    while z + LIGHT_H < z1 - 0.05:
        if slot % 5 != 4:  # every fifth slot is a dark plate: the column breathes
            lights.append((cx, z + LIGHT_H / 2))
        else:
            dark = ((cx - LIGHT_W / 2, 0.06, z), (cx + LIGHT_W / 2, 0.1, z + LIGHT_H))
            ribs.box(*dark, "M_Struct_Gunmetal")
        z += LIGHT_H + LIGHT_GAP
        slot += 1


def _grille(ribs, slats, a: float, b: float, z1: float) -> None:
    """Gunmetal ribs at the module edges, dark horizontal slats between."""
    for x in (a + 0.05, b - 0.05):
        ribs.box((x - 0.05, -0.025, PLINTH), (x + 0.05, 0.1, z1), "M_Struct_Gunmetal")
    z = PLINTH + 0.06
    while z < z1 - 0.04:
        slats.box((a + 0.1, 0.03, z), (b - 0.1, 0.07, z + 0.016), "M_Struct_Gunmetal")
        z += 0.05


def _light_quads(name: str, lights: list[tuple[float, float]]) -> None:
    quads, faces = [], []
    w, h = LIGHT_W / 2, LIGHT_H / 2
    for cx, cz in lights:
        n = len(quads)
        quads += [(cx - w, 0.08, cz - h), (cx + w, 0.08, cz - h)]
        quads += [(cx + w, 0.08, cz + h), (cx - w, 0.08, cz + h)]
        faces.append((n, n + 1, n + 2, n + 3))
    kit.mesh_object(f"{name}_lights", quads, faces, "M_Light_Backlit")


def build_wall(width: float, *, cut: bool = False, height: float = HEIGHT) -> None:
    """Charcoal hero wall: light columns alternating with grilles."""
    name = _hero_name(width, cut, height)
    top = CUT_HEIGHT if cut else height
    band = height - BAND_BELOW_TOP
    body = kit.MeshBuilder()
    backing(body, width, top)
    body.box((-width / 2, 0.03, 0.0), (width / 2, THICKNESS, PLINTH), "M_Wall_PaintedDark")
    body.box((-width / 2, 0.012, PLINTH - 0.02), (width / 2, 0.035, PLINTH), "M_Trim_BrushedSteel")
    if not cut:
        trim = ((-width / 2, -0.01, band), (width / 2, PANEL_DEPTH, band + 0.05))
        body.box(*trim, "M_Trim_BrushedSteel")
        panel_row(body, width, band + 0.05, height - 0.02, "M_Wall_Charcoal")
    section_cap(body, width, top)
    body.build(f"{name}_body", bevel_width=0.003)

    z1 = min(band, top - 0.02)
    panels, ribs, slats = kit.MeshBuilder(), kit.MeshBuilder(), kit.MeshBuilder()
    lights: list[tuple[float, float]] = []
    for i, (a, b) in enumerate(module_spans(width)):
        if i % 2 == 0:
            _light_column(panels, ribs, lights, a, b, z1)
        else:
            _grille(ribs, slats, a, b, z1)
    panels.build(f"{name}_panels", bevel_width=0.003)
    ribs.build(f"{name}_ribs", bevel_width=0.006)
    slats.build(f"{name}_slats", bevel_width=0.0)
    if lights:
        _light_quads(name, lights)
    kit.occluder(((-width / 2, 0.0, 0.0), (width / 2, THICKNESS, top)))
    if cut:
        with kit.ghost(CUT_HEIGHT):
            build_wall(width, height=height)


# ------------------------------------------------------- light-grey walls


def hatch(prefix: str, cx: float, z_center: float, w: float = 0.7, h: float = 0.9) -> None:
    """Access hatch: proud plate in a dark gasket, four fasteners, a pull."""
    mb = kit.MeshBuilder()
    z0, z1 = z_center - h / 2, z_center + h / 2
    gasket = ((cx - w / 2 - 0.006, -0.002, z0 - 0.006), (cx + w / 2 + 0.006, 0.03, z1 + 0.006))
    mb.box(*gasket, "M_Rubber_Black")
    mb.box((cx - w / 2, -0.008, z0), (cx + w / 2, 0.03, z1), "M_Wall_PaintedLight")
    mb.box((cx - 0.09, -0.012, z1 - 0.16), (cx + 0.09, -0.006, z1 - 0.1), "M_Trim_BrushedSteel")
    mb.box((cx - 0.07, -0.009, z0 + 0.12), (cx + 0.07, -0.004, z0 + 0.15), "M_Recess_Dark")
    mb.build(f"{prefix}_hatch", bevel_width=0.003)
    bolts = kit.MeshBuilder()
    for bx in (cx - w / 2 + 0.04, cx + w / 2 - 0.04):
        for bz in (z0 + 0.04, z1 - 0.04):
            bolts.tube((bx, -0.008, bz), (bx, -0.014, bz), 0.009, "M_Trim_BrushedSteel", 10)
    bolts.build(f"{prefix}_hatch_bolts", bevel_width=0.0)


def _vent(mb: kit.MeshBuilder, a: float, b: float) -> None:
    """Louvred vent in the base band."""
    x0, x1 = a + 0.25, b - 0.25
    mb.box((x0 - 0.02, -0.006, 0.14), (x1 + 0.02, 0.02, 0.46), "M_Struct_Gunmetal")
    z = 0.17
    while z < 0.43:
        mb.box((x0, -0.012, z), (x1, 0.0, z + 0.012), "M_Recess_Dark")
        z += 0.035


def build_wall_light(
    width: float, *, cut: bool = False, with_hatch: bool = False, height: float = HEIGHT
) -> None:
    """Light-grey panelled wall module (full height or cut-away)."""
    name = _light_name(width, cut, with_hatch, height)
    top = CUT_HEIGHT if cut else height
    body = kit.MeshBuilder()
    backing(body, width, top)
    for a, b in module_spans(width):
        base_panel = ((a + GAP, 0.012, 0.0), (b - GAP, PANEL_DEPTH, BASE[1] - GAP))
        body.box(*base_panel, "M_Wall_PaintedDark")
    body.box(
        (-width / 2, -0.004, BASE[1] - 0.025), (width / 2, 0.02, BASE[1]), "M_Trim_BrushedSteel"
    )
    panel_row(body, width, BASE[1], min(MAIN[1], top - 0.02), "M_Wall_PaintedLight")
    spans = module_spans(width)
    for i, (a, b) in enumerate(spans):
        if i % 2 == 1:
            _vent(body, a, b)
    if cut:
        section_cap(body, width, top)
    body.build(f"{name}_body", bevel_width=0.003)
    if cut:
        kit.occluder(((-width / 2, 0.0, 0.0), (width / 2, THICKNESS, top)))
        with kit.ghost(CUT_HEIGHT):
            build_wall_light(width, height=height)
        return
    panels = kit.MeshBuilder()
    panel_row(panels, width, CHANNEL[1], height - 0.02, "M_Wall_PaintedMid")
    section_cap(panels, width, height)
    panels.build(f"{name}_panels", bevel_width=0.003)
    light_channel(name, width, *CHANNEL)
    for i, (a, b) in enumerate(spans):
        if (with_hatch and i == 0) or i % 4 == 3:
            hatch(f"{name}_{i}", (a + b) / 2, (MAIN[0] + MAIN[1]) / 2 + 0.1)
    kit.occluder(((-width / 2, 0.0, 0.0), (width / 2, THICKNESS, height)))


def build_corner(*, cut: bool = False) -> None:
    """Gunmetal corner post where two walls meet (0.3 x 0.3 m)."""
    top = CUT_HEIGHT if cut else HEIGHT
    mb = kit.MeshBuilder()
    s = THICKNESS / 2
    mb.box((-s, -s, 0.0), (s, s, top - 0.02), "M_Struct_Gunmetal")
    mb.box((-s - 0.002, -s - 0.002, top - 0.02), (s + 0.002, s + 0.002, top), "M_Section_Cap")
    mb.build(f"SM_Wall_Corner{'_Cut' if cut else ''}_post", bevel_width=0.012, segments=3)
    kit.occluder(((-s, -s, 0.0), (s, s, top)))
    if cut:
        with kit.ghost(CUT_HEIGHT):
            build_corner()


def _height_suffix(height: float) -> str:
    return "" if abs(height - HEIGHT) < 1e-6 else f"_H{round(height * 100):03d}"


def _hero_name(width: float, cut: bool, height: float = HEIGHT) -> str:
    return f"SM_Wall_{round(width * 100)}{'_Cut' if cut else _height_suffix(height)}"


def _light_name(width: float, cut: bool, with_hatch: bool, height: float = HEIGHT) -> str:
    suffix = "_Cut" if cut else ("_Hatch" if with_hatch else _height_suffix(height))
    return f"SM_WallLight_{round(width * 100)}{suffix}"


for _w in WIDTHS:
    _dims, _cut_dims = (_w, THICKNESS, HEIGHT), (_w, THICKNESS, CUT_HEIGHT)
    kit.register_variant(_hero_name(_w, False), build_wall, dims=_dims, width=_w)
    kit.register_variant(_hero_name(_w, True), build_wall, dims=_cut_dims, width=_w, cut=True)
    kit.register_variant(
        _hero_name(_w, False, TALL), build_wall, dims=(_w, THICKNESS, TALL), width=_w, height=TALL
    )
    kit.register_variant(_light_name(_w, False, False), build_wall_light, dims=_dims, width=_w)
    kit.register_variant(
        _light_name(_w, True, False), build_wall_light, dims=_cut_dims, width=_w, cut=True
    )
    kit.register_variant(
        _light_name(_w, False, False, TALL),
        build_wall_light,
        dims=(_w, THICKNESS, TALL),
        width=_w,
        height=TALL,
    )
for _w in (1.2, 2.4):
    kit.register_variant(
        _light_name(_w, False, True),
        build_wall_light,
        dims=(_w, THICKNESS, HEIGHT),
        width=_w,
        with_hatch=True,
    )
kit.register_variant("SM_Wall_Corner", build_corner, dims=(THICKNESS, THICKNESS, HEIGHT))
kit.register_variant(
    "SM_Wall_Corner_Cut", build_corner, dims=(THICKNESS, THICKNESS, CUT_HEIGHT), cut=True
)
