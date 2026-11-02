"""Blender builders of the destructible kit (WP06.2, WP06.3, art-pipeline 13).

Registers, for every piece of `catalogue.catalogue()`:

- `SM_<Piece>`: the Intact render mesh (solid, reference thickness).
- `SM_<Piece>_<State>_<n>`: render mesh of each Holed / Breached variant.
- `SM_<Piece>_Proxy_Intact`, `SM_<Piece>_Proxy_<State>_<n>`: collision-only
  proxies, one `UECOL_Box_<nn>` primitive per proxy box (renamed to `UBX_` at
  export, art-pipeline 3.1); never rendered.
- `SM_<Piece>_Frac`: the seeded Voronoi chunks, one object per chunk, the
  input of `verse_pipeline.geometry_collections` (`GC_<Piece>`). Not for glass.
- `SM_<Piece>_Frac_<State>[_<n>]`: the chunks one state's burst spawns
  (`GC_<Piece>_<State>[_<n>]`, at most the class's body count), from
  `catalogue.debris_sets`. The piece's `DebrisSets` list points at them.

The geometry lives in `geometry.py` and `catalogue.py` (pure Python, tested by
`tests/test_destructible_kit.py`); this module only turns it into objects.
Every builder runs the builder validator first and fails on any error.
"""

from __future__ import annotations

from lib import kit

from . import catalogue as cat
from . import geometry as g
from . import validate

#: Blender material per penetration material (lib/materials.py).
MATERIAL = {
    "sheet_metal": "M_Struct_Gunmetal",
    "container_wall": "M_Crate_Paint",
    "cladding_panel": "M_Wall_Charcoal",
    "glass": "M_Glass_Clear",
    "catwalk_grating": "M_Floor_Grating",
    "ceiling_panel": "M_Ceiling_Panel",
}
PROXY_MATERIAL = "M_Recess_Dark"


def fracture_seed(spec: cat.PieceSpec) -> int:
    return kit.seed_for("verse.destructible", spec.name)


def _object(name: str, mesh: g.Mesh, material: str, **props):
    return kit.mesh_object(name, mesh.verts, mesh.faces, material, bevel_width=0.0, **props)


def _check(spec: cat.PieceSpec, look: cat.StateLook) -> None:
    ref = spec.thickness if look.state == "Intact" else 0.0
    report = validate.check_solid(look.shells, spec.thickness_axis, ref)
    if not report.ok:
        raise ValueError(f"{spec.name} {look.state} {look.variant}: {'; '.join(report.errors)}")


def _render(spec: cat.PieceSpec, look: cat.StateLook, name: str) -> None:
    _check(spec, look)
    nav = "walk" if spec.piece_class == "CatwalkSegment" else "block"
    if spec.piece_class == "CeilingPanel":
        nav = "none"
    _object(f"{name}_body", g.merge(look.shells), MATERIAL[spec.material], nav=nav)


def _proxy(spec: cat.PieceSpec, look: cat.StateLook, name: str) -> None:
    for k, (lo, hi) in enumerate(look.proxy_boxes):
        _object(f"UECOL_Box_{k:02d}", g.box(lo, hi), PROXY_MATERIAL, nav="none")
    # The proxy mesh itself is the union of its boxes (hidden in game, Verse_ProxyOnly).
    _object(
        f"{name}_body",
        g.merge(g.box(lo, hi) for lo, hi in look.proxy_boxes),
        PROXY_MATERIAL,
        nav="none",
    )


def _frac(spec: cat.PieceSpec, name: str) -> None:
    chunks = spec.fracture_chunks(fracture_seed(spec))
    for chunk in chunks:
        _object(
            f"{name}_Chunk_{chunk.cell:02d}", chunk.to_mesh(), MATERIAL[spec.material], nav="none"
        )


def _debris(spec: cat.PieceSpec, debris: cat.DebrisSet, name: str) -> None:
    for chunk in debris.chunks:
        _object(
            f"{name}_Chunk_{chunk.cell:02d}", chunk.to_mesh(), MATERIAL[spec.material], nav="none"
        )


def _register(spec: cat.PieceSpec) -> None:
    dims = (spec.width, spec.depth or spec.thickness, spec.height or spec.thickness)
    for look in spec.looks():
        render_name = (
            spec.name if look.state == "Intact" else f"{spec.name}_{look.state}_{look.variant}"
        )
        proxy_name = f"{spec.name}_Proxy_{look.proxy_name_suffix}"
        kit.register_variant(
            render_name, lambda s=spec, lk=look, n=render_name: _render(s, lk, n), dims=dims
        )
        kit.register_variant(
            proxy_name,
            lambda s=spec, lk=look, n=proxy_name: _proxy(s, lk, n),
            dims=dims,
            nav="none",
        )
    if spec.piece_class != "GlassPane":
        frac_name = f"{spec.name}_Frac"
        kit.register_variant(
            frac_name, lambda s=spec, n=frac_name: _frac(s, n), dims=dims, nav="none"
        )
        for debris in cat.debris_sets(spec, fracture_seed(spec)):
            set_name = f"{frac_name}_{debris.name_suffix}"
            kit.register_variant(
                set_name,
                lambda s=spec, d=debris, n=set_name: _debris(s, d, n),
                dims=dims,
                nav="none",
            )


def load_all() -> None:
    """Registers every destructible piece (the export entry calls this per module)."""
    for spec in cat.catalogue():
        _register(spec)
