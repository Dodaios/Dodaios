"""The hangar above its section cuts: what the plate never shows but the
eye-level view must (BRIEF section 5, docs/verse/realtime.md).

All of it is built as ceiling ghosts: invisible to the plate camera and to
shadow rays, it closes the rooms for floor reflections and probes, and the
realtime export turns it into normal walls.

- Side hull walls over the flight deck: cut at 4.5 m; closed up to the 21 m
  ceiling with hull frames on the ceiling girders' 7.2 m rhythm.
- Front skin: the hangar's near wall above the front band's 4.7 m ceiling,
  from the band's ceiling edge up to the hangar ceiling.
- Front band (booth, crew bay, arrivals, lift lobby, armoury): the near hull
  wall, the side walls and the room walls cut at 1.1 m, closed up to the
  band ceiling, with door heads over the openings and the booth's window
  wall glazed up to its head.

The front band's upper walls are dark paint and charcoal enamel panels over
a gunmetal rail at the cut, with thin light strips: the mid-grey wainscot
below the cut stays as the plate shows it, and at eye level the rooms read
as panelled walls instead of flat light-grey slabs.
"""

from __future__ import annotations

import hangar_arch as arch
import hangar_layout as L
from hangar_arch import CEILING_H, HULL, PANEL_DARK, PANEL_MID, RECESS, STEEL, box
from lib import kit

BAND_CEILING = 4.7  # underside of the front band's ceiling slab
DOOR_HEAD = 2.7
PANEL_INSET = 0.02
GLASS = "M_Glass_Viewport"
CHARCOAL = "M_Wall_Charcoal"
STRIP = "M_Light_WallStrip"
STRIP_EVERY = 4  # a vertical light strip after every this many panels


def _panel_mat(i: int, mat: str | None) -> str:
    """`mat`, or dark paint alternating with charcoal enamel."""
    if mat is not None:
        return mat
    return CHARCOAL if i % 3 == 1 else PANEL_DARK


def _panels_x(mb: kit.MeshBuilder, x0, x1, z_face, h0, h1, toward, module=1.2, mat=None,
              lights=None):  # fmt: skip
    """Inset panels on a face at plan z = z_face facing `toward` (+1 = toward +z);
    with `lights`, a thin vertical light strip every `STRIP_EVERY` panels."""
    n = max(1, round((x1 - x0) / module))
    step = (x1 - x0) / n
    za, zb = sorted((z_face, z_face + toward * PANEL_INSET))
    la, lb = sorted((z_face, z_face + toward * (PANEL_INSET + 0.006)))
    for i in range(n):
        a, b = x0 + i * step, x0 + (i + 1) * step
        box(mb, a + 0.008, b - 0.008, za, zb, h0 + 0.02, h1 - 0.02, _panel_mat(i, mat))
        if lights is not None and i > 0 and i % STRIP_EVERY == 0:
            box(lights, a - 0.02, a + 0.02, la, lb, h0 + 0.25, h1 - 0.25, STRIP)


def _panels_z(mb: kit.MeshBuilder, z0, z1, x_face, h0, h1, toward, module=1.2, mat=None,
              lights=None):  # fmt: skip
    """Inset panels on a face at plan x = x_face facing `toward` (+1 = toward +x);
    with `lights`, a thin vertical light strip every `STRIP_EVERY` panels."""
    n = max(1, round((z1 - z0) / module))
    step = (z1 - z0) / n
    xa, xb = sorted((x_face, x_face + toward * PANEL_INSET))
    la, lb = sorted((x_face, x_face + toward * (PANEL_INSET + 0.006)))
    for i in range(n):
        a, b = z0 + i * step, z0 + (i + 1) * step
        box(mb, xa, xb, a + 0.008, b - 0.008, h0 + 0.02, h1 - 0.02, _panel_mat(i, mat))
        if lights is not None and i > 0 and i % STRIP_EVERY == 0:
            box(lights, la, lb, a - 0.02, a + 0.02, h0 + 0.25, h1 - 0.25, STRIP)


def _band_face_z(faces, lights, x_face, toward, z0, z1, h0, top):
    """Rail at the cut, panels with strips, recessed top on a face at plan x = x_face."""
    lo, hi = sorted((x_face, x_face + toward * 0.05))
    box(faces, lo, hi, z0, z1, h0, h0 + 0.12, STEEL)
    _panels_z(faces, z0, z1, x_face, h0 + 0.12, top - 0.3, toward, lights=lights)
    lo, hi = sorted((x_face, x_face + toward * 0.03))
    box(faces, lo, hi, z0, z1, top - 0.3, top, RECESS)


