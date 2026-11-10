"""Modelling and shading kit for the hero first-person weapons (bpy).

Weapon space as in `weapons/specs.py`: metres, +X to the muzzle, +Z up, +Y to
the weapon's left, origin at the grip point. Every part is its own object with
a bevel and a weighted-normal modifier, so hard edges catch light the way
machined and moulded parts do. `join()` applies the modifiers and merges the
parts per bone.

Materials are procedural Cycles node trees. They are the look source: the
export bakes them into one texture set (base colour, ORM, normal).
"""

from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Matrix, Vector

COLLECTION = "HeroWeapon"


def collection() -> bpy.types.Collection:
    col = bpy.data.collections.get(COLLECTION)
    if col is None:
        col = bpy.data.collections.new(COLLECTION)
        bpy.context.scene.collection.children.link(col)
    return col


def _object(name: str, bm: bmesh.types.BMesh, material, bone: str) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    collection().objects.link(obj)
    if material is not None:
        mesh.materials.append(material)
    obj["bone"] = bone
    for poly in mesh.polygons:
        poly.use_smooth = True
    return obj


def finish(
    obj: bpy.types.Object, bevel: float, segments: int = 2, angle: float = 40.0
) -> bpy.types.Object:
    """Bevel the hard edges and keep the flat faces flat (weighted normals)."""
    if bevel > 0.0:
        mod = obj.modifiers.new("Bevel", "BEVEL")
        mod.width = bevel
        mod.segments = segments
        mod.limit_method = "ANGLE"
        mod.angle_limit = math.radians(angle)
        mod.harden_normals = True
        mod.miter_outer = "MITER_ARC"
    wn = obj.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
    wn.keep_sharp = True
    wn.weight = 100
    return obj


def box(
    name, lo, hi, material, bone="Root", bevel=0.0015, segments=2, rot=(0.0, 0.0, 0.0), pivot=None
):
    """Axis box from corner `lo` to `hi`, optionally rotated (degrees XYZ) about `pivot`."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    size = Vector(hi) - Vector(lo)
    centre = (Vector(hi) + Vector(lo)) / 2
    bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    bmesh.ops.translate(bm, vec=centre, verts=bm.verts)
    if any(rot):
        p = Vector(pivot if pivot is not None else centre)
        r = Matrix.Translation(p) @ _euler(rot) @ Matrix.Translation(-p)
        bmesh.ops.transform(bm, matrix=r, verts=bm.verts)
    return finish(_object(name, bm, material, bone), bevel, segments)


def curved_box(name, lo, hi, material, bone="Root", bend=1.0, steps=16, bevel=0.002):
    """Box from `lo` to `hi` whose lower part sweeps forward (+X) by `bend` * depth^2."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    size = Vector(hi) - Vector(lo)
    centre = (Vector(hi) + Vector(lo)) / 2
    bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    bmesh.ops.translate(bm, vec=centre, verts=bm.verts)
    for i in range(1, steps):
        z = hi[2] - size.z * i / steps
        geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
        bmesh.ops.bisect_plane(bm, geom=geom, plane_co=(0, 0, z), plane_no=(0, 0, 1))
    for v in bm.verts:
        depth = hi[2] - v.co.z
        v.co.x += bend * depth * depth
    return finish(_object(name, bm, material, bone), bevel, 2)


def cylinder(
    name, x0, x1, radius, material, bone="Root", y=0.0, z=0.0, sides=32, bevel=0.0008, radius1=None
):
    """Cylinder (or cone) along +X from x0 to x1."""
    bm = bmesh.new()
    r1 = radius if radius1 is None else radius1
    bmesh.ops.create_cone(
        bm, cap_ends=True, segments=sides, radius1=radius, radius2=r1, depth=x1 - x0
    )
    bmesh.ops.rotate(
        bm, cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(90), 3, "Y"), verts=bm.verts
    )
    bmesh.ops.translate(bm, vec=((x0 + x1) / 2, y, z), verts=bm.verts)
    return finish(_object(name, bm, material, bone), bevel, 2, 30.0)


