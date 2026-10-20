"""Texture atlases for the crew, painted in 3D.

Every character gets one UV atlas shared by all its meshes (Body, Cap, RankPlate)
and two images: a base colour map and a tangent-space normal map. Nothing is
hand-painted: the atlas is rasterised in numpy, every texel is mapped back to its
point on the rest-pose surface, and `looks.py` decides colour and relief there
from the measured anatomy (eyes, mouth, joints) and the garment pieces.

- Base colour is a *multiplier* on the material's own colour (white = the colour
  the runtime sets). Tinted slots (uniform, trousers, trim, cap, accent) stay
  neutral grey, so a rank tier still sets the colour by material name.
- The normal map carries two things: the full-resolution garment surface (the
  undecimated body with its nose, lips, ears, fingers and cloth folds), baked onto
  the game mesh, plus procedural relief (seams, welts, stitching, armour panel
  lines, hair strands).
- The tangent frame is the one three.js builds from screen derivatives when a
  mesh has no tangents (`getTangentFrame`): the surface gradients of u and v.
  The glTF exporter flips v and GLTFLoader flips the normal scale's y for that
  frame, so the map is written in Blender's UV orientation (OpenGL convention).

Deterministic: no random numbers; noise is a fixed hash of the position.
"""

from __future__ import annotations

import math

import bmesh
import bpy
import numpy as np
from bpy_extras import bmesh_utils
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from characters import common as C

RES = 1024
# Materials that stay flat colour (the runtime drives them as solid colour / emission).
UNTEXTURED = {"M_Glow", "M_Lens"} | {f"M_RankTile_{i}" for i in range(1, 7)}


def srgb_encode(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)


# ------------------------------------------------------------------------ UV atlas


def _ensure_uv(ob):
    me = ob.data
    if not me.uv_layers:
        me.uv_layers.new(name="UVMap")
    for i, layer in enumerate(me.uv_layers):
        if i:
            layer.name = f"UV_{i}"
    me.uv_layers.active_index = 0
    me.uv_layers[0].name = "UVMap"
    while len(me.uv_layers) > 1:
        me.uv_layers.remove(me.uv_layers[1])


def unwrap(objs, weight, margin=0.003, angle=66.0):
    """Smart-project every mesh, scale islands by `weight(ob, face)` (texel density
    factor), then pack all of them into one square atlas."""
    for o in objs:
        _ensure_uv(o)
    ensure_object_mode()
    for o in bpy.context.scene.objects:
        o.select_set(False)
    for o in objs:
        o.hide_set(False)
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(
        angle_limit=math.radians(angle),
        margin_method="SCALED",
        island_margin=0.0,
        area_weight=0.0,
        correct_aspect=True,
        scale_to_bounds=False,
    )
    bpy.ops.object.mode_set(mode="OBJECT")
    # texel density per island (3D area is what smart_project preserves)
    for o in objs:
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bm.faces.ensure_lookup_table()
        uv = bm.loops.layers.uv.active
        lay = bm.faces.layers.int.get("part")
        names = list(o.get("parts", [o.name.split(":")[-1]]))

        def part_of(f, lay=lay, names=names):
            return names[f[lay]] if lay is not None and f[lay] < len(names) else names[0]

        for island in bmesh_utils.bmesh_linked_uv_islands(bm, uv):
            area = sum(f.calc_area() for f in island) or 1.0
            w = sum(weight(o, f, part_of(f)) * f.calc_area() for f in island) / area
            if abs(w - 1.0) < 1e-3:
                continue
            pts = [lp[uv].uv.copy() for f in island for lp in f.loops]
            c = sum(pts, Vector((0.0, 0.0))) / len(pts)
            for f in island:
                for lp in f.loops:
                    lp[uv].uv = c + (lp[uv].uv - c) * w
        bm.to_mesh(o.data)
        bm.free()
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.select_all(action="SELECT")
    bpy.ops.uv.pack_islands(
        rotate=True,
        rotate_method="ANY",
        scale=True,
        margin_method="FRACTION",
        margin=margin,
        shape_method="CONCAVE",
    )
    bpy.ops.object.mode_set(mode="OBJECT")


# ---------------------------------------------------------------------- sampling


