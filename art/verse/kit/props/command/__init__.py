"""Command props: consoles, tables, seats and crew fittings for the Verse decks.

Importing this package registers every piece with the kit registry, so deck
builders can ``kit.place("SM_...")``. See README.md for the piece list,
dimensions, anchors and sockets.
"""

from __future__ import annotations

from . import (  # noqa: F401 - importing registers the pieces
    consoles,
    crew,
    engineering,
    fittings,
    hangar,
    seating,
    tables,
)

PIECES = (
    "SM_Console_CrewPit",
    "SM_Console_CrewPitB",
    "SM_Console_CrewPitDouble",
    "SM_Console_Standing",
    "SM_Terminal_Wall",
    "SM_Console_Command",
    "SM_Console_MasterSystems",
    "SM_Terminal_Desk",
    "SM_Terminal_Engineering",
    "SM_Terminal_EngineeringFill",
    "SM_Terminal_EngineeringFillShort",
    "SM_Terminal_EngineeringEnd",
    "SM_Terminal_EngineeringBank",
    "SM_Console_MasterDesk",
    "SM_Console_BoothRear",
    "SM_Counter_Arrivals",
    "SM_Console_Instructor",
    "SM_Chair_Crew",
    "SM_Chair_Bridge",
    "SM_Chair_Conference",
    "SM_Chair_Commander",
    "SM_Stool",
    "SM_Table_HoloStrategy",
    "SM_Table_Briefing",
    "SM_Table_TeamRound",
    "SM_Desk_Commander",
    "SM_Case_Display",
    "SM_Lectern",
    "SM_Board_Rank",
    "SM_Dispenser",
    "SM_Counter_Serving",
    "SM_Counter_Quartermaster",
    "SM_Lockers_Uniform",
    "SM_Platform_Fitting",
    "SM_Table_Mess",
    "SM_Bunk_Double",
    "SM_Bunk_Single",
    "SM_Pod_Simulator",
    "SM_Bed_Medical",
)


def place_without_station(name: str, *args, **kwargs):
    """``kit.place`` that drops the piece's own SOCKET_station.

    For decks that emit their station anchor themselves. Every station piece
    otherwise needs ``station=<id>, station_kind=<kind>`` in ``kit.place``
    (the cook rejects a SOCKET_station without a station_kind).
    """
    import bpy
    from lib import kit

    root = kit.place(name, *args, **kwargs)
    for obj in list(bpy.data.objects):
        if obj.name.startswith("SOCKET_station_") and obj.get("owner") == root.name:
            bpy.data.objects.remove(obj, do_unlink=True)
    return root
