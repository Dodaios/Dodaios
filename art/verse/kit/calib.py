"""Calibration assets of the `fbx-ue/1` export settings (art-pipeline 6.1).

`SM_Calib_Axes` is an asymmetric arrow: a 20 cm hub, a long arm toward +X,
a short arm toward +Y, a tall arm toward +Z, and one 45 degree chamfer on the
top edge of the +X tip. No rotation can map it onto itself or its mirror, so
its bounds alone tell whether units, axes and handedness came through right.

`SK_Calib_Rig` is a small armature (`Root` along +Y with roll 0, so its rest
rotation is identity in Unreal; `Calib_Arm` toward +X,
`Calib_Side` toward +Y, each with an end bone at its tip) skinned to a small
box per bone. The import check compares every bone's rest position with
`unreal/Verse/Art/space_vectors.json`.

The numbers below are the contract of the calibration: the vector file holds
the same values converted to Unreal space; change both together and rerun
`python scripts/unreal/import_art.py calib`.
"""

from __future__ import annotations

from lib import kit

MATERIAL = "M_Struct_Gunmetal"

HUB = 0.1  # half size of the hub cube, metres
ARM = 0.05  # half thickness of every arm
X_TIP = 1.0
Y_TIP = 0.5
Z_TIP = 0.8
CHAMFER = 0.05  # 45 degree cut on the top edge of the +X tip

#: Rig bones: (name, parent, head, tail) in Blender metres.
RIG_BONES = (
    ("Root", None, (0.0, 0.0, 0.0), (0.0, 0.2, 0.0)),
    ("Calib_Arm", "Root", (0.0, 0.0, 0.5), (0.4, 0.0, 0.5)),
    ("Calib_Side", "Root", (0.0, 0.0, 0.5), (0.0, 0.25, 0.5)),
    ("Calib_ArmEnd", "Calib_Arm", (0.4, 0.0, 0.5), (0.5, 0.0, 0.5)),
    ("Calib_SideEnd", "Calib_Side", (0.0, 0.25, 0.5), (0.0, 0.35, 0.5)),
)


@kit.piece(
    "SM_Calib_Axes",
    dims=(X_TIP + HUB, Y_TIP + HUB, Z_TIP),
    nav="none",
)
def calib_axes() -> None:
    """Asymmetric axis arrow used to calibrate the Blender-to-Unreal export."""
    mb = kit.MeshBuilder()
    mb.box((-HUB, -HUB, 0.0), (HUB, HUB, 2 * HUB), MATERIAL)
    zc = HUB  # arm centre height
    # +X arm with the chamfer on its top tip edge (profile in XZ, extruded along Y).
    mb.prism_y(
        [
            (HUB, zc - ARM),
            (X_TIP, zc - ARM),
            (X_TIP, zc + ARM - CHAMFER),
            (X_TIP - CHAMFER, zc + ARM),
            (HUB, zc + ARM),
        ],
        -ARM,
        ARM,
        MATERIAL,
    )
    mb.box((-ARM, HUB, zc - ARM), (ARM, Y_TIP, zc + ARM), MATERIAL)
    mb.box((-ARM, -ARM, 2 * HUB), (ARM, ARM, Z_TIP), MATERIAL)
    mb.build("SM_Calib_Axes_body", bevel_width=0.0)


def build_rig_marker() -> None:
    """Source marker of `SK_Calib_Rig`: built by `lib.unreal_export.build_rig` from `RIG_BONES`."""