class Mesh:
    """Triangles of all meshes of a character, with per-corner data."""

    def __init__(self, objs):
        P, N, UV, mat, part, obj = [], [], [], [], [], []
        self.mat_names: list[str] = []
        self.mat_rough: dict[str, float] = {}
        self.part_names: list[str] = []
        for oi, o in enumerate(objs):
            me = o.data
            me.calc_loop_triangles()
            nt = len(me.loop_triangles)
            loops = np.empty(nt * 3, np.int64)
            me.loop_triangles.foreach_get("loops", loops)
            polys = np.empty(nt, np.int64)
            me.loop_triangles.foreach_get("polygon_index", polys)
            mi = np.empty(nt, np.int64)
            me.loop_triangles.foreach_get("material_index", mi)
            vidx = np.empty(len(me.loops), np.int64)
            me.loops.foreach_get("vertex_index", vidx)
            co = np.empty(len(me.vertices) * 3)
            me.vertices.foreach_get("co", co)
            co = co.reshape(-1, 3)
            cn = np.empty(len(me.loops) * 3)
            me.corner_normals.foreach_get("vector", cn)
            cn = cn.reshape(-1, 3)
            uv = np.empty(len(me.loops) * 2)
            me.uv_layers.active.data.foreach_get("uv", uv)
            uv = uv.reshape(-1, 2)
            names = [m.name.split("@")[0] if m else "" for m in me.materials]
            for m in me.materials:
                if m is not None and m.node_tree:
                    bsdf = m.node_tree.nodes.get("Principled BSDF")
                    r = bsdf.inputs["Roughness"].default_value if bsdf else 0.5
                    self.mat_rough.setdefault(m.name.split("@")[0], float(r))
            gm = []
            for n in names:
                if n not in self.mat_names:
                    self.mat_names.append(n)
                gm.append(self.mat_names.index(n))
            gm = np.array(gm or [0])
            if "part" in me.attributes:
                pa = np.empty(len(me.polygons), np.int64)
                me.attributes["part"].data.foreach_get("value", pa)
                pnames = list(o["parts"])
            else:
                pa = np.zeros(len(me.polygons), np.int64)
                pnames = [o.name.split(":")[-1]]
            gp = []
            for n in pnames:
                if n not in self.part_names:
                    self.part_names.append(n)
                gp.append(self.part_names.index(n))
            gp = np.array(gp)
            L = loops.reshape(-1, 3)
            P.append(co[vidx[L]])
            N.append(cn[L])
            UV.append(uv[L])
            mat.append(gm[np.clip(mi, 0, len(gm) - 1)])
            part.append(gp[pa[polys]])
            obj.append(np.full(nt, oi))
        self.P = np.concatenate(P)  # (T, 3, 3)
        self.N = np.concatenate(N)
        self.UV = np.concatenate(UV)
        self.mat = np.concatenate(mat)
        self.part = np.concatenate(part)
        self.obj = np.concatenate(obj)
        self._gradients()

    def _gradients(self):
        """Surface gradients of u and v per triangle (three's derivative frame)."""
        P, UV = self.P, self.UV
        e1, e2 = P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]
        d1, d2 = UV[:, 1] - UV[:, 0], UV[:, 2] - UV[:, 0]
        det = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
        det = np.where(np.abs(det) < 1e-14, 1e-14, det)
        # dP/du and dP/dv
        a = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) / det[:, None]
        b = (e2 * d1[:, 0:1] - e1 * d2[:, 0:1]) / det[:, None]
        aa = (a * a).sum(1)
        ab = (a * b).sum(1)
        bb = (b * b).sum(1)
        g = aa * bb - ab * ab
        g = np.where(np.abs(g) < 1e-20, 1e-20, g)
        self.gu = (a * bb[:, None] - b * ab[:, None]) / g[:, None]
        self.gv = (b * aa[:, None] - a * ab[:, None]) / g[:, None]


