"""Drones: the commander's hovering companion and the ambient utility floor drone.

Both are built from code (no third-party data), rigidly skinned to a tiny rig and
exported as glTF binaries with their clips. Blender axes: -Y = forward, Z = up;
the glTF exporter turns -Y into three.js +Z, so both drones face +Z at runtime.

Every part is a separate bmesh piece with its own material and bone; the pieces
are joined into one skinned mesh per drone. Panel seams are real gaps between
bevelled shell panels over a dark core, so they read at any scale.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree

from characters import common as C
from characters import looks_gear as LG
from characters import paint as PT

TAU = 2.0 * math.pi

# ----------------------------------------------------------------------- materials

MATERIALS = {
    # name: (base colour (linear), metallic, roughness, coat, emission strength)
    "M_Shell": ((0.78, 0.78, 0.76), 0.0, 0.32, 0.6, 0.0),
    "M_Lens": ((0.006, 0.008, 0.012), 0.2, 0.06, 1.0, 0.0),
    "M_Ring": ((0.20, 0.21, 0.22), 0.9, 0.34, 0.0, 0.0),
    "M_Trim": ((0.018, 0.019, 0.021), 0.3, 0.55, 0.0, 0.0),
    "M_Glow": ((0.35, 0.75, 1.0), 0.0, 0.4, 0.0, 6.0),
    # twice the paint colour: the atlas halves it and lifts the hex-bar mark above it
    "M_Chassis": ((0.10, 0.104, 0.112), 0.6, 0.45, 0.15, 0.0),
}


def make_material(name: str):
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    base, metal, rough, coat, emit = MATERIALS[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*base, 1.0)
    bsdf.inputs["Metallic"].default_value = metal
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Coat Weight"].default_value = coat
    bsdf.inputs["Coat Roughness"].default_value = 0.05
    if emit > 0:
        bsdf.inputs["Emission Color"].default_value = (*base, 1.0)
        bsdf.inputs["Emission Strength"].default_value = emit
    m.diffuse_color = (*base, 1.0)
    return m


# ------------------------------------------------------------------ mesh helpers


class Part:
    """A bmesh piece with one material and one bone (rigid skinning)."""

    def __init__(self, bm: bmesh.types.BMesh, material: str, bone: str):
        self.bm = bm
        self.material = material
        self.bone = bone


def _finish(bm: bmesh.types.BMesh, sharp_deg: float = 38.0) -> bmesh.types.BMesh:
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    for f in bm.faces:
        f.smooth = True
    lim = math.radians(sharp_deg)
    for e in bm.edges:
        if len(e.link_faces) == 2:
            e.smooth = e.calc_face_angle(0.0) < lim
        else:
            e.smooth = False
    return bm


def bevel(bm: bmesh.types.BMesh, width: float, segments: int = 1, angle_deg: float = 30.0):
    edges = [
        e
        for e in bm.edges
        if len(e.link_faces) != 2 or e.calc_face_angle(0.0) > math.radians(angle_deg)
    ]
    if edges:
        bmesh.ops.bevel(
            bm,
            geom=edges,
            offset=width,
            offset_type="OFFSET",
            segments=segments,
            profile=0.5,
            affect="EDGES",
            clamp_overlap=True,
        )
    return bm


def rounded_box(size, center, width=0.004, segments=1) -> bmesh.types.BMesh:
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    bevel(bm, width, segments)
    bmesh.ops.translate(bm, vec=Vector(center), verts=bm.verts)
    return _finish(bm)


def cylinder(
    radius, depth, center, axis="Z", segments=16, r2=None, cap=True, bevel_w=0.0
) -> bmesh.types.BMesh:
    bm = bmesh.new()
    bmesh.ops.create_cone(
        bm,
        cap_ends=cap,
        cap_tris=False,
        segments=segments,
        radius1=radius,
        radius2=radius if r2 is None else r2,
        depth=depth,
    )
    if bevel_w > 0:
        bevel(bm, bevel_w, 1, 40.0)
    rot = {
        "Z": Matrix.Identity(3),
        "Y": Matrix.Rotation(math.pi / 2, 3, "X"),
        "X": Matrix.Rotation(math.pi / 2, 3, "Y"),
    }[axis]
    bmesh.ops.rotate(bm, cent=Vector(), matrix=rot, verts=bm.verts)
    bmesh.ops.translate(bm, vec=Vector(center), verts=bm.verts)
    return _finish(bm)


def ellipsoid_point(rx, ry, rz_top, rz_bot, th, ph) -> Vector:
    """th: longitude from the front (-Y) towards +X; ph: latitude."""
    rz = rz_top if ph >= 0 else rz_bot
    return Vector(
        (rx * math.cos(ph) * math.sin(th), -ry * math.cos(ph) * math.cos(th), rz * math.sin(ph))
    )


def shell_panel(
    radii, th0, th1, ph0, ph1, nu, nv, center, thick=0.006, gap=0.004, bevel_w=0.0018
) -> bmesh.types.BMesh:
    """A bevelled shell panel on an ovoid between two longitudes and latitudes."""
    rx, ry, rzt, rzb = radii
    r_mean = (rx + rzt) * 0.5
    ga = gap / r_mean  # angular half-gap
    full = abs((th1 - th0) - TAU) < 1e-6
    t0, t1 = (th0, th1) if full else (th0 + ga, th1 - ga)
    p0 = ph0 + (ga if ph0 > -math.pi / 2 + 1e-6 else 0.0)
    p1 = ph1 - (ga if ph1 < math.pi / 2 - 1e-6 else 0.0)
    bm = bmesh.new()
    grid = []
    cols = nu if full else nu + 1
    for j in range(nv + 1):
        ph = p0 + (p1 - p0) * j / nv
        row = []
        for i in range(cols):
            th = t0 + (t1 - t0) * i / nu
            row.append(bm.verts.new(ellipsoid_point(rx, ry, rzt, rzb, th, ph)))
        grid.append(row)
    for j in range(nv):
        for i in range(nu):
            i1 = (i + 1) % cols if full else i + 1
            a, b, c, d = grid[j][i], grid[j][i1], grid[j + 1][i1], grid[j + 1][i]
            if a is b or c is d:
                continue
            bm.faces.new((a, b, c, d))
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-7)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    # make normals point outwards
    for f in bm.faces:
        if f.normal.dot(f.calc_center_median()) < 0:
            f.normal_flip()
    ret = bmesh.ops.solidify(bm, geom=bm.faces[:], thickness=thick)
    del ret
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bevel(bm, bevel_w, 1, 50.0)
    bmesh.ops.translate(bm, vec=Vector(center), verts=bm.verts)
    return _finish(bm)


def ovoid(radii, center, nu=24, nv=12) -> bmesh.types.BMesh:
    """Closed ovoid (dark core under the panels)."""
    rx, ry, rzt, rzb = radii
    bm = bmesh.new()
    top = bm.verts.new((0, 0, rzt))
    bot = bm.verts.new((0, 0, -rzb))
    rings = []
    for j in range(1, nv):
        ph = -math.pi / 2 + math.pi * j / nv
        rings.append(
            [bm.verts.new(ellipsoid_point(rx, ry, rzt, rzb, TAU * i / nu, ph)) for i in range(nu)]
        )
    for i in range(nu):
        i1 = (i + 1) % nu
        bm.faces.new((bot, rings[0][i1], rings[0][i]))
        bm.faces.new((top, rings[-1][i], rings[-1][i1]))
        for j in range(len(rings) - 1):
            bm.faces.new((rings[j][i], rings[j][i1], rings[j + 1][i1], rings[j + 1][i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bmesh.ops.translate(bm, vec=Vector(center), verts=bm.verts)
    return _finish(bm, 60.0)


def torus_band(r_in, r_out, height, center, segments=48, bevel_w=None) -> bmesh.types.BMesh:
    """Flat band ring (rectangular section, chamfered) around Z."""
    bm = bmesh.new()
    prof = [(r_in, -height / 2), (r_out, -height / 2), (r_out, height / 2), (r_in, height / 2)]
    rings = []
    for i in range(segments):
        a = TAU * i / segments
        ca, sa = math.cos(a), math.sin(a)
        rings.append([bm.verts.new((r * sa, -r * ca, z)) for r, z in prof])
    for i in range(segments):
        i1 = (i + 1) % segments
        for k in range(4):
            k1 = (k + 1) % 4
            bm.faces.new((rings[i][k], rings[i1][k], rings[i1][k1], rings[i][k1]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    for f in bm.faces:
        c = f.calc_center_median()
        radial = Vector((c.x, c.y, 0.0))
        if (
            abs(f.normal.z) < 0.5
            and f.normal.dot(radial) < 0
            and radial.length > (r_in + r_out) / 2
        ):
            f.normal_flip()
    bw = min(0.0025, height * 0.15) if bevel_w is None else bevel_w
    if bw > 0:
        bevel(bm, bw, 1, 40.0)
    bmesh.ops.translate(bm, vec=Vector(center), verts=bm.verts)
    return _finish(bm, 40.0)


# -------------------------------------------------------------------------- rigs


def build_rig(name: str, bones: list[tuple[str, tuple, tuple, str | None]]):
    arm = bpy.data.armatures.new(name)
    ob = bpy.data.objects.new(name, arm)
    C.link(ob)
    C.set_active(ob)
    bpy.ops.object.mode_set(mode="EDIT")
    for bn, head, tail, parent in bones:
        b = arm.edit_bones.new(bn)
        b.head, b.tail = Vector(head), Vector(tail)
        b.roll = 0.0
        if parent:
            b.parent = arm.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    return ob


def assemble(name: str, parts: list[Part], rig_ob):
    """Join parts into one mesh, rigidly skinned; returns the mesh object."""
    bm = bmesh.new()
    mats: list[str] = []
    face_mat: list[int] = []
    vert_bone: list[str] = []
    for p in parts:
        if p.material not in mats:
            mats.append(p.material)
        mi = mats.index(p.material)
        vmap = {}
        for v in p.bm.verts:
            nv = bm.verts.new(v.co)
            vmap[v] = nv
            vert_bone.append(p.bone)
        bm.verts.ensure_lookup_table()
        for f in p.bm.faces:
            nf = bm.faces.new([vmap[v] for v in f.verts])
            nf.smooth = f.smooth
            face_mat.append(mi)
            nf.material_index = mi
        bm.edges.ensure_lookup_table()
        for e in p.bm.edges:
            if not e.smooth:
                ne = bm.edges.get((vmap[e.verts[0]], vmap[e.verts[1]]))
                if ne:
                    ne.smooth = False
        p.bm.free()
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    C.link(ob)
    for m in mats:
        me.materials.append(make_material(m))
    groups = {}
    for i, bn in enumerate(vert_bone):
        g = groups.get(bn) or ob.vertex_groups.new(name=bn)
        groups[bn] = g
        g.add([i], 1.0, "REPLACE")
    ob.parent = rig_ob
    mod = ob.modifiers.new("Armature", "ARMATURE")
    mod.object = rig_ob
    return ob


def bake_ao(ob, samples: int = 48, dist: float = 0.25):
    """Per-vertex ambient occlusion into COLOR_0 (deterministic hemisphere rays)."""
    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bvh = BVHTree.FromBMesh(bm)
    bm.free()
    dirs = []
    golden = math.pi * (3.0 - math.sqrt(5.0))
    for i in range(samples):
        z = 1.0 - (i + 0.5) / samples  # upper hemisphere, cosine-ish spread
        r = math.sqrt(max(0.0, 1.0 - z * z))
        a = golden * i
        dirs.append(Vector((r * math.cos(a), r * math.sin(a), z)))
    me.calc_loop_triangles()
    vn = [v.normal.copy() for v in me.vertices]
    ao = []
    for v in me.vertices:
        n = vn[v.index]
        if n.length < 1e-6:
            ao.append(1.0)
            continue
        q = n.to_track_quat("Z", "Y")
        hit = 0.0
        tot = 0.0
        origin = v.co + n * 0.0015
        for d in dirs:
            w = d.z
            dd = q @ d
            loc, _, _, _ = bvh.ray_cast(origin, dd, dist)
            tot += w
            if loc is not None:
                hit += w * (1.0 - (loc - origin).length / dist) ** 0.5
        ao.append(1.0 - 0.85 * hit / tot)
    glow = {i for i, m in enumerate(me.materials) if m.name in ("M_Glow", "M_Lens")}
    attr = me.color_attributes.new("Col", "FLOAT_COLOR", "CORNER")
    for poly in me.polygons:
        for li in poly.loop_indices:
            vi = me.loops[li].vertex_index
            a = 1.0 if poly.material_index in glow else ao[vi]
            attr.data[li].color = (a, a, a, 1.0)
    me.color_attributes.active_color = attr
    me.color_attributes.render_color_index = 0


# --------------------------------------------------------------------- animation


def _write_action(rig_ob, name: str, frames: list[dict[str, Matrix]]):
    """Bake per-frame armature-space bone matrices into a slotted action."""
    rest = {b.name: b.matrix_local.copy() for b in rig_ob.data.bones}
    parent = {b.name: (b.parent.name if b.parent else None) for b in rig_ob.data.bones}
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    rig_ob.animation_data_create()
    slot = act.slots.new(id_type="OBJECT", name=rig_ob.name)
    strip = act.layers.new("Layer").strips.new(type="KEYFRAME")
    bag = strip.channelbag(slot, ensure=True)
    for bn in rest:
        prev = None
        quats, locs = [], []
        for M in frames:
            m = M.get(bn)
            if m is None:
                m = _rest_pose(bn, M, rest, parent)
                M[bn] = m
            p = parent[bn]
            if p is None:
                basis = rest[bn].inverted() @ m
            else:
                basis = (rest[p].inverted() @ rest[bn]).inverted() @ M[p].inverted() @ m
            loc, q, _ = basis.decompose()
            if prev is not None and q.dot(prev) < 0:
                q = Quaternion((-q.w, -q.x, -q.y, -q.z))
            prev = q
            quats.append(q)
            locs.append(loc)
        grp = bag.groups.new(bn)
        for i in range(4):
            fc = bag.fcurves.new(f'pose.bones["{bn}"].rotation_quaternion', index=i)
            fc.group = grp
            _fill(fc, [q[i] for q in quats])
        for i in range(3):
            fc = bag.fcurves.new(f'pose.bones["{bn}"].location', index=i)
            fc.group = grp
            _fill(fc, [lv[i] for lv in locs])
    for pb in rig_ob.pose.bones:
        pb.rotation_mode = "QUATERNION"
    return act, slot


def _rest_pose(bn, M, rest, parent):
    p = parent[bn]
    if p is None:
        return rest[bn].copy()
    if p not in M:
        M[p] = _rest_pose(p, M, rest, parent)
    return M[p] @ (rest[p].inverted() @ rest[bn])


def _fill(fc, values):
    fc.keyframe_points.add(len(values))
    co = []
    for f, v in enumerate(values):
        co += [float(f), float(v)]
    fc.keyframe_points.foreach_set("co", co)
    for kp in fc.keyframe_points:
        kp.interpolation = "LINEAR"
    fc.update()


def _stash(rig_ob, actions):
    ad = rig_ob.animation_data or rig_ob.animation_data_create()
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


def harm(t, period, terms):
    return sum(a * math.sin(TAU * k * t / period + ph) for k, a, ph in terms)


def _frames(seconds):
    return int(round(seconds * C.FPS)) + 1


def _rot(yaw=0.0, pitch=0.0, roll=0.0) -> Matrix:
    """World rotation: yaw about Z (left > 0), pitch about X (nose down/forward > 0),
    roll about Y (lean left > 0); degrees."""
    return (
        Matrix.Rotation(math.radians(yaw), 4, "Z")
        @ Matrix.Rotation(math.radians(pitch), 4, "X")
        @ Matrix.Rotation(math.radians(roll), 4, "Y")
    )


def _posed(rest_m: Matrix, pivot: Vector, rot: Matrix) -> Matrix:
    """Rotate a bone's rest matrix about `pivot`."""
    return Matrix.Translation(pivot) @ rot @ Matrix.Translation(-pivot) @ rest_m


