"""The far hull wall's facade: the deck's hero wall, seen full height.

Each room gets its own symmetric run of bays (about 2.4 m) between heavy piers
at the room edges. Layers from the floor: a sloped skirt, the panel field with
a mid rail, a steel valance that washes the panels with light from above, and
the cornice that ``arch.hero_wall_body`` builds. Bay kinds:

``panel``  two satin-grey panels with a seam and the mid rail
``slots``  a recessed channel with staggered columns of slot lights
``slit``   a viewport band with a dim star field inside the glass
``hatch``  a back-lit galley pass-through (the mess serving line)
``feature`` plain panels kept clear for a wall-mounted prop (board, screen)
"""

from __future__ import annotations

import math

from decks.ops import layout as L
from decks.ops.arch import PAINT, PAINT_DARK, PAINT_MID, RECESS, STEEL
from decks.ops.geo import Mesh, tag

HZ = L.HERO_Z
SKIRT_TOP = 0.9
SKIRT_FOOT = HZ + 0.45
FIELD_TOP = 4.2
RAIL_H = 2.4

PLANS = {
    # room: (x0, x1, bay kinds left to right)
    "mess": (
        3.0,
        31.0,
        [
            "panel",
            "slots",
            "hatch",
            "hatch",
            "hatch",
            "hatch",
            "slots",
            "slit",
            "slit",
            "slit",
            "slit",
            "panel",
        ],
    ),
    "records": (
        33.0,
        51.0,
        ["panel", "slots", "slots", "feature", "feature", "slots", "slots", "panel"],
    ),
    "simulator": (
        53.0,
        73.0,
        ["panel", "slots", "feature", "feature", "feature", "feature", "slots", "panel"],
    ),
    "quartermaster": (
        75.0,
        93.0,
        ["panel", "feature", "feature", "feature", "feature", "feature", "feature", "panel"],
    ),
}
PIERS = ((-0.5, 3.0), (31.0, 33.0), (51.0, 53.0), (73.0, 75.0), (93.0, 96.5))
ROOM_PAINT: dict[str, str] = {}  # hero wall: charcoal panelling everywhere
# Wall-mounted props stand on the floor against the panel field: no skirt there.
SKIRT_HOLES = {
    "mess": [(3.15, 5.25)],
    "records": [(40.1, 43.9)],
    "quartermaster": [(77.8, 90.2)],
}
WARM_SCONCES = {"mess"}
_PAINT = [PAINT_DARK]


def build() -> dict[str, list[tuple[float, float, str]]]:
    """Build every facade; return the bay spans per room for the dressing."""
    out = {}
    body, field, lights, glass, stars = Mesh(), Mesh(), Mesh(), Mesh(), Mesh()
    for rid, (x0, x1, kinds) in PLANS.items():
        bay = (x1 - x0) / len(kinds)
        spans = [(x0 + i * bay, x0 + (i + 1) * bay, k) for i, k in enumerate(kinds)]
        out[rid] = spans
        _PAINT[0] = ROOM_PAINT.get(rid, PAINT_DARK)
        holes = SKIRT_HOLES.get(rid, [])
        for a, b in L.solid_spans(x0, x1, holes):
            _skirt(field, a, b, bay)
        for a, b in holes:
            field.box(a, b, HZ - 0.06, HZ, 0.0, SKIRT_TOP + 0.06, PAINT_DARK)
            field.box(a, b, HZ - 0.02, HZ + 0.03, 0.0, 0.12, "M_Rubber_Black")
        for a, b, kind in spans:
            {
                "panel": _bay_panel,
                "feature": _bay_feature,
                "slots": _bay_slots,
                "slit": _bay_slit,
                "hatch": _bay_hatch,
            }[kind](field, lights, glass, stars, a, b)
        for i in range(1, len(kinds)):
            xa = x0 + i * bay
            if kinds[i - 1] == kinds[i] and kinds[i] in ("slit", "hatch"):
                continue
            field.box(xa - 0.05, xa + 0.05, HZ - 0.02, HZ + 0.1, SKIRT_TOP, FIELD_TOP, STEEL)
            if rid in WARM_SCONCES:
                # Warm vertical sconce on the rib: the mess hall's one warm note.
                field.box(xa - 0.07, xa + 0.07, HZ + 0.1, HZ + 0.16, 1.9, 3.0, STEEL)
                lights.box(xa - 0.04, xa + 0.04, HZ + 0.16, HZ + 0.17, 2.0, 2.9, "M_Ops_Light_Warm")
        _valance(field, lights, x0, x1)
    for x0, x1 in PIERS:
        _pier(body, lights, x0, x1)
    tag(field.build("SM_Ops_Facade", bevel=0.006), nav="block")
    tag(body.build("SM_Ops_FacadePiers", bevel=0.012), nav="block")
    tag(lights.build("SM_Ops_FacadeLights", bevel=0.0, keep_normals=True), nav="none")
    if not glass.mb.is_empty():
        tag(glass.build("SM_Ops_ViewportGlass", bevel=0.0, keep_normals=True), nav="none")
    if not stars.mb.is_empty():
        o = stars.build("SM_Ops_Starfield", bevel=0.0, keep_normals=True)
        o.visible_shadow = False
        tag(o, nav="none")
    _lozenges()
    return out


