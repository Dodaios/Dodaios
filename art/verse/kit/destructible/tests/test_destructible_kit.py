"""WP06 destructible kit: geometry rule, variants, proxies and fracture (pure Python).

Run: python -m pytest art/verse/kit/destructible/tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ART = Path(__file__).resolve().parents[3]  # art/verse
sys.path.insert(0, str(ART))

from kit.destructible import catalogue as cat  # noqa: E402
from kit.destructible import geometry as g  # noqa: E402
from kit.destructible import validate as v  # noqa: E402

PIECES = cat.catalogue()
IDS = [p.name for p in PIECES]


def test_six_classes_and_names():
    assert {p.piece_class for p in PIECES} == {
        "WallPanel",
        "CladdingWall",
        "ContainerWall",
        "GlassPane",
        "CatwalkSegment",
        "CeilingPanel",
    }
    assert {"SM_WallPanel_120", "SM_WallPanel_240", "SM_WallPanel_480"} <= set(IDS)
    for p in PIECES:
        assert p.name.startswith("SM_") and len(p.name) <= 64


@pytest.mark.parametrize("spec", PIECES, ids=IDS)
def test_every_state_is_a_closed_solid_of_reference_thickness(spec):
    for look in spec.looks():
        ref = spec.thickness if look.state == "Intact" else 0.0
        report = v.check_solid(look.shells, spec.thickness_axis, ref)
        assert report.ok, (look.state, look.variant, report.errors)
        if ref:
            assert abs(report.thickness_m - spec.thickness) <= spec.thickness * 0.10


@pytest.mark.parametrize(
    "spec", [p for p in PIECES if p.wall_like], ids=[p.name for p in PIECES if p.wall_like]
)
def test_walls_ship_holed_and_breached_variants(spec):
    looks = spec.looks()
    holed = [lk for lk in looks if lk.state == "Holed"]
    breached = [lk for lk in looks if lk.state == "Breached"]
    assert 1 <= len(holed) <= 4 and 1 <= len(breached) <= 4
    # Holes are to see and shoot through, never to walk through.
    for openings in spec.holed:
        for x0, z0, x1, z1 in openings:
            assert x1 - x0 < 0.9 or z1 - z0 < 1.2
    standing = spec.breached[0][0]
    assert (
        standing[2] - standing[0] >= 0.9 and standing[3] - standing[1] >= 2.0 and standing[1] == 0.0
    )
    low = spec.breached[spec.mantle_variant][0]
    assert low[1] > 0.0 and low[3] <= 1.2, "the low breach is a mantle opening"
    # Variant centroids differ, so the server can pick the nearest one.
    cents = {lk.centroid for lk in holed}
    assert len(cents) == len(holed)


@pytest.mark.parametrize("spec", PIECES, ids=IDS)
def test_proxies_are_simple_and_match_the_material(spec):
    for look in spec.looks():
        assert 1 <= len(look.proxy_boxes) <= 16, "art-pipeline 5: at most 16 primitives"
        for lo, hi in look.proxy_boxes:
            assert all(hi[i] > lo[i] for i in range(3))
            if spec.wall_like:
                # The traced thickness through a wall proxy is the reference thickness.
                assert hi[1] - lo[1] == pytest.approx(spec.thickness, rel=1e-6)


@pytest.mark.parametrize(
    "spec", [p for p in PIECES if p.wall_like], ids=[p.name for p in PIECES if p.wall_like]
)
def test_proxy_openings_match_the_render_openings(spec):
    # A ray straight through the opening centre hits no proxy box; one through solid wall does.
    for look in spec.looks():
        cx, _, cz = look.centroid

        def blocked(x, z, boxes=look.proxy_boxes):
            return any(lo[0] <= x <= hi[0] and lo[2] <= z <= hi[2] for lo, hi in boxes)

        if look.state == "Intact":
            assert blocked(0.0, spec.height / 2)
        else:
            assert not blocked(cx, cz), (look.state, look.variant)


@pytest.mark.parametrize(
    "spec",
    [p for p in PIECES if p.piece_class != "GlassPane"],
    ids=[p.name for p in PIECES if p.piece_class != "GlassPane"],
)
def test_fracture_is_seeded_closed_and_within_budget(spec):
    seed = 0x0600 + len(spec.name)
    a = spec.fracture_chunks(seed)
    b = spec.fracture_chunks(seed)
    assert a, "a geometry collection needs at least one chunk"
    assert len(a) <= cat.MAX_BODIES
    assert [c.to_mesh().verts for c in a] == [c.to_mesh().verts for c in b], (
        "same seed, same chunks"
    )
    for chunk in a:
        assert chunk.size() >= cat.MIN_RIGID_M
        for part in chunk.parts:
            assert v.check_closed(part.to_mesh()).ok
    if spec.fracture_cells > 1:
        assert [c.seed_point for c in spec.fracture_chunks(seed + 1)] != [c.seed_point for c in a]


def test_fracture_conserves_volume():
    spec = cat.by_name("SM_WallPanel_240")
    whole = g.Convex.from_mesh(spec.render_shells([])[0]).volume()
    points = g.voronoi_points((-1.2, 0.0, 0.0), (1.2, 0.003, 2.7), 24, 7)
    chunks = g.fracture(spec.render_shells([]), points)
    assert sum(c.volume() for c in chunks) == pytest.approx(whole, rel=1e-6)


def test_validator_rejects_double_planes_and_open_shells():
    double = g.Mesh()
    double.add([(-1, 0, 0), (1, 0, 0), (1, 0, 2), (-1, 0, 2)], [(0, 1, 2, 3)])
    double.add([(-1, 0.003, 0), (-1, 0.003, 2), (1, 0.003, 2), (1, 0.003, 0)], [(0, 1, 2, 3)])
    report = v.check_solid([double], (0, 1, 0), 0.003)
    assert not report.ok and "watertight" in report.errors[0]
    thick = g.box((-1, 0, 0), (1, 0.1, 2))
    assert not v.check_solid([thick], (0, 1, 0), 0.003).ok, "10 cm is not sheet metal"
    open_box = g.box((-1, 0, 0), (1, 0.003, 2))
    open_box.faces.pop()
    assert not v.check_closed(open_box).ok


def test_slab_with_openings_is_one_manifold_shell():
    slab = g.slab_with_openings(2.4, 2.7, 0.0, 0.04, [(-0.5, 0.0, 0.5, 2.05), (0.7, 1.0, 1.0, 1.3)])
    assert v.check_closed(slab).ok
    with pytest.raises(ValueError):
        g.slab_with_openings(2.4, 2.7, 0.0, 0.04, [(-2.0, 0.0, 0.5, 1.0)])
