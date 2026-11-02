"""Zones of reactor engineering (deck 3) for Unreal (WP12.6).

Each zone is a box of the deck that one work package owns (contracts/art-pipeline.md 9);
all engineering zones are WP12's. The reactor shaft stays a deck feature; the duel moved to
the hangar (README "Arena"). `art/verse/kit/deck_import.py` turns the rooms, sockets and
stations into `unreal/Verse/Art/Placements/engineering/<zone>.placement.json`.
Pure data: importing this file needs no bpy.
"""

from __future__ import annotations

from collections import namedtuple

Zone = namedtuple("Zone", "id rooms rest", defaults=((), False))

ZONES = (
    Zone("control", ("control",)),
    Zone("reactor", ("reactor",)),
    Zone("gallery", ("gallery",)),
    Zone("bay", ("bay",)),
    Zone("lift_lobby", ("lobby",), rest=True),
)