# ---------------------------------------------------------------- layers


def _skirt(m: Mesh, x0: float, x1: float, bay: float) -> None:
    """Sloped skirt along the foot of the wall, seams at half bays."""
    foot, top = (SKIRT_FOOT, 0.0), (HZ, SKIRT_TOP)
    m.prism_x([(HZ - 0.1, 0.0), foot, top, (HZ - 0.1, SKIRT_TOP)], x0, x1, RECESS)
    n = max(1, round((x1 - x0) / (bay / 2)))
    step = (x1 - x0) / n

    def at(h, off):
        z = foot[0] + (top[0] - foot[0]) * h / SKIRT_TOP
        run, rise = foot[0] - top[0], SKIRT_TOP
        k = math.hypot(run, rise)
        return (z + off * rise / k, h + off * run / k)

    for i in range(n):
        a, b = x0 + i * step + 0.004, x0 + (i + 1) * step - 0.004
        m.prism_x(
            [at(0.0, 0.004), at(0.0, 0.02), at(0.12, 0.02), at(0.12, 0.004)], a, b, PAINT_DARK
        )
        m.prism_x(
            [at(0.125, 0.004), at(0.125, 0.022), at(SKIRT_TOP, 0.022), at(SKIRT_TOP, 0.004)],
            a,
            b,
            _PAINT[0],
        )
    # Grille in the skirt: return-air slots every bay.
    m.box(x0, x1, HZ - 0.02, HZ + 0.05, SKIRT_TOP, SKIRT_TOP + 0.06, STEEL)


def _panel_pair(m: Mesh, a: float, b: float, h0: float, h1: float, rail: bool = True) -> None:
    mid = (a + b) / 2
    m.box(a, b, HZ - 0.06, HZ, h0, h1, RECESS)
    for pa, pb in ((a + 0.06, mid - 0.004), (mid + 0.004, b - 0.06)):
        if rail and h0 < RAIL_H < h1:
            m.box(pa, pb, HZ - 0.03, HZ + 0.02, h0 + 0.01, RAIL_H - 0.05, _PAINT[0])
            m.box(pa, pb, HZ - 0.03, HZ + 0.02, RAIL_H + 0.05, h1 - 0.01, _PAINT[0])
        else:
            m.box(pa, pb, HZ - 0.03, HZ + 0.02, h0 + 0.01, h1 - 0.01, _PAINT[0])
    if rail and h0 < RAIL_H < h1:
        m.box(a, b, HZ - 0.03, HZ + 0.045, RAIL_H - 0.04, RAIL_H + 0.04, STEEL)


def _bay_panel(m, lights, glass, stars, a, b):
    _panel_pair(m, a, b, SKIRT_TOP + 0.06, FIELD_TOP)


def _bay_feature(m, lights, glass, stars, a, b):
    _panel_pair(m, a, b, SKIRT_TOP + 0.06, FIELD_TOP, rail=False)