# ---------------------------------------------------------------- companion drone

COMP_HOVER = 0.85
COMP_RADII = (0.148, 0.148, 0.168, 0.152)  # rx, ry, rz top, rz bottom
RING_Z = -0.028  # ring centre relative to the body centre


def companion_parts() -> list[Part]:
    c = Vector((0, 0, COMP_HOVER))
    rx, ry, rzt, rzb = COMP_RADII
    parts: list[Part] = []
    core = (rx - 0.012, ry - 0.012, rzt - 0.012, rzb - 0.012)
    parts.append(Part(ovoid(core, c, 16, 8), "M_Trim", "Body"))
    d = math.radians
    # Upper band: four panels; the front one carries the lens.
    for k in range(4):
        th0 = d(-45 + 90 * k)
        parts.append(
            Part(shell_panel(COMP_RADII, th0, th0 + d(90), d(6), d(56), 4, 4, c), "M_Shell", "Body")
        )
    parts.append(Part(shell_panel(COMP_RADII, 0.0, TAU, d(56), d(90), 14, 2, c), "M_Shell", "Body"))
    # Lower band and bottom cap.
    for k in range(4):
        th0 = d(45 * (2 * k + 1) - 45 + 45)
        parts.append(
            Part(
                shell_panel(COMP_RADII, th0, th0 + d(90), d(-58), d(-16), 4, 3, c),
                "M_Shell",
                "Body",
            )
        )
    parts.append(
        Part(shell_panel(COMP_RADII, 0.0, TAU, d(-90), d(-58), 12, 1, c), "M_Shell", "Body")
    )
    # Hover emitter under the body.
    parts.append(
        Part(cylinder(0.034, 0.01, c + Vector((0, 0, -rzb - 0.002)), segments=14), "M_Trim", "Body")
    )
    parts.append(
        Part(
            cylinder(0.022, 0.004, c + Vector((0, 0, -rzb - 0.008)), segments=14), "M_Glow", "Body"
        )
    )
    # Equatorial ring with three pods (they make the spin readable).
    rc = c + Vector((0, 0, RING_Z))
    r_body = rx * math.cos(math.asin(min(1.0, abs(RING_Z) / rzb)))
    parts.append(Part(torus_band(r_body + 0.006, r_body + 0.022, 0.03, rc, 32), "M_Ring", "Ring"))
    for k in range(3):
        a = TAU * k / 3 + math.radians(60)
        pos = rc + Vector((math.sin(a) * (r_body + 0.026), -math.cos(a) * (r_body + 0.026), 0))
        pod = rounded_box((0.026, 0.016, 0.036), (0, 0, 0), 0.004, 1)
        bmesh.ops.rotate(pod, cent=Vector(), matrix=Matrix.Rotation(a, 3, "Z"), verts=pod.verts)
        bmesh.ops.translate(pod, vec=pos, verts=pod.verts)
        parts.append(Part(pod, "M_Ring", "Ring"))
        lamp = cylinder(0.0045, 0.004, (0, 0, 0), axis="Y", segments=8)
        bmesh.ops.rotate(lamp, cent=Vector(), matrix=Matrix.Rotation(a, 3, "Z"), verts=lamp.verts)
        out = Vector((math.sin(a), -math.cos(a), 0)) * 0.009
        bmesh.ops.translate(lamp, vec=pos + out, verts=lamp.verts)
        parts.append(Part(lamp, "M_Glow", "Ring"))
    # Lens: housing, glass, iris ring, on the Eye bone.
    lens_dir = Vector((0, -math.cos(d(20)), math.sin(d(20))))
    surf = c + Vector(ellipsoid_point(rx, ry, rzt, rzb, 0.0, d(20)))
    rot = lens_dir.to_track_quat("Z", "Y").to_matrix()

    def placed(bm, depth):
        bmesh.ops.rotate(bm, cent=Vector(), matrix=rot, verts=bm.verts)
        bmesh.ops.translate(bm, vec=surf + lens_dir * depth, verts=bm.verts)
        return bm

    housing = bmesh.new()
    bmesh.ops.create_cone(
        housing, cap_ends=True, segments=20, radius1=0.064, radius2=0.056, depth=0.024
    )
    bevel(housing, 0.003, 1, 30.0)
    parts.append(Part(_finish(placed(housing, 0.002)), "M_Trim", "Eye"))
    bezel = torus_band(0.040, 0.052, 0.008, (0, 0, 0), 20)
    parts.append(Part(_finish(placed(bezel, 0.016)), "M_Ring", "Eye"))
    glass = bmesh.new()
    bmesh.ops.create_uvsphere(glass, u_segments=16, v_segments=6, radius=0.042)
    for v in glass.verts:
        v.co.z = max(v.co.z, 0.0) * 0.45
    bmesh.ops.remove_doubles(glass, verts=glass.verts, dist=1e-5)
    parts.append(Part(_finish(placed(glass, 0.011), 70.0), "M_Lens", "Eye"))
    iris = torus_band(0.012, 0.020, 0.002, (0, 0, 0), 16, bevel_w=0.0)
    parts.append(Part(_finish(placed(iris, 0.031)), "M_Glow", "Eye"))
    # Status light on top in a bezel, and two antenna stubs.
    top = c + Vector((0, 0, rzt))
    parts.append(
        Part(
            cylinder(0.022, 0.012, top + Vector((0, 0, 0.001)), segments=14, bevel_w=0.002),
            "M_Trim",
            "Body",
        )
    )
    dome = bmesh.new()
    bmesh.ops.create_uvsphere(dome, u_segments=12, v_segments=4, radius=0.014)
    for v in dome.verts:
        v.co.z = max(v.co.z, 0.0) * 0.7
    bmesh.ops.remove_doubles(dome, verts=dome.verts, dist=1e-5)
    bmesh.ops.translate(dome, vec=top + Vector((0, 0, 0.007)), verts=dome.verts)
    parts.append(Part(_finish(dome, 70.0), "M_Glow", "Body"))
    for sx in (1.0, -1.0):
        th, ph = d(90) * sx, d(52)
        base = c + Vector(ellipsoid_point(rx, ry, rzt, rzb, th, ph))
        n = Vector((base.x - c.x, base.y - c.y, (base.z - c.z) * 1.4)).normalized()
        n = (n + Vector((0, 0.35, 0.6))).normalized()
        rotm = n.to_track_quat("Z", "Y").to_matrix()
        stem = cylinder(0.0035, 0.07, (0, 0, 0.03), segments=8)
        cap = cylinder(0.008, 0.008, (0, 0, 0.0), segments=12, bevel_w=0.0015)
        tip = cylinder(0.006, 0.01, (0, 0, 0.066), segments=10, bevel_w=0.002)
        for bm_, mat in ((stem, "M_Ring"), (cap, "M_Trim"), (tip, "M_Ring")):
            bmesh.ops.rotate(bm_, cent=Vector(), matrix=rotm, verts=bm_.verts)
            bmesh.ops.translate(bm_, vec=base, verts=bm_.verts)
            parts.append(Part(bm_, mat, "Body"))
    return parts


