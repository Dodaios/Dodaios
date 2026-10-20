"""Ceilings and ceiling light panels (BRIEF section 5: never seen by the
plate camera, but they light the room and mirror in the black floor).

Every object made here has ``visible_camera = False``. The light panels are
real fixtures: a dark housing with a recessed diffuser 4 cm below the
ceiling plane, so their reflections in the floor show a frame, not a hole.

* :func:`ceiling_slab` - the ceiling plane over a polygon or rectangle.
* :func:`panel_grid` - diffuser panels on a regular grid over a rectangle.
* :func:`fill_ceiling` - both, plus one ``SOCKET_light`` describing the grid
  for the runtime's light probes.
* ``SM_CeilingLight_Grid_480`` - a 4.8 x 4.8 m ceiling tile with four panels.
"""

from __future__ import annotations

from collections.abc import Sequence

from lib import kit
from mathutils import Matrix

PANEL = (1.2, 0.6)  # diffuser size (X, Y) in metres
PITCH = (2.4, 2.4)
HOUSING_DEPTH = 0.06


def ceiling_slab(name: str, polygon: Sequence[Sequence[float]], z: float, thickness: float = 0.08):
    mb = kit.MeshBuilder()
    mb.prism_z([tuple(p) for p in polygon], z, z + thickness, "M_Ceiling_Panel")
    obj = mb.build(name, bevel_width=0.0, nav="none")
    return kit.hide_from_camera(obj)


def light_panel(prefix: str, center: Sequence[float], size: Sequence[float] = PANEL) -> None:
    """One recessed diffuser with its housing (camera-invisible)."""
    cx, cy, z = center
    w, d = size[0] / 2, size[1] / 2
    rim = 0.05
    housing = kit.MeshBuilder()
    housing.box(
        (cx - w - rim, cy - d - rim, z - HOUSING_DEPTH),
        (cx + w + rim, cy - d, z),
        "M_Struct_Gunmetal",
    )
    housing.box(
        (cx - w - rim, cy + d, z - HOUSING_DEPTH),
        (cx + w + rim, cy + d + rim, z),
        "M_Struct_Gunmetal",
    )
    housing.box((cx - w - rim, cy - d, z - HOUSING_DEPTH), (cx - w, cy + d, z), "M_Struct_Gunmetal")
    housing.box((cx + w, cy - d, z - HOUSING_DEPTH), (cx + w + rim, cy + d, z), "M_Struct_Gunmetal")
    kit.hide_from_camera(housing.build(f"{prefix}_housing", bevel_width=0.004))
    diffuser = kit.emissive_panel(
        f"{prefix}_diffuser",
        (cx, cy, z - HOUSING_DEPTH + 0.02),
        (size[0], size[1]),
        "M_Light_CeilingPanel",
        normal="-Z",
        camera_visible=False,
    )
    diffuser["light_kind"] = "ceiling_panel"


def panel_grid(
    prefix: str,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    z: float,
    pitch: Sequence[float] = PITCH,
    size: Sequence[float] = PANEL,
) -> int:
    """Panels centred on a grid inside the rectangle; returns the count."""
    nx = max(1, int((x_range[1] - x_range[0]) / pitch[0] + 1e-6))
    ny = max(1, int((y_range[1] - y_range[0]) / pitch[1] + 1e-6))
    x0 = (x_range[0] + x_range[1]) / 2 - (nx - 1) * pitch[0] / 2
    y0 = (y_range[0] + y_range[1]) / 2 - (ny - 1) * pitch[1] / 2
    for i in range(nx):
        for j in range(ny):
            light_panel(
                f"{prefix}_{i:02d}_{j:02d}", (x0 + i * pitch[0], y0 + j * pitch[1], z), size
            )
    return nx * ny


def fill_ceiling(
    room_id: str,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    z: float = 4.5,
    pitch: Sequence[float] = PITCH,
    size: Sequence[float] = PANEL,
) -> None:
    """Ceiling slab + light panel grid over a rectangular room."""
    (x0, x1), (y0, y1) = x_range, y_range
    ceiling_slab(f"CEIL_{room_id}", [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], z)
    count = panel_grid(f"LGT_{room_id}", x_range, y_range, z, pitch, size)
    center = ((x0 + x1) / 2, (y0 + y1) / 2, z - HOUSING_DEPTH)
    kit.socket(
        "light",
        f"{room_id}_ceiling",
        Matrix.Translation(center) @ Matrix.Rotation(3.14159265, 4, "X"),
        room=room_id,
        light_kind="ceiling_grid",
        count=count,
        pitch_x=pitch[0],
        pitch_y=pitch[1],
        panel_w=size[0],
        panel_h=size[1],
        kelvin=6200.0,
    )


@kit.piece("SM_CeilingLight_Grid_480", dims=(4.8, 4.8, 0.1), nav="none")
def build_ceiling_tile(z: float = 4.5) -> None:
    """4.8 x 4.8 m ceiling tile with four diffuser panels (camera-invisible)."""
    ceiling_slab(
        "SM_CeilingLight_Grid_480_slab", [(-2.4, -2.4), (2.4, -2.4), (2.4, 2.4), (-2.4, 2.4)], z
    )
    panel_grid("SM_CeilingLight_Grid_480_lgt", (-2.4, 2.4), (-2.4, 2.4), z)