def _bay_slots(m, lights, glass, stars, a, b):
    """Recessed channel; the slot lights themselves are built by `_lozenges`."""
    m.box(a, b, HZ - 0.1, HZ - 0.06, SKIRT_TOP + 0.06, FIELD_TOP, RECESS)
    for pa, pb in ((a + 0.06, a + 0.42), (b - 0.42, b - 0.06)):
        m.box(pa, pb, HZ - 0.03, HZ + 0.02, SKIRT_TOP + 0.07, FIELD_TOP - 0.01, PAINT)
    m.box(a + 0.42, b - 0.42, HZ - 0.1, HZ - 0.02, SKIRT_TOP + 0.06, SKIRT_TOP + 0.24, STEEL)
    m.box(a + 0.42, b - 0.42, HZ - 0.1, HZ - 0.02, FIELD_TOP - 0.18, FIELD_TOP, STEEL)
    _SLOT_BAYS.append((a + 0.42, b - 0.42))


_SLOT_BAYS: list[tuple[float, float]] = []
SLIT = (1.55, 3.45)


def _bay_slit(m, lights, glass, stars, a, b):
    """Viewport band: panels below and above, a heavy frame, glass, stars."""
    lo, hi = SLIT
    _panel_pair(m, a, b, SKIRT_TOP + 0.06, lo - 0.12, rail=False)
    _panel_pair(m, a, b, hi + 0.12, FIELD_TOP, rail=False)
    # Frame: sill, head, reveals.
    m.box(a, b, HZ - 0.4, HZ + 0.08, lo - 0.12, lo, STEEL)
    m.box(a, b, HZ - 0.4, HZ + 0.06, hi, hi + 0.12, STEEL)
    m.box(a - 0.06, a + 0.06, HZ - 0.4, HZ + 0.1, lo - 0.12, hi + 0.12, STEEL)
    m.box(b - 0.06, b + 0.06, HZ - 0.4, HZ + 0.1, lo - 0.12, hi + 0.12, STEEL)
    m.box(a, b, HZ - 0.36, HZ - 0.3, lo, lo + 0.04, "M_Rubber_Black")
    glass.quad_v(a + 0.06, b - 0.06, HZ - 0.3, lo, hi, "M_Ops_Glass_Slit")
    # Star field: a plane square to the camera just behind the glass. The
    # ortho camera has no parallax, so depth does not matter; the hull body
    # behind it is hollowed by `arch.hero_wall_body` (see `cavities`).
    up_z, up_h = -math.sin(math.radians(60)), math.cos(math.radians(60))
    p0z, p0h = HZ - 0.34, lo + 0.005
    s0, s1 = 0.0, 1.25
    stars.quad(
        [
            (a - 0.1, p0z + s0 * up_z, p0h + s0 * up_h),
            (b + 0.1, p0z + s0 * up_z, p0h + s0 * up_h),
            (b + 0.1, p0z + s1 * up_z, p0h + s1 * up_h),
            (a - 0.1, p0z + s1 * up_z, p0h + s1 * up_h),
        ],
        "M_Ops_Starfield",
    )


def cavities() -> list[tuple[float, float, float, float]]:
    """Hull-body cut-outs behind the viewport slits and the galley hatch:
    (x0, x1, h0, h1)."""
    out = []
    for x0, x1, kinds in PLANS.values():
        bay = (x1 - x0) / len(kinds)
        for i, k in enumerate(kinds):
            if k == "slit":
                out.append((x0 + i * bay, x0 + (i + 1) * bay, SLIT[0], SLIT[1]))
            elif k == "hatch":
                out.append((x0 + i * bay, x0 + (i + 1) * bay, HATCH[0], HATCH[1]))
    return out


HATCH = (1.05, 2.25)
HATCH_D = 0.55  # shallow enough that the camera sees the lit back wall


