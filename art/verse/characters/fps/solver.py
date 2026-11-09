"""Pose solver for `SKEL_Verse_Human` on top of the crew pose solver.

A pose is the crew pose dict of `characters/posing.py` (hips, spine angles,
two-bone IK arm and leg targets with poles, hand and foot orientations),
plus optional keys this rig adds:

- ``root``: a Matrix, the root bone's armature-space transform (root motion).
  Everything else is posed in root space.
- ``fingers_L`` / ``fingers_R``: {finger: curl degrees} overriding the crew
  pose's single ``fingers`` curl per finger (trigger finger, grip).
- ``camera``: (pitch, yaw) degrees on the `Camera` bone (finisher, kill cam).

The crew solver gives armature-space matrices for the crew bones; each FPS
bone that lies on a crew bone takes that bone's world rotation delta, every
other bone follows its parent (twist, weapon) or its FK target (IK bones).
Joint positions are forward kinematics on the FPS rest, so bone lengths are
exact.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Matrix, Quaternion, Vector

from characters.fps import skeleton as S

#: FPS bone -> crew bone whose world rotation it takes.
MAPPED = {
    "Hips": "Hips",
    "Spine_01": "Spine",
    "Spine_02": "Spine",
    "Spine_03": "Chest",
    "Neck": "Neck",
    "Head": "Head",
}
for _s in ("L", "R"):
    MAPPED.update(
        {
            f"Clavicle_{_s}": f"Shoulder_{_s}",
            f"UpperArm_{_s}": f"UpperArm_{_s}",
            f"LowerArm_{_s}": f"ForeArm_{_s}",
            f"Hand_{_s}": f"Hand_{_s}",
            f"Thigh_{_s}": f"UpperLeg_{_s}",
            f"Calf_{_s}": f"LowerLeg_{_s}",
            f"Foot_{_s}": f"Foot_{_s}",
            f"Ball_{_s}": f"Toe_{_s}",
        }
    )

#: Share of a finger's curl per joint (01, 02, 03).
CURL_SHARE = (0.42, 0.36, 0.22)
FINGERS4 = ("Index", "Middle", "Ring", "Pinky")


def _rot3(m: Matrix) -> Matrix:
    return m.to_3x3().normalized()


class FpsRig:
    """Rest data of the FPS armature plus the solver."""

    def __init__(self, crew_rig, fps_arm):
        self.crew = crew_rig
        self.ob = fps_arm
        self.rest: dict[str, Matrix] = {}
        self.parent: dict[str, str | None] = {}
        for b in fps_arm.data.bones:
            self.rest[b.name] = b.matrix_local.copy()
            self.parent[b.name] = b.parent.name if b.parent else None
        self.order = [n for n, _ in S.BONES]
        self.offset = {
            n: (self.rest[p].inverted() @ self.rest[n]) if p else self.rest[n].copy()
            for n, p in self.parent.items()
        }
        self._delta_rest = {
            n: _rot3(self.crew.rest[o]).inverted() @ _rot3(self.rest[n]) for n, o in MAPPED.items()
        }

    def refresh(self) -> None:
        """Re-read the rest after a bone was moved (`rig.set_bone_matrix`)."""
        self.__init__(self.crew, self.ob)

    def head(self, name: str) -> Vector:
        return self.rest[name].translation.copy()

    # ------------------------------------------------------------------ solve

    def solve(self, pose: dict) -> dict[str, Matrix]:
        crew = self.crew.solve(pose)
        root = pose.get("root") or Matrix.Identity(4)
        W: dict[str, Matrix] = {}
        for name in self.order:
            parent = self.parent[name]
            if name == "Root":
                W[name] = root @ self.rest["Root"]
                continue
            if name in S.IK_FOLLOWS:
                W[name] = W[S.IK_FOLLOWS[name]].copy()
                continue
            if parent is None:
                raise KeyError(name)
            fk = W[parent] @ self.offset[name]
            if name in MAPPED:
                rot = _rot3(root) @ _rot3(crew[MAPPED[name]]) @ self._delta_rest[name]
                m = rot.to_4x4()
                if name == "Hips":
                    m.translation = (root @ crew["Hips"]).translation
                else:
                    m.translation = fk.translation
                W[name] = m
            elif "_0" in name and name.split("_0")[0] in (*FINGERS4, "Thumb"):
                finger, rest = name.split("_0")
                joint, side = int(rest[0]), rest[-1]
                W[name] = fk @ Matrix.Rotation(
                    -math.radians(self._curl(pose, finger, side) * CURL_SHARE[joint - 1]), 4, "X"
                )
            elif name == "Camera" and "camera" in pose:
                pitch, yaw = pose["camera"]
                W[name] = fk @ (
                    Matrix.Rotation(math.radians(yaw), 4, "Z")
                    @ Matrix.Rotation(math.radians(pitch), 4, "X")
                )
            else:
                W[name] = fk
        return W

    @staticmethod
    def _curl(pose: dict, finger: str, side: str) -> float:
        per = pose.get(f"fingers_{side}") or {}
        if finger in per:
            return float(per[finger])
        arm = pose.get(f"arm_{side}") or {}
        if finger == "Thumb":
            return float(arm.get("thumb", 8.0)) * 1.6
        return float(arm.get("fingers", 12.0)) * 2.4

    def basis(self, W: dict[str, Matrix]) -> dict[str, Matrix]:
        out = {}
        for n in self.order:
            p = self.parent[n]
            if p is None:
                out[n] = self.rest[n].inverted() @ W[n]
            else:
                out[n] = self.offset[n].inverted() @ W[p].inverted() @ W[n]
        return out

    def apply_static(self, pose: dict) -> None:
        """Set the armature's pose (renders and checks)."""
        for n, m in self.basis(self.solve(pose)).items():
            pb = self.ob.pose.bones[n]
            pb.rotation_mode = "QUATERNION"
            loc, q, _ = m.decompose()
            pb.location = loc
            pb.rotation_quaternion = q
            pb.scale = (1, 1, 1)


