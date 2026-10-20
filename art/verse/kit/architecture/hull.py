"""Hull structure that fills every part of a deck plate outside the rooms.

Seen from the plate camera the hull voids read as open framing below deck
level: frames (ribs) every 2.4 m across the ship, longitudinal stringers,
pipe runs, cable trays and machinery on a dark tank top 2.4 m down, lit by
dim red service lamps and a few cold white work lamps (dark
gunmetal, never brown). Nothing rises above Z = 0, so the structure
never hides a room behind it.

* ``SM_Hull_Bay_A`` .. ``SM_Hull_Bay_D`` - 2.4 x 2.4 m bays (pipes only,
  pump, cable trays, tank), origin at the bay centre, deck level Z = 0.
* ``SM_Hull_Bay_LampRed`` / ``_LampWhite`` - a bay with a service lamp and its light.
* :func:`fill_hull` - tiles bays over a rectangle on the global 2.4 m grid;
  the variant per bay comes from a stable hash, lamps on a regular rhythm.
"""

from __future__ import annotations

import math

import bpy
from lib import kit

BAY = 2.4
DEPTH = 2.4
VARIANTS = ("A", "B", "C", "D")


def _frames(name: str) -> None:
    """Rib along Y at the bay's -X edge, stringer along X at its -Y edge."""
    h = BAY / 2
    mb = kit.MeshBuilder()
    # Rib: I-section, web 30 mm, flanges 240 mm, lightening gaps in the web.
    for y0, y1 in ((-h, -0.55), (-0.25, 0.25), (0.55, h)):
        mb.box((-h - 0.015, y0, -DEPTH), (-h + 0.015, y1, -0.04), "M_Hull_Structure")
    mb.box((-h - 0.015, -h, -DEPTH), (-h + 0.015, h, -DEPTH + 0.5), "M_Hull_Structure")
    mb.box((-h - 0.015, -h, -0.4), (-h + 0.015, h, -0.04), "M_Hull_Structure")
    mb.box((-h - 0.12, -h, -0.04), (-h + 0.12, h, 0.0), "M_Hull_Structure")
    # Stringer: lower T-section along X.
    mb.box((-h, -h - 0.012, -DEPTH), (h, -h + 0.012, -0.9), "M_Hull_Structure")
    mb.box((-h, -h - 0.1, -0.94), (h, -h + 0.1, -0.9), "M_Hull_Structure")
    # Tank top plating.
    mb.box((-h, -h, -DEPTH - 0.06), (h, h, -DEPTH), "M_Hull_Structure")
    mb.build(f"{name}_frames", bevel_width=0.008, nav="none")


def _pipes(name: str, seed: int) -> None:
    h = BAY / 2
    mb = kit.MeshBuilder()
    runs = (
        (-0.7, -1.35, 0.11, "M_Hull_PipeInsulated"),
        (-0.35, -1.5, 0.07, "M_Hull_Pipe"),
        (0.75, -1.2, 0.05, "M_Hull_Pipe"),
    )
    for y, z, r, mat in runs[: 2 + seed % 2]:
        mb.tube((-h, y, z), (h, y, z), r, mat, segments=18)
        # Clamp band at the rib.
        mb.tube((-h + 0.05, y, z), (-h + 0.11, y, z), r + 0.012, "M_Struct_Gunmetal", segments=18)
    mb.build(f"{name}_pipes", bevel_width=0.0, nav="none")