def rasterize(mesh: Mesh, res=RES):
    """Texel -> (triangle, barycentrics). Texel centres inside a triangle only."""
    tri = np.full((res, res), -1, np.int64)
    bary = np.zeros((res, res, 3))
    px = mesh.UV * res - 0.5
    for t in range(len(px)):
        p = px[t]
        x0 = max(int(math.floor(p[:, 0].min())), 0)
        x1 = min(int(math.ceil(p[:, 0].max())), res - 1)
        y0 = max(int(math.floor(p[:, 1].min())), 0)
        y1 = min(int(math.ceil(p[:, 1].max())), res - 1)
        if x1 < x0 or y1 < y0:
            continue
        X, Y = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        (ax, ay), (bx, by), (cx, cy) = p
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-12:
            continue
        w0 = ((by - cy) * (X - cx) + (cx - bx) * (Y - cy)) / den
        w1 = ((cy - ay) * (X - cx) + (ax - cx) * (Y - cy)) / den
        w2 = 1.0 - w0 - w1
        e = -1e-4
        inside = (w0 >= e) & (w1 >= e) & (w2 >= e)
        if not inside.any():
            continue
        ys, xs = Y[inside], X[inside]
        tri[ys, xs] = t
        bary[ys, xs, 0] = w0[inside]
        bary[ys, xs, 1] = w1[inside]
        bary[ys, xs, 2] = w2[inside]
    return tri, bary


class Surface:
    """The covered texels of an atlas, mapped back to the rest-pose surface."""

    def __init__(self, mesh: Mesh, res=RES):
        self.mesh = mesh
        self.res = res
        tri, bary = rasterize(mesh, res)
        self.ys, self.xs = np.nonzero(tri >= 0)
        self.tri_img = tri
        t = tri[self.ys, self.xs]
        b = bary[self.ys, self.xs]
        self.t = t
        self.P = (mesh.P[t] * b[:, :, None]).sum(1)
        n = (mesh.N[t] * b[:, :, None]).sum(1)
        self.N = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
        self.Nhi = self.N.copy()
        self.mat = mesh.mat[t]
        self.part = mesh.part[t]
        self.obj = mesh.obj[t]
        self.n = len(t)
        # what the painters write
        self.albedo = np.ones((self.n, 3))
        self.height = np.zeros(self.n)
        # absolute roughness (the atlas carries it; the factor is 1)
        table = np.array([mesh.mat_rough.get(n, 0.5) for n in mesh.mat_names])
        self.rough = table[self.mat].astype(float)

    # masks -----------------------------------------------------------------
    def m(self, *names) -> np.ndarray:
        ids = [i for i, n in enumerate(self.mesh.mat_names) if n in names]
        return np.isin(self.mat, ids)

    def p(self, *names) -> np.ndarray:
        ids = [i for i, n in enumerate(self.mesh.part_names) if n in names]
        return np.isin(self.part, ids)

    # high-poly bake --------------------------------------------------------
    def bake_from(self, hi_ob, mask: np.ndarray, reach=0.012):
        """Shading normals of the full-resolution surface `hi_ob` onto the masked texels."""
        bm = bmesh.new()
        bm.from_mesh(hi_ob.data)
        bmesh.ops.triangulate(bm, faces=bm.faces[:])
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        bm.normal_update()
        bvh = BVHTree.FromBMesh(bm)
        tv = np.array([[v.index for v in f.verts] for f in bm.faces])
        vco = np.array([v.co[:] for v in bm.verts])
        vn = np.array([v.normal[:] for v in bm.verts])
        bm.free()
        idx = np.nonzero(mask)[0]
        hit_f = np.full(len(idx), -1)
        hit_p = np.zeros((len(idx), 3))
        P, N = self.P, self.N
        for k, i in enumerate(idx):
            o = Vector(P[i] + N[i] * reach)
            d = Vector(-N[i])
            loc, _nrm, fi, _dist = bvh.ray_cast(o, d, 2 * reach)
            if fi is None:
                loc, _nrm, fi, dist = bvh.find_nearest(Vector(P[i]), reach)
                if fi is None:
                    continue
            hit_f[k] = fi
            hit_p[k] = loc[:]
        ok = hit_f >= 0
        f = hit_f[ok]
        A, B, Cc = vco[tv[f, 0]], vco[tv[f, 1]], vco[tv[f, 2]]
        w = _barycentric(hit_p[ok], A, B, Cc)
        n = (
            vn[tv[f, 0]] * w[:, 0:1]
            + vn[tv[f, 1]] * w[:, 1:2]
            + vn[tv[f, 2]] * w[:, 2:3]
        )
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
        # never flip a shading normal more than ~70 degrees away from the game mesh
        good = (n * N[idx[ok]]).sum(1) > 0.35
        sel = idx[ok][good]
        self.Nhi[sel] = n[good]
        return int(good.sum())

    # outputs -----------------------------------------------------------------
    def _grid(self, values, fill=np.nan):
        g = np.full((self.res, self.res) + values.shape[1:], fill, dtype=float)
        g[self.ys, self.xs] = values
        return g

    def normal_map(self) -> np.ndarray:
        """Tangent-space normals (res, res, 3) in [-1, 1] from Nhi and the relief."""
        res = self.res
        h = self._grid(self.height)
        valid = ~np.isnan(h)
        hp = np.where(valid, h, 0.0)

        def diff(axis):
            fwd = np.roll(hp, -1, axis)
            bwd = np.roll(hp, 1, axis)
            vf = np.roll(valid, -1, axis)
            vb = np.roll(valid, 1, axis)
            one = np.where(vf, fwd - hp, np.where(vb, hp - bwd, 0.0))
            return np.where(vf & vb, (fwd - bwd) / 2, one)

        gx = diff(1)[self.ys, self.xs] * res  # dh/du
        gy = diff(0)[self.ys, self.xs] * res  # dh/dv
        gu = self.mesh.gu[self.t]
        gv = self.mesh.gv[self.t]
        G = gu * gx[:, None] + gv * gy[:, None]
        Nn = self.Nhi - G
        Nn /= np.maximum(np.linalg.norm(Nn, axis=1, keepdims=True), 1e-9)
        # three.js derivative frame: T = grad u, B = grad v, both projected, common scale
        N = self.N
        T = gu - N * (gu * N).sum(1, keepdims=True)
        B = gv - N * (gv * N).sum(1, keepdims=True)
        sc = 1.0 / np.sqrt(np.maximum(np.maximum((T * T).sum(1), (B * B).sum(1)), 1e-20))
        T *= sc[:, None]
        B *= sc[:, None]
        M = np.stack([T, B, N], axis=2)  # columns
        try:
            m = np.linalg.solve(M, Nn[:, :, None])[:, :, 0]
        except np.linalg.LinAlgError:
            m = np.stack([(Nn * T).sum(1), (Nn * B).sum(1), (Nn * N).sum(1)], 1)
        bad = ~np.isfinite(m).all(1) | (m[:, 2] <= 0.05)
        m[bad] = (0.0, 0.0, 1.0)
        m /= np.linalg.norm(m, axis=1, keepdims=True)
        return self._grid(m, 0.0), valid

    def rough_map(self):
        return self._grid(self.rough, np.nan)

    def albedo_map(self):
        return self._grid(self.albedo, np.nan)