def write_action(rig: FpsRig, target_ob, name: str, poses: list[dict], scale: float = 1.0):
    """Bake per-frame poses (frame 0..n-1) into an action on `target_ob`.

    `target_ob` is an armature with `rig`'s bones (the export copy, whose data
    may be scaled by `scale`, so locations are multiplied by it).
    """
    frames = [rig.basis(rig.solve(p)) for p in poses]
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    target_ob.animation_data_create()
    slot = act.slots.new(id_type="OBJECT", name=target_ob.name)
    layer = act.layers.new("Layer")
    strip = layer.strips.new(type="KEYFRAME")
    bag = strip.channelbag(slot, ensure=True)
    for n in rig.order:
        prev = None
        quats, locs = [], []
        for B in frames:
            loc, q, _ = B[n].decompose()
            if prev is not None and q.dot(prev) < 0:
                q = Quaternion((-q.w, -q.x, -q.y, -q.z))
            prev = q
            quats.append(q)
            locs.append(loc * scale)
        grp = bag.groups.get(n) or bag.groups.new(n)
        for i in range(4):
            fc = bag.fcurves.new(f'pose.bones["{n}"].rotation_quaternion', index=i)
            fc.group = grp
            _fill(fc, [q[i] for q in quats])
        for i in range(3):
            fc = bag.fcurves.new(f'pose.bones["{n}"].location', index=i)
            fc.group = grp
            _fill(fc, [lv[i] for lv in locs])
    act.frame_range = (0, max(1, len(poses) - 1))
    ad = target_ob.animation_data
    # Setting the slot after the action crashes Blender 5.0; naming the slot
    # first makes the assignment pick it.
    ad.last_slot_identifier = slot.identifier
    ad.action = act
    if ad.action_slot is None:
        raise RuntimeError(f"{name}: action slot not assigned on {target_ob.name}")
    for pb in target_ob.pose.bones:
        pb.rotation_mode = "QUATERNION"
    return act


def _fill(fc, values):
    n = len(values)
    fc.keyframe_points.add(n)
    co = []
    for f, v in enumerate(values):
        co += [float(f), float(v)]
    fc.keyframe_points.foreach_set("co", co)
    for kp in fc.keyframe_points:
        kp.interpolation = "LINEAR"
    fc.update()
