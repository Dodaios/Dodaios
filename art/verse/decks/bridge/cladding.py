"""Wall cladding for the bridge's plain walls, seen at eye level.

The plate camera sees the side hull walls, the hall face of the aft bulkhead,
the aft rooms' side walls and the aft wall's room face only edge-on or from
behind, so they were built as plain slabs. In the realtime (eye-level) view
they are large flat grey fields. This module dresses them in the bridge's
language (style bible 2.4, 2.9, 2.14; ART_DIRECTION 2):

* Hall walls (7.2 m): a dark plinth with louvre vents, a lower field of
  vertical 0.6 x 2.4 m charcoal panels with recessed seams (one in four an
  inset field), one light column of stacked backlit rectangles per selected
  bay, a gunmetal rail carrying a conduit bundle with clamps and junction
  boxes, an upper field of 1.2 m panels with a few louvre vents, a recessed
  cornice, and gunmetal ribs every 4.8 m with a column of white dash lamps
  (every third rib a red strip higher up).
* Room walls (3.6 m): the light-grey secondary panelling: dark base band with
  vents, light-grey panels with access hatches, a light channel with a hidden
  fixture under its lip (one lamp of half the bay's length per 2.4 m bay, so
  the rooms read no brighter than the hall's sparse lamps), mid-grey upper
  panels, gunmetal pilasters. ``window_wall`` frames the same panelling
  around slit windows (the ready room's corner viewport, which ``aft.py``
  builds as real plate geometry).

Everything is a ceiling ghost (``kit.ghost``): invisible to the plate camera
and to shadow rays, nav ``none``, no occluders, so the plate, the nav grid and
the occluders keep their shape; the realtime export turns ghosts into normal
walls (docs/verse/realtime.md). The plate still sees the new lamps mirrored in
its floors. Faces the plate does see (the bulkhead's room side below the cut)
are clipped at the cut.

Wear comes from the materials (chipped bevels, grime in cavities); the
builders give them edges and recesses to work on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lib import kit, scene
from mathutils import Matrix

from . import layout as L

CHARCOAL = "M_Wall_Charcoal"
DARK = "M_Wall_PaintedDark"
MID = "M_Wall_PaintedMid"
LIGHT = "M_Wall_PaintedLight"
GUNMETAL = "M_Struct_Gunmetal"
STEEL = "M_Trim_BrushedSteel"
RECESS = "M_Recess_Dark"
RUBBER = "M_Rubber_Black"
PIPE = "M_Hull_Pipe"
PIPE_INS = "M_Hull_PipeInsulated"
BACKLIT = "M_Light_Backlit"
STRIP = "M_Light_WallStrip"
RED = "M_Light_RedTrim"

SEAM = 0.008  # reveal between panels
BACK = 0.012  # dark backing plate: what the seams show
PANEL_V = 0.045  # panel face, metres proud of the wall

# Hall wall bands (heights above deck level).
PLINTH_TOP = 0.3
LOWER = (0.33, 2.73)
RAIL = (2.73, 2.88)
CONDUIT = (2.88, 3.36)
CORNICE = 0.6  # recessed band under the ceiling
RIB_W = 0.6
RIB_V = 0.15  # rib depth (stays inside the nav grid's 0.25 m body clearance)
DASH = (0.1, 0.3, 0.15)  # dash lamp width, height, gap (style bible 2.9)
LIGHT_W, LIGHT_H, LIGHT_GAP = 0.26, 0.15, 0.05  # backlit rectangles (kit hero wall)

# Room wall bands.
ROOM_BASE = 0.6
ROOM_CHANNEL = (2.78, 3.02)

# Rib rhythm: every 4.8 m on the hall's grid, symmetric about the axis.
RIB_STEP = 4.8


def _h(*parts) -> float:
    return (kit.seed_for("bridge-clad", *parts) % 10000) / 10000.0


def run_matrix(axis: str, fixed: float, room_sign: int) -> Matrix:
    """Local (u, v, h) -> Blender for a wall face.

    ``u`` runs along the wall in plan metres (plan x for ``axis`` "x", plan z
    for "z"), ``v`` from the face into the room, ``h`` is the height. The face
    lies at plan ``x = fixed`` (axis "z") or plan ``z = fixed`` (axis "x");
    ``room_sign`` is the room's side along the other plan axis.
    """
    if axis == "z":
        return Matrix(((0, room_sign, 0, fixed), (-1, 0, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)))
    return Matrix(((1, 0, 0, 0), (0, -room_sign, 0, -fixed), (0, 0, 1, 0), (0, 0, 0, 1)))


@dataclass
class Builders:
    """One builder per finish, shared by every wall of a group."""

    panels: kit.MeshBuilder = field(default_factory=kit.MeshBuilder)
    struct: kit.MeshBuilder = field(default_factory=kit.MeshBuilder)
    flat: kit.MeshBuilder = field(default_factory=kit.MeshBuilder)
    pipes: kit.MeshBuilder = field(default_factory=kit.MeshBuilder)
    lamps: kit.MeshBuilder = field(default_factory=kit.MeshBuilder)

    def at(self, matrix: Matrix) -> Builders:
        for mb in self._all():
            mb.matrix = matrix
        return self

    def _all(self):
        return (self.panels, self.struct, self.flat, self.pipes, self.lamps)

    def finish(self, prefix: str) -> None:
        self.panels.build(f"{prefix}_panels", bevel_width=0.003, segments=1)
        self.struct.build(f"{prefix}_struct", bevel_width=0.006, segments=1)
        self.flat.build(f"{prefix}_flat", bevel_width=0.0)
        self.pipes.build(f"{prefix}_conduits", bevel_width=0.0)
        lamps = self.lamps.build(f"{prefix}_lamps", bevel_width=0.0)
        if lamps is not None:
            lamps.visible_shadow = False


def _box(mb: kit.MeshBuilder, u0, u1, v0, v1, h0, h1, material: str) -> None:
    if u1 - u0 > 1e-4 and h1 - h0 > 1e-4:
        mb.box((u0, v0, h0), (u1, v1, h1), material)


def _modules(a: float, b: float, module: float) -> list[tuple[float, float]]:
    n = max(1, round((b - a) / module))
    step = (b - a) / n
    return [(a + i * step, a + (i + 1) * step) for i in range(n)]


def _subtract(a: float, b: float, holes) -> list[tuple[float, float]]:
    """Parts of [a, b] outside the given (u0, u1) holes."""
    spans = [(a, b)]
    for h0, h1 in sorted(holes):
        out = []
        for s0, s1 in spans:
            if h1 <= s0 or h0 >= s1:
                out.append((s0, s1))
                continue
            if h0 > s0:
                out.append((s0, h0))
            if h1 < s1:
                out.append((h1, s1))
        spans = out
    return [(s0, s1) for s0, s1 in spans if s1 - s0 > 0.05]


def _louvre(B: Builders, cu: float, h0: float, w: float = 0.6, h: float = 0.3) -> None:
    """Louvre vent (style bible 2.14): gunmetal frame, 8 dark slats."""
    _box(B.struct, cu - w / 2, cu + w / 2, BACK, PANEL_V + 0.012, h0, h0 + h, GUNMETAL)
    _box(B.flat, cu - w / 2 + 0.04, cu + w / 2 - 0.04, PANEL_V + 0.012, PANEL_V + 0.014,
         h0 + 0.03, h0 + h - 0.03, RECESS)  # fmt: skip
    pitch = (h - 0.06) / 8
    for k in range(8):
        z = h0 + 0.03 + k * pitch + pitch * 0.3
        _box(B.flat, cu - w / 2 + 0.05, cu + w / 2 - 0.05, PANEL_V + 0.014, PANEL_V + 0.03,
             z, z + pitch * 0.45, GUNMETAL)  # fmt: skip


def _panel(B: Builders, u0, u1, h0, h1, material: str, *, inset: bool, v: float = PANEL_V):
    """A panel proud of the backing; ``inset`` adds a recessed field with a
    50 mm border (style bible 2.4)."""
    a, b = u0 + SEAM / 2, u1 - SEAM / 2
    z0, z1 = h0 + SEAM / 2, h1 - SEAM / 2
    if not inset or b - a < 0.25 or z1 - z0 < 0.25:
        _box(B.panels, a, b, BACK, v, z0, z1, material)
        return
    bd = 0.05
    _box(B.panels, a, b, BACK, v, z0, z0 + bd, material)
    _box(B.panels, a, b, BACK, v, z1 - bd, z1, material)
    _box(B.panels, a, a + bd, BACK, v, z0 + bd, z1 - bd, material)
    _box(B.panels, b - bd, b, BACK, v, z0 + bd, z1 - bd, material)
    _box(B.panels, a + bd, b - bd, BACK, v - 0.02, z0 + bd, z1 - bd, material)


def _light_column(B: Builders, cu: float, h0: float, h1: float, seed) -> None:
    """The hero wall's light column in one 0.6 m module: charcoal cheeks,
    gunmetal ribs and a recessed bay of stacked backlit rectangles, every
    fifth slot a dark plate (kit hero wall, ART_DIRECTION 2)."""
    bay = 0.36
    for s in (-1, 1):
        cheek0, cheek1 = sorted((cu + s * (bay / 2 + 0.06), cu + s * (0.3 - SEAM / 2)))
        _box(B.panels, cheek0, cheek1, BACK, PANEL_V, h0 + SEAM / 2, h1 - SEAM / 2, CHARCOAL)
        r0, r1 = sorted((cu + s * bay / 2, cu + s * (bay / 2 + 0.06)))
        _box(B.struct, r0, r1, BACK, PANEL_V + 0.02, h0, h1, GUNMETAL)
    _box(B.flat, cu - bay / 2, cu + bay / 2, BACK, BACK + 0.004, h0, h1, RECESS)
    z = h0 + 0.1
    slot = kit.seed_for(seed) % 5
    while z + LIGHT_H < h1 - 0.06:
        if slot % 5 != 4:
            _box(B.lamps, cu - LIGHT_W / 2, cu + LIGHT_W / 2, BACK + 0.012, BACK + 0.016,
                 z, z + LIGHT_H, BACKLIT)  # fmt: skip
        else:
            _box(B.struct, cu - LIGHT_W / 2, cu + LIGHT_W / 2, BACK + 0.004, BACK + 0.03,
                 z, z + LIGHT_H, GUNMETAL)  # fmt: skip
        z += LIGHT_H + LIGHT_GAP
        slot += 1


def _rib(
    B: Builders, r: float, bottom: float, top: float, *, foot: bool, red: bool, dashes
) -> None:
    """Gunmetal rib: stepped core and front plates around a lamp slot, a
    splayed foot and a chamfered capital (style bible 2.1, 2.9)."""
    w = RIB_W / 2
    _box(B.struct, r - w, r + w, BACK, 0.11, bottom, top, GUNMETAL)
    for s in (-1, 1):
        a, b = sorted((r + s * 0.06, r + s * 0.19))
        _box(B.struct, a, b, 0.11, RIB_V, bottom + (0.4 if foot else 0.0), top - 0.5, GUNMETAL)
    _box(B.flat, r - 0.06, r + 0.06, 0.11, 0.128, bottom, top - 0.5, RECESS)
    if foot:
        B.struct.prism_x(
            [
                (BACK, bottom),
                (0.2, bottom),
                (0.2, bottom + 0.22),
                (0.11, bottom + 0.4),
                (BACK, bottom + 0.4),
            ],
            r - w - 0.06,
            r + w + 0.06,
            GUNMETAL,
        )
    B.struct.prism_x(
        [(BACK, top - 0.5), (0.11, top - 0.5), (0.2, top - 0.36), (0.2, top), (BACK, top)],
        r - w - 0.04,
        r + w + 0.04,
        GUNMETAL,
    )
    dw, dh, _ = DASH
    for z in dashes:
        _box(B.lamps, r - dw / 2, r + dw / 2, 0.128, 0.132, z, z + dh, BACKLIT)
    if red:
        _box(B.lamps, r - 0.025, r + 0.025, 0.128, 0.132, top - 3.0, top - 0.6, RED)


def _conduits(B: Builders, u0: float, u1: float, h0: float, ribs, seed) -> None:
    """Conduit bundle on the rail: three pipes with clamps every 1.2 m and a
    junction box every other bay (style bible 2.14)."""
    _box(B.panels, u0, u1, BACK, BACK + 0.008, h0, h0 + (CONDUIT[1] - CONDUIT[0]), DARK)
    for dh, r, mat in ((0.1, 0.045, PIPE_INS), (0.22, 0.03, PIPE), (0.33, 0.04, PIPE)):
        v = BACK + r + 0.035
        B.pipes.tube((u0 + 0.02, v, h0 + dh), (u1 - 0.02, v, h0 + dh), r, mat, segments=10)
    u = u0 + 0.6
    k = 0
    while u < u1 - 0.3:
        if all(abs(u - rr) > RIB_W / 2 + 0.1 for rr in ribs):
            _box(B.struct, u - 0.03, u + 0.03, BACK, 0.135, h0 + 0.03, h0 + 0.43, GUNMETAL)
            if k % 4 == 2 and _h(seed, "jbox", k) < 0.6:
                _box(B.panels, u + 0.15, u + 0.45, BACK, 0.16, h0 + 0.05, h0 + 0.38, MID)
                lamp = "M_Indicator_Green" if _h(seed, "jl", k) < 0.5 else "M_Indicator_White"
                _box(B.lamps, u + 0.38, u + 0.42, 0.16, 0.164, h0 + 0.3, h0 + 0.34, lamp)
        u += 1.2
        k += 1


@dataclass
class Opening:
    u0: float
    u1: float
    head: float  # top of the opening


def hall_wall(
    B: Builders,
    seed,
    t0: float,
    t1: float,
    *,
    floors: list[tuple[float, float, float]],
    ribs: list[float],
    lit_bays: set[int] | None = None,
    lit_upper: set[int] | None = None,
    red_ribs: set[int] | None = None,
    lower_material: str = CHARCOAL,
    openings: list[Opening] = (),
    top: float = L.HALL_CEILING,
) -> None:
    """Dress a hall wall face between ``t0`` and ``t1`` (plan metres along it).

    ``floors``: (u0, u1, floor height) spans; the wall runs down to the
    floor, the plinth's vents sit just above the visible floor.
    ``lit_bays`` / ``lit_upper``: bay indices with a light column in the lower /
    upper field; ``red_ribs``: rib indices with a red strip.
    """
    lit_bays, lit_upper, red_ribs = lit_bays or set(), lit_upper or set(), red_ribs or set()
    holes = [(o.u0, o.u1) for o in openings]
    low = min(f for _, _, f in floors)
    # Dark backing over the whole face: what the seams and recesses show.
    for a, b in _subtract(t0, t1, holes):
        _box(B.flat, a, b, 0.0, BACK, low, top, RECESS)
    for o in openings:
        _box(B.flat, o.u0, o.u1, 0.0, BACK, o.head, top, RECESS)
    # Plinth with louvre vents on alternate 1.2 m modules.
    for u0, u1, floor in floors:
        vent_h = max(floor, -0.66) + 0.04 if floor < 0 else floor + 0.02
        for a, b in _subtract(u0, u1, holes):
            for i, (m0, m1) in enumerate(_modules(a, b, 1.2)):
                _box(B.panels, m0 + SEAM / 2, m1 - SEAM / 2, BACK, BACK + 0.022,
                     floor, PLINTH_TOP, DARK)  # fmt: skip
                if i % 2 == 1 and m1 - m0 > 0.8:
                    _louvre(B, (m0 + m1) / 2, vent_h, w=0.6, h=0.24)
            _box(B.struct, a, b, BACK, 0.05, PLINTH_TOP, LOWER[0], STEEL)
    # Bays between the ribs.
    edges = [t0, *[r for r in ribs if t0 < r < t1], t1]
    bays = []
    for a, b in zip(edges[:-1], edges[1:], strict=True):
        a2 = a + (RIB_W / 2 if a in ribs else 0.0)
        b2 = b - (RIB_W / 2 if b in ribs else 0.0)
        bays.append((a2, b2))
    upper = (CONDUIT[1], top - CORNICE)
    for bi, (a, b) in enumerate(bays):
        cu = round(((a + b) / 2) / 0.3) * 0.3
        lit_low = bi in lit_bays and b - a > 1.8
        lit_up = bi in lit_upper and b - a > 1.8
        # Lower field: vertical 0.6 m panels, one light column.
        low_holes = holes + ([(cu - 0.3, cu + 0.3)] if lit_low else [])
        for sa, sb in _subtract(a, b, low_holes):
            for i, (m0, m1) in enumerate(_modules(sa, sb, 0.6)):
                inset = _h(seed, bi, sa, i) < 0.25
                mat = DARK if _h(seed, "m", bi, sa, i) < 0.12 else lower_material
                _panel(B, m0, m1, LOWER[0], LOWER[1], mat, inset=inset)
        for o in openings:  # panels above door heads
            for sa, sb in _subtract(max(a, o.u0), min(b, o.u1), []):
                if o.head < LOWER[1] - 0.1:
                    _panel(B, sa, sb, o.head + 0.03, LOWER[1], lower_material, inset=False)
        if lit_low:
            _light_column(B, cu, LOWER[0], LOWER[1], (seed, "low", bi))
        # Upper field: 1.2 m panels in rows of about 1.1 m, a few vents.
        up_holes = [(cu - 0.3, cu + 0.3)] if lit_up else []
        rows = max(1, round((upper[1] - upper[0]) / 1.1))
        rh = (upper[1] - upper[0]) / rows
        for sa, sb in _subtract(a, b, up_holes):
            for i, (m0, m1) in enumerate(_modules(sa, sb, 1.2)):
                for j in range(rows):
                    h0, h1 = upper[0] + j * rh, upper[0] + (j + 1) * rh
                    r = _h(seed, "u", bi, sa, i, j)
                    mat = MID if r < 0.16 else DARK
                    _panel(B, m0, m1, h0, h1, mat, inset=0.16 <= r < 0.4)
                    if j == 0 and r > 0.88 and m1 - m0 > 0.9:
                        _louvre(B, (m0 + m1) / 2, h0 + 0.2)
        if lit_up:
            _light_column(B, cu, upper[0] + 0.25, upper[1] - 0.25, (seed, "up", bi))
            for h0, h1 in ((upper[0], upper[0] + 0.25), (upper[1] - 0.25, upper[1])):
                _panel(B, cu - 0.3, cu + 0.3, h0, h1, CHARCOAL, inset=False)
    # Rail with the conduit bundle along the whole face.
    _box(B.struct, t0, t1, BACK, 0.09, RAIL[0], RAIL[1] - 0.015, GUNMETAL)
    _box(B.struct, t0, t1, BACK, 0.095, RAIL[1] - 0.015, RAIL[1], STEEL)
    _conduits(B, t0, t1, CONDUIT[0], ribs, seed)
    # Recessed cornice under the ceiling with a gunmetal lip.
    _box(B.struct, t0, t1, BACK, 0.07, top - CORNICE, top - CORNICE + 0.06, GUNMETAL)
    for m0, m1 in _modules(t0, t1, 2.4):
        _box(B.panels, m0 + SEAM / 2, m1 - SEAM / 2, BACK, BACK + 0.01,
             top - CORNICE + 0.06, top - 0.06, DARK)  # fmt: skip
    _box(B.struct, t0, t1, BACK, 0.05, top - 0.06, top, GUNMETAL)
    # Ribs.
    dw, dh, gap = DASH
    for ri, r in enumerate(ribs):
        if not t0 < r < t1:
            continue
        bottom = next((f for u0, u1, f in floors if u0 <= r <= u1), 0.0)
        blocked = any(o.u0 - RIB_W < r < o.u1 + RIB_W for o in openings)
        if blocked:
            bottom = CONDUIT[0]
        dashes = []
        if not blocked:
            z = max(bottom, 0.0) + 0.6
            for _ in range(7):
                dashes.append(z)
                z += dh + gap
        _rib(B, r, bottom, top, foot=not blocked, red=ri in red_ribs, dashes=dashes)


def room_wall(
    B: Builders,
    seed,
    t0: float,
    t1: float,
    *,
    top: float = L.ROOM_CEILING,
    pilasters: list[float] = (),
    openings: list[Opening] = (),
    base_from: float = 0.0,
) -> None:
    """Light-grey secondary panelling of an aft room's wall (walls.py
    ``SM_WallLight``): base band with vents, panels with hatches, a light
    channel with its fixture hidden under the lip, upper panels, pilasters."""
    holes = [(o.u0, o.u1) for o in openings]
    for a, b in _subtract(t0, t1, holes):
        _box(B.flat, a, b, 0.0, BACK, base_from, top, RECESS)
        for i, (m0, m1) in enumerate(_modules(a, b, 1.2)):
            _box(B.panels, m0 + SEAM / 2, m1 - SEAM / 2, BACK, BACK + 0.022,
                 base_from, ROOM_BASE - 0.025, DARK)  # fmt: skip
            if i % 2 == 1 and m1 - m0 > 0.8:
                _louvre(B, (m0 + m1) / 2, 0.14, w=0.6, h=0.3)
            hatch = i % 4 == 2 and _h(seed, "hatch", a, i) < 0.7
            _panel(B, m0, m1, ROOM_BASE, ROOM_CHANNEL[0], LIGHT, inset=hatch)
            if hatch:
                cu = (m0 + m1) / 2
                _box(B.struct, cu - 0.09, cu + 0.09, PANEL_V, PANEL_V + 0.01, 2.1, 2.15, STEEL)
            _panel(B, m0, m1, ROOM_CHANNEL[1], top - 0.04, MID, inset=False)
        _box(B.struct, a, b, BACK, 0.05, ROOM_BASE - 0.025, ROOM_BASE, STEEL)
    for o in openings:
        if o.head < ROOM_CHANNEL[0]:
            for m0, m1 in _modules(o.u0, o.u1, 1.2):
                _panel(B, m0, m1, o.head + 0.03, ROOM_CHANNEL[0], LIGHT, inset=False)
            _box(B.flat, o.u0, o.u1, 0.0, BACK, o.head, top, RECESS)
            for m0, m1 in _modules(o.u0, o.u1, 1.2):
                _panel(B, m0, m1, ROOM_CHANNEL[1], top - 0.04, MID, inset=False)
    # Light channel: brushed lower lip, proud upper lip with the strip under it.
    c0, c1 = ROOM_CHANNEL
    _box(B.struct, t0, t1, BACK, 0.065, c0, c0 + 0.05, STEEL)
    _box(B.panels, t0, t1, BACK, 0.1, c1 - 0.07, c1, MID)
    _box(B.flat, t0, t1, BACK, BACK + 0.006, c0 + 0.05, c1 - 0.07, LIGHT)
    for a, b in _modules(t0, t1, 2.4):
        _channel_lamp(B, a, b)
    _box(B.struct, t0, t1, BACK, 0.04, top - 0.04, top, GUNMETAL)
    for p in pilasters:
        if t0 < p < t1:
            _box(B.struct, p - 0.15, p + 0.15, BACK, 0.1, base_from, top, GUNMETAL)
            _box(B.struct, p - 0.08, p + 0.08, 0.1, 0.12, base_from + 0.3, top - 0.3, GUNMETAL)
            _box(B.flat, p - 0.02, p + 0.02, 0.12, 0.122, 0.9, c0 - 0.2, RECESS)


def _channel_lamp(B: Builders, a: float, b: float) -> None:
    """The light channel's fixture in one bay: a strip of half the bay's
    length, centred, so the channel reads as a rhythm of lamps no brighter
    than the hall's sparse fixtures rather than one continuous line."""
    c1 = ROOM_CHANNEL[1]
    cu, half = (a + b) / 2, (b - a) / 4
    _box(B.lamps, cu - half, cu + half, 0.03, 0.09, c1 - 0.074, c1 - 0.07, STRIP)