def dilate(img: np.ndarray, valid: np.ndarray, passes=24) -> np.ndarray:
    """Grow island colours into the gutter so mip levels never pull in black."""
    img = img.copy()
    have = valid.copy()
    for _ in range(passes):
        acc = np.zeros_like(img)
        cnt = np.zeros(have.shape)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
            sh = np.roll(np.roll(have, dy, 0), dx, 1)
            vals = np.roll(np.roll(img, dy, 0), dx, 1)
            acc += np.where(sh[..., None], vals, 0.0)
            cnt += sh
        grow = (~have) & (cnt > 0)
        if not grow.any():
            break
        img[grow] = acc[grow] / cnt[grow][:, None]
        have |= grow
    if (~have).any():
        img[~have] = img[have].mean(axis=0)
    return img


def _barycentric(p, a, b, c):
    v0, v1, v2 = b - a, c - a, p - a
    d00 = (v0 * v0).sum(1)
    d01 = (v0 * v1).sum(1)
    d11 = (v1 * v1).sum(1)
    d20 = (v2 * v0).sum(1)
    d21 = (v2 * v1).sum(1)
    den = d00 * d11 - d01 * d01
    den = np.where(np.abs(den) < 1e-20, 1e-20, den)
    v = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    u = 1.0 - v - w
    return np.clip(np.stack([u, v, w], 1), 0.0, 1.0)


# ------------------------------------------------------------------ images + materials


def make_image(name: str, rgb: np.ndarray, non_color: bool):
    res = rgb.shape[0]
    img = bpy.data.images.get(name)
    if img is not None:
        bpy.data.images.remove(img)
    img = bpy.data.images.new(name, res, res, alpha=False)
    if non_color:
        img.colorspace_settings.name = "Non-Color"
    px = np.ones((res, res, 4), np.float32)
    px[..., :3] = rgb
    img.pixels.foreach_set(px.ravel())
    img.pack()
    return img


