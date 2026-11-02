"""Hangar zone `day_stations` for Unreal (WP12.7): the arrivals counter with the
`create_agent` station where new agents come aboard. The other hangar zones are WP11's.
Pure data: importing this file needs no bpy.
"""

from __future__ import annotations

from collections import namedtuple

Zone = namedtuple("Zone", "id rooms rest", defaults=((), False))

ZONE = Zone("day_stations", ("arrivals",))
