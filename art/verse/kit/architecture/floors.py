"""Deck floors: plate fills, grating panels, light inlays and deck markings.

Plate seams are not geometry: ``M_Floor_GlossBlack`` draws them in world
space on one global grid (2.4 m along the ship x 1.2 m across), so every floor
fill and every module that carries its own floor shares the same seams.

* :func:`fill_floor` - a floor slab over any polygon (nav "walk").
* :func:`inlay_strip` - a flush light inlay strip (walkway edges, steps).
* :func:`marking` - a worn paint decal quad (lines, hazard bands).
* ``SM_Grating_120`` - 1.2 x 1.2 m bar grating panel over a shallow service
  trench with pipes; ``SM_Grating_120_Lit`` adds a dim trench light.
"""

from __future__ import annotations

from collections.abc import Sequence

from lib import kit

SLAB = 0.12  # slab thickness under the walking surface


def fill_floor(
    name: str,
    polygon: Sequence[Sequence[float]],
    z: float = 0.0,
    *,
    room: str | None = None,
    material: str = "M_Floor_GlossBlack",
    nav: str = "walk",
) -> object:
    """Floor slab whose top face is ``polygon`` (Blender XY, CCW) at ``z``."""
    mb = kit.MeshBuilder()
    mb.prism_z([tuple(p) for p in polygon], z - SLAB, z, material)
    return mb.build(name, bevel_width=0.004, segments=2, room=room, nav=nav)


def fill_rect(name: str, x0: float, y0: float, x1: float, y1: float, z: float = 0.0, **kw):
    return fill_floor(name, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], z, **kw)


def inlay_strip(
    name: str, p0: Sequence[float], p1: Sequence[float], width: float = 0.06, z: float = 0.0
):
    """Flush floor light along an axis-aligned line from ``p0`` to ``p1``."""
    (x0, y0), (x1, y1) = p0, p1
    along_x = abs(x1 - x0) >= abs(y1 - y0)
    if along_x:
        lo, hi = (min(x0, x1), y0 - width / 2), (max(x0, x1), y0 + width / 2)
    else:
        lo, hi = (x0 - width / 2, min(y0, y1)), (x0 + width / 2, max(y0, y1))
    frame = kit.MeshBuilder()
    rim = 0.012
    frame.box(
        (lo[0] - rim, lo[1] - rim, z - 0.03),
        (hi[0] + rim, hi[1] + rim, z + 0.0005),
        "M_Trim_BrushedSteel",
    )
    frame.build(f"{name}_frame", bevel_width=0.002, nav="walk")
    kit.emissive_panel(
        f"{name}_light",
        ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, z + 0.001),
        (hi[0] - lo[0], hi[1] - lo[1]),
        "M_Light_FloorInlay",
        normal="Z",
    )


def marking(
    name: str, x0: float, y0: float, x1: float, y1: float, z: float = 0.0, *, hazard: bool = False
):
    """Worn paint decal 1 mm above the deck (no shadow, no nav effect)."""
    obj = kit.mesh_object(
        name,
        [(x0, y0, z + 0.001), (x1, y0, z + 0.001), (x1, y1, z + 0.001), (x0, y1, z + 0.001)],
        [(0, 1, 2, 3)],
        "M_Deck_Hazard" if hazard else "M_Deck_Marking_White",
        nav="none",
    )
    obj.visible_shadow = False
    return obj


def build_grating(lit: bool = False, size: float = kit.MODULE) -> None:
    """Bar grating over a service trench: bearing bars 30 mm deep on 34 mm
    pitch, cross rods every 100 mm, a perimeter frame, pipes below."""
    h = size / 2
    name = "SM_Grating_120_Lit" if lit else "SM_Grating_120"
    bars = kit.MeshBuilder()
    pitch, bar_t, bar_d = 0.034, 0.004, 0.03
    x = -h + 0.03
    while x < h - 0.03:
        bars.box(
            (x - bar_t / 2, -h + 0.02, -bar_d), (x + bar_t / 2, h - 0.02, 0.0), "M_Floor_Grating"
        )
        x += pitch
    y = -h + 0.05
    while y < h - 0.04:
        bars.box((-h + 0.02, y - 0.003, -0.012), (h - 0.02, y + 0.003, -0.004), "M_Floor_Grating")
        y += 0.1
    bars.build(f"{name}_bars", bevel_width=0.0, nav="walk")
    frame = kit.MeshBuilder()
    for lo, hi in (
        ((-h, -h, -0.06), (h, -h + 0.02, 0.0)),
        ((-h, h - 0.02, -0.06), (h, h, 0.0)),
        ((-h, -h, -0.06), (-h + 0.02, h, 0.0)),
        ((h - 0.02, -h, -0.06), (h, h, 0.0)),
    ):
        frame.box(lo, hi, "M_Struct_Gunmetal")
    frame.build(f"{name}_frame", bevel_width=0.003)
    trench = kit.MeshBuilder()
    depth = 0.55
    trench.box((-h, -h, -depth - 0.05), (h, h, -depth), "M_Hull_Structure")
    trench.box((-h, -h, -depth), (-h + 0.04, h, -0.06), "M_Hull_Structure")
    trench.box((h - 0.04, -h, -depth), (h, h, -0.06), "M_Hull_Structure")
    trench.build(f"{name}_trench", bevel_width=0.006)
    pipes = kit.MeshBuilder()
    pipes.tube((-h, -0.25, -0.38), (h, -0.25, -0.38), 0.07, "M_Hull_PipeInsulated", segments=16)
    pipes.tube((-h, 0.05, -0.42), (h, 0.05, -0.42), 0.045, "M_Hull_Pipe", segments=14)
    pipes.tube((-h, 0.28, -0.44), (h, 0.28, -0.44), 0.03, "M_Hull_Pipe", segments=12)
    pipes.box((-0.02, -0.45, -depth), (0.02, 0.45, -0.3), "M_Struct_Gunmetal")
    pipes.build(f"{name}_pipes", bevel_width=0.004)
    if lit:
        kit.emissive_panel(
            f"{name}_lamp", (0.0, 0.45, -0.2), (0.3, 0.06), "M_Light_Maint_Amber", normal="-Y"
        )


kit.register_variant("SM_Grating_120", build_grating, dims=(1.2, 1.2, 0.6), nav="walk")
kit.register_variant(
    "SM_Grating_120_Lit", build_grating, dims=(1.2, 1.2, 0.6), nav="walk", lit=True
)
