"""The six destructible piece classes and every state they ship (WP06.2, WP06.3).

Pure Python: each `PieceSpec` builds, per state and variant, the render
shells, the collision proxy boxes (`SM_<Piece>_Proxy_<State>[_<n>]`, exported
as `UECOL_Box` primitives) and the opening centroid the server uses to pick a
variant (contracts/destruction.md 3.1). `fracture_chunks` gives the seeded
Voronoi chunks of `SM_<Piece>_Frac`; `debris_sets` picks, per state, the chunks
that really fly (`SM_<Piece>_Frac_<State>_<n>`, the per-state geometry
collections the client spawns, destruction.md 10). Dimensions in metres,
Blender piece space.

Thickness is the material's reference thickness (destruction.md 2 and 9,
decision C4): sheet metal 0.3 cm, corrugated container wall 0.4 cm, cladding
4.0 cm, laminated glass 2.4 cm, bar grating 3.0 cm, ceiling tile 2.5 cm. The
collision proxies of wall-like pieces are flat slabs of exactly that
thickness, so a bolt's traced thickness through a proxy is the reference.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import geometry as g

#: Material wire ids of DA_PenetrationTable (destruction.md 2).
MATERIALS = {
    "sheet_metal": 0.003,
    "container_wall": 0.004,
    "glass": 0.024,
    "cladding_panel": 0.040,
    "catwalk_grating": 0.030,
    "ceiling_panel": 0.025,
}

#: Most rigid bodies a fracture may spawn (destruction.md 10).
MAX_BODIES = 40
#: Fragments under this size are Niagara particles, not rigid bodies.
MIN_RIGID_M = 0.05
#: Rigid bodies per state, by material (unreal/Verse/Data/destruction/tuning.json
#: start_values.debris_bodies through the material's debris type; Breached and
#: Destroyed share the full value). Glass is Niagara only.
DEBRIS_BODIES = {
    "sheet_metal": {"Holed": 12, "Breached": 32, "Destroyed": 32},
    "container_wall": {"Holed": 14, "Breached": 36, "Destroyed": 36},
    "cladding_panel": {"Holed": 16, "Breached": 40, "Destroyed": 40},
    "catwalk_grating": {"Destroyed": 6},
    "ceiling_panel": {"Destroyed": 1},
}
#: A chunk belongs to an opening when its centre lies within this margin of it.
OPENING_MARGIN_M = 0.10

Opening = tuple[float, float, float, float]  # x_min, z_min, x_max, z_max


@dataclass
class StateLook:
    """One state variant of a piece."""

    state: str
    variant: int
    shells: list[g.Mesh]
    proxy_boxes: list[tuple[g.Vec3, g.Vec3]]
    centroid: g.Vec3

    @property
    def proxy_name_suffix(self) -> str:
        return self.state if self.state == "Intact" else f"{self.state}_{self.variant}"


@dataclass
class DebrisSet:
    """The chunks one state's debris burst spawns (`GC_<Piece>_<State>_<n>`)."""

    state: str
    variant: int
    chunks: list[g.Chunk]

    @property
    def name_suffix(self) -> str:
        return self.state if self.state == "Destroyed" else f"{self.state}_{self.variant}"