def _machinery(name: str, variant: str) -> None:
    h = BAY / 2
    mb = kit.MeshBuilder()
    base = -DEPTH
    if variant == "B":  # pump set on a skid
        mb.box((-0.6, 0.0, base), (0.6, 0.85, base + 0.12), "M_Struct_Gunmetal")
        mb.box((-0.5, 0.1, base + 0.12), (0.05, 0.75, base + 0.85), "M_Hull_Pipe")
        mb.tube(
            (0.05, 0.42, base + 0.48), (0.55, 0.42, base + 0.48), 0.24, "M_Hull_Pipe", segments=20
        )
        mb.tube((-0.25, 0.42, base + 0.85), (-0.25, 0.42, -0.9), 0.06, "M_Hull_Pipe", segments=12)
    elif variant == "C":  # cable trays on the stringer side
        for z in (-1.1, -1.45):
            mb.box((-h, 0.3, z - 0.01), (h, 0.9, z), "M_Struct_Gunmetal")
            mb.box((-h, 0.3, z), (h, 0.32, z + 0.08), "M_Struct_Gunmetal")
            mb.box((-h, 0.88, z), (h, 0.9, z + 0.08), "M_Struct_Gunmetal")
            for i in range(5):
                y = 0.38 + i * 0.1
                mb.tube((-h, y, z + 0.03), (h, y, z + 0.03), 0.022, "M_Rubber_Black", segments=8)
    elif variant == "D":  # horizontal tank in cradles
        mb.tube(
            (-1.0, 0.35, base + 0.7),
            (1.0, 0.35, base + 0.7),
            0.55,
            "M_Hull_PipeInsulated",
            segments=28,
        )
        for x in (-0.6, 0.6):
            mb.box((x - 0.08, -0.15, base), (x + 0.08, 0.85, base + 0.35), "M_Struct_Gunmetal")
    if not mb.is_empty():
        mb.build(f"{name}_machinery", bevel_width=0.01, nav="none")


LAMPS = {
    "red": ("M_Light_Maint_Red", (1.0, 0.07, 0.035), 5.0),
    "white": ("M_Indicator_White", (0.82, 0.9, 1.0), 24.0),
}


def build_bay(variant: str = "A", lamp: str | None = None) -> None:
    name = f"SM_Hull_Bay_{'Lamp' + lamp.title() if lamp else variant}"
    seed = kit.seed_for(name)
    _frames(name)
    _pipes(name, seed)
    _machinery(name, variant)
    if lamp:
        x = -BAY / 2 + 0.03
        housing = kit.MeshBuilder()
        housing.box((x, -0.12, -0.75), (x + 0.07, 0.12, -0.6), "M_Struct_Gunmetal")
        housing.build(f"{name}_lamp_housing", bevel_width=0.004, nav="none")
        kit.emissive_panel(
            f"{name}_lamp", (x + 0.071, 0.0, -0.675), (0.2, 0.1), LAMPS[lamp][0], normal="X"
        )
        light = bpy.data.lights.new(f"{name}_lamp_light", "POINT")
        light.energy = LAMPS[lamp][2]
        light.color = LAMPS[lamp][1]
        light.shadow_soft_size = 0.1
        obj = bpy.data.objects.new(f"{name}_lamp_light", light)
        obj.location = (x + 0.15, 0.0, -0.675)
        kit.link(obj)


def fill_hull(
    prefix: str, x_range: tuple[float, float], y_range: tuple[float, float], *, lamp_every: int = 2
):
    """Tile hull bays over a rectangle snapped to the global 2.4 m grid."""
    x0 = math.floor(x_range[0] / BAY) * BAY
    y0 = math.floor(y_range[0] / BAY) * BAY
    nx = max(1, math.ceil((x_range[1] - x0) / BAY))
    ny = max(1, math.ceil((y_range[1] - y0) / BAY))
    for i in range(nx):
        for j in range(ny):
            cx, cy = x0 + (i + 0.5) * BAY, y0 + (j + 0.5) * BAY
            gi, gj = round(cx / BAY), round(cy / BAY)
            if (gi + 2 * gj) % lamp_every == 0:
                piece = "SM_Hull_Bay_LampWhite" if (gi + gj) % 3 else "SM_Hull_Bay_LampRed"
            else:
                piece = f"SM_Hull_Bay_{VARIANTS[kit.seed_for(gi, gj) % len(VARIANTS)]}"
            kit.place(piece, (cx, cy, 0.0), 0.0, id=f"{prefix}_{i:02d}_{j:02d}", nav="none")


for _v in VARIANTS:
    kit.register_variant(
        f"SM_Hull_Bay_{_v}", build_bay, dims=(BAY, BAY, DEPTH), nav="none", variant=_v
    )
for _lamp in LAMPS:
    kit.register_variant(
        f"SM_Hull_Bay_Lamp{_lamp.title()}",
        build_bay,
        dims=(BAY, BAY, DEPTH),
        nav="none",
        variant="A",
        lamp=_lamp,
    )
