"""Build `SKEL_Verse_Human` on a body variant and convert the crew skin weights to it.

Runs inside Blender. The FPS rig is built from the same measured landmarks as
the three.js crew skeleton (`characters/body.py`), so every joint the two rigs
share sits at exactly the same place. That lets `fps/solver.py` reuse the crew
pose solver and lets this module convert the proven crew skin weights instead
of re-skinning: each old bone's weight is split onto the new bones that lie on
it (two spine bones, twist bones along the limbs, fifteen finger joints fitted
to the mesh). Deterministic: no random numbers, fixed iteration order.

Blender axes as everywhere in `characters/`: X = the character's left,
-Y = forward, Z = up, metres, origin on the floor between the feet.
"""

from __future__ import annotations

import math

import bpy
import numpy as np
from mathutils import Matrix, Vector

from characters import common as C
from characters.fps import skeleton as S

FWD = Vector((0.0, -1.0, 0.0))
UP = Vector((0.0, 0.0, 1.0))

#: Finger joint split of the measured finger length (knuckle to tip).
FINGER_JOINTS = (0.0, 0.47, 0.74, 1.0)
THUMB_JOINTS = (0.0, 0.40, 0.70, 1.0)
#: Twist bones: (bone, parent, start, end) as fractions along the parent.
TWIST = (
    ("UpperArm_Twist", "UpperArm", 0.50, 0.75),
    ("LowerArm_Twist", "LowerArm", 0.60, 0.85),
    ("Thigh_Twist", "Thigh", 0.35, 0.60),
    ("Calf_Twist", "Calf", 0.50, 0.75),
)


def _m(side: str):
    return (lambda v: v.copy()) if side == "L" else C.mirror


# ----------------------------------------------------------------- finger fit


def fit_fingers(ctx) -> dict[str, list[Vector]]:
    """Joint positions of the four fingers and the thumb of the left hand.

    Returns {finger: [p0, p1, p2, p3]} (three bones each). The crew skeleton
    has one bone for four fingers; its weights say which vertices are finger,
    PCA across them gives the spread axis, and a 1-D k-means on that axis
    separates the four fingers. The finger nearest the thumb is the index.
    """
    L = ctx.L
    fi = ctx.bones.index("Fingers_L")
    ti = ctx.bones.index("Thumb_L")
    V = ctx.V
    knuck = np.array(L["knuckles"])
    tip = np.array(L["finger_tip"])
    d = tip - knuck
    d /= np.linalg.norm(d)
    P = V[(ctx.dom == fi) & (V[:, 0] > 0.0)]
    if len(P) < 40:
        raise RuntimeError(f"too few finger vertices ({len(P)}) to fit the fingers")
    rel = P - knuck
    along = rel @ d
    resid = rel - np.outer(along, d)
    cov = np.cov(resid.T)
    vals, vecs = np.linalg.eigh(cov)
    spread = vecs[:, np.argmax(vals)]
    u = resid @ spread
    centres = np.quantile(u, [0.125, 0.375, 0.625, 0.875])
    for _ in range(40):
        lab = np.argmin(np.abs(u[:, None] - centres[None, :]), axis=1)
        new = np.array([u[lab == k].mean() if np.any(lab == k) else centres[k] for k in range(4)])
        if np.allclose(new, centres, atol=1e-7):
            break
        centres = new
    lab = np.argmin(np.abs(u[:, None] - centres[None, :]), axis=1)
    thumb_u = (np.array(L["thumb_base"]) - knuck) @ spread
    order = np.argsort(np.abs(centres - thumb_u))  # nearest the thumb first
    out: dict[str, list[Vector]] = {}
    for name, k in zip(("Index", "Middle", "Ring", "Pinky"), order, strict=True):
        Q = P[lab == k]
        qa = (Q - knuck) @ d
        a0 = float(np.quantile(qa, 0.02))
        a1 = float(qa.max()) - 0.003
        centre = (Q - knuck - np.outer(qa, d)).mean(axis=0)
        base = knuck + centre + d * a0
        length = max(0.03, a1 - a0)
        out[name] = [Vector(base + d * (length * f)) for f in FINGER_JOINTS]
    T = V[(ctx.dom == ti) & (V[:, 0] > 0.0)]
    tb, tt = np.array(L["thumb_base"]), np.array(L["thumb_tip"])
    if len(T) >= 10:
        td = tt - tb
        td /= np.linalg.norm(td)
        ta = (T - tb) @ td
        centre = (T - tb - np.outer(ta, td)).mean(axis=0)
        tt = tb + centre + td * (float(ta.max()) - 0.003)
        tb = tb + centre * 0.5
    out["Thumb"] = [Vector(tb + (tt - tb) * f) for f in THUMB_JOINTS]
    return out


