"""Crew outfits built on the skinned base body.

Every character starts from the naked base body skinned to the shared skeleton
(`prepare`). The body itself becomes the garment layer: anatomy under cloth is
smoothed away, cloth regions are inflated along their normals and faces get the
outfit's material slots. Separate pieces (boots, belt, collar, tunic skirt, cap,
rank plate, helmets, armour) are generated around measured cross-sections of the
body and receive skin weights by barycentric transfer from the naked body (or a
rigid bone). Original designs only.
"""

from __future__ import annotations

import math

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

from characters import body as B
from characters import common as C
from characters import posing as P

# ---------------------------------------------------------------------- materials

# name: (base colour linear RGB, roughness, metallic, extra)
MATERIALS = {
    "M_Uniform": ((0.105, 0.11, 0.092), 0.8, 0.0, {"sheen": 0.08}),
    "M_Trim": ((0.075, 0.078, 0.066), 0.74, 0.0, {"sheen": 0.08}),
    "M_Accent": ((0.42, 0.045, 0.035), 0.55, 0.0, {}),
    "M_Skin": ((0.62, 0.38, 0.27), 0.52, 0.0, {}),
    # hair: the atlas darkens it between the locks (factor = the lit lock colour)
    "M_Hair": ((0.055, 0.036, 0.025), 0.48, 0.0, {}),
    "M_Boots": ((0.010, 0.010, 0.011), 0.24, 0.0, {"coat": 0.8}),
    "M_Cap": ((0.105, 0.11, 0.092), 0.8, 0.0, {"sheen": 0.08}),
    "M_Belt": ((0.014, 0.014, 0.015), 0.38, 0.0, {"coat": 0.3}),
    "M_RankPlate": ((0.40, 0.42, 0.45), 0.3, 1.0, {}),
    "M_Helmet": ((0.012, 0.012, 0.013), 0.14, 0.0, {"coat": 1.0}),
    "M_Visor": ((0.004, 0.005, 0.006), 0.05, 0.4, {"coat": 1.0}),
    "M_ChestBox": ((0.05, 0.052, 0.056), 0.38, 0.7, {}),
    "M_Glow": ((0.9, 0.55, 0.12), 0.4, 0.0, {"emit": 3.0}),
    "M_Gloves": ((0.016, 0.016, 0.017), 0.48, 0.0, {}),
    "M_Armor": ((0.60, 0.60, 0.58), 0.32, 0.0, {"coat": 0.45}),
    "M_Undersuit": ((0.023, 0.026, 0.030), 0.72, 0.0, {"sheen": 0.08}),
    "M_Trousers": ((0.105, 0.11, 0.092), 0.8, 0.0, {"sheen": 0.08}),
    "M_Mark": ((0.78, 0.78, 0.76), 0.5, 0.0, {}),
    # eyeballs: white factor, the atlas paints sclera, iris and pupil
    "M_Eye": ((0.86, 0.85, 0.83), 0.2, 0.0, {"coat": 0.6}),
}
for _i in range(1, 7):
    MATERIALS[f"M_RankTile_{_i}"] = ((0.023, 0.026, 0.030), 0.35, 0.0, {})


def make_materials():
    for name, (base, rough, metal, extra) in MATERIALS.items():
        if name in bpy.data.materials:
            continue
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        bsdf = m.node_tree.nodes.get("Principled BSDF")
        bsdf.inputs["Base Color"].default_value = (*base, 1.0)
        bsdf.inputs["Roughness"].default_value = rough
        bsdf.inputs["Metallic"].default_value = metal
        if "sheen" in extra:
            # The glTF exporter writes the sheen *tint* as sheenColorFactor and drops the
            # weight, so the amount lives in the tint (weight 1). A white tint made every
            # uniform look washed out in three.js.
            bsdf.inputs["Sheen Weight"].default_value = 1.0
            bsdf.inputs["Sheen Tint"].default_value = (*([extra["sheen"]] * 3), 1.0)
            bsdf.inputs["Sheen Roughness"].default_value = 0.6
        if "coat" in extra:
            bsdf.inputs["Coat Weight"].default_value = extra["coat"]
            bsdf.inputs["Coat Roughness"].default_value = 0.08
        if "emit" in extra:
            bsdf.inputs["Emission Color"].default_value = (*base, 1.0)
            bsdf.inputs["Emission Strength"].default_value = extra["emit"]
        m.diffuse_color = (*base, 1.0)


# ------------------------------------------------------------------------ context


class Ctx:
    """Naked skinned body + skeleton of one body variant."""

    def __init__(self, variant: str):
        self.variant = variant
        ob, eyes, eye_r = B.load_base(variant)
        eyes, s = B.normalise(ob, eyes, variant)
        self.eyes = eyes
        self.eye_r = eye_r * s
        self.L = B.landmarks(ob, variant)
        self.arm = B.build_armature(self.L, f"SK_{variant}")
        B.skin_auto(ob, self.arm)
        B.normalise_weights(ob)
        self.naked = ob
        self.rig = P.Rig(self.arm)
        self.H = C.VARIANTS[variant]["height"]
        self.s = self.H / 1.78
        self.bones = [b.name for b in self.arm.data.bones]
        self.V = B.verts_np(ob)
        self.N = np.array([v.normal[:] for v in ob.data.vertices])
        self.W = self._weights(ob)
        self.dom = np.argmax(self.W, axis=1)
        self.tparam = self._tparam()
        # triangulated source for weight transfer
        self.src_bm = bmesh.new()
        self.src_bm.from_mesh(ob.data)
        bmesh.ops.triangulate(self.src_bm, faces=self.src_bm.faces[:])
        self.src_bm.verts.ensure_lookup_table()
        self.src_bm.faces.ensure_lookup_table()
        self.src_bvh = BVHTree.FromBMesh(self.src_bm)
        ob.hide_render = True
        ob.hide_viewport = True
        z = self.V[:, 2]
        mid = self.V[
            (np.abs(self.V[:, 0]) < 0.012)
            & (z > 0.3 * self.H)
            & (z < 0.6 * self.H)
            & (self.V[:, 1] > 0.0)
        ]
        self.crotch = float(mid[:, 2].min())

    def _weights(self, ob) -> np.ndarray:
        idx = {
            vg.index: self.bones.index(vg.name) for vg in ob.vertex_groups if vg.name in self.bones
        }
        W = np.zeros((len(ob.data.vertices), len(self.bones)))
        for v in ob.data.vertices:
            for g in v.groups:
                if g.group in idx:
                    W[v.index, idx[g.group]] = g.weight
        W /= np.maximum(W.sum(axis=1, keepdims=True), 1e-9)
        return W

    def _tparam(self) -> np.ndarray:
        t = np.zeros(len(self.V))
        for bi, n in enumerate(self.bones):
            m = self.dom == bi
            h = np.array(self.rig.head(n))
            tl = np.array(self.rig.tail(n))
            d = tl - h
            t[m] = ((self.V[m] - h) @ d) / max(d @ d, 1e-9)
        return t

    def bone_mask(self, *names) -> np.ndarray:
        ids = [self.bones.index(n) for n in names if n in self.bones]
        return np.isin(self.dom, ids)

    # ------------------------------------------------------------- weighting

    def transfer(self, ob, hips_blend=None):
        """Skin `ob` by barycentric weights of the nearest point on the naked body."""
        me = ob.data
        res = np.zeros((len(me.vertices), len(self.bones)))
        for v in me.vertices:
            loc, _n, fi, _d = self.src_bvh.find_nearest(v.co)
            f = self.src_bm.faces[fi]
            a, b_, c = (x.co for x in f.verts)
            bc = barycentric_transform(
                loc, a, b_, c, Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))
            )
            w = np.zeros(len(self.bones))
            for k, vv in enumerate(f.verts):
                w += max(0.0, bc[k]) * self.W[vv.index]
            res[v.index] = w / max(w.sum(), 1e-9)
        if hips_blend is not None:
            hi = self.bones.index("Hips")
            for v in me.vertices:
                lam = hips_blend(v.co)
                res[v.index] *= 1.0 - lam
                res[v.index, hi] += lam
        set_weights(ob, self.bones, res)

    def rigid(self, ob, bone: str):
        res = np.zeros((len(ob.data.vertices), len(self.bones)))
        res[:, self.bones.index(bone)] = 1.0
        set_weights(ob, self.bones, res)