def companion_rig():
    c = (0, 0, COMP_HOVER)
    return build_rig(
        "SK_Drone_Companion",
        [
            ("Root", (0, 0, 0), (0, 0, 0.12), None),
            ("Body", c, (0, 0, COMP_HOVER + 0.12), "Root"),
            ("Ring", (0, 0, COMP_HOVER + RING_Z), (0, 0, COMP_HOVER + RING_Z + 0.08), "Body"),
            ("Eye", c, (0, -0.12, COMP_HOVER + 0.04), "Body"),
        ],
    )


def companion_clips(rig_ob):
    rest = {b.name: b.matrix_local.copy() for b in rig_ob.data.bones}
    c = Vector((0, 0, COMP_HOVER))
    rc = Vector((0, 0, COMP_HOVER + RING_Z))

    def pose(t_body: Matrix, ring_spin: float, eye: Matrix) -> dict:
        body = t_body @ rest["Body"]
        ring = t_body @ _posed(rest["Ring"], rc, Matrix.Rotation(ring_spin, 4, "Z"))
        eye_m = t_body @ _posed(rest["Eye"], c, eye)
        return {"Root": rest["Root"].copy(), "Body": body, "Ring": ring, "Eye": eye_m}

    def body_t(z=0.0, yaw=0.0, pitch=0.0, roll=0.0, x=0.0, y=0.0) -> Matrix:
        return (
            Matrix.Translation(c + Vector((x, y, z)))
            @ _rot(yaw, pitch, roll)
            @ Matrix.Translation(-c)
        )

    clips = {}
    T = 4.0
    fr = []
    for f in range(_frames(T)):
        t = f / C.FPS
        z = harm(t, T, [(1, 0.022, 0.0), (3, 0.004, 0.6)])
        bt = body_t(
            z,
            yaw=harm(t, T, [(1, 4.0, 1.0)]),
            pitch=harm(t, T, [(1, 2.0, 2.2)]),
            roll=harm(t, T, [(2, 2.5, 0.4)]),
            x=harm(t, T, [(1, 0.008, 1.7)]),
        )
        eye = _rot(harm(t, T, [(1, 6.0, 0.3), (2, 3.0, 1.1)]), harm(t, T, [(2, 2.0, 0.0)]))
        fr.append(pose(bt, -TAU * t / T, eye))
    clips["A_Hover"] = (fr, True, T)
    T = 2.0
    fr = []
    for f in range(_frames(T)):
        t = f / C.FPS
        z = harm(t, T, [(2, 0.014, 0.0)])
        bt = body_t(z, pitch=10.0 + harm(t, T, [(2, 1.5, 0.8)]), roll=harm(t, T, [(1, 3.0, 0.0)]))
        fr.append(pose(bt, -TAU * 2 * t / T, _rot(0.0, -6.0)))
    clips["A_Follow"] = (fr, True, T)
    T = 4.0
    fr = []
    for f in range(_frames(T)):
        t = f / C.FPS
        yaw = harm(t, T, [(1, 28.0, 0.0), (2, 6.0, 0.5)])
        bt = body_t(harm(t, T, [(2, 0.008, 0.3)]), yaw=yaw * 0.6, roll=harm(t, T, [(1, 3.0, 1.0)]))
        eye = _rot(yaw * 0.6 + harm(t, T, [(3, 4.0, 0.2)]), harm(t, T, [(2, 5.0, 1.3)]))
        fr.append(pose(bt, -TAU * t / T, eye))
    clips["A_Scan"] = (fr, True, T)
    T = 1.5
    fr = []
    for f in range(_frames(T)):
        t = f / C.FPS
        hop = 0.0
        if t < 0.55:
            hop = 0.09 * math.sin(math.pi * t / 0.55)
        elif t < 0.9:
            hop = -0.015 * math.sin(math.pi * (t - 0.55) / 0.35)
        decay = math.exp(-2.2 * t) * (1.0 - min(1.0, max(0.0, (t - 1.25) / 0.25)))
        wig = 12.0 * math.sin(TAU * 3.0 * t) * decay
        spin = TAU * (1.0 - (1.0 - min(1.0, t / 1.1)) ** 3)
        bt = body_t(hop, roll=wig, pitch=-6.0 * math.sin(math.pi * min(1.0, t / 0.55)))
        fr.append(pose(bt, -spin, _rot(0.0, -8.0 * math.sin(math.pi * min(1.0, t / 0.6)))))
    clips["A_Happy"] = (fr, False, T)
    return clips