def side_walls() -> None:
    """Side hull walls from their 4.5 m cut up to the ceiling, over the flight deck."""
    body, faces = kit.MeshBuilder(), kit.MeshBuilder()
    top = CEILING_H + 0.4
    girders = [3.6 + 7.2 * i for i in range(7)]
    for x0, x1, x_face, s in (
        (-2.0, L.SIDE_T, L.SIDE_T, 1),
        (L.WIDTH - L.SIDE_T, L.WIDTH + 2.0, L.WIDTH - L.SIDE_T, -1),
    ):
        box(body, x0, x1, 0.0, L.FRONT_Z, arch.SIDE_CUT_H, top, HULL)
        # Panels between the frames, in three tiers split by gunmetal bands.
        edges = [L.WALL_FACE_Z, *girders, L.FRONT_Z]
        for a, b in zip(edges, edges[1:], strict=False):
            for h0, h1 in ((arch.SIDE_CUT_H, 9.6), (9.9, 15.0), (15.3, CEILING_H - 1.6)):
                _panels_z(faces, a + 0.45, b - 0.45, x_face, h0, h1, s, module=2.4, mat=PANEL_MID)
        for h in (arch.SIDE_CUT_H, 9.6, 15.0):
            lo, hi = sorted((x_face, x_face + s * 0.12))
            box(faces, lo, hi, L.WALL_FACE_Z, L.FRONT_Z, h, h + 0.3, STEEL)
        # Frames: deep I-section posts under every ceiling girder.
        for z in girders:
            lo, hi = sorted((x_face, x_face + s * 0.6))
            box(faces, lo, hi, z - 0.4, z + 0.4, arch.SIDE_CUT_H, CEILING_H, STEEL)
            lo, hi = sorted((x_face + s * 0.6, x_face + s * 0.7))
            box(faces, lo, hi, z - 0.25, z + 0.25, arch.SIDE_CUT_H, CEILING_H, STEEL)
    arch._build(body, "SM_Hangar_SideWallsUpper", bevel=0.0, collection="Ceiling")
    arch._build(faces, "SM_Hangar_SideWallsUpperFaces", bevel=0.004, collection="Ceiling")


def front_skin() -> None:
    """The hangar's near wall above the front band, facing the flight deck."""
    body, faces = kit.MeshBuilder(), kit.MeshBuilder()
    z_face = L.FRONT_Z
    top = CEILING_H + 0.4
    box(body, -2.0, L.WIDTH + 2.0, z_face, z_face + 0.3, BAND_CEILING, top, HULL)
    # A deep fascia over the band's ceiling edge, then panels between frames.
    box(faces, L.SIDE_T, L.WIDTH - L.SIDE_T, z_face - 0.3, z_face, BAND_CEILING - 0.05, 5.6, STEEL)
    posts = [2.4 + 7.2 * i for i in range(14)]
    edges = [L.SIDE_T, *[x for x in posts if L.SIDE_T < x < L.WIDTH - L.SIDE_T], L.WIDTH - L.SIDE_T]
    for a, b in zip(edges, edges[1:], strict=False):
        for h0, h1 in ((5.6, 9.6), (9.9, 15.0), (15.3, CEILING_H - 1.6)):
            _panels_x(faces, a + 0.4, b - 0.4, z_face, h0, h1, -1, module=2.4, mat=PANEL_MID)
    for h in (9.6, 15.0):
        box(faces, L.SIDE_T, L.WIDTH - L.SIDE_T, z_face - 0.12, z_face, h, h + 0.3, STEEL)
    for x in posts:
        if L.SIDE_T < x < L.WIDTH - L.SIDE_T:
            box(faces, x - 0.3, x + 0.3, z_face - 0.6, z_face, 5.6, CEILING_H, STEEL)
    arch._build(body, "SM_Hangar_FrontSkin", bevel=0.0, collection="Ceiling")
    arch._build(faces, "SM_Hangar_FrontSkinFaces", bevel=0.004, collection="Ceiling")