def cylinder_axis(name, centre, radius, depth, axis, material, bone="Root", sides=24, bevel=0.0005):
    """Short cylinder along `axis` ('X', 'Y' or 'Z') centred at `centre` (pins, screws, knobs)."""
    bm = bmesh.new()
    bmesh.ops.create_cone(
        bm, cap_ends=True, segments=sides, radius1=radius, radius2=radius, depth=depth
    )
    if axis == "X":
        bmesh.ops.rotate(
            bm, cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(90), 3, "Y"), verts=bm.verts
        )
    elif axis == "Y":
        bmesh.ops.rotate(
            bm, cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(90), 3, "X"), verts=bm.verts
        )
    bmesh.ops.translate(bm, vec=centre, verts=bm.verts)
    return finish(_object(name, bm, material, bone), bevel, 1, 30.0)


def prism(name, x0, x1, radius, sides, material, bone="Root", z=0.0, rot_deg=0.0, bevel=0.0012):
    """Regular prism along +X (handguards, nuts)."""
    bm = bmesh.new()
    bmesh.ops.create_cone(
        bm, cap_ends=True, segments=sides, radius1=radius, radius2=radius, depth=x1 - x0
    )
    bmesh.ops.rotate(
        bm, cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(rot_deg), 3, "Z"), verts=bm.verts
    )
    bmesh.ops.rotate(
        bm, cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(90), 3, "Y"), verts=bm.verts
    )
    bmesh.ops.translate(bm, vec=((x0 + x1) / 2, 0.0, z), verts=bm.verts)
    return finish(_object(name, bm, material, bone), bevel, 2, 30.0)


def torus(name, centre, major, minor, material, bone="Root", axis="X", sides=48):
    bm = bmesh.new()
    ring = []
    for i in range(sides):
        a = 2 * math.pi * i / sides
        ring.append((math.cos(a), math.sin(a)))
    minor_sides = 8
    verts = []
    for ca, sa in ring:
        row = []
        for j in range(minor_sides):
            b = 2 * math.pi * j / minor_sides
            r = major + minor * math.cos(b)
            row.append(bm.verts.new((minor * math.sin(b), r * ca, r * sa)))
        verts.append(row)
    for i in range(sides):
        for j in range(minor_sides):
            a = verts[i][j]
            b = verts[(i + 1) % sides][j]
            c = verts[(i + 1) % sides][(j + 1) % minor_sides]
            d = verts[i][(j + 1) % minor_sides]
            bm.faces.new((a, b, c, d))
    bmesh.ops.translate(bm, vec=centre, verts=bm.verts)
    return finish(_object(name, bm, material, bone), 0.0)


def cut(target: bpy.types.Object, cutter: bpy.types.Object) -> None:
    """Boolean difference; the cutter is hidden from render and removed at join time."""
    mod = target.modifiers.new(f"Cut_{cutter.name}", "BOOLEAN")
    mod.operation = "DIFFERENCE"
    mod.solver = "EXACT"
    mod.object = cutter
    # Booleans first, then bevel and normals.
    target.modifiers.move(len(target.modifiers) - 1, 0)
    cutter.display_type = "WIRE"
    cutter.hide_render = True
    cutter["cutter"] = True


def engrave(target: bpy.types.Object, text: str, origin, height: float, depth: float = 0.0005):
    """Cut `text` into the +Y (left) face of `target`, reading front to back along +X... from the left."""
    curve = bpy.data.curves.new(f"Txt_{target.name}_{len(target.modifiers)}", "FONT")
    curve.body = text
    curve.size = height
    curve.extrude = depth * 2
    curve.align_y = "CENTER"
    obj = bpy.data.objects.new(curve.name, curve)
    collection().objects.link(obj)
    # Text lies in XY facing +Z; stand it up on the +Y face, reading towards -X... then flip to read
    # left to right as seen from the weapon's left side (towards +X).
    obj.rotation_euler = (math.radians(90), 0.0, math.radians(180))
    obj.location = origin
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(deps))
    cutter = bpy.data.objects.new(f"{curve.name}_Cut", mesh)
    cutter.matrix_world = obj.matrix_world.copy()
    collection().objects.link(cutter)
    bpy.data.objects.remove(obj)
    cut(target, cutter)
    return cutter


def cutter_box(name, lo, hi, rot=(0.0, 0.0, 0.0), pivot=None):
    obj = box(name, lo, hi, None, bevel=0.0)
    obj.modifiers.clear()
    if any(rot):
        pass
    return obj


