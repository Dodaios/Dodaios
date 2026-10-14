# Art study brief: the sky pad and the courier

## Intent

A landing platform standing out of the agents floor into the air of the
city in the singularity, which the person can walk out onto, and on it a
flyable starship: a slender, elegant chrome courier with a pointed nose and
tail, two engine pods on swept outriggers and a glass canopy, gold trim and
blue engine light. An original design; its look serves the Dodaios Verse's
night city and its gold accent.

## Revision 2 (2026-10-14, after the user's review)

The first ship read as a placeholder. The second is a hard-surface design:
a lens hull with a crisp blade edge and needle points, chrome back and a
charcoal belly split at a gold edge trim, inlaid panel seams, belly vents,
a larger bridge with a framed visor, slim pods with flush gold bands, a
recessed nozzle with a glowing core, four stabilisers round each tail
spike, swept wings with gold leading edges, keel and dorsal fins, gold
pinstripes on the nose and navigation lights (red, green and a white
strobe). Everything that does not move is merged per material, so a level
of detail is about thirty meshes.

## Scale and viewing

Authored at 30 m in metres (Blender +Y nose, +Z up), shown at 0.6 scale
(about 19 m) beside the 1.3 m figures. Seen from the office's camera (20° to
72° down, 2.5 m to about 150 m away), from a chase camera 22 m behind it and
from its own canopy.

## Production

- `source/build_courier.py` builds the ship from lofted superellipse
  sections in Blender 5.0 and saves `source/courier.blend`; the three
  collections `CourierLOD0..2` (about 39 k, 17 k and 7 k triangles) are
  exported by `scripts/art/export_study.py` into `exports/` and copied to
  `jarvis/ui/web/frontend/src/assets/society/courier/`.
- Named nodes the runtime drives: `Gear_Nose`, `Gear_Left`, `Gear_Right`
  (retracted by moving them up 1.9 m) and the `EngineGlow` material.
- Materials are PBR (chrome, gold, graphite, canopy glass, emissive glow and
  light strip); the runtime replaces them by name with materials that
  reflect a small environment of the city's night and carry a procedural
  panel bump map. There are no baked texture maps: the hull reads through
  its reflections, which a bake would not improve at this distance.

## Budgets

The ship, its effects and the pad add about a dozen draw calls, most of
them its levels of detail and shadows. The engine sound is synthesised, so
no audio assets are shipped.
