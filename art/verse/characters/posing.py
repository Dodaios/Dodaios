"""Pose solver and clip writer for the shared human skeleton.

A pose is a plain dict (see `Pose` below). The solver computes armature-space
matrices for every bone: the spine, neck, head and shoulders are forward
kinematics (local Euler angles), arms and legs are analytic two-bone IK towards
wrist/ankle targets with a pole direction, hands and feet take a world-space
orientation. Everything is pure math on the rest matrices (no constraints, no
depsgraph), so baking a clip is fast and bit-for-bit reproducible.

Angles are degrees. Directions and positions are Blender armature space
(X = character's left, -Y = forward, Z = up; origin on the floor between the feet).

Spine angles (bend, twist, lean): bend > 0 bends forward, twist > 0 turns to the
character's left, lean > 0 leans to the character's left.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Matrix, Quaternion, Vector

from characters import common as C

FK_SPINE = ("Spine", "Chest", "Neck", "Head")


def _euler_local(bend: float, twist: float, lean: float) -> Matrix:
    # Rest frames of upright bones: X = left, Y = up, Z = forward.
    return (
        Matrix.Rotation(math.radians(twist), 4, "Y")
        @ Matrix.Rotation(math.radians(bend), 4, "X")
        @ Matrix.Rotation(math.radians(-lean), 4, "Z")
    )


def world_rot(bend: float, twist: float, lean: float) -> Matrix:
    """World rotation with the same meaning as the spine angles."""
    return (
        Matrix.Rotation(math.radians(twist), 4, "Z")
        @ Matrix.Rotation(math.radians(bend), 4, "X")
        @ Matrix.Rotation(math.radians(lean), 4, "Y")
    )


class Rig:
    """Rest data of one armature plus the solver."""

    def __init__(self, arm_ob):
        self.ob = arm_ob
        self.rest: dict[str, Matrix] = {}
        self.length: dict[str, float] = {}
        self.parent: dict[str, str | None] = {}
        for b in arm_ob.data.bones:
            self.rest[b.name] = b.matrix_local.copy()
            self.length[b.name] = b.length
            self.parent[b.name] = b.parent.name if b.parent else None
        # child offset in parent space
        self.offset = {
            n: (self.rest[p].inverted() @ self.rest[n]) if p else self.rest[n].copy()
            for n, p in self.parent.items()
        }
        self.twist0 = {}
        for s in ("L", "R"):
            self.twist0[s] = self._twist(self.rest[f"ForeArm_{s}"], self.rest[f"Hand_{s}"])

    # ---------------------------------------------------------------- helpers

    def head(self, name: str) -> Vector:
        return self.rest[name].translation.copy()

    def tail(self, name: str) -> Vector:
        return (self.rest[name] @ Vector((0, self.length[name], 0, 1))).xyz

    @staticmethod
    def _twist(m_fore: Matrix, m_hand: Matrix) -> float:
        y = m_fore.col[1].xyz.normalized()
        zf = m_fore.col[2].xyz
        zh = m_hand.col[2].xyz
        zh = (zh - y * zh.dot(y)).normalized()
        ang = zf.angle(zh, 0.0)
        if zf.cross(zh).dot(y) < 0:
            ang = -ang
        return ang

    def _fk(self, M: dict, name: str, rot: Matrix | None = None):
        p = self.parent[name]
        m = M[p] @ self.offset[name]
        if rot is not None:
            m = m @ rot
        M[name] = m
        return m

    @staticmethod
    def _two_bone(s: Vector, w: Vector, a: float, b: float, pole: Vector):
        d_vec = w - s
        d = d_vec.length
        d = C.clamp(d, abs(a - b) + 1e-4, (a + b) * 0.99995)
        dr = d_vec.normalized()
        n = pole - dr * pole.dot(dr)
        if n.length < 1e-6:
            n = Vector((0, -1, 0)) - dr * (-dr.y)
        n.normalize()
        ca = C.clamp((a * a + d * d - b * b) / (2 * a * d), -1.0, 1.0)
        sa = math.sqrt(max(0.0, 1 - ca * ca))
        mid = s + (dr * ca + n * sa) * a
        end = s + dr * d
        return mid, end, dr, n

    # ------------------------------------------------------------------ solve

    def solve(self, pose: dict) -> dict[str, Matrix]:
        M: dict[str, Matrix] = {}
        hr = world_rot(*pose.get("hips_rot", (0, 0, 0)))
        rest = self.rest["Hips"]
        m = rest.to_3x3().to_4x4()
        m = hr @ m
        m.translation = pose["hips"]
        M["Hips"] = m
        sp = pose.get("spine", {})
        for n in FK_SPINE:
            self._fk(M, n, _euler_local(*sp.get(n, (0, 0, 0))))
        for s in ("L", "R"):
            sign = 1.0 if s == "L" else -1.0
            raise_, fwd = pose.get(f"shoulder_{s}", (0.0, 0.0))
            # Shoulder rest frame: Y outwards, Z up, X forward (left) / backward (right).
            rot = Matrix.Rotation(math.radians(raise_), 4, "X") @ Matrix.Rotation(
                -math.radians(fwd) * sign, 4, "Z"
            )
            self._fk(M, f"Shoulder_{s}", rot)
            self._solve_arm(M, s, pose.get(f"arm_{s}"))
            self._solve_leg(M, s, pose.get(f"leg_{s}"))
        return M

    def _solve_arm(self, M, s, spec):
        sh = (M[f"Shoulder_{s}"] @ Vector((0, self.length[f"Shoulder_{s}"], 0, 1))).xyz
        a, b = self.length[f"UpperArm_{s}"], self.length[f"ForeArm_{s}"]
        if spec is None:
            self._fk(M, f"UpperArm_{s}")
            self._fk(M, f"ForeArm_{s}")
            self._fk(M, f"Hand_{s}")
        else:
            target = Vector(spec["target"]) if "target" in spec else sh + Vector(spec["rel"])
            elbow, wrist, dr, n = self._two_bone(sh, target, a, b, Vector(spec["pole"]))
            hinge = n.cross(dr).normalized()
            yu = (elbow - sh).normalized()
            yf = (wrist - elbow).normalized()
            M[f"UpperArm_{s}"] = C.frame_matrix(sh, yu, hinge.cross(yu))
            mf = C.frame_matrix(elbow, yf, hinge.cross(yf))
            mh = C.frame_matrix(wrist, Vector(spec["hand_dir"]), Vector(spec["dorsal"]))
            # The forearm carries half of the hand's twist (no candy-wrapped wrist).
            tw = self._twist(mf, mh) - self.twist0[s]
            tw = (tw + math.pi) % (2 * math.pi) - math.pi
            mf = mf @ Matrix.Rotation(tw * 0.55, 4, "Y")
            M[f"ForeArm_{s}"] = mf
            M[f"Hand_{s}"] = mh
        spec = spec or {}
        curl = spec.get("fingers", 12.0)
        thumb = spec.get("thumb", 8.0)
        self._fk(M, f"Fingers_{s}", Matrix.Rotation(math.radians(-curl), 4, "X"))
        self._fk(M, f"Thumb_{s}", Matrix.Rotation(math.radians(-thumb), 4, "X"))

    def _solve_leg(self, M, s, spec):
        hip = (M["Hips"] @ self.offset[f"UpperLeg_{s}"]).translation
        a, b = self.length[f"UpperLeg_{s}"], self.length[f"LowerLeg_{s}"]
        if spec is None:
            for n in ("UpperLeg", "LowerLeg", "Foot", "Toe"):
                self._fk(M, f"{n}_{s}")
            return
        knee, ankle, dr, n = self._two_bone(hip, Vector(spec["target"]), a, b, Vector(spec["pole"]))
        hinge = dr.cross(n).normalized()
        yu = (knee - hip).normalized()
        yl = (ankle - knee).normalized()
        M[f"UpperLeg_{s}"] = C.frame_matrix(hip, yu, hinge.cross(yu))
        M[f"LowerLeg_{s}"] = C.frame_matrix(knee, yl, hinge.cross(yl))
        M[f"Foot_{s}"] = C.frame_matrix(
            ankle, Vector(spec["foot_dir"]), Vector(spec.get("foot_up", (0, 0, 1)))
        )
        self._fk(M, f"Toe_{s}", Matrix.Rotation(math.radians(spec.get("toe", 0.0)), 4, "X"))

    # ------------------------------------------------------------ rest helpers

    def rest_foot_dir(self, s: str) -> Vector:
        return (self.tail(f"Foot_{s}") - self.head(f"Foot_{s}")).normalized()

    def basis(self, M: dict[str, Matrix]) -> dict[str, Matrix]:
        out = {}
        for n, p in self.parent.items():
            if p is None:
                out[n] = self.rest[n].inverted() @ M[n]
            else:
                out[n] = self.offset[n].inverted() @ M[p].inverted() @ M[n]
        return out

    def apply_static(self, pose: dict) -> None:
        """Set the armature's pose (for renders and tests)."""
        B = self.basis(self.solve(pose))
        for n, m in B.items():
            pb = self.ob.pose.bones[n]
            pb.rotation_mode = "QUATERNION"
            loc, q, _ = m.decompose()
            pb.location = loc if n == "Hips" else Vector()
            pb.rotation_quaternion = q
            pb.scale = (1, 1, 1)