def set_factor(mat, rgba):
    """Set a material's colour factor (the multiply node when it is textured)."""
    nt = mat.node_tree
    mix = nt.nodes.get("verse_factor")
    if mix is not None:
        mix.inputs[7].default_value = rgba
    else:
        nt.nodes["Principled BSDF"].inputs["Base Color"].default_value = rgba
    mat.diffuse_color = rgba


def get_factor(mat):
    nt = mat.node_tree
    mix = nt.nodes.get("verse_factor")
    if mix is not None:
        return tuple(mix.inputs[7].default_value)
    return tuple(nt.nodes["Principled BSDF"].inputs["Base Color"].default_value)


def textured_copy(mat, cid: str, base_img, normal_img, orm_img=None, normal_strength=1.0):
    """The model's own copy of `mat` ('M_X@cid') reading the atlas."""
    name = f"{mat.name.split('@')[0]}@{cid}"
    old = bpy.data.materials.get(name)
    if old is not None and old is not mat:
        bpy.data.materials.remove(old)
    m = mat.copy()
    m.name = name
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    base = tuple(bsdf.inputs["Base Color"].default_value)
    if bsdf.inputs["Base Color"].is_linked:
        base = get_factor(mat)
    uvn = nt.nodes.new("ShaderNodeUVMap")
    uvn.uv_map = "UVMap"
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = base_img
    tex.interpolation = "Linear"
    nt.links.new(uvn.outputs["UV"], tex.inputs["Vector"])
    mix = nt.nodes.new("ShaderNodeMix")
    mix.name = "verse_factor"
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs["Factor"].default_value = 1.0
    nt.links.new(tex.outputs["Color"], mix.inputs[6])
    mix.inputs[7].default_value = base
    nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    tn = nt.nodes.new("ShaderNodeTexImage")
    tn.image = normal_img
    tn.interpolation = "Linear"
    nt.links.new(uvn.outputs["UV"], tn.inputs["Vector"])
    nm = nt.nodes.new("ShaderNodeNormalMap")
    nm.uv_map = "UVMap"
    nm.inputs["Strength"].default_value = normal_strength
    nt.links.new(tn.outputs["Color"], nm.inputs["Color"])
    nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    if orm_img is not None:
        to = nt.nodes.new("ShaderNodeTexImage")
        to.image = orm_img
        to.interpolation = "Linear"
        nt.links.new(uvn.outputs["UV"], to.inputs["Vector"])
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(to.outputs["Color"], sep.inputs["Color"])
        nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
    return m


def wire(cid: str, objs, base_img, normal_img, orm_img=None):
    """Point every textured slot of the character's meshes at its own atlas copy."""
    copies = {}
    for o in objs:
        for i, mat in enumerate(o.data.materials):
            if mat is None:
                continue
            base = mat.name.split("@")[0]
            if base in UNTEXTURED:
                continue
            if base not in copies:
                copies[base] = textured_copy(mat, cid, base_img, normal_img, orm_img)
            o.data.materials[i] = copies[base]
    return copies


class export_names:
    """Temporarily rename 'M_X@model' copies to 'M_X' for the export."""

    def __init__(self, cid: str):
        self.cid = cid
        self.swaps = []

    def __enter__(self):
        for m in list(bpy.data.materials):
            if m.name.endswith(f"@{self.cid}"):
                base = m.name.split("@")[0]
                orig = bpy.data.materials.get(base)
                if orig:
                    orig.name = f"{base}@__orig"
                m.name = base
                self.swaps.append((m, orig, base))
        return self

    def __exit__(self, *exc):
        for m, orig, base in self.swaps:
            m.name = f"{base}@{self.cid}"
            if orig:
                orig.name = base
        return False


# ------------------------------------------------------------------------ helpers


def hash3(P: np.ndarray, scale: float, seed: int = 0) -> np.ndarray:
    """Value noise in [0, 1] (trilinear over a hashed lattice), deterministic."""
    q = P / scale
    i = np.floor(q).astype(np.int64)
    f = q - i
    f = f * f * (3 - 2 * f)

    def h(ix, iy, iz):
        n = (ix * 73856093) ^ (iy * 19349663) ^ (iz * 83492791) ^ (seed * 2654435761)
        n = (n ^ (n >> 13)) * 1274126177
        n = n ^ (n >> 16)
        return (n & 0xFFFF) / 65535.0

    out = 0.0
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                w = (
                    (f[:, 0] if dx else 1 - f[:, 0])
                    * (f[:, 1] if dy else 1 - f[:, 1])
                    * (f[:, 2] if dz else 1 - f[:, 2])
                )
                out = out + w * h(i[:, 0] + dx, i[:, 1] + dy, i[:, 2] + dz)
    return out


