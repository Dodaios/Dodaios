"""Human base body: load the CC0 base mesh, normalise it, build the shared skeleton.

The source is Blender Studio's "Human Base Meshes" bundle v1.4.1 (CC0, see
LICENSES.md). Only the base subdivision level of the realistic male/female body
is used. The bundle is downloaded into art/verse/.cache/characters/download by
`fetch_base.py`; nothing from it is committed.

Joint positions come from measurements of the mesh (cross-section centroids at
anatomical height fractions), so the skeleton follows the body exactly and the
male and female variants get the same bone names with their own proportions.
"""

from __future__ import annotations

import bpy
import numpy as np
from mathutils import Vector

from characters import common as C

# --------------------------------------------------------------------------- base


def load_base(variant: str):
    """Append the base body for `variant` ('M'/'F'); return (object, eye centres, eye radius)."""
    src = C.VARIANTS[variant]["source"]
    if not C.BUNDLE_BLEND.is_file():
        raise RuntimeError(
            f"base mesh bundle missing: run characters/fetch_base.py ({C.BUNDLE_BLEND})"
        )
    with bpy.data.libraries.load(str(C.BUNDLE_BLEND), link=False) as (data_from, data_to):
        data_to.objects = [src, src + ".eye.L", src + ".eye.R"]
    body, eye_l, eye_r = data_to.objects
    for ob in (body, eye_l, eye_r):
        C.link(ob)
    bpy.context.view_layer.update()
    eyes = []
    for e in (eye_l, eye_r):
        pts = [e.matrix_world @ v.co for v in e.data.vertices]
        c = sum(pts, Vector()) / len(pts)
        eyes.append(c)
        radius = max((p - c).length for p in pts)
    # Base level only: drop the multires stack and any drivers.
    body.modifiers.clear()
    body.animation_data_clear()
    mw = body.matrix_world.copy()
    me = body.data
    me.transform(mw)
    body.matrix_world.identity()
    body.parent = None
    for e in (eye_l, eye_r):
        bpy.data.objects.remove(e, do_unlink=True)
    body.name = f"Body_{variant}"
    me.name = f"Body_{variant}"
    return body, eyes, radius


def verts_np(ob) -> np.ndarray:
    n = len(ob.data.vertices)
    co = np.empty(n * 3, dtype=np.float64)
    ob.data.vertices.foreach_get("co", co)
    return co.reshape(n, 3)


def set_verts_np(ob, arr: np.ndarray) -> None:
    ob.data.vertices.foreach_set("co", arr.astype(np.float32).ravel())
    ob.data.update()


def normalise(body, eyes, variant: str):
    """Scale to the target height, feet on Z=0, centred between the feet."""
    V = verts_np(body)
    height = C.VARIANTS[variant]["height"]
    zmin, zmax = V[:, 2].min(), V[:, 2].max()
    s = height / (zmax - zmin)
    cx = 0.5 * (V[:, 0].min() + V[:, 0].max())
    V = (V - np.array([cx, 0.0, zmin])) * s
    feet = V[V[:, 2] < 0.05]
    cy = 0.5 * (feet[:, 1].min() + feet[:, 1].max())
    V[:, 1] -= cy
    # Enforce exact left/right symmetry of the source (it is symmetric to ~0.1 mm).
    set_verts_np(body, V)
    eyes = [Vector(((e.x - cx) * s, e.y * s - cy, (e.z - zmin) * s)) for e in eyes]
    return eyes, s


# ---------------------------------------------------------------------- landmarks


def _slice(V, z, half=0.008, xmin=None, xmax=None):
    m = np.abs(V[:, 2] - z) < half
    if xmin is not None:
        m &= V[:, 0] > xmin
    if xmax is not None:
        m &= V[:, 0] < xmax
    return V[m]


def _slab(V, point, axis, half=0.008, radius=0.08):
    d = (V - point) @ axis
    m = np.abs(d) < half
    P = V[m]
    perp = (P - point) - np.outer((P - point) @ axis, axis)
    P = P[np.linalg.norm(perp, axis=1) < radius]
    return P