@dataclass
class Window:
    u0: float
    u1: float
    sill: float
    head: float


JAMB = 0.15  # width of the gunmetal jambs that frame a slit window


def window_wall(
    B: Builders,
    t0: float,
    t1: float,
    *,
    windows: list[Window],
    top: float = L.ROOM_CEILING,
) -> None:
    """``room_wall``'s light-grey panelling on a wall pierced by tall slit
    windows. Each slit sits in a gunmetal bay: two pilaster jambs from floor to
    cornice, a dark base panel under a brushed sill, a head plate and a
    mid-grey panel above. The spans between the bays carry the base band
    (vents in the outer spans), the light-grey panels (a hatch in the middle
    span), the light channel with one lamp per span, and the upper panels."""
    c0, c1 = ROOM_CHANNEL
    bays = [(w.u0 - JAMB, w.u1 + JAMB) for w in windows]
    spans = _subtract(t0, t1, bays)
    mid = len(spans) // 2
    for k, (a, b) in enumerate(spans):
        _box(B.flat, a, b, 0.0, BACK, 0.0, top, RECESS)
        _box(B.panels, a + SEAM / 2, b - SEAM / 2, BACK, BACK + 0.022,
             0.0, ROOM_BASE - 0.025, DARK)  # fmt: skip
        hatch = len(spans) % 2 == 1 and k == mid
        if not hatch and b - a > 0.8:
            _louvre(B, (a + b) / 2, 0.14, w=0.6, h=0.3)
        _box(B.struct, a, b, BACK, 0.05, ROOM_BASE - 0.025, ROOM_BASE, STEEL)
        _panel(B, a, b, ROOM_BASE, c0, LIGHT, inset=hatch)
        if hatch:
            cu = (a + b) / 2
            _box(B.struct, cu - 0.09, cu + 0.09, PANEL_V, PANEL_V + 0.01, 2.1, 2.15, STEEL)
        # Light channel as in room_wall, stopped by the jambs.
        _box(B.struct, a, b, BACK, 0.065, c0, c0 + 0.05, STEEL)
        _box(B.panels, a, b, BACK, 0.1, c1 - 0.07, c1, MID)
        _box(B.flat, a, b, BACK, BACK + 0.006, c0 + 0.05, c1 - 0.07, LIGHT)
        _channel_lamp(B, a, b)
        _panel(B, a, b, c1, top - 0.04, MID, inset=False)
    for w, (j0, j1) in zip(windows, bays, strict=True):
        # Dark backing, base panel, sill, head plate and upper panel between
        # the jambs; the slit itself stays open.
        for h0, h1 in ((0.0, w.sill), (w.head, top)):
            _box(B.flat, w.u0, w.u1, 0.0, BACK, h0, h1, RECESS)
        _panel(B, w.u0, w.u1, 0.0, w.sill - 0.06, DARK, inset=False, v=BACK + 0.022)
        _box(B.struct, w.u0 - 0.03, w.u1 + 0.03, BACK, 0.09, w.sill - 0.06, w.sill, STEEL)
        _box(B.struct, w.u0, w.u1, BACK, 0.07, w.head, w.head + 0.06, GUNMETAL)
        _panel(B, w.u0, w.u1, w.head + 0.06, top - 0.04, MID, inset=False)
        # Pilaster jambs with a recessed groove, as room_wall's pilasters.
        for p0, p1 in ((j0, w.u0), (w.u1, j1)):
            pm = (p0 + p1) / 2
            _box(B.struct, p0, p1, BACK, 0.1, 0.0, top, GUNMETAL)
            _box(B.struct, pm - 0.04, pm + 0.04, 0.1, 0.12, 0.3, top - 0.3, GUNMETAL)
            _box(B.flat, pm - 0.012, pm + 0.012, 0.12, 0.122, 0.9, c0 - 0.2, RECESS)
    _box(B.struct, t0, t1, BACK, 0.04, top - 0.04, top, GUNMETAL)


