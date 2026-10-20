"""Deck 1 ``bridge``: the Command Bridge.

A 72 x 44 m hall seen from aft: the slanted forward viewports along the top
of the plate, the command walkway running up the middle to the commander's
station, a strategy holo-table on the walkway, two sunken crew pits with
sixteen crew stations, and behind the cut-away aft bulkhead the briefing
room, the turbolift lobby and the commander's ready room.

Layout numbers live in ``layout.py``; the bespoke hero pieces in
``viewport.py`` (forward wall), ``pits.py``, ``hall.py`` and ``aft.py``;
hull structure in ``fill.py``; ceilings and fixtures in ``lights.py``.
Kit pieces (consoles, chairs, stairs, rails, hull bays, ceiling panels) come
from ``art/verse/kit``.

Run: python scripts/verse/cook.py deck bridge --quality preview
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE.parents[1]) not in sys.path:  # art/verse, for `decks.bridge.*`
    sys.path.insert(0, str(_HERE.parents[1]))

from lib import kit, scene  # noqa: E402

DECK_ID = "bridge"
EXPOSURE = 0.0


def _modules():
    names = ("layout", "geo", "panels", "viewport", "hall", "pits", "aft", "fill", "lights")
    mods = {}
    for name in names:
        full = f"decks.bridge.{name}"
        mod = sys.modules.get(full)
        mods[name] = importlib.reload(mod) if mod else importlib.import_module(full)
    return mods


def _load_kit() -> bool:
    """Import the kit families the bridge places; False if any is broken."""
    try:
        for name in (
            "kit.architecture.ceiling",
            "kit.architecture.hull",
            "kit.architecture.structure",
            "kit.props.command",
        ):
            importlib.import_module(name)
    except Exception as error:  # noqa: BLE001 - teammates' modules may be mid-edit
        print(f"[deck-bridge] kit unavailable, using placeholders: {error!r}")
        return False
    return True


def _waypoints(L) -> None:
    def wp(wid, x, z, facing, h=0.0, room="bridge"):
        kit.socket("waypoint", wid, kit.facing_matrix(L.P(x, z, h), facing), room=room)

    for i, x in enumerate((14.4, 21.6, 28.8, 43.2, 50.4, 57.6), start=1):
        wp(f"vp_{i}", x, L.VP_FACE_Z + 0.85, 180.0)
    for i, z in enumerate((16.8, 21.6, 26.4), start=1):
        wp(f"walk_p_{i}", L.WALKWAY_X[0] + 0.7, z, -90.0)
        wp(f"walk_s_{i}", L.WALKWAY_X[1] - 0.7, z, 90.0)
    wp("aft_p", 18.0, L.AFT_EDGE_Z + 1.2, 180.0)
    wp("aft_s", 54.0, L.AFT_EDGE_Z + 1.2, 180.0)
    wp("pit_p_aisle", 18.0, 26.4, 180.0, L.PIT_Z, room="pit_p")
    wp("pit_s_aisle", 54.0, 26.4, 180.0, L.PIT_Z, room="pit_s")
    kit.socket(
        "stand", "command_aide", kit.facing_matrix(L.P(L.AXIS_X + 2.4, 9.0), 180.0), room="bridge"
    )


def _rooms(L) -> None:
    kit.room("bridge", "Command Bridge", L.poly(L.upper_deck_outline()), 0.0, main=True)
    kit.room("pit_p", "Port Crew Pit", L.poly(L.pit_outline(-1)), L.PIT_Z)
    kit.room("pit_s", "Starboard Crew Pit", L.poly(L.pit_outline(1)), L.PIT_Z)
    kit.room(
        "briefing",
        "Briefing Room",
        L.rect(L.BRIEFING_X[0], L.ROOMS_Z[0], L.BRIEFING_X[1], L.ROOMS_Z[1]),
    )
    kit.room(
        "lobby", "Turbolift Lobby", L.rect(L.LOBBY_X[0], L.ROOMS_Z[0], L.LOBBY_X[1], L.ROOMS_Z[1])
    )
    kit.room("ready", "Ready Room", L.rect(L.READY_X[0], L.ROOMS_Z[0], L.READY_X[1], L.ROOMS_Z[1]))


def build() -> None:
    m = _modules()
    L = m["layout"]
    bounds = scene.Bounds(x_min=0.0, y_min=-L.DEPTH, x_max=L.WIDTH, y_max=0.0, z_min=0.0, z_max=6.0)
    scene.new_deck(DECK_ID, bounds, name="Command Bridge", floor=1, exposure=EXPOSURE)
    use_kit = _load_kit()
    arch = scene.collection("Architecture")
    props = scene.collection("Props")
    with kit.into(arch):
        m["hall"].build_deck()
        m["hall"].build_walkway()
        m["hall"].build_side_walls()
        m["viewport"].build()
        m["fill"].build(use_kit)
    with kit.into(props):
        m["hall"].build_command_station(use_kit)
        m["hall"].build_holo_table(use_kit)
    seats = []
    for side in (-1, 1):
        with kit.into(arch):
            m["pits"].build_floor(side)
            m["pits"].build_copings(side)
            m["pits"].build_ledges(side)
            m["pits"].build_systems_wall(side)
            m["pits"].build_stairs(side, use_kit)
            m["pits"].build_railings(side, use_kit)
        with kit.into(props):
            seats += m["pits"].build_rows(side, use_kit)
    with kit.into(arch):
        m["aft"].build_floors()
        m["aft"].build_bulkhead()
        m["aft"].build_aft_wall_and_chases()
    with kit.into(props):
        m["aft"].build_briefing(use_kit)
        m["aft"].build_lobby()
        m["aft"].build_ready(use_kit)
    m["lights"].build()
    _waypoints(L)
    _rooms(L)
    if not use_kit:
        # Placeholder seat/screen sockets so the contract holds without the kit.
        for s in seats:
            kit.socket("seat", s["id"], kit.facing_matrix(L.P(s["x"], s["z"], L.PIT_Z), 180.0))
    print(f"[deck-bridge] built: kit={use_kit}, seats={len(seats)}")


if __name__ == "__main__":
    build()
