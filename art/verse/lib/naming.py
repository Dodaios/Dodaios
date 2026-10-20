"""Naming conventions of the Verse pipeline (pure Python, no bpy).

Shared by the Blender builders, the cook and the validator so a name means the
same thing everywhere. See docs/verse/pipeline.md for the full table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Object / asset prefixes.
STATIC_MESH = "SM_"
SKELETAL_MESH = "SK_"
ANIMATION = "A_"
MATERIAL = "M_"
MATERIAL_INSTANCE = "MI_"
TEXTURE = "T_"
OCCLUDER = "UCX_"
SOCKET = "SOCKET_"
ROOM = "ROOM_"
LEVEL = "LV_"
BLUEPRINT = "BP_"

TEXTURE_SUFFIXES = ("_BC", "_N", "_ORM", "_E", "_M")

SOCKET_KINDS = (
    "screen",
    "seat",
    "stand",
    "bunk",
    "holo",
    "light",
    "door",
    "spawn",
    "lift",
    "station",
    "waypoint",
)

# Values of the `nav` custom property on mesh objects.
NAV_WALK = "walk"
NAV_BLOCK = "block"
NAV_NONE = "none"
NAV_VALUES = (NAV_WALK, NAV_BLOCK, NAV_NONE)

# Child collections of LV_<deck>, in outliner order.
DECK_COLLECTIONS = (
    "Architecture",
    "Props",
    "Lights",
    "Ceiling",
    "Occluders",
    "Sockets",
    "NavOnly",
)

DECK_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_IDENT = r"[A-Za-z0-9][A-Za-z0-9_\-]*"
SOCKET_RE = re.compile(rf"^SOCKET_(?P<kind>[a-z]+)_(?P<id>{_IDENT})$")
ROOM_RE = re.compile(rf"^ROOM_(?P<id>{_IDENT})$")
OCCLUDER_RE = re.compile(rf"^UCX_{_IDENT}$")
STATIC_MESH_RE = re.compile(rf"^SM_{_IDENT}$")
SKELETAL_MESH_RE = re.compile(rf"^SK_{_IDENT}$")
ANIMATION_RE = re.compile(rf"^A_{_IDENT}$")
TEXTURE_RE = re.compile(rf"^T_{_IDENT}(?:{'|'.join(TEXTURE_SUFFIXES)})$")


@dataclass(frozen=True)
class SocketName:
    kind: str
    id: str


def level_name(deck_id: str) -> str:
    if not DECK_ID_RE.match(deck_id):
        raise ValueError(f"deck id must match {DECK_ID_RE.pattern}: {deck_id!r}")
    return f"{LEVEL}{deck_id}"


def socket_name(kind: str, socket_id: str) -> str:
    if kind not in SOCKET_KINDS:
        raise ValueError(f"unknown socket kind {kind!r}; expected one of {SOCKET_KINDS}")
    name = f"{SOCKET}{kind}_{socket_id}"
    if not SOCKET_RE.match(name):
        raise ValueError(f"invalid socket id {socket_id!r}")
    return name


def parse_socket(name: str) -> SocketName | None:
    """`SOCKET_screen_bridge_01` -> SocketName('screen', 'bridge_01'); None if not a socket."""
    match = SOCKET_RE.match(_strip_blender_suffix(name))
    if not match or match["kind"] not in SOCKET_KINDS:
        return None
    return SocketName(kind=match["kind"], id=match["id"])


def room_name(room_id: str) -> str:
    name = f"{ROOM}{room_id}"
    if not ROOM_RE.match(name):
        raise ValueError(f"invalid room id {room_id!r}")
    return name


def parse_room(name: str) -> str | None:
    match = ROOM_RE.match(_strip_blender_suffix(name))
    return match["id"] if match else None


def is_occluder(name: str) -> bool:
    return bool(OCCLUDER_RE.match(_strip_blender_suffix(name)))


def _strip_blender_suffix(name: str) -> str:
    """Drop Blender's automatic `.001` duplicate suffix."""
    return re.sub(r"\.\d{3}$", "", name)
