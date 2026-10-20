"""Deck 3, Reactor Engineering: reactor shaft, engineering control room,
power conduit gallery, turbolift lobby and maintenance bay (LEVELS.md).

Layout in three.js metres, W 84 x D 54: control room at the west (12 coding
terminals in three rows facing the camera, master systems console against the
far wall), the reactor shaft at (54, 22) behind a glass partition, the conduit
gallery along the near side, lobby and maintenance bay in the south-west.

Run: python scripts/verse/cook.py deck engineering --quality preview
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import bpy  # noqa: E402
import eng_arch  # noqa: E402
import eng_common as c  # noqa: E402
import eng_reactor  # noqa: E402
import eng_rooms  # noqa: E402
import eng_sockets  # noqa: E402
from lib import scene  # noqa: E402

DECK_ID = "engineering"


def build() -> None:
    bounds = scene.Bounds(
        x_min=0.0, y_min=-c.DECK_D, x_max=c.DECK_W, y_max=0.0, z_min=-1.0, z_max=c.HALL_H
    )
    scene.new_deck(DECK_ID, bounds, name="Reactor Engineering", floor=3, exposure=0.0)
    c.KIT_REACTOR = c.kit_module("kit.props.industrial")
    c.KIT_COMMAND = c.kit_module("kit.props.command")
    c.KIT_ARCH = c.kit_module("kit.architecture")
    if c.KIT_ARCH:
        from kit import architecture

        architecture.load_all()
    eng_arch.OCCLUDER_BOXES.clear()
    eng_arch.build()
    eng_reactor.build()
    eng_rooms.build()
    eng_sockets.build()
    bpy.context.view_layer.update()  # world matrices for the cook's socket export


if __name__ == "__main__":
    build()