# ---------------------------------------------------------------- the deck


def _hall_ribs(t0: float, t1: float) -> list[float]:
    """Rib stations on the 4.8 m grid (multiples of 4.8 are symmetric about
    the walkway axis, 36 = 33.6 + 2.4)."""
    out, r = [], 0.0
    while r <= t1 + 1e-6:
        if t0 + 0.2 < r < t1 - 0.2:
            out.append(round(r, 3))
        r += RIB_STEP
    return out


def side_walls() -> None:
    """The port and starboard hull walls of the hall, the pits included."""
    z0, z1 = 9.3, L.BULKHEAD_Z[0]  # from behind the corner pier to the bulkhead
    (_, _), (_, cz1) = L.PIT_CHAMFER
    floors = [(z0, cz1, 0.0), (cz1, L.AFT_EDGE_Z, L.PIT_Z), (L.AFT_EDGE_Z, z1, 0.0)]
    ribs = _hall_ribs(z0, z1)  # 9.6 .. 28.8
    for name, x, sign in (("p", L.SIDE_WALL_X[0], 1), ("s", L.SIDE_WALL_X[1], -1)):
        B = Builders().at(run_matrix("z", x, sign))
        hall_wall(
            B,
            ("side", name),
            z0,
            z1,
            floors=floors,
            ribs=ribs,
            lit_bays={1, 3},
            lit_upper={2},
            red_ribs={2},
        )
        B.finish(f"SM_clad_sidewall_{name}")