def _bay_hatch(m, lights, glass, stars, a, b):
    """Galley pass-through: a shallow opening behind the serving counter with
    a warm back-lit wall and steel shelving in silhouette in front of it (the
    hull body behind it is cut away by ``cavities``)."""
    lo, hi = HATCH
    back = HZ - HATCH_D
    _panel_pair(m, a, b, hi + 0.1, FIELD_TOP)
    m.box(a, b, HZ - 0.06, HZ + 0.02, SKIRT_TOP + 0.06, lo, PAINT_DARK)
    m.box(a, b, back - 0.05, back, lo - 0.04, hi + 0.02, PAINT_DARK)
    m.box(a + 0.04, b - 0.04, back, back + 0.01, lo, hi, "M_Ops_Light_Hatch")
    m.box(a, b, back, HZ + 0.02, lo - 0.04, lo, PAINT_MID)
    m.box(a, b, back, HZ + 0.06, hi, hi + 0.1, STEEL)
    m.box(a - 0.04, a + 0.04, back, HZ + 0.06, lo, hi, STEEL)
    m.box(b - 0.04, b + 0.04, back, HZ + 0.06, lo, hi, STEEL)
    # Galley shelving with stacked trays and canisters, dark against the glow.
    for k, hh in enumerate((1.3, 1.56)):
        m.box(a + 0.05, b - 0.05, back + 0.01, back + 0.2, hh, hh + 0.02, "M_Trim_BrushedSteel")
        n = 4 + k
        for i in range(n):
            x = a + 0.25 + i * (b - a - 0.5) / (n - 1)
            if (i + k) % 3 == 2:
                m.box(x - 0.14, x + 0.14, back + 0.03, back + 0.18, hh + 0.02, hh + 0.09, STEEL)
            else:
                m.cyl(x, back + 0.11, 0.07, hh + 0.02, hh + 0.2, "M_Trim_BrushedSteel", 16)
    for x in (a + 0.3, b - 0.3):
        m.box(x - 0.015, x + 0.015, back + 0.01, back + 0.2, lo, hi, STEEL)


def _valance(m: Mesh, lights: Mesh, x0: float, x1: float) -> None:
    m.box(x0, x1, HZ - 0.05, HZ + 0.36, FIELD_TOP, FIELD_TOP + 0.36, STEEL)
    m.box(x0, x1, HZ + 0.3, HZ + 0.38, FIELD_TOP - 0.02, FIELD_TOP + 0.36, PAINT_DARK)
    lights.quad_h(
        x0 + 0.1, x1 - 0.1, HZ + 0.04, HZ + 0.26, FIELD_TOP - 0.005, "M_Light_WallStrip", up=False
    )


def _pier(m: Mesh, lights: Mesh, x0: float, x1: float) -> None:
    """Heavy structural pier where the room walls meet the hull."""
    m.box(x0, x1, HZ - 0.1, HZ + 0.32, 0.0, L.ROOM_H, STEEL)
    w = x1 - x0
    for k in range(int(w / 0.6)):
        xa = x0 + 0.15 + k * 0.6
        if xa + 0.35 > x1 - 0.1:
            break
        m.box(xa, xa + 0.35, HZ + 0.32, HZ + 0.36, 0.3, L.ROOM_H - 0.4, "M_Hull_Structure")
    m.box(x0 + 0.08, x1 - 0.08, HZ + 0.32, HZ + 0.4, 0.0, 0.25, PAINT_DARK)
    # A red marker lamp at the top of each pier.
    xc = (x0 + x1) / 2
    lights.box(xc - 0.05, xc + 0.05, HZ + 0.36, HZ + 0.38, 3.9, 4.05, "M_Indicator_Red")


def _lozenges() -> None:
    """Staggered slot lights in every `slots` bay: the fleet's light signature."""
    m = Mesh()
    pattern = (0.34, 0.2, 0.34, 0.34, 0.2, 0.34, 0.2)
    for a, b in _SLOT_BAYS:
        xc = (a + b) / 2
        for col, dx in enumerate((-0.17, 0.0, 0.17)):
            h = SKIRT_TOP + 0.4 + (0.17 if col == 1 else 0.0)
            i = col
            while True:
                ln = pattern[i % len(pattern)]
                if h + ln > FIELD_TOP - 0.35:
                    break
                m.box(
                    xc + dx - 0.04,
                    xc + dx + 0.04,
                    HZ - 0.07,
                    HZ - 0.045,
                    h,
                    h + ln,
                    "M_Light_WallStrip",
                )
                h += ln + 0.12
                i += 1
    o = m.build("SM_Ops_SlotLights", bevel=0.03, segments=4)
    tag(o, nav="none")
    _SLOT_BAYS.clear()