# ------------------------------------------------------------------ clip writer


def write_action(rig: Rig, name: str, poses: list[dict]):
    """Bake a list of per-frame poses (frame 0..n-1) into an action on `rig.ob`."""
    frames = [rig.basis(rig.solve(p)) for p in poses]
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    ob = rig.ob
    ob.animation_data_create()
    slot = act.slots.new(id_type="OBJECT", name=ob.name)
    layer = act.layers.new("Layer")
    strip = layer.strips.new(type="KEYFRAME")
    bag = strip.channelbag(slot, ensure=True)
    for n in rig.parent:
        prev = None
        quats, locs = [], []
        for B in frames:
            loc, q, _ = B[n].decompose()
            if prev is not None and q.dot(prev) < 0:
                q = Quaternion((-q.w, -q.x, -q.y, -q.z))
            prev = q
            quats.append(q)
            locs.append(loc)
        grp = n
        for i in range(4):
            fc = bag.fcurves.new(f'pose.bones["{n}"].rotation_quaternion', index=i)
            fc.group = bag.groups.get(grp) or bag.groups.new(grp)
            _fill(fc, [q[i] for q in quats])
        if n == "Hips":
            for i in range(3):
                fc = bag.fcurves.new(f'pose.bones["{n}"].location', index=i)
                fc.group = bag.groups.get(grp) or bag.groups.new(grp)
                _fill(fc, [lv[i] for lv in locs])
    act.frame_range = (0, len(poses) - 1)
    return act, slot


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


def stash_actions(ob, actions):
    """Put every (action, slot) on its own NLA track so the glTF exporter writes all."""
    ad = ob.animation_data or ob.animation_data_create()
    for act, slot in actions:
        tr = ad.nla_tracks.new()
        tr.name = act.name
        st = tr.strips.new(act.name, 0, act)
        try:
            st.action_slot = slot
        except (AttributeError, TypeError):
            pass
        tr.mute = True
    ad.action = None
