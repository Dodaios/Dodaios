"""Operations deck (deck 2, ``ops``): the main corridor spine with the mess hall,
records hall, simulator room and quartermaster on its far side, and the crew
quarters, two team ready rooms, the turbolift lobby, stores and the medical bay
on its near side. Layout: art/verse/LEVELS.md (deck 2).

Run: python scripts/verse/cook.py deck ops --quality preview
"""

from __future__ import annotations

import sys
from pathlib import Path

_ART = Path(__file__).resolve().parents[2]
if str(_ART) not in sys.path:
    sys.path.insert(0, str(_ART))

from lib import scene  # noqa: E402

DECK_ID = "ops"


def build() -> None:
    from decks.ops import arch, dressing, facade, mats
    from decks.ops import layout as L

    mats.ensure()
    bounds = scene.Bounds(x_min=0.0, y_min=-L.D, x_max=L.W, y_max=0.0, z_min=0.0, z_max=L.HULL_H)
    bpy_scene = scene.new_deck(DECK_ID, bounds, name="Operations Deck", floor=2, exposure=0.0)
    # Sharper mirrored light panels in the black decks than the default filter.
    bpy_scene.cycles.blur_glossy = 0.4
    arch.build(cavities=facade.cavities())
    bays = facade.build()
    dressing.build(bays)


if __name__ == "__main__":
    build()
