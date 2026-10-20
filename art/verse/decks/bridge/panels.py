"""Instrument faces for the bridge's console banks and rack walls.

A face is drawn in a panel frame (X right, Y up, Z out toward the viewer)
into three builders: ``body`` (bezels, blank plates), ``keys`` (unlit caps,
grilles) and ``lamps`` (backlit tiles and indicator lamps). Layouts follow
the real thing: legends in columns, slat read-outs, a small screen, blank
access plates; mostly white light with a little red, a rare green or amber.
"""

from __future__ import annotations

from lib import kit
from mathutils import Matrix

from .geo import xform

WHITE = "M_Indicator_White"
RED = "M_Indicator_Red"
GREEN = "M_Indicator_Green"
AMBER = "M_Indicator_Amber"
BEZEL = "M_Console_Deck"
DARK = "M_Console_Body"
KEYS = "M_Console_Keys"
SCREEN = "M_Screen"
RECESS = "M_Recess_Dark"

STYLES = ("legend", "slats", "screen", "blank", "matrix", "legend2")


def _h(*parts) -> float:
    return (kit.seed_for(*parts) % 10000) / 10000.0


def face(mbs: dict, frame: Matrix, w: float, h: float, style: str, seed) -> None:
    """Draw one instrument face of ``w`` x ``h`` centred on ``frame``."""
    body, keys, lamps = mbs["body"], mbs["keys"], mbs["lamps"]
    with xform(body, frame):
        body.box((-w / 2, -h / 2, 0.0), (w / 2, h / 2, 0.012), DARK)
    fn = {
        "legend": _legend,
        "legend2": _legend2,
        "slats": _slats,
        "screen": _screen,
        "blank": _blank,
        "matrix": _matrix,
    }[style]
    fn(body, keys, lamps, frame, w, h, seed)


def _tile(mb, frame, x0, y0, x1, y1, mat, z=0.012, t=0.006):
    with xform(mb, frame):
        mb.box((x0, y0, z), (x1, y1, z + t), mat)


def _pick(seed, *keys, red=0.18, green=0.03, amber=0.02, dark=0.3) -> str | None:
    r = _h(seed, *keys)
    if r < dark:
        return None
    r = (r - dark) / (1 - dark)
    if r < red:
        return RED
    if r < red + green:
        return GREEN
    if r < red + green + amber:
        return AMBER
    return WHITE


def _legend(body, keys, lamps, frame, w, h, seed) -> None:
    """Two columns of backlit legend tiles in mid-grey bezels."""
    cols = 2
    cw = (w - 0.12) / cols
    for c in range(cols):
        cx0 = -w / 2 + 0.06 + c * cw
        _tile(body, frame, cx0 + 0.02, -h / 2 + 0.1, cx0 + cw - 0.02, h / 2 - 0.08, BEZEL)
        rows = 6
        th = (h - 0.3) / rows
        for r in range(rows):
            y0 = -h / 2 + 0.14 + r * th
            mat = _pick(seed, c, r, dark=0.22)
            x0, x1 = cx0 + 0.06, cx0 + cw - 0.06
            if mat is None:
                _tile(keys, frame, x0, y0, x1, y0 + th * 0.62, KEYS, z=0.018)
            else:
                _tile(lamps, frame, x0, y0, x1, y0 + th * 0.62, mat, z=0.018, t=0.004)


def _legend2(body, keys, lamps, frame, w, h, seed) -> None:
    """Tall legend column beside a stack of small square lamps."""
    _tile(body, frame, -w / 2 + 0.06, -h / 2 + 0.08, 0.02, h / 2 - 0.08, BEZEL)
    rows = 9
    th = (h - 0.24) / rows
    for r in range(rows):
        y0 = -h / 2 + 0.12 + r * th
        mat = _pick(seed, "l2", r, dark=0.3)
        target, m = (keys, KEYS) if mat is None else (lamps, mat)
        _tile(target, frame, -w / 2 + 0.1, y0, -0.02, y0 + th * 0.55, m, z=0.018, t=0.004)
    for r in range(6):
        for c in range(3):
            x = 0.1 + c * 0.11
            y = -h / 2 + 0.2 + r * 0.16
            mat = _pick(seed, "sq", r, c, red=0.3, dark=0.55)
            target, m = (keys, KEYS) if mat is None else (lamps, mat)
            _tile(target, frame, x, y, x + 0.06, y + 0.06, m, z=0.012, t=0.006)