def _euler(rot) -> Matrix:
    from mathutils import Euler

    return Euler(tuple(math.radians(a) for a in rot), "XYZ").to_matrix().to_4x4()


# --------------------------------------------------------------------------
# Materials (Cycles node trees)
# --------------------------------------------------------------------------


def _new_material(name: str):
    mat = bpy.data.materials.get(name)
    if mat is not None:
        bpy.data.materials.remove(mat)
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    return mat, mat.node_tree.nodes, mat.node_tree.links


def _principled(nodes):
    return next(n for n in nodes if n.type == "BSDF_PRINCIPLED")


def _noise(nodes, links, scale, detail=8.0, roughness=0.6, coord=None):
    tex = nodes.new("ShaderNodeTexNoise")
    tex.inputs["Scale"].default_value = scale
    tex.inputs["Detail"].default_value = detail
    tex.inputs["Roughness"].default_value = roughness
    if coord is not None:
        links.new(coord, tex.inputs["Vector"])
    return tex


def _ramp(nodes, links, src, stops):
    ramp = nodes.new("ShaderNodeValToRGB")
    els = ramp.color_ramp.elements
    els[0].position, els[0].color = stops[0][0], (*stops[0][1], 1.0)
    els[1].position, els[1].color = stops[-1][0], (*stops[-1][1], 1.0)
    for pos, col in stops[1:-1]:
        e = els.new(pos)
        e.color = (*col, 1.0)
    links.new(src, ramp.inputs["Fac"])
    return ramp


def _edge_mask(nodes, links, width, noise_scale, threshold):
    """Edge wear: bevel-normal difference (convex edges) broken up by noise."""
    geo = nodes.new("ShaderNodeNewGeometry")
    bevel = nodes.new("ShaderNodeBevel")
    bevel.inputs["Radius"].default_value = width
    dot = nodes.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    links.new(bevel.outputs["Normal"], dot.inputs[0])
    links.new(geo.outputs["Normal"], dot.inputs[1])
    inv = nodes.new("ShaderNodeMath")
    inv.operation = "SUBTRACT"
    inv.inputs[0].default_value = 1.0
    links.new(dot.outputs["Value"], inv.inputs[1])
    gain = nodes.new("ShaderNodeMath")
    gain.operation = "MULTIPLY"
    gain.inputs[1].default_value = 14.0
    links.new(inv.outputs["Value"], gain.inputs[0])
    tc = nodes.new("ShaderNodeTexCoord")
    n = _noise(nodes, links, noise_scale, 10.0, 0.7, tc.outputs["Object"])
    mul = nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    links.new(gain.outputs["Value"], mul.inputs[0])
    links.new(n.outputs["Fac"], mul.inputs[1])
    step = nodes.new("ShaderNodeMapRange")
    step.inputs["From Min"].default_value = threshold
    step.inputs["From Max"].default_value = threshold + 0.25
    links.new(mul.outputs["Value"], step.inputs["Value"])
    return step.outputs["Result"]


def _cavity(nodes, links, distance):
    ao = nodes.new("ShaderNodeAmbientOcclusion")
    ao.inside = False
    ao.inputs["Distance"].default_value = distance
    return ao.outputs["AO"]


