"""Build the SK_Test_Human placeholder in Blender and export it as FBX (G0.9).

Runs inside Blender (``blender -b --factory-startup -P <this> -- <out.fbx>``);
``scripts/unreal/g0_content.py`` calls it. The skeleton carries every frozen
bone name of ``docs/verse/unreal/contracts/art-pipeline.md`` 12.1 in the
hierarchy given there. The mesh is crude on purpose: one box per body bone,
rigidly skinned, so movement, combat and gore tests have hit zones and bones
to address before the real rig (WP13) lands. A-pose, origin on the floor
between the feet, character facing -Y in Blender (Unreal +X after import).

The FBX goes to an ignored cache; only the imported ``.uasset`` is committed.
"""

from __future__ import annotations

import math
import sys

import bpy
from mathutils import Vector

# (name, parent, head, tail) in metres. Left side is +X (the character faces -Y).
BONES: list[tuple[str, str | None, tuple[float, float, float], tuple[float, float, float]]] = []

# Body bones that get a box in the placeholder mesh: name -> box half-size across the bone.
BOX_HALF_WIDTH: dict[str, float] = {}


def bone(name, parent, head, tail, box=None):
    BONES.append((name, parent, head, tail))
    if box is not None:
        BOX_HALF_WIDTH[name] = box


def _along(start, direction, length):
    return tuple(s + d * length for s, d in zip(start, direction, strict=True))


def build_bone_table() -> None:
    bone("Root", None, (0, 0, 0), (0, 0, 0.1))
    bone("Hips", "Root", (0, 0, 0.95), (0, 0, 1.05), box=0.16)
    bone("Spine_01", "Hips", (0, 0, 1.05), (0, 0, 1.20), box=0.15)
    bone("Spine_02", "Spine_01", (0, 0, 1.20), (0, 0, 1.35), box=0.16)
    bone("Spine_03", "Spine_02", (0, 0, 1.35), (0, 0, 1.48), box=0.17)
    # Wide neck box: the engine's physics asset generator welds bodies under
    # 20 cm into their parent, and the neck is a hit zone of its own.
    bone("Neck", "Spine_03", (0, 0, 1.48), (0, 0, 1.58), box=0.11)
    bone("Head", "Neck", (0, 0, 1.58), (0, 0, 1.80), box=0.10)
    bone("Camera", "Head", (0, -0.10, 1.68), (0, -0.20, 1.68))

    # A-pose: upper arms 45 degrees down from horizontal.
    down = math.radians(45.0)
    for side, sx in (("L", 1.0), ("R", -1.0)):
        arm_dir = (sx * math.cos(down), 0.0, -math.sin(down))
        shoulder = (sx * 0.17, 0.0, 1.44)
        elbow = _along(shoulder, arm_dir, 0.28)
        wrist = _along(elbow, arm_dir, 0.26)
        palm = _along(wrist, arm_dir, 0.08)
        bone(f"Clavicle_{side}", "Spine_03", (sx * 0.03, 0, 1.44), shoulder, box=0.04)
        bone(f"UpperArm_{side}", f"Clavicle_{side}", shoulder, elbow, box=0.05)
        bone(
            f"UpperArm_Twist_{side}", f"UpperArm_{side}",
            _along(shoulder, arm_dir, 0.14), _along(shoulder, arm_dir, 0.20),
        )
        bone(f"LowerArm_{side}", f"UpperArm_{side}", elbow, wrist, box=0.04)
        bone(
            f"LowerArm_Twist_{side}", f"LowerArm_{side}",
            _along(elbow, arm_dir, 0.18), _along(elbow, arm_dir, 0.24),
        )
        bone(f"Hand_{side}", f"LowerArm_{side}", wrist, palm, box=0.035)
        # Fingers spread across the palm along Y; the thumb starts at the wrist, forward.
        for finger, y in (("Index", -0.03), ("Middle", -0.01), ("Ring", 0.01), ("Pinky", 0.03)):
            start = (palm[0], palm[1] + y, palm[2])
            parent = f"Hand_{side}"
            for j in (1, 2, 3):
                end = _along(start, arm_dir, 0.03)
                name = f"{finger}_0{j}_{side}"
                bone(name, parent, start, end, box=0.008)
                parent, start = name, end
        thumb_dir = (arm_dir[0] * 0.5, -0.8, arm_dir[2] * 0.5)
        start = _along(wrist, arm_dir, 0.02)
        start = (start[0], start[1] - 0.03, start[2])
        parent = f"Hand_{side}"
        for j in (1, 2, 3):
            end = _along(start, thumb_dir, 0.03)
            name = f"Thumb_0{j}_{side}"
            bone(name, parent, start, end, box=0.009)
            parent, start = name, end
        grip = _along(wrist, arm_dir, 0.05)
        bone(f"Weapon_{side}", f"Hand_{side}", grip, (grip[0], grip[1] - 0.10, grip[2]))

        hip = (sx * 0.10, 0.0, 0.95)
        knee = (sx * 0.10, 0.0, 0.52)
        ankle = (sx * 0.10, 0.0, 0.10)
        ball = (sx * 0.10, -0.12, 0.03)
        toe = (sx * 0.10, -0.20, 0.03)
        bone(f"Thigh_{side}", "Hips", hip, knee, box=0.08)
        bone(f"Thigh_Twist_{side}", f"Thigh_{side}", (hip[0], 0, 0.80), (hip[0], 0, 0.70))
        bone(f"Calf_{side}", f"Thigh_{side}", knee, ankle, box=0.06)
        bone(f"Calf_Twist_{side}", f"Calf_{side}", (knee[0], 0, 0.30), (knee[0], 0, 0.20))
        bone(f"Foot_{side}", f"Calf_{side}", ankle, ball, box=0.05)
        bone(f"Ball_{side}", f"Foot_{side}", ball, toe, box=0.04)

    # IK bones follow their FK targets; at rest they sit on them.
    bone("IK_Foot_Root", "Root", (0, 0, 0), (0, 0, 0.1))
    bone("IK_Hand_Root", "Root", (0, 0, 0), (0, 0, 0.1))
    tails = {name: (head, tail) for name, _, head, tail in BONES}
    for side in ("L", "R"):
        head, tail = tails[f"Foot_{side}"]
        bone(f"IK_Foot_{side}", "IK_Foot_Root", head, tail)
    gun_head, gun_tail = tails["Hand_R"]
    bone("IK_Hand_Gun", "IK_Hand_Root", gun_head, gun_tail)
    for side in ("L", "R"):
        head, tail = tails[f"Hand_{side}"]
        bone(f"IK_Hand_{side}", "IK_Hand_Gun", head, tail)