@dataclass
class PieceSpec:
    name: str
    piece_class: str
    material: str
    width: float
    height: float
    depth: float = 0.0
    sill: float = 0.0
    holed: list[list[Opening]] = field(default_factory=list)
    breached: list[list[Opening]] = field(default_factory=list)
    fracture_cells: int = 24
    #: Breached variant that is a low breach (mantle nav link through it).
    mantle_variant: int | None = None

    @property
    def thickness(self) -> float:
        return MATERIALS[self.material]

    @property
    def thickness_axis(self) -> g.Vec3:
        return (
            (0.0, 0.0, 1.0)
            if self.piece_class in ("CatwalkSegment", "CeilingPanel")
            else (0.0, 1.0, 0.0)
        )

    @property
    def wall_like(self) -> bool:
        return self.piece_class in ("WallPanel", "CladdingWall", "ContainerWall")

    # ----------------------------------------------------------------------
    # Shapes

    def _slab_y(self) -> tuple[float, float]:
        """Y range of the gameplay slab (container: the middle of the corrugation)."""
        if self.piece_class == "ContainerWall":
            mid = self.depth / 2
            return mid - self.thickness / 2, mid + self.thickness / 2
        return 0.0, self.thickness

    def render_shells(self, openings: list[Opening]) -> list[g.Mesh]:
        cls = self.piece_class
        if cls in ("WallPanel", "CladdingWall"):
            return [g.slab_with_openings(self.width, self.height, 0.0, self.thickness, openings)]
        if cls == "ContainerWall":
            strips = g.corrugated(self.width, self.height, self.thickness, self.depth, ribs=8)
            if not openings:
                return [g.corrugated_solid(self.width, self.height, self.thickness, self.depth, 8)]
            return [m for strip in strips for m in _cut_openings(strip, openings)]
        if cls == "GlassPane":
            lo = (-self.width / 2, 0.0, self.sill)
            hi = (self.width / 2, self.thickness, self.sill + self.height)
            return [g.box(lo, hi)]
        if cls == "CatwalkSegment":
            return g.grating(self.width, self.depth, self.thickness, 0.005, 0.03, 0.006)
        if cls == "CeilingPanel":
            return [
                g.box(
                    (-self.width / 2, -self.depth / 2, 0.0),
                    (self.width / 2, self.depth / 2, self.thickness),
                )
            ]
        raise ValueError(cls)

    def proxy_boxes(self, openings: list[Opening]) -> list[tuple[g.Vec3, g.Vec3]]:
        """Collision boxes of a state: the slab minus the openings, merged row by row (<= 16)."""
        if not self.wall_like:
            return [_bounds(self.render_shells([]))]
        y0, y1 = self._slab_y()
        xs = sorted(
            {-self.width / 2, self.width / 2, *(o[0] for o in openings), *(o[2] for o in openings)}
        )
        zs = sorted({0.0, self.height, *(o[1] for o in openings), *(o[3] for o in openings)})
        boxes = []
        for k in range(len(zs) - 1):
            cz = (zs[k] + zs[k + 1]) / 2
            run_start = None
            for i in range(len(xs) - 1):
                cx = (xs[i] + xs[i + 1]) / 2
                solid = not any(o[0] < cx < o[2] and o[1] < cz < o[3] for o in openings)
                if solid and run_start is None:
                    run_start = xs[i]
                if not solid and run_start is not None:
                    boxes.append(((run_start, y0, zs[k]), (xs[i], y1, zs[k + 1])))
                    run_start = None
            if run_start is not None:
                boxes.append(((run_start, y0, zs[k]), (xs[-1], y1, zs[k + 1])))
        return boxes

    def looks(self) -> list[StateLook]:
        out = [
            StateLook(
                "Intact",
                0,
                self.render_shells([]),
                self.proxy_boxes([]),
                (0.0, 0.0, self.height / 2),
            )
        ]
        for state, variants in (("Holed", self.holed), ("Breached", self.breached)):
            for k, openings in enumerate(variants):
                out.append(
                    StateLook(
                        state,
                        k,
                        self.render_shells(openings),
                        self.proxy_boxes(openings),
                        _centroid(openings),
                    )
                )
        return out

    def fracture_chunks(self, seed: int) -> list[g.Chunk]:
        """Seeded Voronoi chunks of the Intact solid; only chunks of at least 5 cm, at most 40."""
        if self.piece_class == "GlassPane":
            return []  # glass breaks into Niagara shards only (destruction.md 2)
        if self.piece_class == "CeilingPanel":
            shell = self.render_shells([])[0]
            return [
                g.Chunk(0, (0.0, 0.0, 0.0), [g.Convex.from_mesh(shell)])
            ]  # the whole tile falls
        if self.piece_class == "ContainerWall":
            parts = g.corrugated(self.width, self.height, self.thickness, self.depth, ribs=8)
        else:
            # Walls fracture as their intact slab; catwalks as their bars and frames.
            parts = self.render_shells([])
        lo, hi = _bounds(parts)
        points = g.voronoi_points(lo, hi, self.fracture_cells, seed)
        chunks = [c for c in g.fracture(parts, points) if c.size() >= MIN_RIGID_M]
        return chunks[:MAX_BODIES]


def _chunk_centre(chunk: g.Chunk) -> g.Vec3:
    lo, hi = chunk.to_mesh().bounds()
    return tuple((lo[i] + hi[i]) / 2 for i in range(3))


def _in_openings(point: g.Vec3, openings: list[Opening], margin: float) -> bool:
    x, z = point[0], point[2]
    return any(
        x0 - margin <= x <= x1 + margin and z0 - margin <= z <= z1 + margin
        for x0, z0, x1, z1 in openings
    )


def debris_sets(spec: PieceSpec, seed: int) -> list[DebrisSet]:
    """Per-state debris bursts, each at most the material's body count for that state.

    Holed and Breached: the chunks of the Intact fracture whose centre lies in the
    variant's openings (nearest the opening centroid first), so the wall that still
    stands never gets a full chunk set inside it. Destroyed: the largest chunks of the
    whole piece. Glass has none (Niagara shards only).
    """
    budget = DEBRIS_BODIES.get(spec.material, {})
    chunks = spec.fracture_chunks(seed)
    if not budget or not chunks:
        return []
    out: list[DebrisSet] = []
    for look in spec.looks():
        if look.state not in budget:
            continue
        openings = (spec.holed if look.state == "Holed" else spec.breached)[look.variant]
        inside = [c for c in chunks if _in_openings(_chunk_centre(c), openings, OPENING_MARGIN_M)]
        if not inside:
            # A small opening between cell centres still throws its nearest chunk.
            inside = chunks

        def near(c: g.Chunk, centroid: g.Vec3 = look.centroid) -> float:
            p = _chunk_centre(c)
            return (p[0] - centroid[0]) ** 2 + (p[2] - centroid[2]) ** 2

        picked = sorted(inside, key=near)[: budget[look.state] if inside is not chunks else 1]
        out.append(DebrisSet(look.state, look.variant, picked))
    if "Destroyed" in budget:
        largest = sorted(chunks, key=lambda c: -c.volume())[: budget["Destroyed"]]
        out.append(DebrisSet("Destroyed", 0, largest))
    return out