def set_weights(ob, bones, res: np.ndarray, limit=4):
    ob.vertex_groups.clear()
    groups = [ob.vertex_groups.new(name=n) for n in bones]
    for i, row in enumerate(res):
        top = np.argsort(-row)[:limit]
        tot = sum(row[j] for j in top if row[j] > 0.005)
        for j in top:
            if row[j] > 0.005:
                groups[j].add([i], float(row[j] / tot), "REPLACE")


# ---------------------------------------------------------------- mesh helpers


def polar_radii(P, center, n=32, smooth=2):
    d = P[:, :2] - np.asarray(center)[:2]
    ang = np.arctan2(d[:, 1], d[:, 0])
    rad = np.hypot(d[:, 0], d[:, 1])
    bins = (((ang + math.pi) / (2 * math.pi)) * n).astype(int) % n
    r = np.full(n, np.nan)
    for i in range(n):
        sel = rad[bins == i]
        if len(sel):
            r[i] = sel.max()
    good = ~np.isnan(r)
    if not good.all():
        idx = np.arange(n)
        r = np.interp(idx, idx[good], r[good], period=n)
    for _ in range(smooth):
        r = (np.roll(r, 1) + 2 * r + np.roll(r, -1)) / 4.0
    angles = -math.pi + (np.arange(n) + 0.5) * 2 * math.pi / n
    return angles, r


def ring_points(center, angles, radii, z):
    zs = z if hasattr(z, "__len__") else [z] * len(angles)
    return [
        Vector((center[0] + r * math.cos(a), center[1] + r * math.sin(a), zz))
        for a, r, zz in zip(angles, radii, zs, strict=True)
    ]


def tube(bm, rings, cap_top=False, cap_bottom=False, mat=0):
    """Quad strip through rings (lists of Vectors, same length, closed loops)."""
    vs = [[bm.verts.new(p) for p in ring] for ring in rings]
    n = len(rings[0])
    for a, b in zip(vs[:-1], vs[1:], strict=True):
        for i in range(n):
            f = bm.faces.new((a[i], a[(i + 1) % n], b[(i + 1) % n], b[i]))
            f.material_index = mat
    if cap_top:
        f = bm.faces.new(list(reversed(vs[-1])))
        f.material_index = mat
    if cap_bottom:
        f = bm.faces.new(vs[0])
        f.material_index = mat
    return vs


def box(bm, center: Vector, x: Vector, y: Vector, z: Vector, size, mat=0):
    """Oriented box; x/y/z unit axes, size = (sx, sy, sz)."""
    sx, sy, sz = (v / 2 for v in size)
    corners = []
    for dz in (-1, 1):
        for dy in (-1, 1):
            for dx in (-1, 1):
                corners.append(bm.verts.new(center + x * dx * sx + y * dy * sy + z * dz * sz))
    idx = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    for q in idx:
        f = bm.faces.new([corners[i] for i in q])
        f.material_index = mat
    return corners


def new_obj(name, bm, mats):
    bm.normal_update()
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    ob = C.mesh_object(name, bm)
    for m in mats:
        ob.data.materials.append(bpy.data.materials[m])
    for p in ob.data.polygons:
        p.use_smooth = True
    return ob


def apply_mod(ob, mod):
    C.set_active(ob)
    bpy.ops.object.modifier_apply(modifier=mod.name)