def bulkhead_hall_face() -> None:
    """The aft bulkhead's face toward the hall, around its three doors (the
    lifts open to the lobby only; their shafts are closed toward the hall)."""
    t0, t1 = L.SIDE_WALL_X
    openings = [
        Opening(*L.BRIEF_DOOR_X, 2.7),
        Opening(*L.MAIN_DOOR_X, 2.7),
        Opening(*L.READY_DOOR_X, 2.7),
    ]
    ribs = _hall_ribs(t0, t1)  # 4.8 .. 67.2
    # Bay i lies between rib i-1 and rib i; the axis bay (above the main door)
    # is 7. Upper light columns in the odd bays, lower ones in even bays clear
    # of the doors: a symmetric checkerboard about the axis.
    lit = {1, 3, 5, 7, 9, 11, 13}
    B = Builders().at(run_matrix("x", L.BULKHEAD_Z[0], -1))
    hall_wall(
        B,
        "bulkhead",
        t0,
        t1,
        floors=[(t0, t1, 0.0)],
        ribs=ribs,
        lit_bays={2, 4, 10, 12},
        lit_upper=lit,
        red_ribs={3, 10},
        openings=openings,
    )
    B.finish("SM_clad_bulkhead_hall")


ROOMS = (
    ("briefing", L.BRIEFING_X),
    ("lobby", L.LOBBY_X),
    ("ready", L.READY_X),
)


