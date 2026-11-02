"""`SKEL_Verse_Human`: the frozen bone names and hierarchy (art-pipeline 12.1).

Pure Python, no bpy. The Blender rig (`fps/rig.py`), the Unreal checks
(`Verse.Anim.Skeleton.*`) and the unit tests all read this table, so the bone
names exist exactly once on the Python side. The C++ copy in
`VerseMovement/Private/Anim/VerseHumanSkeleton.cpp` is checked against it by
`tests/verse/test_unreal_characters.py`.
"""

from __future__ import annotations

SKELETON = "SKEL_Verse_Human"
PHYSICS = "PHYS_Verse_Human"
IK_RIG = "IKRig_Verse_Human"
RIG_FOLDER = "/Game/Verse/Characters/Rig"

MAX_BONES = 200
MAX_INFLUENCES = 8

FINGERS = ("Thumb", "Index", "Middle", "Ring", "Pinky")
SIDES = ("L", "R")


def _side_chain() -> list[tuple[str, str]]:
    """(bone, parent) for one side, with `{s}` standing for the side."""
    out = [
        ("Clavicle_{s}", "Spine_03"),
        ("UpperArm_{s}", "Clavicle_{s}"),
        ("UpperArm_Twist_{s}", "UpperArm_{s}"),
        ("LowerArm_{s}", "UpperArm_{s}"),
        ("LowerArm_Twist_{s}", "LowerArm_{s}"),
        ("Hand_{s}", "LowerArm_{s}"),
    ]
    for finger in FINGERS:
        parent = "Hand_{s}"
        for joint in (1, 2, 3):
            name = f"{finger}_0{joint}_{{s}}"
            out.append((name, parent))
            parent = name
    out.append(("Weapon_{s}", "Hand_{s}"))
    out += [
        ("Thigh_{s}", "Hips"),
        ("Thigh_Twist_{s}", "Thigh_{s}"),
        ("Calf_{s}", "Thigh_{s}"),
        ("Calf_Twist_{s}", "Calf_{s}"),
        ("Foot_{s}", "Calf_{s}"),
        ("Ball_{s}", "Foot_{s}"),
    ]
    return out


def bone_table() -> list[tuple[str, str | None]]:
    """Every bone of `SKEL_Verse_Human` as (name, parent), parents first."""
    bones: list[tuple[str, str | None]] = [
        ("Root", None),
        ("Hips", "Root"),
        ("Spine_01", "Hips"),
        ("Spine_02", "Spine_01"),
        ("Spine_03", "Spine_02"),
        ("Neck", "Spine_03"),
        ("Head", "Neck"),
        ("Camera", "Head"),
    ]
    for side in SIDES:
        bones += [(b.format(s=side), p.format(s=side)) for b, p in _side_chain()]
    bones.append(("IK_Foot_Root", "Root"))
    bones += [(f"IK_Foot_{s}", "IK_Foot_Root") for s in SIDES]
    bones.append(("IK_Hand_Root", "Root"))
    bones.append(("IK_Hand_Gun", "IK_Hand_Root"))
    bones += [(f"IK_Hand_{s}", "IK_Hand_Gun") for s in SIDES]
    return bones


BONES: tuple[tuple[str, str | None], ...] = tuple(bone_table())
NAMES: tuple[str, ...] = tuple(name for name, _ in BONES)
PARENT: dict[str, str | None] = dict(BONES)

#: Bones that skin the mesh. IK, weapon and camera bones never carry weights.
NON_DEFORM: frozenset[str] = frozenset(
    {"Root", "Camera", "Weapon_L", "Weapon_R"} | {n for n in NAMES if n.startswith("IK_")}
)
DEFORM: tuple[str, ...] = tuple(n for n in NAMES if n not in NON_DEFORM)

#: The three spine bones that share lean and aim offsets (art-pipeline 12.1),
#: with the share of the full rotation each one takes (sums to 1).
SPINE_SHARE: tuple[tuple[str, float], ...] = (
    ("Spine_01", 0.25),
    ("Spine_02", 0.35),
    ("Spine_03", 0.40),
)

#: IK bone -> the FK bone it follows in every clip.
IK_FOLLOWS: dict[str, str] = {
    "IK_Foot_L": "Foot_L",
    "IK_Foot_R": "Foot_R",
    "IK_Hand_Gun": "Hand_R",
    "IK_Hand_L": "Hand_L",
    "IK_Hand_R": "Hand_R",
}

#: Hit-zone bodies of `PHYS_Verse_Human` (architecture 3.3): bone, capsule end
#: bone (None continues along the parent direction), radius cm, hit zone.
HIT_BODIES: tuple[tuple[str, str | None, float, str], ...] = (
    ("Hips", "Spine_01", 14.0, "LowerTorso"),
    ("Spine_01", "Spine_03", 14.5, "LowerTorso"),
    ("Spine_03", "Neck", 16.5, "UpperTorso"),
    ("Neck", "Head", 6.0, "Neck"),
    ("Head", None, 11.0, "Head"),
    ("UpperArm_L", "LowerArm_L", 6.0, "Arm"),
    ("UpperArm_R", "LowerArm_R", 6.0, "Arm"),
    ("LowerArm_L", "Hand_L", 4.8, "Arm"),
    ("LowerArm_R", "Hand_R", 4.8, "Arm"),
    ("Thigh_L", "Calf_L", 8.5, "Leg"),
    ("Thigh_R", "Calf_R", 8.5, "Leg"),
    ("Calf_L", "Foot_L", 6.0, "Leg"),
    ("Calf_R", "Foot_R", 6.0, "Leg"),
)

#: `IKRig_Verse_Human` retarget chains: (chain, start bone, end bone, goal bone or None).
IK_CHAINS: tuple[tuple[str, str, str, str | None], ...] = (
    ("Spine", "Spine_01", "Spine_03", None),
    ("Neck", "Neck", "Head", None),
    *(
        item
        for s, side in (("L", "Left"), ("R", "Right"))
        for item in (
            (f"{side}Clavicle", f"Clavicle_{s}", f"Clavicle_{s}", None),
            (f"{side}Arm", f"UpperArm_{s}", f"Hand_{s}", f"Hand_{s}"),
            (f"{side}Leg", f"Thigh_{s}", f"Ball_{s}", f"Foot_{s}"),
            *((f"{side}{f}", f"{f}_01_{s}", f"{f}_03_{s}", None) for f in FINGERS),
        )
    ),
)


def check_names(names: list[str] | tuple[str, ...]) -> list[str]:
    """Problems of a skeleton's bone list against the frozen table (empty = match)."""
    problems = []
    given = list(names)
    if len(given) > MAX_BONES:
        problems.append(f"{len(given)} bones, at most {MAX_BONES}")
    missing = [n for n in NAMES if n not in given]
    extra = [n for n in given if n not in PARENT]
    if missing:
        problems.append(f"missing bones: {', '.join(missing)}")
    if extra:
        problems.append(f"bones not in art-pipeline 12.1: {', '.join(extra)}")
    if len(set(given)) != len(given):
        problems.append("duplicate bone names")
    return problems


def check_hierarchy(parents: dict[str, str | None]) -> list[str]:
    """Problems of a {bone: parent} map against the frozen hierarchy."""
    return [
        f"{bone}: parent {parents.get(bone)!r}, want {want!r}"
        for bone, want in BONES
        if bone in parents and parents[bone] != want
    ]