def _cut_openings(strip: g.Mesh, openings: list[Opening]) -> list[g.Mesh]:
    """Removes the opening rectangles (x, z) from one convex strip; returns convex closed parts."""
    parts = [g.Convex.from_mesh(strip)]
    for x0, z0, x1, z1 in openings:
        next_parts: list[g.Convex] = []
        for part in parts:
            # Outside the rectangle = left of x0, right of x1, or between them below z0 / above z1.
            for keep in (
                [((1.0, 0.0, 0.0), x0)],
                [((-1.0, 0.0, 0.0), -x1)],
                [((-1.0, 0.0, 0.0), -x0), ((1.0, 0.0, 0.0), x1), ((0.0, 0.0, 1.0), z0)],
                [((-1.0, 0.0, 0.0), -x0), ((1.0, 0.0, 0.0), x1), ((0.0, 0.0, -1.0), -z1)],
            ):
                piece: g.Convex | None = part
                for normal, offset in keep:
                    if piece is None:
                        break
                    piece = piece.clip(normal, offset)
                if piece is not None:
                    next_parts.append(piece)
        parts = next_parts
    return [p.to_mesh() for p in parts]


def _bounds(parts: list[g.Mesh]) -> tuple[g.Vec3, g.Vec3]:
    return g.merge(parts).bounds()


def _centroid(openings: list[Opening]) -> g.Vec3:
    area = sum((o[2] - o[0]) * (o[3] - o[1]) for o in openings)
    cx = sum((o[0] + o[2]) / 2 * (o[2] - o[0]) * (o[3] - o[1]) for o in openings) / area
    cz = sum((o[1] + o[3]) / 2 * (o[2] - o[0]) * (o[3] - o[1]) for o in openings) / area
    return (cx, 0.0, cz)


def _holes(width: float) -> list[list[Opening]]:
    """Four irregular see-and-shoot-through openings (unions of rectangles), never walkable."""
    q = width / 4
    out = []
    for cx, cz in ((-q, 1.45), (q, 1.45), (-q, 0.85), (q, 0.85)):
        out.append(
            [
                (cx - 0.20, cz - 0.12, cx + 0.16, cz + 0.10),
                (cx - 0.08, cz + 0.10, cx + 0.10, cz + 0.22),
                (cx + 0.16, cz - 0.04, cx + 0.24, cz + 0.06),
            ]
        )
    return out


def _breaches(width: float) -> list[list[Opening]]:
    """Standing breach (at least 0.9 x 2.0 m, from the floor) and a low breach to mantle through."""
    half = min(0.5, width / 2 - 0.12)
    return [
        [(-half, 0.0, half, 2.05)],
        [(-half, 0.30, half, 1.10)],
    ]


def catalogue() -> list[PieceSpec]:
    """Every destructible kit piece WP06 ships."""
    pieces = []
    for width in (1.2, 2.4, 4.8):
        cm = round(width * 100)
        pieces.append(
            PieceSpec(
                f"SM_WallPanel_{cm}",
                "WallPanel",
                "sheet_metal",
                width,
                2.7,
                holed=_holes(width),
                breached=_breaches(width),
                fracture_cells=24 if width < 4 else 36,
                mantle_variant=1,
            )
        )
    pieces.append(
        PieceSpec(
            "SM_CladdingWall_240",
            "CladdingWall",
            "cladding_panel",
            2.4,
            2.7,
            holed=_holes(2.4),
            breached=_breaches(2.4),
            fracture_cells=30,
            mantle_variant=1,
        )
    )
    pieces.append(
        PieceSpec(
            "SM_ContainerWall_240",
            "ContainerWall",
            "container_wall",
            2.4,
            2.59,
            depth=0.04,
            holed=_holes(2.4),
            breached=_breaches(2.4),
            fracture_cells=36,
            mantle_variant=1,
        )
    )
    pieces.append(PieceSpec("SM_GlassPane_120", "GlassPane", "glass", 1.2, 1.5, sill=0.9))
    pieces.append(
        PieceSpec(
            "SM_CatwalkSegment_240",
            "CatwalkSegment",
            "catwalk_grating",
            2.4,
            0.0,
            depth=1.2,
            fracture_cells=6,
        )
    )
    pieces.append(
        PieceSpec(
            "SM_CeilingPanel_120",
            "CeilingPanel",
            "ceiling_panel",
            1.2,
            0.0,
            depth=1.2,
            fracture_cells=1,
        )
    )
    return pieces


def by_name(name: str) -> PieceSpec:
    for spec in catalogue():
        if spec.name == name:
            return spec
    raise KeyError(name)