def landmarks(body, variant: str) -> dict[str, Vector]:
    """Joint positions (left side + centre line) in Blender metres."""
    V = verts_np(body)
    H = V[:, 2].max()
    s = H / 1.78
    L: dict[str, Vector] = {}

    # Perineum: lowest mid-line point behind the frontal plane (skips the genitals).
    mid = V[(np.abs(V[:, 0]) < 0.012) & (V[:, 2] > 0.3 * H) & (V[:, 2] < 0.6 * H) & (V[:, 1] > 0.0)]
    crotch = mid[:, 2].min()
    thigh = _slice(V, crotch - 0.03, 0.01, xmin=0.01, xmax=0.25)
    hip = Vector((thigh[:, 0].mean() + 0.006 * s, thigh[:, 1].mean(), crotch + 0.095 * s))
    L["hip"] = hip

    knee_z = 0.285 * H
    ks = _slice(V, knee_z, 0.008, xmin=0.0, xmax=0.25)
    L["knee"] = Vector((ks[:, 0].mean(), ks[:, 1].mean(), knee_z))

    shin = _slice(V, 0.115 * s, 0.01, xmin=0.0, xmax=0.25)
    ankle = Vector((shin[:, 0].mean(), shin[:, 1].mean() - 0.016 * s, 0.078 * s))
    L["ankle"] = ankle

    foot = V[(V[:, 2] < 0.05) & (V[:, 0] > 0.0)]
    tip_y = foot[:, 1].min()
    heel_y = foot[:, 1].max()
    ball_y = tip_y + 0.072 * s
    near = foot[np.abs(foot[:, 1] - ball_y) < 0.015]
    L["ball"] = Vector((near[:, 0].mean(), ball_y, 0.028 * s))
    L["toe_tip"] = Vector((near[:, 0].mean() - 0.004, tip_y + 0.01, 0.022 * s))
    L["heel"] = Vector((ankle.x, heel_y, 0.0))

    def spine_point(z, back_frac=0.38, half_w=0.07):
        sl = _slice(V, z, 0.008, xmin=-half_w, xmax=half_w)
        y0, y1 = sl[:, 1].min(), sl[:, 1].max()
        return Vector((0.0, y1 - back_frac * (y1 - y0), z))

    L["pelvis"] = Vector((0.0, hip.y, hip.z + 0.015 * s))
    L["spine"] = spine_point(hip.z + 0.115 * s, 0.36)
    L["chest"] = spine_point(0.70 * H, 0.34)
    L["neck"] = spine_point(0.822 * H, 0.45, 0.05)
    L["head"] = spine_point(0.886 * H, 0.47, 0.05)
    L["head_top"] = Vector((0.0, L["head"].y - 0.01, H))

    band = V[(V[:, 2] > 0.80 * H) & (V[:, 2] < 0.825 * H)]
    x_outer = band[:, 0].max()
    outer = band[band[:, 0] > x_outer - 0.07]
    shoulder = Vector((x_outer - 0.058 * s, outer[:, 1].mean() + 0.006, 0.792 * H))
    L["shoulder"] = shoulder
    L["clavicle"] = Vector((0.022 * s, L["neck"].y - 0.035 * s, 0.808 * H))

    arm = V[(V[:, 0] > shoulder.x + 0.10) & (V[:, 2] < shoulder.z) & (V[:, 2] > 0.38 * H)]
    tip = arm[np.argmin(arm[:, 2])]
    tip = Vector(tip)
    d = (tip - shoulder).normalized()
    hand_len = 0.108 * H
    wrist0 = shoulder + d * ((tip - shoulder).length - hand_len)
    ax = np.array(d)
    sl = _slab(V, np.array(wrist0), ax, 0.008, 0.06)
    wrist = Vector(sl.mean(axis=0)) if len(sl) else wrist0
    elbow0 = shoulder + (wrist - shoulder) * 0.555
    sl = _slab(V, np.array(elbow0), np.array((wrist - shoulder).normalized()), 0.008, 0.07)
    elbow = Vector(sl.mean(axis=0)) if len(sl) else elbow0
    L["elbow"], L["wrist"], L["finger_tip"] = elbow, wrist, tip
    dh = (tip - wrist).normalized()
    L["knuckles"] = wrist + dh * (0.53 * (tip - wrist).length)
    hand = V[
        ((V - np.array(wrist)) @ np.array(dh) > 0.0)
        & (V[:, 0] > wrist.x - 0.05)
        & (np.linalg.norm(V - np.array(wrist), axis=1) < 0.22)
    ]
    thumb_tip = Vector(hand[np.argmin(hand[:, 1])])
    L["thumb_tip"] = thumb_tip
    L["thumb_base"] = wrist + (thumb_tip - wrist) * 0.30
    return L


# ----------------------------------------------------------------------- skeleton


