"""Space view meshes for the Unreal Verse (WP12.9): the Earth sphere and the star dome.

Importing this package registers two kit pieces (own work, built from code):

* ``SM_Space_Earth`` - a UV sphere of radius 1 m, 96 x 48 segments, equirectangular
  UVs (longitude -180 deg at U = 0, north pole at the top), material ``M_Space_Earth``;
* ``SM_Space_StarDome`` - the same sphere with its faces turned inward, material
  ``M_Space_Stars``.

`AVerseSpaceView` (`unreal/Verse/Source/VerseDecks`) scales both, keeps them at the
camera (space at infinity, no parallax) and turns the Earth at today's orbital rate. The
textures are own work too (`kit/props/space/space_textures.py`); the MI recipes are in
`kit/mi_recipes.py` (`SPACE`). Neither piece has collision.
"""

from __future__ import annotations

import bmesh
import bpy
from lib import kit

EARTH_MATERIAL = "M_Space_Earth"
STARS_MATERIAL = "M_Space_Stars"
SEGMENTS = 96
RINGS = 48

PIECES = ("SM_Space_Earth", "SM_Space_StarDome")


def _material(name: str) -> bpy.types.Material:
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)
        material.diffuse_color = (0.2, 0.2, 0.22, 1.0)
    return material


def _sphere(name: str, material: str, *, inward: bool) -> None:
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=SEGMENTS, v_segments=RINGS, radius=1.0, calc_uvs=True)
    if inward:
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    for poly in mesh.polygons:
        poly.use_smooth = True
    mesh.materials.append(_material(material))
    kit.tag(kit.link(bpy.data.objects.new(name, mesh)), nav="none")


def build_earth() -> None:
    _sphere("SM_Space_Earth_body", EARTH_MATERIAL, inward=False)


def build_star_dome() -> None:
    _sphere("SM_Space_StarDome_body", STARS_MATERIAL, inward=True)


kit.register_variant("SM_Space_Earth", build_earth, dims=(2.0, 2.0, 2.0), nav="none")
kit.register_variant("SM_Space_StarDome", build_star_dome, dims=(2.0, 2.0, 2.0), nav="none")