def repair_spikes(ob, limit=0.04, passes=3):
    """Pull any vertex far from its neighbours' average back onto it."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    fixed = 0
    for _ in range(passes):
        for v in bm.verts:
            nb = [e.other_vert(v).co for e in v.link_edges]
            if not nb:
                continue
            avg = sum(nb, Vector()) / len(nb)
            if (v.co - avg).length > limit:
                v.co = avg
                fixed += 1
    bm.to_mesh(ob.data)
    bm.free()
    return fixed


def decimate(ob, ratio, symmetric=True):
    if ratio >= 1.0:
        repair_spikes(ob)
        return
    m = ob.modifiers.new("dec", "DECIMATE")
    m.decimate_type = "COLLAPSE"
    m.ratio = ratio
    m.use_symmetry = symmetric
    m.symmetry_axis = "X"
    apply_mod(ob, m)
    repair_spikes(ob)


def remesh(ob, voxel, smooth_iter=6):
    m = ob.modifiers.new("rm", "REMESH")
    m.mode = "VOXEL"
    m.voxel_size = voxel
    m.adaptivity = 0.0
    m.use_smooth_shade = True
    apply_mod(ob, m)
    if smooth_iter:
        m = ob.modifiers.new("sm", "LAPLACIANSMOOTH")
        m.iterations = smooth_iter
        m.lambda_factor = 0.6
        m.use_volume_preserve = True
        apply_mod(ob, m)


# ------------------------------------------------------------------ garment body


def garment_body(ctx: Ctx, classify, name="Body"):
    """Copy of the naked body with per-vertex labels -> material, inflation, deletion.

    classify(ctx) -> (labels: list[str] per vertex, inflate: np.ndarray, smooth: np.ndarray)
    labels map to material names; label "DELETE" removes the vertex.
    """
    ob = ctx.naked.copy()
    ob.data = ctx.naked.data.copy()
    ob.name = name
    ob.data.name = name
    C.link(ob)
    ob.hide_render = False
    ob.hide_viewport = False
    ob.modifiers.clear()
    ob.parent = None
    labels, inflate, smooth = classify(ctx)
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.verts.ensure_lookup_table()
    # smoothing passes (cloth drapes over anatomy)
    for it in range(int(smooth.max())):
        vs = [bm.verts[i] for i in np.nonzero(smooth > it)[0]]
        # Uniform smoothing: cotangent weights explode on the few degenerate triangles of
        # the source mesh.
        bmesh.ops.smooth_vert(
            bm, verts=vs, factor=0.5, use_axis_x=True, use_axis_y=True, use_axis_z=True
        )
    bm.normal_update()
    for i, v in enumerate(bm.verts):
        if inflate[i]:
            v.co += v.normal * float(inflate[i])
    mats = sorted({lab for lab in labels if lab != "DELETE"})
    for m in mats:
        ob.data.materials.append(bpy.data.materials[m])
    mi = {m: k for k, m in enumerate(mats)}
    order = {"M_Skin": 0, "M_Hair": 1}
    for f in bm.faces:
        labs = [labels[v.index] for v in f.verts]
        if "DELETE" in labs:
            continue
        best = max(set(labs), key=lambda lab: (labs.count(lab), -order.get(lab, 5)))
        f.material_index = mi[best]
    dead = [v for v in bm.verts if labels[v.index] == "DELETE"]
    bmesh.ops.delete(bm, geom=dead, context="VERTS")
    bm.to_mesh(ob.data)
    bm.free()
    for p in ob.data.polygons:
        p.use_smooth = True
    return ob


def hair_volume(ctx: Ctx, V: np.ndarray, female: bool) -> np.ndarray:
    """Thickness of the hair over the scalp (metres at 1.78 m), per vertex.

    Male: a short side-parted cut with volume on top and a lifted front, tapered
    over the ears and at the nape. Female: hair drawn back smoothly into the bun,
    a little fuller at the crown."""
    ez, ey = ctx.eyes[0].z, ctx.eyes[0].y
    up = np.clip((V[:, 2] - (ez + 0.015)) / 0.085, 0.0, 1.0)
    up = up * up * (3 - 2 * up)
    nape = np.clip((ez - 0.01 - V[:, 2]) / 0.06, 0.0, 1.0) * (V[:, 1] > ey + 0.06)
    if female:
        t = 0.0045 + 0.0055 * up
        crown = np.exp(-(((V[:, 1] - (ey + 0.09)) / 0.05) ** 2)) * up
        return (t + 0.003 * crown) * (1.0 - 0.4 * nape)
    t = 0.004 + 0.010 * up
    front = np.exp(-(((V[:, 1] - (ey + 0.025)) / 0.035) ** 2)) * up
    side = np.clip((np.abs(V[:, 0]) - 0.055) / 0.03, 0.0, 1.0) * (1.0 - up)
    return (t + 0.006 * front) * (1.0 - 0.45 * side) * (1.0 - 0.55 * nape)


def hairline(ctx: Ctx, V: np.ndarray, female: bool) -> np.ndarray:
    """Height of the hairline for every vertex (scalp is above)."""
    ez = ctx.eyes[0].z
    ey = ctx.eyes[0].y
    back = np.clip((V[:, 1] - (ey + 0.05)) / 0.09, 0.0, 1.0)
    front_z = ez + (0.058 if not female else 0.052) * ctx.s
    side_z = ez + (0.022 if not female else -0.01) * ctx.s
    nape_z = ez - (0.075 if not female else 0.085) * ctx.s
    side = np.clip((np.abs(V[:, 0]) - 0.035) / 0.035, 0.0, 1.0)
    z = front_z * (1 - side) + side_z * side
    return z * (1 - back) + nape_z * back


# ------------------------------------------------------------------------ pieces


def slab(ctx: Ctx, z, half=0.008, mask=None):
    m = np.abs(ctx.V[:, 2] - z) < half
    if mask is not None:
        m &= mask
    return ctx.V[m]


def boots(ctx: Ctx, top_z: float, flare=0.012, inflate=0.009, name="Boots", mat="M_Boots"):
    """Boots grown from the lower legs and feet of the naked body (voxel remesh)."""
    bm = bmesh.new()
    bm.from_mesh(ctx.naked.data)
    bm.verts.ensure_lookup_table()
    keep = set(v.index for v in bm.verts if v.co.z < top_z)
    dead = [f for f in bm.faces if not all(v.index in keep for v in f.verts)]
    bmesh.ops.delete(bm, geom=dead, context="FACES")
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bmesh.ops.holes_fill(bm, edges=bm.edges[:], sides=0)
    bm.normal_update()
    for v in bm.verts:
        k = C.smoothstep(top_z - 0.12, top_z, v.co.z)
        toe = C.smoothstep(0.06, 0.0, v.co.z) * 0.004
        v.co += v.normal * (inflate + flare * k + toe)
    ob = new_obj(name, bm, [mat])
    remesh(ob, 0.0065 * ctx.s, smooth_iter=8)
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    for v in bm.verts:
        if v.co.z < 0.012:
            v.co.z = max(0.0, v.co.z - 0.004)
        if v.co.z < 0.004:
            v.co.z = 0.0
    # cut the top flat at top_z (rim)
    for v in bm.verts:
        if v.co.z > top_z:
            v.co.z = top_z + (v.co.z - top_z) * 0.15
    bm.to_mesh(ob.data)
    bm.free()
    decimate(ob, 1400 / max(1, C.tri_count(ob)))
    ctx.transfer(ob)
    return ob


def belt(
    ctx: Ctx,
    z: float,
    height=0.044,
    out=0.022,
    buckle=True,
    mat="M_Belt",
    buckle_mat="M_RankPlate",
    n=40,
    name="Belt",
    pts=None,
):
    """Belt ring around the torso at z. `pts` (N x 3) replaces the naked body as the
    surface the belt is measured from (e.g. the tailored cloth surface)."""
    if pts is not None:
        # narrower than the naked-body slab: the female elbows reach down to the waist
        torso = pts[(np.abs(pts[:, 2] - z) < 0.03) & (np.abs(pts[:, 0]) < 0.205 * ctx.s)]
    else:
        torso = slab(
            ctx,
            z,
            0.03,
            mask=(np.abs(ctx.V[:, 0]) < 0.25)
            & ~ctx.bone_mask(
                "Hand_L",
                "Hand_R",
                "Fingers_L",
                "Fingers_R",
                "ForeArm_L",
                "ForeArm_R",
                "Thumb_L",
                "Thumb_R",
            ),
        )
    c = torso[:, :2].mean(axis=0)
    ang, r = polar_radii(torso, c, n, smooth=3)
    r_lo = r_hi = r
    if pts is not None:
        # Follow the waist-to-hip cone: each edge of the belt takes the cloth radius of
        # its own half, so it never stands off a narrow waist above flared hips.
        lo = torso[torso[:, 2] < z + 0.004]
        hi = torso[torso[:, 2] > z - 0.004]
        if len(lo) >= 12 and len(hi) >= 12:
            r_lo = polar_radii(lo, c, n, smooth=3)[1]
            r_hi = polar_radii(hi, c, n, smooth=3)[1]
            r = (r_lo + r_hi) / 2
    bm = bmesh.new()
    rings = []
    for dz, dr, rr in (
        (-height / 2, out - 0.004, r_lo),
        (-height / 2, out + 0.002, r_lo),
        (height / 2, out + 0.002, r_hi),
        (height / 2, out - 0.004, r_hi),
    ):
        rings.append(ring_points(c, ang, rr + dr, z + dz))
    tube(bm, rings, mat=0)
    mats = [mat]
    if buckle:
        mats.append(buckle_mat)
        i = int(np.argmin(np.abs(ang + math.pi / 2)))
        front = Vector((c[0], c[1] - r[i] - out - 0.006, z))
        box(
            bm,
            front,
            Vector((1, 0, 0)),
            Vector((0, 1, 0)),
            Vector((0, 0, 1)),
            (0.064 * ctx.s, 0.008, 0.044 * ctx.s),
            mat=1,
        )
    ob = new_obj(name, bm, mats)
    ctx.transfer(ob)
    return ob


def collar(ctx: Ctx, z0: float, z1: float, out=0.011, mat="M_Trim", piping="M_Accent"):
    neck = slab(
        ctx, (z0 + z1) / 2, (z1 - z0) / 2 + 0.01, mask=ctx.bone_mask("Neck", "Chest", "Head")
    )
    neck = neck[np.abs(neck[:, 0]) < 0.09]
    c = neck[:, :2].mean(axis=0)
    ang, r = polar_radii(neck, c, 28, smooth=3)
    # Follow the wider base of the neck at the back corners (a tight clamp let the
    # shoulder cloth show inside the collar from behind), but not the shoulders.
    r = np.minimum(r, np.median(r) * 1.3)
    tilt = 0.012 * np.sin(ang)  # higher at the back (+Y)
    bm = bmesh.new()
    rings = [
        ring_points(c, ang, r + out, z0 + tilt - 0.01),
        ring_points(c, ang, r + out + 0.002, z1 + tilt),
        ring_points(c, ang, r + out - 0.004, z1 + tilt + 0.003),
        ring_points(c, ang, r + 0.002, z1 + tilt - 0.004),
        ring_points(c, ang, r - 0.002, z1 + tilt - 0.03),
    ]
    tube(bm, rings, mat=0)
    mats = [mat]
    if piping:
        mats.append(piping)
        pr = [
            ring_points(
                c,
                ang,
                r + out + 0.0025 + 0.0032 * math.cos(k * math.pi / 3),
                z1 + tilt + 0.001 + 0.0032 * math.sin(k * math.pi / 3),
            )
            for k in range(7)
        ]
        tube(bm, pr, mat=1)
    ob = new_obj("Collar", bm, mats)
    ctx.transfer(ob)
    return ob


def collar_pin(ctx: Ctx, col, z: float, mat="M_RankPlate"):
    """12 mm steel hexagon on the right collar point (style bible 7.2)."""
    bvh = BVHTree.FromObject(col, bpy.context.evaluated_depsgraph_get())
    a = math.radians(-90 - 32)  # front, towards the wearer's right (-X)
    d = Vector((math.cos(a), math.sin(a), 0.0))
    hit, nrm, _i, _d = bvh.ray_cast(Vector((0.0, ctx.L["neck"].y, z)) + d * 0.3, -d)
    if hit is None:
        raise RuntimeError("collar pin: collar not found")
    out = Vector((nrm.x, nrm.y, 0.0)).normalized()
    if out.dot(d) < 0:
        out = -out
    up = Vector((0, 0, 1))
    side = up.cross(out).normalized()
    bm = bmesh.new()
    hexagon(bm, hit + out * 0.0006, side, up, out, 0.012, 0.0104, 0.0022, chamfer=0.003)
    ob = new_obj("CollarPin", bm, [mat])
    for p in ob.data.polygons:
        p.use_smooth = False
    ctx.transfer(ob)
    return ob


def skirt(
    ctx: Ctx,
    garment,
    z_top: float,
    z_hem: float,
    out=0.008,
    flare=0.02,
    mat="M_Uniform",
    hem_mat="M_Trim",
    cloth=None,
):
    # Hull of the pelvis only (not the spread thighs of the rest pose). `cloth` is the
    # garment surface per naked vertex (tailored), else a flat 8 mm over the body.
    pelvis = ctx.bone_mask("Hips", "Spine")
    # The seat and the top of the thighs belong to the leg bones; the skirt must close
    # over them too, or the trousers show through it from behind (the game camera
    # follows the commander from the back).
    pelvis |= (
        ctx.bone_mask("UpperLeg_L", "UpperLeg_R")
        & (ctx.V[:, 2] > z_hem - 0.03)
        & (ctx.V[:, 1] > ctx.L["hip"].y + 0.02)
    )
    if cloth is not None:
        Vg = cloth[pelvis]
    else:
        Vg = ctx.V[pelvis] + ctx.N[pelvis] * 0.008
    mask = (np.abs(Vg[:, 0]) < 0.25) & (Vg[:, 2] > z_hem - 0.05) & (Vg[:, 2] < z_top + 0.03)
    P_ = Vg[mask]
    c = P_[:, :2].mean(axis=0)
    rings = []
    zs = np.linspace(z_top, z_hem, 6)
    r = None
    for k, z in enumerate(zs):
        pts = P_[np.abs(P_[:, 2] - z) < 0.03]
        if len(pts) >= 24 or r is None:
            ang, r = polar_radii(pts, c, 36, smooth=4)
        fl = flare * (k / (len(zs) - 1)) ** 1.5
        rings.append(ring_points(c, ang, r + out + fl, z))
    # make radii monotonic outwards downwards (a skirt never tucks in)
    for k in range(1, len(rings)):
        for i, p in enumerate(rings[k]):
            q = rings[k - 1][i]
            dp = Vector((p.x - c[0], p.y - c[1], 0))
            dq = Vector((q.x - c[0], q.y - c[1], 0))
            if dp.length < dq.length + 0.002:
                dp = dp.normalized() * (dq.length + 0.002)
                p.x, p.y = c[0] + dp.x, c[1] + dp.y
    hem_in = [
        Vector((c[0] + (p.x - c[0]) * 0.97, c[1] + (p.y - c[1]) * 0.97, p.z + 0.004))
        for p in rings[-1]
    ]
    bm = bmesh.new()
    tube(bm, rings + [hem_in], mat=0)
    ob = new_obj("Skirt", bm, [mat])
    top = z_top
    span = max(1e-3, z_top - z_hem)
    # Front and back bridge both legs and ride the hips; the sides ride the thighs, so a
    # leg drawn in at rest or swung while walking carries the skirt with it instead of
    # pushing the breeches out through it.
    def hips_blend(co):
        side = C.clamp((abs(co.x) - 0.06 * ctx.s) / (0.06 * ctx.s), 0, 1)
        return (0.45 + 0.35 * C.clamp((top - co.z) / span, 0, 1)) * (1.0 - 0.75 * side)

    ctx.transfer(ob, hips_blend=hips_blend)
    return ob


def officer_cap(ctx: Ctx, n=36):
    H = ctx.H
    head = slab(ctx, H - 0.085 * ctx.s, 0.008, mask=ctx.bone_mask("Head"))
    c = head[:, :2].mean(axis=0)
    ang, r = polar_radii(head, c, n, smooth=3)
    zb = H - 0.070 * ctx.s + 0.012 * np.sin(ang)  # band bottom, higher at the back
    r0 = r + 0.011
    bm = bmesh.new()
    rings = [
        ring_points(c, ang, r0 - 0.005, zb + 0.004),
        ring_points(c, ang, r0, zb),
        ring_points(c, ang, r0 + 0.002, zb + 0.040 * ctx.s),
        ring_points(c, ang, r0 * 1.035 + 0.002, zb + 0.072 * ctx.s),
        ring_points(c, ang, r0 * 1.045 + 0.002, zb + 0.080 * ctx.s),
        ring_points(c, ang, r0 * 1.04, zb + 0.0845 * ctx.s),
        ring_points(c, ang, r0 * 0.97, zb + 0.087 * ctx.s),
        ring_points(c, ang, r0 * 0.5, zb + 0.0885 * ctx.s),
    ]
    tube(bm, rings, cap_top=True, mat=0)
    # brim: front arc, angled down
    arc = [i for i, a in enumerate(ang) if abs(a + math.pi / 2) < math.radians(78)]
    arc.sort(key=lambda i: ang[i])
    top_in, top_out, bot_out, bot_in = [], [], [], []
    for i in arc:
        a = ang[i]
        k = math.cos((a + math.pi / 2) / math.radians(78) * math.pi / 2) ** 0.7
        d = Vector((math.cos(a), math.sin(a), 0))
        base = Vector((c[0], c[1], 0)) + d * (r0[i] + 0.001)
        base.z = zb[i] + 0.004
        vis = 0.040 * ctx.s * k + 0.003
        rake = math.radians(20)
        tip = base + d * vis * math.cos(rake) - Vector((0, 0, vis * math.sin(rake)))
        top_in.append(bm.verts.new(base + Vector((0, 0, 0.002))))
        top_out.append(bm.verts.new(tip + Vector((0, 0, 0.002))))
        bot_out.append(bm.verts.new(tip - Vector((0, 0, 0.002))))
        bot_in.append(bm.verts.new(base - Vector((0, 0, 0.002))))
    for j in range(len(arc) - 1):
        for a_, b_ in ((top_in, top_out), (top_out, bot_out), (bot_out, bot_in)):
            bm.faces.new((a_[j], b_[j], b_[j + 1], a_[j + 1]))
    for a_, b_, c_, d_ in ((top_in, top_out, bot_out, bot_in),):
        bm.faces.new((a_[0], d_[0], c_[0], b_[0]))
        bm.faces.new((a_[-1], b_[-1], c_[-1], d_[-1]))
    # badge (steel) on the front band
    i = int(np.argmin(np.abs(ang + math.pi / 2)))
    pf = Vector((c[0], c[1] - r0[i] - 0.003, zb[i] + 0.05 * ctx.s))
    hexagon(
        bm,
        pf,
        Vector((1, 0, 0)),
        Vector((0, 0, 1)),
        Vector((0, -1, 0)),
        0.018 * ctx.s,
        0.010 * ctx.s,
        0.003,
        mat=1,
    )
    ob = new_obj("Cap", bm, ["M_Cap", "M_RankPlate"])
    # Crisp crown edge and a firm brim: flat-shade the top and the visor.
    top_z = float(np.max(zb)) + 0.08 * ctx.s
    for p in ob.data.polygons:
        if p.center.z > top_z or p.center.z < float(np.min(zb)) + 0.004:
            p.use_smooth = False
    ctx.rigid(ob, "Head")
    return ob


def hexagon(bm, center, side, up, out, w, h, depth, mat=0, chamfer=None):
    """Elongated hexagon prism (45 degree chamfered ends) facing `out`."""
    c = chamfer if chamfer is not None else h / 2
    outline = [
        (-w / 2, 0),
        (-w / 2 + c, h / 2),
        (w / 2 - c, h / 2),
        (w / 2, 0),
        (w / 2 - c, -h / 2),
        (-w / 2 + c, -h / 2),
    ]
    back = [bm.verts.new(center + side * x + up * y) for x, y in outline]
    front = [bm.verts.new(center + side * x + up * y + out * depth) for x, y in outline]
    f = bm.faces.new(list(reversed(back)))
    f.material_index = mat
    f = bm.faces.new(front)
    f.material_index = mat
    for i in range(6):
        j = (i + 1) % 6
        f = bm.faces.new((back[i], back[j], front[j], front[i]))
        f.material_index = mat


def rank_plate(ctx: Ctx, garment):
    """Steel chest plate (elongated hexagon) with six hexagon pips M_RankTile_1..6.

    Original rendering of the level-system plate (style bible 7.2): 54 x 22 x 3 mm,
    pips 12 x 7 mm at 15 x 9 mm pitch, two rows of three, left chest at the second rib.
    Tiles 1-3 are the top row, 4-6 the bottom row (left to right as seen from the front).
    """
    bvh = BVHTree.FromObject(garment, bpy.context.evaluated_depsgraph_get())
    x = 0.092 * ctx.s
    z = 0.762 * ctx.H
    hit, nrm, _i, _d = bvh.ray_cast(Vector((x, -1.0, z)), Vector((0, 1, 0)))
    if hit is None:
        raise RuntimeError("rank plate: chest not found")
    nz = Vector((nrm.x * 0.5, nrm.y, nrm.z * 0.3)).normalized()
    up = (Vector((0, 0, 1)) - nz * nz.z).normalized()
    side = up.cross(nz).normalized()
    sc = 1.15  # slightly enlarged so the plate survives the 96 px/m plate density
    base = hit + nz * 0.0008
    bm = bmesh.new()
    hexagon(bm, base, side, up, nz, 0.054 * sc, 0.022 * sc, 0.003, mat=0)
    k = 1
    for row in (1, -1):
        for col in (-1, 0, 1):
            pc = base + side * (col * 0.015 * sc) + up * (row * 0.0045 * sc) + nz * 0.003
            hexagon(bm, pc, side, up, nz, 0.012 * sc, 0.007 * sc, 0.0009, mat=k)
            k += 1
    for sx in (-1, 1):
        pc = base + side * (sx * 0.024 * sc) + nz * 0.003
        hexagon(bm, pc, side, up, nz, 0.004, 0.004, 0.001, mat=0, chamfer=0.0015)
    mats = ["M_RankPlate"] + [f"M_RankTile_{i}" for i in range(1, 7)]
    ob = new_obj("RankPlate", bm, mats)
    for p in ob.data.polygons:
        p.use_smooth = False
    ctx.rigid(ob, "Chest")
    return ob


def shoulder_piping(ctx: Ctx, garment, mat="M_Accent"):
    """Thin cords along both shoulder seams (personal accent colour)."""
    Vg = B.verts_np(garment)
    neck_z = ctx.L["neck"].z
    bm = bmesh.new()
    for sg in (1.0, -1.0):
        pts = []
        x0, x1 = 0.072 * ctx.s, ctx.L["shoulder"].x + 0.04 * ctx.s
        for k in range(9):
            x = C.lerp(x0, x1, k / 8)
            sel = Vg[
                (np.abs(Vg[:, 0] - sg * x) < 0.008)
                & (Vg[:, 2] > neck_z - 0.12)
                & (Vg[:, 2] < neck_z + 0.05)
                & (np.abs(Vg[:, 1]) < 0.12)
            ]
            if not len(sel):
                continue
            top = sel[np.argmax(sel[:, 2])]
            pts.append(Vector((top[0], top[1], top[2] + 0.0025)))
        for _ in range(2):
            pts = (
                [pts[0]]
                + [(pts[i - 1] + 2 * pts[i] + pts[i + 1]) / 4 for i in range(1, len(pts) - 1)]
                + [pts[-1]]
            )
        rings = []
        for i, p in enumerate(pts):
            d = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
            u = Vector((0, 0, 1))
            sv = d.cross(u).normalized()
            u = sv.cross(d).normalized()
            rings.append(
                [
                    p + (u * math.cos(a) + sv * math.sin(a)) * 0.0034
                    for a in np.linspace(0, 2 * math.pi, 6, endpoint=False)
                ]
            )
        tube(bm, rings, cap_top=True, cap_bottom=True)
    ob = new_obj("Piping", bm, [mat])
    ctx.transfer(ob)
    return ob


def eyes(ctx: Ctx, mat="M_Eye"):
    """Eyeballs (the atlas paints sclera, iris and pupil)."""
    bm = bmesh.new()
    for e in ctx.eyes:
        m = Matrix.Translation(e) @ Matrix.Rotation(math.pi / 2, 4, "X")
        bmesh.ops.create_uvsphere(
            bm, u_segments=14, v_segments=8, radius=ctx.eye_r * 0.98, matrix=m
        )
    ob = new_obj("Eyes", bm, [mat])
    ctx.rigid(ob, "Head")
    return ob


def hair_bun(ctx: Ctx):
    ez = ctx.eyes[0].z
    head = slab(ctx, ez, 0.01, mask=ctx.bone_mask("Head"))
    back = head[:, 1].max()
    bm = bmesh.new()
    m = Matrix.Translation(Vector((0, back + 0.012, ez - 0.045 * ctx.s))) @ Matrix.Diagonal(
        (1.15, 0.9, 0.85, 1.0)
    )
    bmesh.ops.create_uvsphere(bm, u_segments=12, v_segments=8, radius=0.042, matrix=m)
    ob = new_obj("Bun", bm, ["M_Hair"])
    ctx.rigid(ob, "Head")
    return ob


# -------------------------------------------------------------------- classifiers


def _limbs(ctx: Ctx):
    hands = ctx.bone_mask("Hand_L", "Hand_R", "Fingers_L", "Fingers_R", "Thumb_L", "Thumb_R")
    fore = ctx.bone_mask("ForeArm_L", "ForeArm_R")
    upper_arm = ctx.bone_mask("UpperArm_L", "UpperArm_R")
    head = ctx.bone_mask("Head", "Neck")
    thigh = ctx.bone_mask("UpperLeg_L", "UpperLeg_R")
    return hands, fore, upper_arm, head, thigh


def shoulder_pad(ctx: Ctx) -> np.ndarray:
    """Outward offset that squares the shoulder line (a light tailored pad)."""
    V, N = ctx.V, ctx.N
    ax = np.abs(V[:, 0])
    neck_z = ctx.L["neck"].z
    k_x = np.clip((ax - 0.06 * ctx.s) / (0.09 * ctx.s), 0.0, 1.0)
    k_x = k_x * k_x * (3 - 2 * k_x) * (ax < 0.22 * ctx.s)
    k_n = np.clip((N[:, 2] - 0.3) / 0.45, 0.0, 1.0)
    k_z = (V[:, 2] > neck_z - 0.10 * ctx.s).astype(float)
    return 0.007 * ctx.s * k_x * k_n * k_z


def classify_officer(ctx: Ctx, female: bool, boot_top: float, belt_z: float):
    """Tailored tunic and riding breeches.

    The cut is slim: the belly and the hips are taken in under the cloth, the outer
    shoulder is padded square, and the breeches flare only on the outer thigh (a
    narrow knee into the boot).
    """
    V, N = ctx.V, ctx.N
    n = len(V)
    hands, fore, upper_arm, head, thigh = _limbs(ctx)
    t = ctx.tparam
    labels = ["M_Uniform"] * n
    inflate = np.full(n, 0.006)
    smooth = np.full(n, 3.0)
    neck_z = ctx.L["neck"].z
    pad = shoulder_pad(ctx)
    # Skin starts just under the collar's top edge (the collar rises towards the back),
    # so no neck skin shows outside the collar where the trapezius is wider than it.
    skin_z = neck_z + (0.032 + 0.016 * np.clip(V[:, 1] / 0.06, -1, 1)) * ctx.s
    hl = hairline(ctx, V, female)
    vol = hair_volume(ctx, V, female)
    tuck = np.zeros(n)  # how far the cloth hidden under the skirt is taken in
    for i in range(n):
        z = V[i, 2]
        if z < boot_top - 0.035:
            labels[i] = "DELETE"
            continue
        if head[i] and z > skin_z[i]:
            if z > hl[i]:
                labels[i] = "M_Hair"
                # a short ramp: the hair edge stands off the skin like real hair
                k = C.smoothstep(hl[i], hl[i] + 0.009, z)
                inflate[i] = (0.0015 + vol[i] * k) * ctx.s
                smooth[i] = 2
            else:
                labels[i] = "M_Skin"
                inflate[i] = 0.0
                smooth[i] = 0
            continue
        if hands[i] or (fore[i] and t[i] > 0.985):
            labels[i] = "M_Skin"
            inflate[i] = 0.0
            smooth[i] = 0
            continue
        if fore[i] and t[i] > 0.86:
            labels[i] = "M_Trim"
            inflate[i] = 0.012
            smooth[i] = 3
            continue
        if fore[i] or upper_arm[i]:
            inflate[i] = 0.0045 + 0.003 * C.smoothstep(0.6, 1.0, t[i]) * fore[i] + pad[i]
            continue
        lat = max(0.0, N[i, 0] * (1 if V[i, 0] > 0 else -1))
        # Under the tunic skirt the body is tunic cloth, not breeches: where a moving
        # leg pushes it out through the skirt it shows the skirt's own colour.
        if (thigh[i] or z < ctx.crotch) and z < ctx.crotch - 0.03:
            # Riding breeches: a slight flare on the outer thigh only, slim front, back
            # and inside, narrow at the knee, a small blouse over the boot top.
            ft = C.clamp((z - (boot_top + 0.04)) / (ctx.crotch - boot_top - 0.02), 0, 1)
            prof = math.sin(math.pi * ft**0.7) ** 2
            fl = 0.034 * prof * (0.1 + 0.9 * lat**1.5)
            take_in = 0.004 * C.smoothstep(0.55, 1.0, ft) * (1.0 - lat)
            bl = 0.005 * C.smoothstep(boot_top + 0.07, boot_top, z)
            labels[i] = "M_Trousers"
            inflate[i] = 0.0035 + (fl - take_in) * ctx.s + bl
            # Under the tunic skirt the breeches are taken in, so a moving leg never
            # pushes them out through the skirt's hem.
            under = C.smoothstep(ctx.crotch - 0.05, ctx.crotch - 0.01, z)
            tuck[i] = inflate[i] * under + 0.004 * under
            inflate[i] -= tuck[i]
            smooth[i] = 4
            continue
        # torso
        smooth[i] = 8 if z > belt_z else 6
        front = N[i, 1] < -0.3
        # Tailoring: take in the belly and the waist, and the hips under the belt.
        fr = C.clamp((-N[i, 1] - 0.2) / 0.6, 0.0, 1.0)
        waist = math.exp(-(((z - (belt_z + 0.03 * ctx.s)) / (0.075 * ctx.s)) ** 2))
        hip = C.smoothstep(belt_z + 0.01, belt_z - 0.05, z) * C.smoothstep(
            ctx.crotch - 0.04, ctx.crotch + 0.03, z
        )
        bk = C.clamp((N[i, 1] - 0.3) / 0.5, 0.0, 1.0)
        trim = 0.011 * fr * waist + 0.004 * lat * waist + 0.009 * lat * hip + 0.006 * bk * hip
        base = 0.006 - trim * ctx.s + pad[i]
        # below the belt the body is hidden by the skirt piece: keep it well inside
        tuck[i] = 0.006 * C.smoothstep(belt_z - 0.025, belt_z - 0.06, z)
        base -= tuck[i]
        # Asymmetric closure: the front flap ends in a straight vertical edge 70 mm to
        # the wearer's right of the centre line (a small step in the cloth).
        edge = flap_edge_x(ctx, z, belt_z, neck_z)
        if front and belt_z - 0.02 < z < neck_z + 0.01 and V[i, 0] > edge:
            inflate[i] = base + 0.0025 * C.smoothstep(0.14 * ctx.s, edge, V[i, 0])
        else:
            inflate[i] = base
    ctx.tuck = tuck
    return labels, inflate, smooth


def flap_edge_x(ctx: Ctx, z: float, belt_z: float, neck_z: float) -> float:
    """x of the tunic's front-flap edge: from the collar down to the hip on the wearer's
    right, slightly diagonal."""
    k = C.clamp((z - belt_z) / max(1e-3, neck_z - belt_z), 0.0, 1.0)
    return C.lerp(-0.085, -0.035, k) * ctx.s


def flap_seam(ctx: Ctx, garment, belt_z: float, neck_z: float, mat="M_Trim"):
    """Darker seam ribbon along the front-flap edge (reads from above)."""
    bvh = BVHTree.FromObject(garment, bpy.context.evaluated_depsgraph_get())
    pts = []
    for k in np.linspace(0.0, 1.0, 14):
        z = C.lerp(belt_z + 0.02, neck_z - 0.005, k)
        x = flap_edge_x(ctx, z, belt_z, neck_z)
        hit = bvh.ray_cast(Vector((x, -1.0, z)), Vector((0, 1, 0)))
        if hit[0] is not None:
            pts.append((hit[0], hit[1]))
    bm = bmesh.new()
    # Raised bead (half-round piping, 9 mm wide, 2.5 mm high): it catches the ceiling
    # light, so the flap line reads from the 60 degree game camera even tone-on-tone.
    prof = [(-1.0, 0.0), (-0.65, 0.65), (0.0, 1.0), (0.65, 0.65), (1.0, 0.0)]
    rows = []
    for i, (p, nrm) in enumerate(pts):
        nxt = pts[min(i + 1, len(pts) - 1)][0]
        prv = pts[max(i - 1, 0)][0]
        d = (nxt - prv).normalized()
        side = d.cross(nrm).normalized()
        base = p + nrm * 0.0008
        rows.append(
            [bm.verts.new(base + side * (a * 0.0045) + nrm * (h * 0.0025)) for a, h in prof]
        )
    for i in range(len(rows) - 1):
        for j in range(len(prof) - 1):
            bm.faces.new((rows[i][j], rows[i][j + 1], rows[i + 1][j + 1], rows[i + 1][j]))
    ob = new_obj("Seam", bm, [mat])
    ctx.transfer(ob)
    return ob


# ------------------------------------------------------------------------ finish


def tag_part(ob, name: str):
    """Face attribute 'part' (index into ob['parts']) so the painter knows each piece."""
    me = ob.data
    attr = me.attributes.get("part") or me.attributes.new("part", "INT", "FACE")
    attr.data.foreach_set("value", [0] * len(me.polygons))
    ob["parts"] = [name]


def finish(ctx: Ctx, parts: list, body_name: str):
    """Join parts into the skinned 'Body' mesh, bake AO into COLOR_0, bind to the rig.

    Every face keeps the name of the piece it came from (attribute 'part', names in
    the object's 'parts' property) for the texture painter."""
    main = parts[0]
    names = [p.name.split(".")[0] for p in parts]
    for k, p in enumerate(parts):
        me = p.data
        attr = me.attributes.get("part") or me.attributes.new("part", "INT", "FACE")
        attr.data.foreach_set("value", [k] * len(me.polygons))
    for o in bpy.context.scene.objects:
        o.select_set(False)
    for p in parts:
        p.select_set(True)
    bpy.context.view_layer.objects.active = main
    dark_names = {p.name for p in parts if p.get("dark")}
    dark_ranges = []
    off = 0
    for p in parts:
        nv = len(p.data.vertices)
        if p.name in dark_names:
            dark_ranges.append((off, off + nv))
        off += nv
    if len(parts) > 1:
        bpy.ops.object.join()
    main.name = body_name
    main.data.name = body_name
    main["parts"] = names
    bake_vertex_ao(main, dark_ranges)
    bind(ctx, main)
    return main


def keep_hi(ob, name: str):
    """A hidden full-resolution copy of `ob` (rest pose) to bake shading normals from."""
    hi = ob.copy()
    hi.data = ob.data.copy()
    hi.name = name
    hi.data.name = name
    hi.modifiers.clear()
    hi.vertex_groups.clear()
    C.link(hi)
    hi.hide_render = True
    hi.hide_viewport = True
    return hi


def decimate_head_aware(ob, ctx: Ctx, total: int, head_tris: int):
    """Decimate to about `total` triangles, keeping `head_tris` of them on the head.

    The face reads at close range (nose, lips, ears, chin), so it keeps more of the
    source resolution than the cloth, whose detail goes into the baked normal map."""
    z_cut = ctx.L["neck"].z + 0.035 * ctx.s

    def head_faces():
        return [p.index for p in ob.data.polygons if p.center.z > z_cut]

    n_head = sum(len(ob.data.polygons[i].vertices) - 2 for i in head_faces())
    n_all = C.tri_count(ob)
    n_body = n_all - n_head
    for sel_head, target, have in ((False, total - head_tris, n_body), (True, head_tris, n_head)):
        ratio = min(1.0, target / max(1, have))
        if ratio >= 0.999:
            continue
        C.set_active(ob)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.object.mode_set(mode="OBJECT")
        heads = set(head_faces())
        for p in ob.data.polygons:
            p.select = (p.index in heads) == sel_head
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.decimate(ratio=ratio, use_symmetry=True, symmetry_axis="X")
        bpy.ops.object.mode_set(mode="OBJECT")
    repair_spikes(ob)
    # collapsing edges mixes the weights of both ends: back to 4 influences per vertex
    B.normalise_weights(ob)


def bind(ctx: Ctx, ob):
    ob.parent = ctx.arm
    ob.matrix_parent_inverse.identity()
    mod = ob.modifiers.new("Armature", "ARMATURE")
    mod.object = ctx.arm


def bake_vertex_ao(ob, dark_ranges=(), rays=28, dist=0.22):
    """Ambient occlusion per vertex (rest pose) into the active colour attribute."""
    dg = bpy.context.evaluated_depsgraph_get()
    bvh = BVHTree.FromObject(ob, dg)
    me = ob.data
    golden = math.pi * (3 - math.sqrt(5))
    dirs = []
    for k in range(rays):
        zc = 1 - (k + 0.5) / rays
        r = math.sqrt(1 - zc * zc)
        dirs.append(Vector((r * math.cos(golden * k), r * math.sin(golden * k), zc)))
    ao = np.ones(len(me.vertices))
    for v in me.vertices:
        nrm = v.normal
        if nrm.length < 0.5:
            continue
        rot = nrm.to_track_quat("Z", "Y")
        o = v.co + nrm * 0.0015
        hits = 0.0
        for d in dirs:
            dd = rot @ d
            h = bvh.ray_cast(o, dd, dist)
            if h[0] is not None:
                hits += (1.0 - h[3] / dist) ** 0.5 * d.z * 2.0
        ao[v.index] = max(0.0, 1.0 - hits / rays)
    for a, b in dark_ranges:
        ao[a:b] *= 0.12
    val = 0.30 + 0.70 * np.clip(ao, 0, 1) ** 0.9
    attr = me.color_attributes.new("AO", "BYTE_COLOR", "POINT")
    cols = np.repeat(val[:, None], 4, axis=1)
    cols[:, 3] = 1.0
    attr.data.foreach_set("color", cols.ravel().astype(np.float32))
    me.color_attributes.active_color = attr
    me.color_attributes.render_color_index = me.color_attributes.find("AO")


# ------------------------------------------------------------------------- builds


def build_officer(ctx: Ctx):
    female = ctx.variant == "F"
    s = ctx.s
    boot_top = 0.48 * s
    belt_z = (0.597 if female else 0.585) * ctx.H  # natural waist
    neck_z = ctx.L["neck"].z
    cut = classify_officer(ctx, female, boot_top, belt_z)
    # the skirt is fitted over the cloth as it would be without the tuck under it
    cloth = ctx.V + ctx.N * (cut[1] + ctx.tuck)[:, None]
    garment = garment_body(ctx, lambda c: cut, name="Garment")
    ctx.hi = {"Garment": keep_hi(garment, f"Hi_Officer_{ctx.variant}")}
    ctx.look = {"belt_z": belt_z, "boot_top": boot_top, "neck_z": neck_z, "female": female}
    decimate_head_aware(garment, ctx, 8200, 2900)
    parts = [garment]
    parts.append(boots(ctx, boot_top, flare=0.006, inflate=0.006))
    parts.append(
        skirt(
            ctx, garment, belt_z - 0.02, ctx.crotch - 0.01 * s, out=0.005, flare=0.006, cloth=cloth
        )
    )
    parts.append(belt(ctx, belt_z, out=0.013, buckle=True, pts=B.verts_np(garment)))
    col = collar(ctx, neck_z - 0.004, neck_z + 0.040 * s, mat="M_Uniform")
    parts.append(col)
    parts.append(collar_pin(ctx, col, neck_z + 0.022 * s))
    parts.append(shoulder_piping(ctx, garment))
    parts.append(flap_seam(ctx, garment, belt_z, neck_z))
    parts.append(eyes(ctx))
    if female:
        parts.append(hair_bun(ctx))
    plate = rank_plate(ctx, garment)
    cap = officer_cap(ctx)
    body = finish(ctx, parts, "Body")
    for o in (plate, cap):
        bake_vertex_ao(o)
        bind(ctx, o)
    return [body, cap, plate]