def _slats(body, keys, lamps, frame, w, h, seed) -> None:
    """Horizontal slat read-out with a lamp column."""
    _tile(body, frame, -w / 2 + 0.06, -h / 2 + 0.12, w / 2 - 0.2, h / 2 - 0.1, BEZEL)
    n = 10
    sh = (h - 0.34) / n
    for i in range(n):
        y = -h / 2 + 0.17 + i * sh
        lit = _h(seed, "s", i) > 0.2
        mat = RED if _h(seed, "r", i) < 0.12 else WHITE
        target, m = (lamps, mat) if lit else (keys, KEYS)
        _tile(target, frame, -w / 2 + 0.1, y, w / 2 - 0.24, y + sh * 0.45, m, z=0.018, t=0.004)
    for i in range(5):
        y = -h / 2 + 0.2 + i * 0.2
        mat = _pick(seed, "c", i, red=0.35, dark=0.35)
        target, m = (keys, KEYS) if mat is None else (lamps, mat)
        _tile(target, frame, w / 2 - 0.15, y, w / 2 - 0.09, y + 0.08, m, z=0.012, t=0.008)


def _screen(body, keys, lamps, frame, w, h, seed) -> None:
    """Small read-out screen in a bezel with a key row under it."""
    sw, sh = min(0.58, w - 0.3), min(0.42, h * 0.38)
    cy = h / 2 - 0.12 - sh / 2
    _tile(body, frame, -sw / 2 - 0.05, cy - sh / 2 - 0.05, sw / 2 + 0.05, cy + sh / 2 + 0.05, BEZEL)
    _tile(lamps, frame, -sw / 2, cy - sh / 2, sw / 2, cy + sh / 2, SCREEN, z=0.016, t=0.002)
    for r in range(3):
        for c in range(7):
            x = -0.33 + c * 0.11
            y = -h / 2 + 0.16 + r * 0.1
            mat = _pick(seed, "k", r, c, red=0.25, dark=0.6)
            target, m = (keys, KEYS) if mat is None else (lamps, mat)
            _tile(target, frame, x, y, x + 0.07, y + 0.05, m, z=0.012, t=0.008)


def _blank(body, keys, lamps, frame, w, h, seed) -> None:
    """Access plate with a vent grille and one status lamp."""
    _tile(body, frame, -w / 2 + 0.05, -h / 2 + 0.05, w / 2 - 0.05, h / 2 - 0.05, DARK, t=0.008)
    for i in range(7):
        y = -h / 2 + 0.2 + i * 0.06
        _tile(keys, frame, -w / 2 + 0.16, y, w / 2 - 0.16, y + 0.025, RECESS, z=0.02, t=0.002)
    mat = GREEN if _h(seed, "b") < 0.5 else WHITE
    _tile(lamps, frame, w / 2 - 0.18, h / 2 - 0.16, w / 2 - 0.12, h / 2 - 0.12, mat, z=0.02)
    _tile(keys, frame, -0.06, h / 2 - 0.2, 0.06, h / 2 - 0.17, "M_Trim_BrushedSteel", z=0.02)


def _matrix(body, keys, lamps, frame, w, h, seed) -> None:
    """Indicator matrix: square lamps, sparsely lit."""
    _tile(body, frame, -w / 2 + 0.06, -h / 2 + 0.1, w / 2 - 0.06, h / 2 - 0.1, BEZEL)
    cols, rows = 7, 8
    for r in range(rows):
        for c in range(cols):
            x = -w / 2 + 0.12 + c * (w - 0.24) / cols
            y = -h / 2 + 0.16 + r * (h - 0.32) / rows
            mat = _pick(seed, "m", r, c, red=0.22, dark=0.5)
            target, m = (keys, KEYS) if mat is None else (lamps, mat)
            _tile(target, frame, x, y, x + 0.07, y + 0.07, m, z=0.012, t=0.006)


def style_for(seed, i: int) -> str:
    """Deterministic, rhythmic style sequence (no two identical neighbours)."""
    cycle = ("legend", "slats", "legend2", "screen", "legend", "matrix", "blank", "slats")
    return cycle[(i + kit.seed_for(seed) % len(cycle)) % len(cycle)]


def builders() -> dict:
    return {"body": kit.MeshBuilder(), "keys": kit.MeshBuilder(), "lamps": kit.MeshBuilder()}


def finish(mbs: dict, prefix: str, **props) -> None:
    mbs["body"].build(f"{prefix}_faces", bevel_width=0.003, segments=1, **props)
    mbs["keys"].build(f"{prefix}_keys", bevel_width=0.0015, segments=1, **props)
    lamps = mbs["lamps"].build(f"{prefix}_lamps", bevel_width=0.0, **props)
    if lamps is not None:
        lamps.visible_shadow = False
