"""Hangar shell, arena zones and armoury of the Unreal hangar, as boxes.

Plan metres, the frame of `hangar_layout.py` and coordinates 3.1: `x` grows
east (0 = west hull wall, 100 = east), `z` grows toward the near wall (0 = the
hero wall, 62 = the near wall), `h` is height above the hall floor. Unreal
space is `(100 x, 100 z, 100 h)` cm (coordinates 2.1, three.js frame with
y = h), so a box converts by scaling only.

Everything the arena is made of is listed here once: the analysis (`nav`,
`flow`), the placement export (`placements`) and the spec
(docs/verse/unreal/arena.md) all read these tables. Change the arena here,
then rerun `python art/verse/decks/hangar/unreal_arena_build.py` and the
tests in tests/verse/test_verse_hangar_arena.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DECK = "hangar"
OWNER = "WP11"

HALL = (0.0, 100.0, 0.0, 62.0)
CEILING_H = 21.0
FLOOR_T = 0.5

#: Walkable arena bounds (x0, x1, z0, z1): 50 x 40 m inside the hall (A11.1).
ARENA = (25.0, 75.0, 4.0, 44.0)
LEVELS = {"L0": 0.0, "L1": 3.0, "L2": 6.0}
#: Height bands that count as one level for the A11.1 share rule.
LEVEL_BANDS = (("L0", -1.0, 1.5), ("L1", 1.5, 4.5), ("L2", 4.5, 9.0))

#: Launch well opening (x0, x1, z0, z1); 26 m deep, the floor never breaks.
WELL = (27.0, 37.0, 9.0, 19.0)
WELL_DEPTH = 26.0

ZONES = ("shell", "arena_canyon", "arena_shuttle", "arena_booth", "arena_catwalks", "armoury")
ARENA_ZONES = ("arena_canyon", "arena_shuttle", "arena_booth", "arena_catwalks")

#: Destruction classes of destruction.md 3.2 -> (penetration material, max HP, repair s).
PIECE_CLASSES = {
    "wall_panel": ("sheet_metal", 200.0, 8.0),
    "cladding_wall": ("cladding_panel", 250.0, 8.0),
    "container_wall": ("container_wall", 300.0, 8.0),
    "glass": ("glass", 20.0, 4.0),
    "catwalk": ("catwalk_grating", 1.0, 10.0),
    "ceiling_panel": ("ceiling_panel", 60.0, 5.0),
}
#: Reference thickness in metres per penetration material (destruction.md 2, rule 9).
REF_THICKNESS_M = {
    "sheet_metal": 0.003,
    "container_wall": 0.004,
    "glass": 0.024,
    "cladding_panel": 0.04,
    "catwalk_grating": 0.03,
    "ceiling_panel": 0.025,
}


@dataclass(frozen=True)
class Box:
    """An axis-aligned solid. `walk` marks a top surface people stand on."""

    id: str
    zone: str
    x0: float
    x1: float
    z0: float
    z1: float
    h0: float
    h1: float
    family: str  # piece family; the placement piece is SM_<Family> / GC_<Family>
    sight: bool = True  # blocks sight (glass, grating and railings do not)
    solid: bool = True  # blocks pawns
    walk: bool = False
    material: str = "concrete"
    piece_class: str | None = None  # destruction class, None = never breaks
    layer: str = "arena"  # "base", "day" or "arena"

    @property
    def size(self) -> tuple[float, float, float]:
        return (self.x1 - self.x0, self.z1 - self.z0, self.h1 - self.h0)

    @property
    def centre(self) -> tuple[float, float, float]:
        return ((self.x0 + self.x1) / 2, (self.z0 + self.z1) / 2, (self.h0 + self.h1) / 2)


@dataclass(frozen=True)
class Ramp:
    """A stair or ramp: a walk surface whose height runs linearly along one axis."""

    id: str
    zone: str
    x0: float
    x1: float
    z0: float
    z1: float
    h_start: float  # height at the start edge (x0 for axis "x", z0 for axis "z")
    h_end: float
    axis: str  # "x" or "z"
    family: str = "Stair"
    layer: str = "arena"

    def height_at(self, x: float, z: float) -> float:
        if self.axis == "x":
            t = (x - self.x0) / (self.x1 - self.x0)
        else:
            t = (z - self.z0) / (self.z1 - self.z0)
        t = min(1.0, max(0.0, t))
        return self.h_start + (self.h_end - self.h_start) * t


@dataclass(frozen=True)
class Spawn:
    id: str
    zone: str
    x: float
    z: float
    h: float
    heading_deg: float  # Unreal heading: 0 = +X (east), 90 = +Y (toward the near wall)


@dataclass(frozen=True)
class Light:
    id: str
    zone: str
    x: float
    z: float
    h: float
    type: str  # spot, rect, point
    kelvin: float
    intensity_lm: float
    attenuation_m: float
    cone_deg: float | None = None
    source_size_m: float | None = None
    pitch_deg: float = -90.0  # spots point down unless stated


@dataclass(frozen=True)
class Station:
    id: str
    kind: str
    zone: str
    x: float
    z: float
    h: float
    heading_deg: float
    family: str
    size: tuple[float, float, float]


@dataclass
class Layout:
    boxes: list[Box] = field(default_factory=list)
    ramps: list[Ramp] = field(default_factory=list)
    spawns: list[Spawn] = field(default_factory=list)
    lights: list[Light] = field(default_factory=list)
    stations: list[Station] = field(default_factory=list)

    def zone_boxes(self, zone: str) -> list[Box]:
        return [b for b in self.boxes if b.zone == zone]

    def zone_ramps(self, zone: str) -> list[Ramp]:
        return [r for r in self.ramps if r.zone == zone]


def _split(a0: float, a1: float, step: float) -> list[tuple[float, float]]:
    """Cut [a0, a1] into pieces of about `step` (destructibles are per segment)."""
    n = max(1, round((a1 - a0) / step))
    width = (a1 - a0) / n
    return [(a0 + i * width, a0 + (i + 1) * width) for i in range(n)]


# ---------------------------------------------------------------------------
# shell: hall floor, hull walls, ceiling, launch well, arena perimeter
# ---------------------------------------------------------------------------


def _shell(out: Layout) -> None:
    z = "shell"
    wx0, wx1, wz0, wz1 = WELL
    hx0, hx1, hz0, hz1 = HALL
    floor = dict(zone=z, h0=-FLOOR_T, h1=0.0, family="HangarFloor", walk=True, layer="base")
    # The hall floor never breaks (A11.7): concrete, no destruction class.
    out.boxes += [
        Box("floor_north", x0=hx0, x1=hx1, z0=hz0, z1=wz0, **floor),
        Box("floor_south", x0=hx0, x1=hx1, z0=wz1, z1=hz1, **floor),
        Box("floor_west", x0=hx0, x1=wx0, z0=wz0, z1=wz1, **floor),
        Box("floor_east", x0=wx1, x1=hx1, z0=wz0, z1=wz1, **floor),
    ]
    wall = dict(zone=z, family="HullWall", layer="base")
    out.boxes += [
        Box("hero_wall", x0=hx0, x1=hx1, z0=hz0, z1=1.5, h0=0.0, h1=22.0, **wall),
        Box("near_wall", x0=hx0, x1=hx1, z0=61.6, z1=62.6, h0=0.0, h1=CEILING_H, **wall),
        Box("hull_west", x0=hx0, x1=2.5, z0=1.5, z1=61.6, h0=0.0, h1=CEILING_H, **wall),
        Box("hull_east", x0=97.5, x1=hx1, z0=1.5, z1=61.6, h0=0.0, h1=CEILING_H, **wall),
        Box(
            "ceiling",
            x0=hx0,
            x1=hx1,
            z0=hz0,
            z1=hz1,
            h0=CEILING_H,
            h1=CEILING_H + 1.0,
            zone=z,
            family="HangarCeiling",
            layer="base",
        ),
    ]
    pit = dict(zone=z, family="WellWall", layer="base", h0=-WELL_DEPTH, h1=0.0)
    out.boxes += [
        Box("well_wall_n", x0=wx0, x1=wx1, z0=wz0, z1=wz0 + 0.5, **pit),
        Box("well_wall_s", x0=wx0, x1=wx1, z0=wz1 - 0.5, z1=wz1, **pit),
        Box("well_wall_w", x0=wx0, x1=wx0 + 0.5, z0=wz0, z1=wz1, **pit),
        Box("well_wall_e", x0=wx1 - 0.5, x1=wx1, z0=wz0, z1=wz1, **pit),
        # Pit floor: not part of the arena nav (fall = death volume, WP02 world damage).
        Box(
            "well_floor",
            x0=wx0,
            x1=wx1,
            z0=wz0,
            z1=wz1,
            h0=-WELL_DEPTH - 0.5,
            h1=-WELL_DEPTH,
            zone=z,
            family="WellFloor",
            layer="base",
        ),
    ]
    # Structural columns of the roof truss, base layer: they also cut the long
    # diagonals of the open floor.
    for i, (cx, cz) in enumerate(((41.5, 10.5), (41.5, 26.5), (57.2, 21.5), (57.5, 9.0)), 1):
        out.boxes.append(
            Box(
                f"column_{i}",
                z,
                cx - 0.6,
                cx + 0.6,
                cz - 0.6,
                cz + 0.6,
                0.0,
                CEILING_H,
                "TrussColumn",
                layer="base",
            )
        )
    # Hero wall pier: splits the north catwalk, so the 50 m run along the wall is two.
    out.boxes.append(Box("hero_pier", z, 49.0, 51.0, 1.5, 7.0, 0.0, 12.0, "HeroPier", layer="base"))
    # Arena perimeter: blast barriers plus a see-through mesh fence, arena layer only.
    ax0, ax1, az0, az1 = ARENA
    barrier = dict(zone=z, family="BlastBarrier", h0=0.0, h1=4.5, layer="arena")
    fence = dict(zone=z, family="ArenaFence", h0=4.5, h1=10.0, sight=False, layer="arena")
    for name, x0, x1, z0, z1 in (
        ("west", ax0 - 0.6, ax0, az0, az1),
        ("south", ax0 - 0.6, ax1 + 0.6, az1, az1 + 0.6),
        ("east", ax1, ax1 + 0.6, az0, az1),
    ):
        for k, (a, b) in enumerate(
            _split(z0, z1, 10.0) if name != "south" else _split(x0, x1, 10.0), 1
        ):
            if name == "south":
                out.boxes.append(Box(f"barrier_{name}_{k}", x0=a, x1=b, z0=z0, z1=z1, **barrier))
                out.boxes.append(Box(f"fence_{name}_{k}", x0=a, x1=b, z0=z0, z1=z1, **fence))
            else:
                out.boxes.append(Box(f"barrier_{name}_{k}", x0=x0, x1=x1, z0=a, z1=b, **barrier))
                out.boxes.append(Box(f"fence_{name}_{k}", x0=x0, x1=x1, z0=a, z1=b, **fence))
    # Railing around the well: blocks pawns, not sight.
    rail = dict(zone=z, family="Railing", h0=0.0, h1=1.1, sight=False, layer="arena")
    out.boxes += [
        Box("well_rail_n", x0=wx0, x1=wx1, z0=wz0 - 0.1, z1=wz0, **rail),
        Box("well_rail_s", x0=wx0, x1=wx1, z0=wz1, z1=wz1 + 0.1, **rail),
        Box("well_rail_w", x0=wx0 - 0.1, x1=wx0, z0=wz0, z1=wz1, **rail),
        Box("well_rail_e", x0=wx1, x1=wx1 + 0.1, z0=wz0, z1=wz1, **rail),
    ]
    # Work lights hang from the roof truss: hard, neutral-warm, shadowed (README Look).
    n = 0
    for lx in (12.0, 32.0, 50.0, 68.0, 88.0):
        for lz in (8.0, 24.0, 40.0, 54.0):
            n += 1
            out.lights.append(
                Light(
                    f"work_{n:02d}",
                    z,
                    lx,
                    lz,
                    18.5,
                    "spot",
                    4300.0,
                    42000.0,
                    30.0,
                    cone_deg=55.0,
                    source_size_m=0.4,
                )
            )


# ---------------------------------------------------------------------------
# arena_catwalks: upper level, ceiling panels, launch well crossing
# ---------------------------------------------------------------------------

CAT_T = 0.03  # grating deck thickness: the catwalk_grating reference (destruction 9)


def _catwalk_run(
    out: Layout, name: str, x0: float, x1: float, z0: float, z1: float, along: str
) -> None:
    z = "arena_catwalks"
    h = LEVELS["L2"]
    a0, a1 = (x0, x1) if along == "x" else (z0, z1)
    for k, (a, b) in enumerate(_split(a0, a1, 4.0), 1):
        bx0, bx1, bz0, bz1 = (a, b, z0, z1) if along == "x" else (x0, x1, a, b)
        out.boxes.append(
            Box(
                f"{name}_{k:02d}",
                z,
                bx0,
                bx1,
                bz0,
                bz1,
                h - CAT_T,
                h,
                "CatwalkSegment",
                sight=False,
                walk=True,
                material="catwalk_grating",
                piece_class="catwalk",
            )
        )


def _catwalks(out: Layout) -> None:
    z = "arena_catwalks"
    h = LEVELS["L2"]
    # North run along the hero wall, west leg, east leg over the canyon, well
    # crossing and its landing, and the south gantry over the open floor.
    _catwalk_run(out, "cat_north_w", 25.2, 49.0, 4.0, 6.4, "x")
    _catwalk_run(out, "cat_north_e", 51.0, 74.8, 4.0, 6.4, "x")
    _catwalk_run(out, "cat_west", 25.2, 27.4, 6.4, 32.0, "z")
    _catwalk_run(out, "cat_well", 27.4, 37.0, 13.0, 15.0, "x")
    _catwalk_run(out, "cat_landing", 37.0, 39.6, 13.0, 17.0, "x")
    # Railings on the open edges (pawns only).
    rail = dict(zone=z, family="Railing", sight=False)
    out.boxes += [
        Box("cat_north_rail_w", x0=27.4, x1=49.0, z0=6.3, z1=6.4, h0=h, h1=h + 1.1, **rail),
        Box("cat_north_rail_e", x0=63.0, x1=74.8, z0=6.3, z1=6.4, h0=h, h1=h + 1.1, **rail),
        Box("cat_west_rail", x0=27.3, x1=27.4, z0=6.4, z1=13.0, h0=h, h1=h + 1.1, **rail),
        Box("cat_west_rail_2", x0=27.3, x1=27.4, z0=15.0, z1=32.0, h0=h, h1=h + 1.1, **rail),
    ]
    # The south gantry is an enclosed gallery on a solid deck (booth upper room to the east stair):
    # sheet-metal walls that bolts hole and charges breach, so its sightlines are earned.
    out.boxes.append(
        Box(
            "gallery_deck",
            z,
            38.0,
            60.4,
            36.0,
            39.0,
            h - 0.2,
            h,
            "GalleryDeck",
            walk=True,
            material="armor_steel",
        )
    )
    sheet = REF_THICKNESS_M["sheet_metal"]
    for side, (x0, x1, z0) in (("n", (38.0, 57.8, 36.0)), ("s", (38.0, 60.4, 39.0 - sheet))):
        for k, (a, b) in enumerate(_split(x0, x1, 3.0), 1):
            out.boxes.append(
                Box(
                    f"gallery_wall_{side}_{k}",
                    z,
                    a,
                    b,
                    z0,
                    z0 + sheet,
                    h,
                    h + 2.4,
                    "GalleryWallPanel",
                    material="sheet_metal",
                    piece_class="wall_panel",
                )
            )
    out.boxes.append(
        Box("gallery_wall_e", z, 60.4 - 0.2, 60.4, 36.0, 39.0, h, h + 2.4, "GalleryWall")
    )
    out.boxes.append(
        Box("gallery_roof", z, 38.0, 60.4, 36.0, 39.0, h + 2.4, h + 2.6, "GalleryRoof")
    )
    # A container hanging from the gantry crane over the shuttle: cuts the upper diagonals.
    out.boxes.append(
        Box(
            "hung_container",
            z,
            44.0,
            56.0,
            22.0,
            24.6,
            6.5,
            9.5,
            "HungContainer",
            material="armor_steel",
        )
    )
    # Ceiling panels over the north run: break and fall (ceiling_panel), block sight.
    panels = _split(25.2, 49.0, 1.8) + _split(51.0, 74.8, 1.8)
    for k, (a, b) in enumerate(panels, 1):
        out.boxes.append(
            Box(
                f"ceil_panel_{k:02d}",
                z,
                a,
                b,
                4.0,
                6.4,
                9.0,
                9.0 + 0.025,
                "CeilingPanel",
                material="ceiling_panel",
                piece_class="ceiling_panel",
            )
        )
    # Hanging blast screens below the truss: break the long upper-level diagonals.
    for k, (sx0, sx1, sz0, sz1) in enumerate(
        ((43.0, 49.0, 20.0, 20.3), (51.0, 57.0, 27.5, 27.8), (31.0, 31.3, 27.0, 33.0)), 1
    ):
        out.boxes.append(
            Box(
                f"screen_{k}",
                z,
                sx0,
                sx1,
                sz0,
                sz1,
                4.2,
                9.0,
                "HangingScreen",
                material="armor_steel",
            )
        )
    # Stairs between the levels.
    out.ramps += [
        Ramp("stair_cat_canyon", z, 60.6, 63.0, 6.4, 11.0, h, LEVELS["L1"], "z"),
        Ramp("stair_cat_shuttle", z, 39.6, 46.0, 15.0, 17.0, h, LEVELS["L1"], "x"),
        Ramp("stair_gantry", z, 57.8, 59.8, 28.0, 36.0, 0.0, h, "z"),
    ]
    out.lights += [
        Light("cat_north_a", z, 34.0, 5.0, 8.8, "rect", 3600.0, 2400.0, 9.0, source_size_m=1.2),
        Light("cat_north_b", z, 52.0, 5.0, 8.8, "rect", 3600.0, 2400.0, 9.0, source_size_m=1.2),
        Light("cat_gantry", z, 50.0, 37.5, h + 2.3, "rect", 3200.0, 1500.0, 6.0, source_size_m=0.8),
    ]


# ---------------------------------------------------------------------------
# arena_booth: glazed lookout with breakable glass, mid level
# ---------------------------------------------------------------------------


def _booth(out: Layout) -> None:
    z = "arena_booth"
    l1 = LEVELS["L1"]
    bx0, bx1, bz0, bz1 = 25.0, 38.0, 32.0, 44.0
    out.boxes.append(Box("plinth", z, bx0, bx1, bz0, bz1, 0.0, l1, "BoothPlinth", walk=True))
    glass_t = REF_THICKNESS_M["glass"]
    clad = REF_THICKNESS_M["cladding_panel"]
    up = 6.0 + 0.3  # upper room floor (L2)
    # Lower room (L1): cladding on the north and south faces, glass to the east.
    for side, zz in (("n", bz0), ("s", bz1 - clad)):
        for k, (a, b) in enumerate(_split(bx0, bx1, 3.0), 1):
            out.boxes.append(
                Box(
                    f"wall_{side}_{k}",
                    z,
                    a,
                    b,
                    zz,
                    zz + clad,
                    l1,
                    6.0,
                    "BoothCladding",
                    material="cladding_panel",
                    piece_class="cladding_wall",
                )
            )
    # East face: door from the bridge and the floor stair at z 32.2..35.5.
    out.boxes.append(Box("parapet_e", z, bx1 - 0.2, bx1, 35.5, 39.5, l1, l1 + 0.9, "BoothParapet"))
    out.boxes.append(Box("lintel_e", z, bx1 - 0.2, bx1, 35.5, 39.5, l1 + 2.7, 6.0, "BoothParapet"))
    out.boxes.append(Box("wall_e_s", z, bx1 - 0.2, bx1, 39.5, bz1, l1, 6.0, "BoothWallSolid"))
    for k, (a, b) in enumerate(_split(35.5, 39.5, 2.0), 1):
        out.boxes.append(
            Box(
                f"glass_e_{k}",
                z,
                bx1 - 0.1 - glass_t,
                bx1 - 0.1,
                a,
                b,
                l1 + 0.9,
                l1 + 2.7,
                "BoothGlass",
                sight=False,
                material="glass",
                piece_class="glass",
            )
        )
    out.boxes.append(Box("wall_w", z, bx0, bx0 + 0.2, bz0, bz1, l1, 6.0, "BoothWallSolid"))
    # Upper room (L2): from the west catwalk leg, the south gallery and an inner stair.
    out.boxes += [
        Box("upper_floor_a", z, 28.0, bx1, bz0, bz1, 6.0, up, "BoothFloor", walk=True),
        Box("upper_floor_b", z, bx0, 28.0, bz0, 35.5, 6.0, up, "BoothFloor", walk=True),
        Box("upper_wall_n", z, 27.6, bx1, bz0, bz0 + 0.2, up, up + 3.0, "BoothWallSolid"),
        Box("upper_wall_w", z, bx0, bx0 + 0.2, bz0 + 0.2, bz1, up, up + 3.0, "BoothWallSolid"),
        Box("upper_wall_e_n", z, bx1 - 0.2, bx1, bz0, 36.0, up, up + 3.0, "BoothWallSolid"),
        Box("upper_wall_e_s", z, bx1 - 0.2, bx1, 39.0, bz1, up, up + 3.0, "BoothWallSolid"),
        Box("upper_parapet_s", z, bx0, bx1, bz1 - 0.2, bz1, up, up + 0.9, "BoothParapet"),
        Box("upper_roof", z, bx0, bx1, bz0, bz1, up + 3.0, up + 3.3, "BoothRoof"),
    ]
    for k, (a, b) in enumerate(_split(bx0, bx1, 2.0), 1):
        out.boxes.append(
            Box(
                f"upper_glass_s_{k}",
                z,
                a,
                b,
                bz1 - 0.1 - glass_t,
                bz1 - 0.1,
                up + 0.9,
                up + 2.7,
                "BoothGlass",
                sight=False,
                material="glass",
                piece_class="glass",
            )
        )
    out.ramps.append(Ramp("stair_booth_inner", z, 26.2, 28.0, 35.5, 41.5, up, l1, "z"))
    # Consoles inside: half cover.
    out.boxes += [
        Box(
            "console_1",
            z,
            30.0,
            34.0,
            35.0,
            35.8,
            l1,
            l1 + 1.0,
            "BoothConsole",
            material="sheet_metal",
        ),
        Box(
            "console_2",
            z,
            28.0,
            29.0,
            38.0,
            40.5,
            l1,
            l1 + 1.0,
            "BoothConsole",
            material="sheet_metal",
        ),
    ]
    # Bridge to the shuttle roof (grating) and the floor stair.
    out.boxes.append(
        Box(
            "bridge_shuttle",
            z,
            bx1,
            46.0,
            31.5,
            34.0,
            l1 - CAT_T,
            l1,
            "BridgeGrating",
            sight=False,
            walk=True,
            material="catwalk_grating",
            piece_class="catwalk",
        )
    )
    out.ramps.append(Ramp("stair_booth_floor", z, 38.0, 39.6, 34.0, 42.0, l1, 0.0, "z"))
    out.lights += [
        Light("booth_a", z, 30.0, 37.0, l1 + 2.9, "rect", 3500.0, 1800.0, 7.0, source_size_m=1.0),
        Light("booth_b", z, 35.0, 37.0, l1 + 2.9, "rect", 3500.0, 1800.0, 7.0, source_size_m=1.0),
    ]


# ---------------------------------------------------------------------------
# arena_shuttle: walkable gunship as the mid building
# ---------------------------------------------------------------------------


def _shuttle(out: Layout) -> None:
    z = "arena_shuttle"
    l1 = LEVELS["L1"]
    sx0, sx1, sz0, sz1 = 46.0, 54.0, 15.0, 33.0
    hatch = (23.0, 25.0)
    hull = dict(zone=z, family="GunshipHull", material="armor_steel")
    out.boxes += [
        Box("hull_w_fore", x0=sx0, x1=sx0 + 0.4, z0=sz0, z1=hatch[0], h0=0.0, h1=l1, **hull),
        Box("hull_w_aft", x0=sx0, x1=sx0 + 0.4, z0=hatch[1], z1=sz1, h0=0.0, h1=l1, **hull),
        Box("hull_e_fore", x0=sx1 - 0.4, x1=sx1, z0=sz0, z1=hatch[0], h0=0.0, h1=l1, **hull),
        Box("hull_e_aft", x0=sx1 - 0.4, x1=sx1, z0=hatch[1], z1=sz1, h0=0.0, h1=l1, **hull),
        Box("nose", x0=sx0, x1=sx1, z0=sz0, z1=sz0 + 0.4, h0=0.0, h1=l1, **hull),
        Box(
            "roof",
            zone=z,
            x0=sx0,
            x1=sx1,
            z0=sz0,
            z1=sz1,
            h0=l1 - 0.4,
            h1=l1,
            family="GunshipRoof",
            walk=True,
            material="armor_steel",
        ),
        # Dorsal turret: cover on the roof, cuts the upper diagonals.
        Box(
            "turret",
            zone=z,
            x0=48.8,
            x1=51.2,
            z0=21.0,
            z1=25.5,
            h0=l1,
            h1=l1 + 2.2,
            family="GunshipTurret",
            material="armor_steel",
        ),
    ]
    # Interior bulkhead with breakable service panels (sheet metal): a choice to open a lane.
    out.boxes += [
        Box(
            "bulkhead_w",
            z,
            sx0 + 0.4,
            49.0,
            27.8,
            28.0,
            0.0,
            l1 - 0.4,
            "GunshipBulkhead",
            material="armor_steel",
        ),
        Box(
            "bulkhead_e",
            z,
            51.0,
            sx1 - 0.4,
            27.8,
            28.0,
            0.0,
            l1 - 0.4,
            "GunshipBulkhead",
            material="armor_steel",
        ),
        Box(
            "service_panel",
            z,
            49.0,
            51.0,
            27.85,
            27.85 + REF_THICKNESS_M["sheet_metal"],
            0.0,
            2.2,
            "GunshipServicePanel",
            material="sheet_metal",
            piece_class="wall_panel",
        ),
    ]
    # Engine nacelles outside the tail and ground cover around the pad.
    out.boxes += [
        Box(
            "nacelle_w",
            z,
            43.8,
            46.0,
            28.0,
            33.0,
            0.4,
            2.4,
            "GunshipNacelle",
            material="armor_steel",
        ),
        Box(
            "nacelle_e",
            z,
            54.0,
            56.2,
            28.0,
            33.0,
            0.4,
            2.4,
            "GunshipNacelle",
            material="armor_steel",
        ),
        Box("fuel_cart", z, 42.0, 44.4, 39.6, 44.0, 0.0, 2.4, "FuelCart", material="sheet_metal"),
        Box("crate_n_1", z, 44.0, 46.0, 6.8, 8.8, 0.0, 2.4, "CargoCrate", material="sheet_metal"),
        Box(
            "crate_n_2", z, 51.5, 53.5, 9.0, 11.0, 0.0, 1.2, "CargoCrateLow", material="sheet_metal"
        ),
        Box("barrier_s", z, 47.0, 52.0, 40.5, 41.1, 0.0, 1.1, "LowBarrier"),
        Box("crate_s", z, 56.0, 58.0, 38.6, 40.6, 0.0, 2.2, "CargoCrate", material="sheet_metal"),
        Box("crate_w_1", z, 30.0, 32.0, 23.0, 25.0, 0.0, 2.4, "CargoCrate", material="sheet_metal"),
        Box("lowwall_w", z, 33.6, 36.0, 28.4, 29.0, 0.0, 1.1, "LowBarrier"),
    ]
    out.lights += [
        Light("cabin_a", z, 50.0, 19.0, l1 - 0.5, "rect", 3800.0, 1200.0, 6.0, source_size_m=0.8),
        Light("cabin_b", z, 50.0, 30.0, l1 - 0.5, "rect", 3800.0, 1200.0, 6.0, source_size_m=0.8),
    ]


# ---------------------------------------------------------------------------
# arena_canyon: container rows with destructible walls and 3.6 m aisles
# ---------------------------------------------------------------------------

CONTAINER_W = 2.4
CONTAINER_H = 3.0
AISLE = 3.6
ROW_X0 = (60.6, 60.6 + CONTAINER_W + AISLE, 60.6 + 2 * (CONTAINER_W + AISLE))
#: Containers per row as (z0, z1, roof walkable). Gaps between them are the cross alleys.
ROWS = (
    ((11.0, 17.0, True), (17.0, 23.0, True), (25.0, 31.0, False), (31.0, 37.0, False)),
    (
        (5.0, 11.0, False),
        (13.0, 19.0, False),
        (19.0, 25.0, False),
        (27.0, 33.0, True),
        (33.0, 39.0, True),
    ),
    (
        (5.0, 11.0, False),
        (11.0, 17.0, False),
        (19.0, 25.0, False),
        (27.0, 33.0, False),
        (35.0, 41.0, False),
    ),
)


def _canyon(out: Layout) -> None:
    z = "arena_canyon"
    wt = REF_THICKNESS_M["container_wall"]
    for r, (x0, row) in enumerate(zip(ROW_X0, ROWS, strict=True), 1):
        x1 = x0 + CONTAINER_W
        for c, (z0, z1, roof_walk) in enumerate(row, 1):
            cid = f"r{r}c{c}"
            # Long walls break (container_wall); the frame and roof do not.
            out.boxes += [
                Box(
                    f"{cid}_wall_w",
                    z,
                    x0,
                    x0 + wt,
                    z0,
                    z1,
                    0.0,
                    CONTAINER_H - 0.2,
                    "ContainerWall",
                    material="container_wall",
                    piece_class="container_wall",
                ),
                Box(
                    f"{cid}_wall_e",
                    z,
                    x1 - wt,
                    x1,
                    z0,
                    z1,
                    0.0,
                    CONTAINER_H - 0.2,
                    "ContainerWall",
                    material="container_wall",
                    piece_class="container_wall",
                ),
                Box(
                    f"{cid}_roof",
                    z,
                    x0,
                    x1,
                    z0,
                    z1,
                    CONTAINER_H - 0.2,
                    CONTAINER_H,
                    "ContainerRoof",
                    walk=roof_walk,
                    material="armor_steel",
                ),
            ]
            # Every second container has its doors shut at the north end: a dead
            # end that a charge opens.
            if c % 2 == 0:
                out.boxes.append(
                    Box(
                        f"{cid}_doors",
                        z,
                        x0,
                        x1,
                        z0,
                        z0 + wt,
                        0.0,
                        CONTAINER_H - 0.2,
                        "ContainerDoors",
                        material="container_wall",
                        piece_class="container_wall",
                    )
                )
    l1 = LEVELS["L1"]
    out.boxes.append(
        Box(
            "bridge_shuttle",
            z,
            54.0,
            ROW_X0[0],
            15.0,
            17.0,
            l1 - CAT_T,
            l1,
            "BridgeGrating",
            sight=False,
            walk=True,
            material="catwalk_grating",
            piece_class="catwalk",
        )
    )
    r2x0 = ROW_X0[1]
    out.ramps.append(Ramp("stair_r2", z, r2x0, r2x0 + CONTAINER_W, 39.0, 43.6, l1, 0.0, "z"))
    for k, cz in enumerate((9.0, 21.0, 33.0), 1):
        for a, ax in enumerate(
            (ROW_X0[0] + CONTAINER_W + AISLE / 2, ROW_X0[1] + CONTAINER_W + AISLE / 2), 1
        ):
            out.lights.append(
                Light(f"aisle_{k}{a}", z, ax, cz, 7.5, "spot", 3200.0, 5000.0, 10.0, cone_deg=60.0)
            )


# ---------------------------------------------------------------------------
# armoury: loadout room in the front band, station placements for WP16/WP18
# ---------------------------------------------------------------------------

ARMOURY = (77.0, 97.5, 47.2, 61.6)


def _armoury(out: Layout) -> None:
    z = "armoury"
    x0, x1, z0, z1 = ARMOURY
    h = 4.5
    wall = dict(zone=z, family="ArmouryWall", layer="base")
    out.boxes += [
        Box("wall_n_w", x0=x0, x1=85.0, z0=z0, z1=z0 + 0.3, h0=0.0, h1=h, **wall),
        Box("wall_n_e", x0=88.0, x1=x1, z0=z0, z1=z0 + 0.3, h0=0.0, h1=h, **wall),
        Box("lintel_n", x0=85.0, x1=88.0, z0=z0, z1=z0 + 0.3, h0=2.6, h1=h, **wall),
        Box("wall_w", x0=x0, x1=x0 + 0.3, z0=z0, z1=z1, h0=0.0, h1=h, **wall),
        Box(
            "ceiling",
            zone=z,
            x0=x0,
            x1=x1,
            z0=z0,
            z1=z1,
            h0=h,
            h1=h + 0.3,
            family="ArmouryCeiling",
            layer="base",
        ),
        Box(
            "rack_e",
            zone=z,
            x0=96.7,
            x1=97.5,
            z0=50.0,
            z1=58.0,
            h0=0.0,
            h1=2.4,
            family="ArmouryRack",
            material="sheet_metal",
            layer="base",
        ),
        Box(
            "bench",
            zone=z,
            x0=83.0,
            x1=91.0,
            z0=56.5,
            z1=57.3,
            h0=0.0,
            h1=0.5,
            family="ArmouryBench",
            material="sheet_metal",
            layer="base",
        ),
    ]
    out.stations += [
        # The duel entry (parity S-17, D-04): WP16 owns the station class, WP18 the panel it opens.
        Station("armoury", "armoury", z, 87.0, 51.5, 0.0, 90.0, "ArmouryConsole", (1.6, 0.8, 1.2)),
        # Loadout display beside the rack: WP18 armoury view on a station screen.
        Station(
            "armoury_loadout",
            "armoury",
            z,
            96.4,
            54.0,
            0.0,
            180.0,
            "ArmouryLoadoutBoard",
            (0.2, 3.0, 2.0),
        ),
    ]
    out.lights += [
        Light("armoury_a", z, 82.0, 54.0, h - 0.1, "rect", 3800.0, 3000.0, 8.0, source_size_m=1.2),
        Light("armoury_b", z, 92.0, 54.0, h - 0.1, "rect", 3800.0, 3000.0, 8.0, source_size_m=1.2),
    ]


# ---------------------------------------------------------------------------
# spawns: AVerseSpawnPoint sockets, at least 8, every pair 20 m path apart (A11.2)
# ---------------------------------------------------------------------------

SPAWNS = (
    Spawn("sp_nw_floor", "arena_catwalks", 26.0, 5.0, 0.0, 45.0),
    Spawn("sp_north_mid", "arena_shuttle", 48.0, 8.0, 0.0, 90.0),
    Spawn("sp_ne_canyon", "arena_canyon", 70.8, 6.0, 0.0, 90.0),
    Spawn("sp_e_canyon", "arena_canyon", 71.0, 40.0, 0.0, 270.0),
    Spawn("sp_south_mid", "arena_shuttle", 48.5, 43.0, 0.0, 270.0),
    Spawn("sp_booth", "arena_booth", 31.5, 40.5, LEVELS["L1"], 0.0),
    Spawn("sp_cat_west", "arena_catwalks", 26.2, 18.0, LEVELS["L2"], 90.0),
    Spawn("sp_shuttle_roof", "arena_shuttle", 50.0, 30.5, LEVELS["L1"], 270.0),
    Spawn("sp_cat_gantry", "arena_catwalks", 57.5, 37.2, LEVELS["L2"], 180.0),
)


# ---------------------------------------------------------------------------
# cover rhythm: blockers placed with the flow tool (unreal_arena.flow) so that
# no unbroken sightline exceeds 40 m (A11.5). Hanging screens cut the upper
# diagonals, cover walls and crates the floor lanes, truss columns both.
# ---------------------------------------------------------------------------

#: (kind, centre x, centre z, along) - "x" or "z" is the long axis of a screen or wall.
COVER = (
    ("screen", 45.0, 28.0, "z"),
    ("screen", 55.0, 10.0, "z"),
    ("screen", 63.0, 30.0, "z"),
    ("wall", 63.0, 40.0, "z"),
    ("screen", 37.0, 22.0, "z"),
    ("screen", 63.0, 36.0, "z"),
    ("screen", 47.0, 10.0, "z"),
    ("screen", 67.0, 8.0, "x"),
    ("screen", 39.0, 18.0, "x"),
    ("column", 41.0, 30.0, ""),
    ("column", 59.0, 24.0, ""),
    ("wall", 47.0, 11.4, "z"),
    ("column", 65.0, 40.0, ""),
    ("screen", 57.0, 14.0, "x"),
    ("column", 47.0, 14.0, ""),
    ("screen", 65.0, 20.0, "z"),
    ("column", 43.0, 22.0, ""),
    ("wall", 59.0, 6.0, "z"),
    ("wall", 45.0, 38.0, "x"),
    ("column", 45.0, 18.0, ""),
    ("crate", 39.0, 8.0, ""),
    ("wall", 59.0, 40.0, "z"),
    ("screen", 49.0, 10.0, "z"),
    ("column", 53.0, 40.0, ""),
    ("column", 41.0, 40.0, ""),
    ("screen_high", 60.0, 17.75, "x"),
    ("wall", 37.0, 24.0, "z"),
    ("wall", 52.0, 37.0, "z"),
    ("screen", 66.0, 24.0, "x"),
    ("screen", 40.0, 22.0, "z"),
    ("screen", 61.0, 37.0, "z"),
    ("column", 55.0, 19.0, ""),
    ("column", 37.0, 27.0, ""),
    ("screen_high", 50.0, 29.0, "x"),
    ("column", 53.0, 8.0, ""),
    ("column", 41.0, 13.0, ""),
    ("wall", 34.0, 30.0, "x"),
    ("wall", 47.0, 39.0, "x"),
    ("screen", 42.0, 35.0, "x"),
    ("screen", 37.0, 30.0, "x"),
)
COVER_SIZES = {
    "screen": (6.0, 0.3, 3.6, 9.0),
    "screen_high": (6.0, 0.3, 5.0, 9.0),
    "wall": (4.0, 0.4, 0.0, 3.4),
    "crate": (2.4, 2.4, 0.0, 2.6),
    "column": (1.2, 1.2, 0.0, CEILING_H),
}


def _cover_zone(kind: str, x: float) -> str:
    if kind == "column":
        return "shell"
    if kind.startswith("screen"):
        return "arena_catwalks"
    if x >= ROW_X0[0] - 0.5:
        return "arena_canyon"
    if x < 40.0:
        return "arena_booth"
    return "arena_shuttle"


def _cover(out: Layout) -> None:
    family = {
        "screen": "HangingScreen",
        "screen_high": "HangingScreen",
        "wall": "CoverWall",
        "crate": "CargoCrate",
        "column": "TrussColumn",
    }
    material = {
        "screen": "armor_steel",
        "screen_high": "armor_steel",
        "wall": "concrete",
        "crate": "sheet_metal",
        "column": "concrete",
    }
    for k, (kind, cx, cz, along) in enumerate(COVER, 1):
        long_, short, h0, h1 = COVER_SIZES[kind]
        wx, wz = (long_, short) if along != "z" else (short, long_)
        if kind in ("crate", "column"):
            wx = wz = long_
        zone = _cover_zone(kind, cx)
        out.boxes.append(
            Box(
                f"cover_{kind.split('_')[0]}_{k:02d}",
                zone,
                cx - wx / 2,
                cx + wx / 2,
                cz - wz / 2,
                cz + wz / 2,
                h0,
                h1,
                family[kind],
                material=material[kind],
                layer="base" if kind == "column" else "arena",
            )
        )


def build() -> Layout:
    out = Layout()
    _shell(out)
    _catwalks(out)
    _booth(out)
    _shuttle(out)
    _canyon(out)
    _armoury(out)
    _cover(out)
    out.spawns = list(SPAWNS)
    return out
