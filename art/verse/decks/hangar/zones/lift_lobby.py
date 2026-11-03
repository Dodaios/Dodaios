"""Hangar zone `lift_lobby` for Unreal (WP12.7): the lift doors, the commander spawn
and the lobby where arrivals walk to the lift. The other hangar zones are WP11's.
Pure data: importing this file needs no bpy.
"""

from __future__ import annotations

from collections import namedtuple

Zone = namedtuple("Zone", "id rooms rest", defaults=((), False))

ZONE = Zone("lift_lobby", ("lift_lobby",))
