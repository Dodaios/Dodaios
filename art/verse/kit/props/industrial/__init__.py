"""Industrial props of the Verse kit: reactor shaft, engineering machinery,
hangar equipment and the arrival shuttle.

Importing this package registers every piece with ``lib.kit`` so deck
builders can ``kit.place("SM_...")``. See README.md for the piece table.
"""

from __future__ import annotations

import sys

import bpy

from . import _mats


def _install_material_fallback() -> None:
    """Let ``lib.materials.get`` resolve this package's temporary materials.

    MeshBuilder resolves every material name through ``lib.materials.get``.
    Until the shared library carries the props' own materials, names with
    the ``M_TMP_PropsInd_`` prefix resolve to the local ones built in
    ``_mats``. Other names are untouched. If ``lib.materials`` does not exist
    yet, a minimal stand-in module is registered.
    """
    import lib

    try:
        from lib import materials
    except ImportError:
        import types

        materials = types.ModuleType("lib.materials")

        def get(name: str) -> bpy.types.Material:
            mat = bpy.data.materials.get(name)
            return mat if mat is not None else bpy.data.materials.new(name)

        materials.get = get
        sys.modules["lib.materials"] = materials
        lib.materials = materials
        return
    original = materials.get
    if getattr(original, "_props_industrial", False):
        return

    def get_with_fallback(name: str, *args, **kwargs):
        if name.startswith(_mats.TMP_PREFIX):
            mat = bpy.data.materials.get(name)
            if mat is not None:
                return mat
        return original(name, *args, **kwargs)

    get_with_fallback._props_industrial = True
    materials.get = get_with_fallback


_install_material_fallback()

from . import engineering, hangar, hangar_service, reactor, shuttle  # noqa: E402

__all__ = ["engineering", "hangar", "hangar_service", "reactor", "shuttle"]