# ------------------------------------------------------------------- armature


def joint_table(ctx) -> dict[str, tuple[Vector, Vector, Vector]]:
    """{bone: (head, tail, roll target)} for every bone, Blender metres."""
    L = ctx.L
    t: dict[str, tuple[Vector, Vector, Vector]] = {}
    t["Root"] = (Vector((0, 0, 0)), Vector((0, 0, 0.1)), FWD)
    t["Hips"] = (L["pelvis"], L["spine"], FWD)
    mid = (L["spine"] + L["chest"]) * 0.5
    t["Spine_01"] = (L["spine"], mid, FWD)
    t["Spine_02"] = (mid, L["chest"], FWD)
    t["Spine_03"] = (L["chest"], L["neck"], FWD)
    t["Neck"] = (L["neck"], L["head"], FWD)
    t["Head"] = (L["head"], L["head_top"], FWD)
    eye = (Vector(ctx.eyes[0]) + Vector(ctx.eyes[1])) * 0.5
    t["Camera"] = (eye, eye + FWD * 0.10, UP)
    fingers = fit_fingers(ctx)
    for side, sx in (("L", 1.0), ("R", -1.0)):
        m = _m(side)
        lateral = Vector((sx, 0, 0))
        d = (m(L["wrist"]) - m(L["shoulder"])).normalized()
        hinge = Vector((0, 1, 0)).cross(d).normalized()
        t[f"Clavicle_{side}"] = (m(L["clavicle"]), m(L["shoulder"]), UP)
        for name, h, tl in (("UpperArm", "shoulder", "elbow"), ("LowerArm", "elbow", "wrist")):
            y = (m(L[tl]) - m(L[h])).normalized()
            t[f"{name}_{side}"] = (m(L[h]), m(L[tl]), hinge.cross(y))
        t[f"Hand_{side}"] = (m(L["wrist"]), m(L["knuckles"]), lateral)
        for finger, pts in fingers.items():
            for j in range(3):
                t[f"{finger}_0{j + 1}_{side}"] = (m(pts[j]), m(pts[j + 1]), lateral)
        d = (m(L["ankle"]) - m(L["hip"])).normalized()
        hinge = d.cross(FWD).normalized()
        for name, h, tl in (("Thigh", "hip", "knee"), ("Calf", "knee", "ankle")):
            y = (m(L[tl]) - m(L[h])).normalized()
            t[f"{name}_{side}"] = (m(L[h]), m(L[tl]), hinge.cross(y))
        t[f"Foot_{side}"] = (m(L["ankle"]), m(L["ball"]), UP)
        t[f"Ball_{side}"] = (m(L["ball"]), m(L["toe_tip"]), UP)
        for name, parent, a, b in TWIST:
            ph, pt, roll = t[f"{parent}_{side}"]
            t[f"{name}_{side}"] = (ph.lerp(pt, a), ph.lerp(pt, b), roll)
        # Weapon bones start on the palm with the hand's frame; `solver` rotates
        # Weapon_R into the rifle's grip frame (`set_weapon_rest`).
        wh, wt, roll = t[f"Hand_{side}"]
        palm = wh.lerp(wt, 0.55)
        t[f"Weapon_{side}"] = (palm, palm + (wt - wh).normalized() * 0.1, roll)
    t["IK_Foot_Root"] = (Vector((0, 0, 0)), Vector((0, 0, 0.1)), FWD)
    t["IK_Hand_Root"] = (Vector((0, 0, 0)), Vector((0, 0, 0.1)), FWD)
    for ik, fk in S.IK_FOLLOWS.items():
        t[ik] = t[fk]
    return t