# ------------------------------------------------------------------ utility drone

UT_L, UT_W = 0.50, 0.26


def chamfered_block(w, length, h, center, corner=0.03, edge=0.006, taper=0.0):
    """Box with chamfered vertical corners and bevelled edges; top shrunk by `taper`."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector((w, length, h)), verts=bm.verts)
    vert_edges = [e for e in bm.edges if abs((e.verts[0].co - e.verts[1].co).normalized().z) > 0.99]
    bmesh.ops.bevel(
        bm,
        geom=vert_edges,
        offset=corner,
        offset_type="OFFSET",
        segments=1,
        profile=0.5,
        affect="EDGES",
        clamp_overlap=True,
    )
    if taper:
        for v in bm.verts:
            if v.co.z > 0:
                v.co.x -= math.copysign(taper, v.co.x)
                v.co.y -= math.copysign(taper, v.co.y)
    bevel(bm, edge, 1, 25.0)
    bmesh.ops.translate(bm, vec=Vector(center), verts=bm.verts)
    return _finish(bm, 30.0)


HEAD_Y, HEAD_Z = -0.150, 0.172


def utility_parts() -> list[Part]:
    parts: list[Part] = []
    L, W = UT_L, UT_W
    # Skirt (hides the wheels) and the main hull: lower tub plus a tapered deck.
    parts.append(
        Part(
            chamfered_block(W - 0.025, L - 0.035, 0.05, (0, 0.0, 0.036), 0.04, 0.008),
            "M_Trim",
            "Body",
        )
    )
    parts.append(
        Part(
            chamfered_block(W, L - 0.05, 0.072, (0, 0.012, 0.096), 0.045, 0.01), "M_Chassis", "Body"
        )
    )
    parts.append(
        Part(
            chamfered_block(W - 0.03, L - 0.09, 0.046, (0, 0.03, 0.155), 0.04, 0.006, taper=0.012),
            "M_Chassis",
            "Body",
        )
    )
    # Deck: two armour plates either side of a dark service strip with slats.
    parts.append(
        Part(rounded_box((W - 0.09, L - 0.16, 0.006), (0, 0.04, 0.179), 0.002), "M_Trim", "Body")
    )
    for y0, y1 in ((-0.135, -0.03), (0.085, 0.205)):
        parts.append(
            Part(
                chamfered_block(W - 0.10, y1 - y0, 0.012, (0, (y0 + y1) / 2, 0.184), 0.012, 0.003),
                "M_Chassis",
                "Body",
            )
        )
    for k in range(4):
        parts.append(
            Part(
                rounded_box((W - 0.13, 0.010, 0.006), (0, -0.012 + 0.026 * k, 0.181), 0.002),
                "M_Ring",
                "Body",
            )
        )
    for sx in (1.0, -1.0):
        for sy in (-0.12, 0.19):
            parts.append(
                Part(cylinder(0.006, 0.004, (sx * 0.058, sy, 0.191), segments=6), "M_Ring", "Body")
            )
    # Flanks: vents and a rub strip.
    for sx in (1.0, -1.0):
        for k in range(5):
            y = 0.035 + 0.03 * k
            parts.append(
                Part(
                    rounded_box((0.006, 0.018, 0.032), (sx * (W / 2 + 0.001), y, 0.10), 0.0015),
                    "M_Trim",
                    "Body",
                )
            )
        parts.append(
            Part(
                rounded_box((0.012, L - 0.14, 0.014), (sx * (W / 2 + 0.004), 0.012, 0.064), 0.004),
                "M_Trim",
                "Body",
            )
        )
    # Rear: bumper, handle bar, tail lamp.
    parts.append(
        Part(
            rounded_box((W - 0.07, 0.022, 0.03), (0, L / 2 - 0.018, 0.066), 0.006), "M_Trim", "Body"
        )
    )
    for sx in (1.0, -1.0):
        parts.append(
            Part(
                rounded_box((0.012, 0.012, 0.03), (sx * 0.06, 0.215, 0.193), 0.003),
                "M_Ring",
                "Body",
            )
        )
    parts.append(
        Part(rounded_box((0.132, 0.014, 0.012), (0, 0.215, 0.212), 0.004), "M_Ring", "Body")
    )
    parts.append(
        Part(rounded_box((0.07, 0.004, 0.008), (0, L / 2 - 0.006, 0.12), 0.0015), "M_Glow", "Body")
    )
    # Front bumper.
    parts.append(
        Part(
            rounded_box((W - 0.08, 0.02, 0.026), (0, -L / 2 + 0.014, 0.062), 0.006),
            "M_Trim",
            "Body",
        )
    )
    # Sensor head: a short drum with a dark visor band and a glowing slit.
    hy, hz = HEAD_Y, HEAD_Z
    parts.append(
        Part(
            cylinder(0.072, 0.05, (0, hy, hz), segments=20, r2=0.064, bevel_w=0.006),
            "M_Chassis",
            "Head",
        )
    )
    parts.append(
        Part(
            cylinder(0.055, 0.008, (0, hy, hz + 0.027), segments=20, bevel_w=0.002),
            "M_Trim",
            "Head",
        )
    )
    visor = bmesh.new()
    seg = 12
    ring_lo, ring_hi = [], []
    for i in range(seg + 1):
        a = math.radians(-70 + 140 * i / seg)
        for z, ring in ((hz - 0.012, ring_lo), (hz + 0.014, ring_hi)):
            r = 0.0735 if z < hz else 0.0705
            ring.append(visor.verts.new((r * math.sin(a), hy - r * math.cos(a), z)))
    for i in range(seg):
        visor.faces.new((ring_lo[i], ring_lo[i + 1], ring_hi[i + 1], ring_hi[i]))
    sol = bmesh.ops.solidify(visor, geom=visor.faces[:], thickness=0.004)
    del sol
    parts.append(Part(_finish(visor), "M_Trim", "Head"))
    slit = bmesh.new()
    lo, hi = [], []
    for i in range(seg + 1):
        a = math.radians(-46 + 92 * i / seg)
        r = 0.0782
        lo.append(slit.verts.new((r * math.sin(a), hy - r * math.cos(a), hz - 0.0015)))
        hi.append(slit.verts.new((r * math.sin(a), hy - r * math.cos(a), hz + 0.0045)))
    for i in range(seg):
        slit.faces.new((lo[i], lo[i + 1], hi[i + 1], hi[i]))
    parts.append(Part(_finish(slit), "M_Glow", "Head"))
    parts.append(
        Part(cylinder(0.003, 0.05, (0.04, hy + 0.03, hz + 0.05), segments=6), "M_Ring", "Head")
    )
    parts.append(
        Part(cylinder(0.005, 0.006, (0.04, hy + 0.03, hz + 0.077), segments=8), "M_Glow", "Head")
    )
    return parts


def utility_rig():
    return build_rig(
        "SK_Drone_Utility",
        [
            ("Root", (0, 0, 0), (0, 0, 0.08), None),
            ("Body", (0, 0, 0.10), (0, 0, 0.18), "Root"),
            ("Head", (0, HEAD_Y, 0.15), (0, HEAD_Y, 0.23), "Body"),
        ],
    )


def utility_clips(rig_ob):
    rest = {b.name: b.matrix_local.copy() for b in rig_ob.data.bones}
    piv = Vector((0, 0, 0.0))
    hpiv = Vector((0, HEAD_Y, 0.15))

    def pose(z, pitch, roll, head_yaw, head_pitch):
        bt = Matrix.Translation(Vector((0, 0, z))) @ _posed(
            Matrix.Identity(4), piv, _rot(0.0, pitch, roll)
        )
        return {
            "Root": rest["Root"].copy(),
            "Body": bt @ rest["Body"],
            "Head": bt @ _posed(rest["Head"], hpiv, _rot(head_yaw, head_pitch)),
        }

    clips = {}
    T = 1.0
    fr = []
    for f in range(_frames(T)):
        t = f / C.FPS
        z = harm(t, T, [(4, 0.0016, 0.0), (7, 0.0008, 1.3), (11, 0.0005, 0.4)])
        fr.append(
            pose(
                z,
                harm(t, T, [(3, 0.5, 0.2), (5, 0.3, 1.0)]) - 1.0,
                harm(t, T, [(2, 0.6, 0.7)]),
                harm(t, T, [(1, 3.0, 0.0)]),
                harm(t, T, [(6, 0.8, 0.5)]),
            )
        )
    clips["A_Drive"] = (fr, True, T)
    T = 4.0
    fr = []
    for f in range(_frames(T)):
        t = f / C.FPS
        fr.append(
            pose(
                harm(t, T, [(1, 0.0015, 0.0)]),
                harm(t, T, [(1, 0.4, 0.7)]),
                0.0,
                harm(t, T, [(1, 35.0, 0.0), (2, 10.0, 0.8)]),
                harm(t, T, [(2, 6.0, 0.4), (3, 3.0, 1.1)]),
            )
        )
    clips["A_Idle"] = (fr, True, T)
    return clips


# ------------------------------------------------------------------------ export


def _export(rig_ob, mesh_ob, path: Path):
    for o in bpy.context.scene.objects:
        o.select_set(False)
    rig_ob.select_set(True)
    mesh_ob.select_set(True)
    bpy.context.view_layer.objects.active = rig_ob
    C.ensure_dir(path.parent)
    bpy.ops.export_scene.gltf(
        filepath=str(path),
        export_format="GLB",
        use_selection=True,
        export_yup=True,
        export_apply=False,
        export_animations=True,
        export_animation_mode="ACTIONS",
        export_force_sampling=True,
        export_optimize_animation_size=True,
        export_def_bones=False,
        export_skins=True,
        export_materials="EXPORT",
        export_vertex_color="ACTIVE",
        export_cameras=False,
        export_lights=False,
        export_image_format="WEBP",
        export_image_quality=90,
        export_extras=False,
        export_frame_range=False,
        export_anim_slide_to_zero=True,
    )


# Atlas size of the drones (they are small: ~600 texels per metre at 512 px).
ATLAS = 512


def _build_one(name, parts, rig_ob, clips, out_dir: Path, painter=None) -> dict:
    mesh_ob = assemble(f"{name}_Mesh", parts, rig_ob)
    bake_ao(mesh_ob)
    if painter is not None:
        PT.texture(name, [mesh_ob], painter, res=ATLAS, debug_dir=C.CACHE / "atlas")
    actions = [_write_action(rig_ob, cn, fr) for cn, (fr, _loop, _t) in clips.items()]
    _stash(rig_ob, actions)
    path = out_dir / f"{name}.glb"
    with PT.export_names(name):
        _export(rig_ob, mesh_ob, path)
    rig_ob.animation_data_clear()
    for act, _slot in actions:
        bpy.data.actions.remove(act)
    zs = [v.co.z for v in mesh_ob.data.vertices]
    return {
        "id": name,
        "url": f"verse/characters/{name}.glb",
        "kind": "drone",
        "materials": [m.name.split("@")[0] for m in mesh_ob.data.materials],
        "clips": {
            cn: {"loop": loop, "seconds": round(t, 3)} for cn, (_fr, loop, t) in clips.items()
        },
        "bones": [b.name for b in rig_ob.data.bones],
        "height": round(max(zs), 3),
        "triangles": C.tri_count(mesh_ob),
        "bytes": path.stat().st_size,
    }


def build_drones(out_dir: Path) -> dict:
    out: dict = {}
    rig = companion_rig()
    entry = _build_one(
        "SK_Drone_Companion",
        companion_parts(),
        rig,
        companion_clips(rig),
        out_dir,
        LG.companion((0.0, 0.0, COMP_HOVER), COMP_RADII),
    )
    entry["hoverHeight"] = COMP_HOVER
    entry["bodyDiameter"] = round(2 * COMP_RADII[0], 3)
    out[entry["id"]] = entry
    rig = utility_rig()
    entry = _build_one(
        "SK_Drone_Utility", utility_parts(), rig, utility_clips(rig), out_dir, LG.utility()
    )
    entry["driveSpeed"] = 1.2
    entry["length"] = UT_L
    out[entry["id"]] = entry
    return out


def write_manifest(entries: dict, path: Path) -> None:
    C.ensure_dir(path.parent)
    path.write_text(json.dumps(entries, indent=2), encoding="utf-8")