def coated(
    name: str,
    base,
    worn,
    rough=0.55,
    metallic_base=0.0,
    wear=0.55,
    micro=0.25,
    dirt=0.35,
    scratches=0.8,
    dust_amount=0.25,
):
    """Sprayed or anodised finish over metal: worn to bare metal on edges, grime in corners."""
    mat, nodes, links = _new_material(name)
    bsdf = _principled(nodes)
    tc = nodes.new("ShaderNodeTexCoord")
    edge = _edge_mask(nodes, links, 0.0012, 180.0, wear)
    cav = _cavity(nodes, links, 0.006)

    # Base colour: finish with a soft mottle, bare metal on edges, darker in cavities.
    mottle = _noise(nodes, links, 60.0, 6.0, 0.55, tc.outputs["Object"])
    mottle_c = _ramp(
        nodes,
        links,
        mottle.outputs["Fac"],
        [(0.3, tuple(c * 0.86 for c in base)), (0.7, tuple(min(1.0, c * 1.08) for c in base))],
    )
    mix_edge = nodes.new("ShaderNodeMix")
    mix_edge.data_type = "RGBA"
    links.new(edge, mix_edge.inputs["Factor"])
    links.new(mottle_c.outputs["Color"], mix_edge.inputs["A"])
    mix_edge.inputs["B"].default_value = (*worn, 1.0)
    grime = nodes.new("ShaderNodeMix")
    grime.data_type = "RGBA"
    inv_cav = nodes.new("ShaderNodeMath")
    inv_cav.operation = "SUBTRACT"
    inv_cav.inputs[0].default_value = 1.0
    links.new(cav, inv_cav.inputs[1])
    gscale = nodes.new("ShaderNodeMath")
    gscale.operation = "MULTIPLY"
    gscale.inputs[1].default_value = dirt
    links.new(inv_cav.outputs["Value"], gscale.inputs[0])
    links.new(gscale.outputs["Value"], grime.inputs["Factor"])
    links.new(mix_edge.outputs["Result"], grime.inputs["A"])
    grime.inputs["B"].default_value = (0.03, 0.025, 0.02, 1.0)
    # Scratches: thin streaks through the coating to bare metal.
    sc_map = nodes.new("ShaderNodeMapping")
    sc_map.inputs["Scale"].default_value = (1.0, 28.0, 28.0)
    sc_map.inputs["Rotation"].default_value = (0.3, 0.0, 0.5)
    links.new(tc.outputs["Object"], sc_map.inputs["Vector"])
    sc = nodes.new("ShaderNodeTexNoise")
    sc.inputs["Scale"].default_value = 24.0
    sc.inputs["Detail"].default_value = 2.0
    links.new(sc_map.outputs["Vector"], sc.inputs["Vector"])
    sc_step = nodes.new("ShaderNodeMapRange")
    sc_step.inputs["From Min"].default_value = 0.715
    sc_step.inputs["From Max"].default_value = 0.73
    links.new(sc.outputs["Fac"], sc_step.inputs["Value"])
    sc_mix = nodes.new("ShaderNodeMix")
    sc_mix.data_type = "RGBA"
    sc_amt = nodes.new("ShaderNodeMath")
    sc_amt.operation = "MULTIPLY"
    sc_amt.inputs[1].default_value = scratches
    links.new(sc_step.outputs["Result"], sc_amt.inputs[0])
    links.new(sc_amt.outputs["Value"], sc_mix.inputs["Factor"])
    links.new(grime.outputs["Result"], sc_mix.inputs["A"])
    sc_mix.inputs["B"].default_value = (*worn, 1.0)
    # Dust settles light in corners and on upward faces.
    dust = nodes.new("ShaderNodeMix")
    dust.data_type = "RGBA"
    geo_d = nodes.new("ShaderNodeNewGeometry")
    sep = nodes.new("ShaderNodeSeparateXYZ")
    links.new(geo_d.outputs["Normal"], sep.inputs["Vector"])
    dn = _noise(nodes, links, 35.0, 6.0, 0.6, tc.outputs["Object"])
    dmul = nodes.new("ShaderNodeMath")
    dmul.operation = "MULTIPLY"
    links.new(sep.outputs["Z"], dmul.inputs[0])
    links.new(dn.outputs["Fac"], dmul.inputs[1])
    dclamp = nodes.new("ShaderNodeMapRange")
    dclamp.inputs["From Min"].default_value = 0.35
    dclamp.inputs["From Max"].default_value = 0.8
    dclamp.inputs["To Max"].default_value = dust_amount
    links.new(dmul.outputs["Value"], dclamp.inputs["Value"])
    links.new(dclamp.outputs["Result"], dust.inputs["Factor"])
    links.new(sc_mix.outputs["Result"], dust.inputs["A"])
    dust.inputs["B"].default_value = (0.36, 0.32, 0.26, 1.0)
    links.new(dust.outputs["Result"], bsdf.inputs["Base Color"])

    # Metallic: bare edges are metal.
    met = nodes.new("ShaderNodeMapRange")
    met.inputs["To Min"].default_value = metallic_base
    met.inputs["To Max"].default_value = 1.0
    links.new(edge, met.inputs["Value"])
    links.new(met.outputs["Result"], bsdf.inputs["Metallic"])

    # Roughness: finish with fine variation, bare metal smoother, fingerprints/oil streaks.
    rn = _noise(nodes, links, 140.0, 8.0, 0.6, tc.outputs["Object"])
    rr = nodes.new("ShaderNodeMapRange")
    rr.inputs["To Min"].default_value = rough - 0.12
    rr.inputs["To Max"].default_value = rough + 0.12
    links.new(rn.outputs["Fac"], rr.inputs["Value"])
    rmix = nodes.new("ShaderNodeMix")
    rmix.data_type = "FLOAT"
    links.new(edge, rmix.inputs["Factor"])
    links.new(rr.outputs["Result"], rmix.inputs["A"])
    rmix.inputs["B"].default_value = 0.28
    links.new(rmix.outputs["Result"], bsdf.inputs["Roughness"])

    # Micro surface: fine orange-peel of the coating.
    bn = _noise(nodes, links, 900.0, 4.0, 0.5, tc.outputs["Object"])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = micro
    bump.inputs["Distance"].default_value = 0.0004
    links.new(bn.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def polymer(name: str, base=(0.028, 0.028, 0.03), stipple=0.6):
    """Moulded polymer with a stippled grip texture."""
    mat, nodes, links = _new_material(name)
    bsdf = _principled(nodes)
    tc = nodes.new("ShaderNodeTexCoord")
    vor = nodes.new("ShaderNodeTexVoronoi")
    vor.inputs["Scale"].default_value = 700.0
    links.new(tc.outputs["Object"], vor.inputs["Vector"])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = stipple
    bump.inputs["Distance"].default_value = 0.0003
    links.new(vor.outputs["Distance"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    edge = _edge_mask(nodes, links, 0.001, 200.0, 0.75)
    col = nodes.new("ShaderNodeMix")
    col.data_type = "RGBA"
    links.new(edge, col.inputs["Factor"])
    col.inputs["A"].default_value = (*base, 1.0)
    col.inputs["B"].default_value = (0.09, 0.09, 0.09, 1.0)
    links.new(col.outputs["Result"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.72
    bsdf.inputs["Metallic"].default_value = 0.0
    return mat


def steel(name: str, base=(0.06, 0.06, 0.065), rough=0.38):
    """Parkerised / nitrided steel: barrel, brake, pins."""
    mat, nodes, links = _new_material(name)
    bsdf = _principled(nodes)
    tc = nodes.new("ShaderNodeTexCoord")
    n = _noise(nodes, links, 300.0, 8.0, 0.65, tc.outputs["Object"])
    rr = nodes.new("ShaderNodeMapRange")
    rr.inputs["To Min"].default_value = rough - 0.1
    rr.inputs["To Max"].default_value = rough + 0.15
    links.new(n.outputs["Fac"], rr.inputs["Value"])
    links.new(rr.outputs["Result"], bsdf.inputs["Roughness"])
    edge = _edge_mask(nodes, links, 0.0008, 220.0, 0.6)
    col = nodes.new("ShaderNodeMix")
    col.data_type = "RGBA"
    links.new(edge, col.inputs["Factor"])
    col.inputs["A"].default_value = (*base, 1.0)
    col.inputs["B"].default_value = (0.45, 0.45, 0.46, 1.0)
    links.new(col.outputs["Result"], bsdf.inputs["Base Color"])
    bsdf.inputs["Metallic"].default_value = 1.0
    return mat


def glass(name: str, tint=(0.93, 0.98, 1.0)):
    """Coated optic glass: clear, a faint cool tint and a thin anti-reflection sheen."""
    mat, nodes, links = _new_material(name)
    bsdf = _principled(nodes)
    bsdf.inputs["Base Color"].default_value = (*tint, 1.0)
    bsdf.inputs["Transmission Weight"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = 0.0
    bsdf.inputs["IOR"].default_value = 1.52
    bsdf.inputs["Coat Weight"].default_value = 0.15
    bsdf.inputs["Thin Film Thickness"].default_value = 140.0
    bsdf.inputs["Thin Film IOR"].default_value = 1.38
    return mat


def emissive(name: str, colour=(1.0, 0.18, 0.06), strength=40.0):
    mat, nodes, links = _new_material(name)
    bsdf = _principled(nodes)
    bsdf.inputs["Base Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    bsdf.inputs["Emission Color"].default_value = (*colour, 1.0)
    bsdf.inputs["Emission Strength"].default_value = strength
    return mat