def build_armature(ctx, name: str):
    """Create the FPS armature object for `ctx` (rest = A-pose of the variant)."""
    table = joint_table(ctx)
    arm = bpy.data.armatures.new(name)
    ob = bpy.data.objects.new(name, arm)
    C.link(ob)
    arm.display_type = "STICK"
    C.set_active(ob)
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.edit_bones
    for bone, parent in S.BONES:
        head, tail, roll = table[bone]
        b = eb.new(bone)
        b.head, b.tail = head, tail
        b.align_roll(roll)
        b.use_deform = bone in S.DEFORM
        if parent:
            b.parent = eb[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    return ob


def set_bone_matrix(arm_ob, bone: str, matrix: Matrix) -> None:
    """Move one bone's rest (armature space, Y along the bone), keeping its length."""
    C.set_active(arm_ob)
    bpy.ops.object.mode_set(mode="EDIT")
    b = arm_ob.data.edit_bones[bone]
    length = b.length
    b.matrix = matrix
    b.length = length
    bpy.ops.object.mode_set(mode="OBJECT")


# -------------------------------------------------------------------- weights


def _smooth(e0: float, e1: float, x: np.ndarray) -> np.ndarray:
    k = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return k * k * (3 - 2 * k)


def _seg_dist(P: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ab = b - a
    t = np.clip(((P - a) @ ab) / max(ab @ ab, 1e-12), 0.0, 1.0)
    return np.linalg.norm(P - (a + np.outer(t, ab)), axis=1)


class WeightMap:
    """Turns crew-skeleton weights into `SKEL_Verse_Human` weights for any mesh."""

    def __init__(self, ctx, fps_arm):
        self.old = ctx.rig  # posing.Rig of the crew skeleton
        self.rest = {b.name: b.matrix_local.copy() for b in fps_arm.data.bones}
        self.length = {b.name: b.length for b in fps_arm.data.bones}

    def _t(self, P: np.ndarray, old_bone: str) -> np.ndarray:
        h = np.array(self.old.head(old_bone))
        tl = np.array(self.old.tail(old_bone))
        d = tl - h
        return ((P - h) @ d) / max(d @ d, 1e-12)

    def _seg(self, bone: str) -> tuple[np.ndarray, np.ndarray]:
        m = self.rest[bone]
        head = np.array(m.translation)
        tail = np.array((m @ Vector((0, self.length[bone], 0, 1))).xyz)
        return head, tail

    def _split_nearest(self, P: np.ndarray, w: np.ndarray, bones: list[str], out: dict) -> None:
        dist = np.stack([_seg_dist(P, *self._seg(b)) for b in bones], axis=1)
        inv = 1.0 / (dist**4 + 1e-12)
        top2 = np.argsort(dist, axis=1)[:, :2]
        mask = np.zeros_like(inv)
        np.put_along_axis(mask, top2, 1.0, axis=1)
        inv *= mask
        inv /= inv.sum(axis=1, keepdims=True)
        for j, b in enumerate(bones):
            out[b] = out.get(b, 0.0) + w * inv[:, j]

    def convert(self, P: np.ndarray, old: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        """`old` = {crew bone: weight per vertex}; returns {FPS bone: weight per vertex}."""
        out: dict[str, np.ndarray] = {}

        def add(bone, w):
            out[bone] = out.get(bone, 0.0) + w

        for ob, w in old.items():
            if not np.any(w > 0):
                continue
            base, _, side = ob.partition("_")
            s = f"_{side}" if side else ""
            if ob == "Spine":
                k = _smooth(0.3, 0.7, self._t(P, ob))
                add("Spine_01", w * (1 - k))
                add("Spine_02", w * k)
            elif ob in ("Hips", "Neck", "Head"):
                add(ob, w)
            elif ob == "Chest":
                add("Spine_03", w)
            elif base == "Shoulder":
                add(f"Clavicle{s}", w)
            elif base in ("UpperArm", "ForeArm", "UpperLeg", "LowerLeg"):
                main = {
                    "UpperArm": "UpperArm",
                    "ForeArm": "LowerArm",
                    "UpperLeg": "Thigh",
                    "LowerLeg": "Calf",
                }[base]
                share, e0, e1 = {
                    "UpperArm": (0.5, 0.2, 0.9),
                    "LowerArm": (0.7, 0.3, 1.0),
                    "Thigh": (0.4, 0.2, 0.9),
                    "Calf": (0.4, 0.3, 1.0),
                }[main]
                k = share * _smooth(e0, e1, self._t(P, ob))
                add(f"{main}{s}", w * (1 - k))
                add(f"{main}_Twist{s}", w * k)
            elif base == "Hand":
                add(f"Hand{s}", w)
            elif base == "Fingers":
                bones = [
                    f"{f}_0{j}{s}" for f in ("Index", "Middle", "Ring", "Pinky") for j in (1, 2, 3)
                ]
                self._split_nearest(P, w, bones, out)
            elif base == "Thumb":
                self._split_nearest(P, w, [f"Thumb_0{j}{s}" for j in (1, 2, 3)], out)
            elif base == "Foot":
                add(f"Foot{s}", w)
            elif base == "Toe":
                add(f"Ball{s}", w)
            else:
                raise KeyError(f"no FPS mapping for crew bone {ob}")
        return out


def old_weights(ob) -> dict[str, np.ndarray]:
    n = len(ob.data.vertices)
    names = {vg.index: vg.name for vg in ob.vertex_groups}
    out = {name: np.zeros(n) for name in names.values()}
    for v in ob.data.vertices:
        for g in v.groups:
            out[names[g.group]][v.index] = g.weight
    return out


def apply_weights(ob, weights: dict[str, np.ndarray], limit: int = S.MAX_INFLUENCES) -> int:
    """Replace the mesh's groups; keep the `limit` largest per vertex, normalised.

    Returns the largest influence count of any vertex.
    """
    names = [n for n in S.DEFORM if n in weights]
    n = len(ob.data.vertices)
    W = np.zeros((n, len(names)))
    for j, name in enumerate(names):
        W[:, j] = weights[name]
    W[W < 0.005] = 0.0
    order = np.argsort(-W, axis=1)
    keep = np.zeros_like(W)
    np.put_along_axis(keep, order[:, :limit], 1.0, axis=1)
    W *= keep
    tot = W.sum(axis=1, keepdims=True)
    empty = tot[:, 0] <= 0
    if np.any(empty):
        raise RuntimeError(f"{ob.name}: {int(empty.sum())} vertices lost every weight")
    W /= tot
    ob.vertex_groups.clear()
    groups = [ob.vertex_groups.new(name=name) for name in names]
    worst = 0
    for i in range(n):
        nz = np.nonzero(W[i])[0]
        worst = max(worst, len(nz))
        for j in nz:
            groups[j].add([i], float(W[i, j]), "REPLACE")
    return worst


def rebind(ob, fps_arm, wmap: WeightMap) -> int:
    """Convert `ob`'s crew weights and bind it to the FPS armature."""
    P = np.array([v.co[:] for v in ob.data.vertices], dtype=np.float64)
    worst = apply_weights(ob, wmap.convert(P, old_weights(ob)))
    for mod in list(ob.modifiers):
        if mod.type == "ARMATURE":
            ob.modifiers.remove(mod)
    ob.parent = fps_arm
    ob.matrix_parent_inverse.identity()
    mod = ob.modifiers.new("Armature", "ARMATURE")
    mod.object = fps_arm
    return worst


def bone_lengths_ok(arm_ob) -> list[str]:
    """Bones shorter than 5 mm (the importer collapses them)."""
    return [b.name for b in arm_ob.data.bones if b.length < 0.005]


def deg(x: float) -> float:
    return math.radians(x)
