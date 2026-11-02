# Destructible kit (WP06)

Builders of the six breakable piece classes of `docs/verse/unreal/contracts/destruction.md`
3.2: wall panel (1.2 / 2.4 / 4.8 m), cladding wall, container wall, glass pane, catwalk segment
and ceiling panel. Owner: WP06. Zone owners place them; they never edit them.

| File | What it does | Needs Blender |
|---|---|---|
| `geometry.py` | Solids: boxes, slabs with real openings, corrugated sheet, bar grating; convex clipping; seeded Voronoi fracture | no |
| `catalogue.py` | The pieces, their reference thickness, Holed and Breached variants (up to 4 each), proxy boxes, opening centroids, fracture chunks | no |
| `validate.py` | The builder validator: closed, manifold, thickness by inward ray sampling within 10 % | no |
| `pieces.py` | Registers `SM_<Piece>`, `SM_<Piece>_<State>_<n>`, `SM_<Piece>_Proxy_<State>[_<n>]` and `SM_<Piece>_Frac` as kit pieces | yes |
| `tests/test_destructible_kit.py` | pytest of all of the above | no |

Run the tests: `python -m pytest art/verse/kit/destructible/tests -q`.

## Geometry rule

Every piece and every variant is one or more solid, closed, manifold shells with the thickness
of its penetration material (sheet metal 0.3 cm, container wall 0.4 cm, cladding 4.0 cm, glass
2.4 cm, bar grating 3.0 cm, ceiling tile 2.5 cm). Openings are cut as real geometry: the slab
face is split on the grid of the opening edges and the opening gets inner walls, so a Holed or
Breached wall is still one closed shell. A double-plane or one-sided wall fails `validate.py`
here and `UVerseDestructibleValidator` in the editor.

Collision proxies of wall-like pieces are flat slabs of exactly the reference thickness (for the
container wall at the middle of the corrugation), at most 16 boxes per state, so the traced
thickness of a bolt through a proxy is the table's reference thickness.

## Fracture spike (WP06.1): verdict

Route chosen: **Voronoi fracture as code in pure Python, exported as `SM_<Piece>_Frac`**, one
object per chunk; `verse_pipeline.geometry_collections` turns that set into `GC_<Piece>`.

| Question | Finding |
|---|---|
| Determinism | Same seed (`kit.seed_for("verse.destructible", name)`), same chunks, byte for byte (pytest) |
| Closed chunks | Every chunk part is a closed convex shell (pytest); chunks conserve the piece volume within 1e-6 |
| Budget | Chunks under 5 cm are left to Niagara, at most 40 rigid chunks per piece (destruction.md 10) |
| Non-convex pieces | The container wall fractures strip by strip (each corrugation run is convex), the grating bar by bar |
| Ceiling panel | One chunk: the whole tile falls |
| Glass | No geometry collection: Niagara shards only |
| Fallback | The editor fracture tool with the same seed, if the GC import below cannot build from chunks |

Not proven yet, and owned outside this folder: the export host
`scripts/verse/export_unreal.py` exports only `kit.architecture` and `kit.props` (its
`KIT_GROUPS`), so `kit.destructible` pieces cannot be exported until it gains a
`Destructible` group and content folder `/Game/Verse/Destruction/`; and
`unreal/Verse/Content/Python/verse_pipeline/geometry_collections.py` is still the reserved
stub. Both are integration-owner paths; the PR of this package lists them as open.
