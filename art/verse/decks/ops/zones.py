"""Zones of the operations deck (deck 2) for Unreal (WP12.5).

Each zone is a box of the deck that one work package owns (contracts/art-pipeline.md 9);
all ops zones are WP12's. A zone claims manifest rooms; `art/verse/kit/deck_import.py`
turns them, their sockets and stations into `unreal/Verse/Art/Placements/ops/<zone>.placement.json`.
Pure data: importing this file needs no bpy.
"""

from __future__ import annotations

from collections import namedtuple

Zone = namedtuple("Zone", "id rooms rest", defaults=((), False))

ZONES = (
    Zone("corridor", ("corridor",)),
    Zone("lift_lobby", ("lobby",), rest=True),
    Zone("quarters", ("quarters",)),
    Zone("mess", ("mess",)),
    Zone("medbay", ("medbay",)),
    Zone("quartermaster", ("quartermaster", "storage")),
    Zone("records", ("records",)),
    Zone("simulator", ("simulator",)),
    Zone("team_rooms", ("team_a", "team_b")),
)