def fbm(P, scale, octaves=3, seed=0):
    tot, amp, norm = 0.0, 1.0, 0.0
    for k in range(octaves):
        tot = tot + amp * hash3(P, scale / (2**k), seed + k)
        norm += amp
        amp *= 0.5
    return tot / norm


def band(d: np.ndarray, half: float, soft: float) -> np.ndarray:
    """1 inside |d| < half, smooth fall-off over `soft`."""
    a = np.abs(d)
    return 1.0 - np.clip((a - half) / max(soft, 1e-6), 0.0, 1.0)


def groove(d: np.ndarray, half: float) -> np.ndarray:
    """Rounded groove profile in [0, 1] (1 at the centre line)."""
    x = np.clip(np.abs(d) / max(half, 1e-6), 0.0, 1.0)
    return 0.5 + 0.5 * np.cos(np.pi * x)


def smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0) if e1 != e0 else (x >= e0).astype(float)
    return t * t * (3 - 2 * t)


def rough(surf: Surface, mask: np.ndarray, value, amount=None):
    """roughness = lerp(roughness, value, amount) on mask."""
    if amount is None:
        amount = np.ones(surf.n)
    a = np.where(mask, amount, 0.0)
    surf.rough = surf.rough * (1.0 - a) + a * value


def mul(surf: Surface, mask: np.ndarray, rgb, amount=None):
    """albedo *= lerp(1, rgb, amount) on mask; rgb is one colour or one per texel."""
    rgb = np.asarray(rgb, float)
    if rgb.ndim == 1:
        rgb = rgb[None, :]
    if amount is None:
        amount = np.ones(surf.n)
    a = np.where(mask, amount, 0.0)[:, None]
    surf.albedo *= 1.0 - a + a * rgb


def ensure_object_mode():
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")


def texture(cid: str, objs, painter, hi=None, weight=None, res=RES, debug_dir=None):
    """Unwrap, paint and wire one character. `painter(surf)` writes albedo/height.
    `hi` maps part names to full-resolution source objects for the normal bake."""
    ensure_object_mode()
    meshes = [o for o in objs if o.type == "MESH"]
    unwrap(meshes, weight or (lambda o, f, part: 1.0))
    mesh = Mesh(meshes)
    surf = Surface(mesh, res)
    for part, ob in (hi or {}).items():
        surf.bake_from(ob, surf.p(part))
    # texel density report (texels per metre, median per material)
    tpm = res * np.linalg.norm(mesh.gu[surf.t], axis=1)
    dens = {
        n: int(np.median(tpm[surf.mat == i]))
        for i, n in enumerate(mesh.mat_names)
        if (surf.mat == i).any()
    }
    print(f"[paint] {cid}: {surf.n / res**2:.0%} of the atlas covered, texels/m {dens}")
    painter(surf)
    nrm, valid = surf.normal_map()
    alb = surf.albedo_map()
    alb_img = dilate(np.nan_to_num(alb, nan=1.0), valid)
    nrm_img = dilate(nrm, valid)
    nrm_img /= np.maximum(np.linalg.norm(nrm_img, axis=2, keepdims=True), 1e-9)
    base = make_image(f"T_{cid}_BaseColor", srgb_encode(alb_img), False)
    normal = make_image(f"T_{cid}_Normal", nrm_img * 0.5 + 0.5, True)
    # glTF metallicRoughness layout: G = roughness, B = metallic (1: the factor rules)
    rgh = dilate(np.nan_to_num(surf.rough_map(), nan=0.5)[..., None].repeat(3, 2), valid)
    orm = np.ones_like(rgh)
    orm[..., 1] = np.clip(rgh[..., 1], 0.04, 1.0)
    orm_img = make_image(f"T_{cid}_ORM", orm, True)
    if debug_dir is not None:
        C.ensure_dir(debug_dir)
        for img in (base, normal, orm_img):
            img.filepath_raw = str(debug_dir / f"{img.name}.png")
            img.file_format = "PNG"
            img.save()
    wire(cid, meshes, base, normal, orm_img)
    return surf