def build_armature(L: dict[str, Vector], name: str):
    """Create the shared 25-bone skeleton from landmarks. Returns the armature object."""
    arm = bpy.data.armatures.new(name)
    ob = bpy.data.objects.new(name, arm)
    C.link(ob)
    arm.display_type = "STICK"
    C.set_active(ob)
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.edit_bones
    fwd = Vector((0, -1, 0))
    up = Vector((0, 0, 1))

    def bone(n, head, tail, roll_to, parent=None, connect=False):
        b = eb.new(n)
        b.head, b.tail = head, tail
        b.align_roll(roll_to)
        if parent:
            b.parent = eb[parent]
            b.use_connect = connect
        return b

    bone("Hips", L["pelvis"], L["spine"], fwd)
    bone("Spine", L["spine"], L["chest"], fwd, "Hips", True)
    bone("Chest", L["chest"], L["neck"], fwd, "Spine", True)
    bone("Neck", L["neck"], L["head"], fwd, "Chest", True)
    bone("Head", L["head"], L["head_top"], fwd, "Neck", True)
    for side, sx in (("L", 1.0), ("R", -1.0)):
        m = (lambda v: v) if sx > 0 else C.mirror
        lateral = Vector((sx, 0, 0))
        bone(f"Shoulder_{side}", m(L["clavicle"]), m(L["shoulder"]), up, "Chest")
        d = (m(L["wrist"]) - m(L["shoulder"])).normalized()
        n = Vector((0, 1, 0))  # elbows point backwards
        hinge = n.cross(d).normalized()
        for bn, h, t, par in (
            ("UpperArm", "shoulder", "elbow", "Shoulder"),
            ("ForeArm", "elbow", "wrist", "UpperArm"),
        ):
            y = (m(L[t]) - m(L[h])).normalized()
            bone(f"{bn}_{side}", m(L[h]), m(L[t]), hinge.cross(y), f"{par}_{side}", True)
        bone(f"Hand_{side}", m(L["wrist"]), m(L["knuckles"]), lateral, f"ForeArm_{side}", True)
        bone(f"Fingers_{side}", m(L["knuckles"]), m(L["finger_tip"]), lateral, f"Hand_{side}", True)
        bone(f"Thumb_{side}", m(L["thumb_base"]), m(L["thumb_tip"]), lateral, f"Hand_{side}")
        d = (m(L["ankle"]) - m(L["hip"])).normalized()
        hinge = d.cross(fwd).normalized()  # knees point forwards
        y = (m(L["knee"]) - m(L["hip"])).normalized()
        bone(f"UpperLeg_{side}", m(L["hip"]), m(L["knee"]), hinge.cross(y), "Hips")
        y = (m(L["ankle"]) - m(L["knee"])).normalized()
        bone(
            f"LowerLeg_{side}",
            m(L["knee"]),
            m(L["ankle"]),
            hinge.cross(y),
            f"UpperLeg_{side}",
            True,
        )
        bone(f"Foot_{side}", m(L["ankle"]), m(L["ball"]), up, f"LowerLeg_{side}", True)
        bone(f"Toe_{side}", m(L["ball"]), m(L["toe_tip"]), up, f"Foot_{side}", True)
    bpy.ops.object.mode_set(mode="OBJECT")
    for b in arm.bones:
        b.use_deform = True
    return ob


def skin_auto(mesh_ob, arm_ob):
    """Parent with Blender's heat-diffusion weights (deterministic for a given mesh)."""
    for o in bpy.context.scene.objects:
        o.select_set(False)
    mesh_ob.select_set(True)
    arm_ob.select_set(True)
    bpy.context.view_layer.objects.active = arm_ob
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    missing = [b.name for b in arm_ob.data.bones if b.name not in mesh_ob.vertex_groups]
    if missing:
        print(f"[characters] WARNING: no weights for {missing}")


def normalise_weights(mesh_ob, max_influences=4):
    """Limit to `max_influences` per vertex and renormalise (glTF/three use 4)."""
    C.set_active(mesh_ob)
    bpy.ops.object.mode_set(mode="WEIGHT_PAINT")
    bpy.ops.object.vertex_group_clean(group_select_mode="ALL", limit=0.01)
    bpy.ops.object.vertex_group_limit_total(group_select_mode="ALL", limit=max_influences)
    bpy.ops.object.vertex_group_normalize_all(group_select_mode="ALL", lock_active=False)
    bpy.ops.object.mode_set(mode="OBJECT")