def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0


def build_armature() -> bpy.types.Object:
    data = bpy.data.armatures.new("SKEL_Test_Human")
    # Named "Armature" so the Unreal importer drops the object node and Root is the top bone.
    rig = bpy.data.objects.new("Armature", data)
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    edit = data.edit_bones
    for name, parent, head, tail in BONES:
        eb = edit.new(name)
        eb.head = Vector(head)
        eb.tail = Vector(tail)
        eb.roll = 0.0
        eb.use_deform = True
        if parent:
            eb.parent = edit[parent]
            eb.use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")
    return rig


def build_mesh(rig: bpy.types.Object) -> bpy.types.Object:
    verts: list[Vector] = []
    faces: list[tuple[int, int, int, int]] = []
    owner: list[str] = []
    quads = ((0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0))
    for name, _, head, tail in BONES:
        half = BOX_HALF_WIDTH.get(name)
        if half is None:
            continue
        h, t = Vector(head), Vector(tail)
        axis = (t - h).normalized()
        helper = Vector((0, 0, 1)) if abs(axis.z) < 0.9 else Vector((0, 1, 0))
        u = axis.cross(helper).normalized() * half
        v = axis.cross(u).normalized() * half
        base = len(verts)
        for end in (h, t):
            verts.extend([end + u + v, end - u + v, end - u - v, end + u - v])
        faces.extend(tuple(base + i for i in q) for q in quads)
        owner.extend([name] * 8)
    mesh = bpy.data.meshes.new("SK_Test_Human")
    mesh.from_pydata([tuple(p) for p in verts], [], faces)
    mesh.validate()
    mesh.update()
    obj = bpy.data.objects.new("SK_Test_Human", mesh)
    bpy.context.scene.collection.objects.link(obj)
    groups = {}
    for index, name in enumerate(owner):
        group = groups.get(name) or obj.vertex_groups.new(name=name)
        groups[name] = group
        group.add([index], 1.0, "REPLACE")
    obj.parent = rig
    mod = obj.modifiers.new("Armature", "ARMATURE")
    mod.object = rig
    return obj


def export(path: str) -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.fbx(
        filepath=path,
        use_selection=True,
        object_types={"ARMATURE", "MESH"},
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_NONE",
        mesh_smooth_type="FACE",
        add_leaf_bones=False,
        use_armature_deform_only=False,
        primary_bone_axis="Y",
        secondary_bone_axis="X",
        bake_anim=False,
        path_mode="STRIP",
        embed_textures=False,
    )


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv:
        raise SystemExit(
            "usage: blender -b --factory-startup -P test_human_blender.py -- <out.fbx>"
        )
    build_bone_table()
    reset_scene()
    rig = build_armature()
    build_mesh(rig)
    export(argv[0])
    print(f"VERSE_G0 exported {len(BONES)} bones to {argv[0]}")


if __name__ == "__main__":
    main()
