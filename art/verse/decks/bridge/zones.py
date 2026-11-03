"""Zones of the command bridge (deck 1) for Unreal (WP12.4).

Each zone is a box of the deck that one work package owns (contracts/art-pipeline.md 9);
all bridge zones are WP12's. A zone claims manifest rooms; `art/verse/kit/deck_import.py`
turns them, their sockets and stations into `unreal/Verse/Art/Placements/bridge/<zone>.placement.json`.
Pure data: importing this file needs no bpy.
"""

from __future__ import annotations

from collections import namedtuple

Zone = namedtuple("Zone", "id rooms rest", defaults=((), False))

ZONES = (
    Zone("command", ("bridge",)),
    Zone("pits", ("pit_p", "pit_s")),
    Zone("briefing", ("briefing",)),
    Zone("ready_room", ("ready",)),
    Zone("lift_lobby", ("lobby",), rest=True),
)