def room_side_walls() -> None:
    """Both side walls of every aft room (hull walls and service chases)."""
    z0, z1 = L.ROOMS_Z
    zm = (z0 + z1) / 2
    for room, (x0, x1) in ROOMS:
        for end, x, sign in (("w", x0, 1), ("e", x1, -1)):
            a = z0
            if room == "ready" and end == "e":
                a = z0 + 3.7  # past the corner viewport
            B = Builders().at(run_matrix("z", x, sign))
            room_wall(B, (room, end), a, z1, pilasters=[zm] if z1 - a > 7.0 else [])
            B.finish(f"SM_clad_{room}_{end}")


def aft_wall_rooms() -> None:
    """The aft wall's room faces (the plate sees only its back)."""
    for room, (x0, x1) in ROOMS:
        B = Builders().at(run_matrix("x", L.AFT_WALL_Z[0], -1))
        xm = (x0 + x1) / 2
        room_wall(B, (room, "aft"), x0, x1, pilasters=[xm] if x1 - x0 > 14.0 else [])
        B.finish(f"SM_clad_{room}_aft")


def bulkhead_room_faces() -> None:
    """The bulkhead's room faces above the cut (the plate sees them below)."""
    door_spans = {
        "briefing": [Opening(*L.BRIEF_DOOR_X, 2.7)],
        "lobby": [
            Opening(L.LIFT_P_X[0] - 0.06, L.LIFT_P_X[1] + 0.06, 2.7),
            Opening(*L.MAIN_DOOR_X, 2.7),
            Opening(L.LIFT_S_X[0] - 0.06, L.LIFT_S_X[1] + 0.06, 2.7),
        ],
        "ready": [Opening(*L.READY_DOOR_X, 2.7)],
    }
    for room, (x0, x1) in ROOMS:
        if room == "ready":
            x1 = L.READY_X[1] - 3.7  # the corner viewport takes the rest
        B = Builders().at(run_matrix("x", L.BULKHEAD_Z[1], 1))
        room_wall(B, (room, "fwd"), x0, x1, openings=door_spans[room], base_from=L.CUT_H - 0.1)
        B.finish(f"SM_clad_{room}_fwd")


def build() -> None:
    with kit.into(scene.collection("Ceiling")):
        with kit.ghost(L.PIT_Z - 0.5):
            side_walls()
            bulkhead_hall_face()
            room_side_walls()
            aft_wall_rooms()
        with kit.ghost(L.CUT_H):
            bulkhead_room_faces()