def front_band() -> None:
    """The front band's cut walls closed up to the band ceiling."""
    cut = L.CUT_H
    nz0, nz1 = L.NEAR_WALL_Z
    body, faces, lights = kit.MeshBuilder(), kit.MeshBuilder(), kit.MeshBuilder()
    # Near hull wall, room face at nz0 facing -z.
    box(body, -2.0, L.WIDTH + 2.0, nz0, nz1, cut, BAND_CEILING + 0.3, PANEL_DARK)
    box(faces, L.SIDE_T, L.WIDTH - L.SIDE_T, nz0 - 0.04, nz0, cut, cut + 0.12, STEEL)
    _panels_x(faces, L.SIDE_T, L.WIDTH - L.SIDE_T, nz0, cut + 0.12, BAND_CEILING - 0.3, -1,
              lights=lights)  # fmt: skip
    box(faces, L.SIDE_T, L.WIDTH - L.SIDE_T, nz0 - 0.03, nz0, BAND_CEILING - 0.3, BAND_CEILING,
        RECESS)  # fmt: skip
    # Side walls in the band.
    for x0, x1, x_face, s in (
        (-2.0, L.SIDE_T, L.SIDE_T, 1),
        (L.WIDTH - L.SIDE_T, L.WIDTH + 2.0, L.WIDTH - L.SIDE_T, -1),
    ):
        box(body, x0, x1, L.FRONT_Z, nz1, cut, BAND_CEILING + 0.3, PANEL_DARK)
        _band_face_z(faces, lights, x_face, s, L.FRONT_Z, nz0, cut, BAND_CEILING)
    # Booth: window wall glazed up to its head, side walls up to the ceiling.
    bx0, bx1, bz0, _ = L.BOOTH
    bf = L.BOOTH_FLOOR
    head = BAND_CEILING - 0.35
    box(body, bx0, bx1, bz0, bz0 + 0.35, head, BAND_CEILING, PANEL_DARK)
    box(faces, bx0 + 0.3, bx1 - 0.3, bz0 + 0.12, bz0 + 0.2, bf + cut, head, GLASS)
    for x in [bx0 + 0.3 + i * 2.4 for i in range(10)]:
        box(faces, x - 0.06, x + 0.06, bz0 + 0.05, bz0 + 0.3, bf + cut, head, STEEL)
    box(body, bx0, bx0 + 0.3, bz0, nz0, bf + cut, BAND_CEILING, PANEL_DARK)
    box(body, bx1 - 0.3, bx1, bz0, 53.4, bf + cut, BAND_CEILING, PANEL_DARK)
    box(body, bx1 - 0.3, bx1, 57.6, nz0, bf + cut, BAND_CEILING, PANEL_DARK)
    box(body, bx1 - 0.3, bx1, 53.4, 57.6, bf + DOOR_HEAD - 0.3, BAND_CEILING, PANEL_DARK)
    # The booth's east wall, crew bay side (the floor there is 1.2 m lower).
    for z0, z1 in ((bz0, 53.4), (57.6, nz0)):
        _band_face_z(faces, lights, bx1, 1, z0, z1, bf + cut, BAND_CEILING)
    box(faces, bx1 - 0.35, bx1 + 0.05, 53.4, 57.6, bf + DOOR_HEAD - 0.36, bf + DOOR_HEAD - 0.3,
        STEEL)  # fmt: skip
    # Armoury: north wall with its door head, west wall.
    ax0, ax1, az0, _ = L.ARMOURY
    for xa, xb in ((ax0, 78.6), (81.2, ax1)):
        box(body, xa, xb, az0, az0 + 0.3, cut, BAND_CEILING, PANEL_DARK)
        _panels_x(faces, xa, xb, az0, cut, BAND_CEILING - 0.3, -1)
    box(body, 78.6, 81.2, az0, az0 + 0.3, DOOR_HEAD, BAND_CEILING, PANEL_DARK)
    box(faces, 78.6, 81.2, az0 - 0.01, az0 + 0.31, DOOR_HEAD - 0.04, DOOR_HEAD, STEEL)
    box(body, ax0, ax0 + 0.3, az0, nz0, cut, BAND_CEILING, PANEL_DARK)
    _band_face_z(faces, lights, ax0, -1, az0, nz0, cut, BAND_CEILING)  # lift lobby side
    _band_face_z(faces, lights, ax0 + 0.3, 1, az0 + 0.3, nz0, cut, BAND_CEILING)  # armoury side
    # Lift lobby | arrivals divider.
    x0, x1 = L.LOBBY[0] - 0.15, L.LOBBY[0] + 0.15
    box(body, x0, x1, 52.8, nz0, cut, BAND_CEILING, PANEL_DARK)
    _band_face_z(faces, lights, x0, -1, 52.8, nz0, cut, BAND_CEILING)
    _band_face_z(faces, lights, x1, 1, 52.8, nz0, cut, BAND_CEILING)
    arch._build(body, "SM_Hangar_FrontBandUpper", bevel=0.004, collection="Ceiling")
    arch._build(faces, "SM_Hangar_FrontBandUpperFaces", bevel=0.003, collection="Ceiling")
    arch._build(lights, "SM_Hangar_FrontBandUpperStrips", bevel=0.0, collection="Ceiling")


def build() -> None:
    with kit.ghost(L.CUT_H):
        side_walls()
        front_skin()
        front_band()
