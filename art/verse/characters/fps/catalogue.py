"""Every mesh and clip WP13 ships, as data (pure Python, no bpy).

The Blender builders author exactly these clips (`fps/clips.py` checks it),
`scripts/verse/export_unreal.py characters` writes one import record per
entry, the editor import reads the same table, and the unit tests check the
contract numbers here (phase times of combat-state 7.4, reload times of 3.1,
WP01 move speeds) without Blender.

Times are seconds. Body clips sample at 30 fps, weapon clips at 60 fps
(art-pipeline 12.2).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from characters.fps import skeleton

OWNER = "WP13"
BODY_FPS = 30
WEAPON_FPS = 60

ANIM_ROOT = "/Game/Verse/Animations"
CHAR_ROOT = "/Game/Verse/Characters"

#: Body variants (CC0 base meshes, `art/verse/LICENSES.md`) and their height in m.
VARIANTS = {"M": 1.78, "F": 1.68}

#: Uniforms: id -> (outfit builder in characters/, rank tier of build.TIERS or None, label).
UNIFORMS = {
    "Commander": ("build_officer", "command", "commander uniform"),
    "Crew": ("build_technician", None, "crew coverall"),
    "Opponent": ("build_trooper", None, "black tactical opponent"),
}


@dataclass(frozen=True)
class MeshSpec:
    name: str
    uniform: str
    variant: str

    @property
    def asset_path(self) -> str:
        return f"{CHAR_ROOT}/{self.uniform}/{self.name}.{self.name}"


MESHES: tuple[MeshSpec, ...] = tuple(
    MeshSpec(f"SK_{uniform}_{variant}", uniform, variant)
    for uniform in UNIFORMS
    for variant in VARIANTS
)
#: The mesh whose rest pose becomes the shared skeleton's reference pose.
SKELETON_SOURCE = "SK_Commander_M"


# ------------------------------------------------------------------- movement

#: Steady ground speeds the locomotion clips are authored for (WP01 start values, m/s).
SPEEDS = {"Stand": 4.5, "Crouch": 2.2, "Prone": 0.9, "Sprint": 6.5}
#: Eight headings: degrees, 0 = forward, 90 = the character's left.
HEADINGS = {
    "F": 0.0,
    "FL": 45.0,
    "L": 90.0,
    "BL": 135.0,
    "B": 180.0,
    "BR": -135.0,
    "R": -90.0,
    "FR": -45.0,
}
#: Mantle presentation: (seconds, ledge height authored m, forward travel m) (WP01).
MANTLE = {"Low": (0.45, 1.0, 0.6), "High": (0.85, 1.6, 0.7)}
SLIDE_SECONDS = 1.1
PRONE_ENTER, PRONE_EXIT = 0.7, 0.6

# --------------------------------------------------------------------- combat

#: Finisher phase times (combat-state 7.4) -> sync marker names on both clips.
FINISHER_MARKERS: tuple[tuple[str, float], ...] = (
    ("Takedown", 0.25),
    ("Struggle", 0.9),
    ("Kill", 1.8),
    ("Recover", 2.1),
    ("Release", 2.5),
)
FINISHER_SECONDS = 2.5
WARP_TARGET = "Warp_Finisher"
#: Motion-warping window on the attacker clip: from lock to the end of the warp.
WARP_WINDOW = (0.0, 0.25)
#: Victim root in the attacker's root space at the end of the warp (cm, Unreal
#: axes): the victim stands this far ahead of the attacker, facing away.
FINISHER_VICTIM_OFFSET_CM = (55.0, 0.0, 0.0)

#: Weapon classes with their reload times (combat-state 3.1 start values).
WEAPON_CLASSES = {
    "Rifle": {"tactical": 2.1, "empty": 2.8, "equip": 0.6, "holster": 0.5, "rpm": 690},
    "Pistol": {"tactical": 1.5, "empty": 1.9, "equip": 0.4, "holster": 0.35, "rpm": 380},
}
KNIFE = {"strike": 0.7, "hit": 0.15, "equip": 0.3, "holster": 0.3}


@dataclass(frozen=True)
class Clip:
    name: str
    group: str
    seconds: float
    loop: bool
    fps: int = BODY_FPS
    root_motion: bool = False
    markers: tuple[tuple[str, float], ...] = ()
    params: dict = field(default_factory=dict, hash=False, compare=False)

    @property
    def asset_path(self) -> str:
        return f"{ANIM_ROOT}/{self.group}/{self.name}.{self.name}"

    @property
    def frames(self) -> int:
        """Number of sampled frames, last frame included (a pose has one)."""
        return int(round(self.seconds * self.fps)) + 1


def _locomotion() -> list[Clip]:
    out = [
        Clip("A_Stand_Idle", "Locomotion", 4.0, True),
        Clip("A_Crouch_Idle", "Locomotion", 4.0, True),
        Clip("A_Prone_Idle", "Locomotion", 4.0, True),
    ]
    cycle = {"Stand": 0.6, "Crouch": 0.8, "Prone": 1.2}
    for stance, seconds in cycle.items():
        for tag, heading in HEADINGS.items():
            out.append(
                Clip(
                    f"A_{stance}_Move_{tag}",
                    "Locomotion",
                    seconds,
                    True,
                    params={"stance": stance, "heading": heading, "speed": SPEEDS[stance]},
                )
            )
    out += [
        Clip(
            "A_Sprint_F",
            "Locomotion",
            round(16 / 30, 4),
            True,
            params={"stance": "Sprint", "heading": 0.0, "speed": SPEEDS["Sprint"]},
        ),
        Clip("A_Jump_Start", "Locomotion", 0.3, False),
        Clip("A_Fall_Loop", "Locomotion", 1.0, True),
        Clip("A_Land", "Locomotion", 0.4, False),
        Clip("A_Slide", "Locomotion", SLIDE_SECONDS, False),
        Clip("A_Prone_Enter", "Locomotion", PRONE_ENTER, False),
        Clip("A_Prone_Exit", "Locomotion", PRONE_EXIT, False),
    ]
    for kind, (seconds, height, travel) in MANTLE.items():
        out.append(
            Clip(
                f"A_Mantle_{kind}",
                "Locomotion",
                seconds,
                False,
                root_motion=True,
                params={"height": height, "travel": travel},
            )
        )
    for stance in ("Stand", "Crouch"):
        for side in ("L", "R"):
            out.append(
                Clip(
                    f"A_{stance}_Lean_{side}",
                    "Locomotion",
                    0.0,
                    False,
                    params={"stance": stance, "side": side},
                )
            )
    return out


def _weapons() -> list[Clip]:
    out = []
    for cls, t in WEAPON_CLASSES.items():
        group = f"Weapons/{cls}"
        shot = 60.0 / t["rpm"]
        out += [
            Clip(f"A_{cls}_Idle", group, 2.0, True, WEAPON_FPS),
            Clip(f"A_{cls}_ADS", group, 2.0, True, WEAPON_FPS),
            Clip(f"A_{cls}_Fire", group, round(shot * 2, 4), False, WEAPON_FPS),
            Clip(f"A_{cls}_Reload_Tactical", group, t["tactical"], False, WEAPON_FPS),
            Clip(f"A_{cls}_Reload_Empty", group, t["empty"], False, WEAPON_FPS),
            Clip(f"A_{cls}_Equip", group, t["equip"], False, WEAPON_FPS),
            Clip(f"A_{cls}_Holster", group, t["holster"], False, WEAPON_FPS),
        ]
    group = "Weapons/Knife"
    out += [
        Clip("A_Knife_Idle", group, 2.0, True, WEAPON_FPS),
        Clip(
            "A_Knife_Strike",
            group,
            KNIFE["strike"],
            False,
            WEAPON_FPS,
            markers=(("Hit", KNIFE["hit"]),),
        ),
        Clip("A_Knife_Equip", group, KNIFE["equip"], False, WEAPON_FPS),
        Clip("A_Knife_Holster", group, KNIFE["holster"], False, WEAPON_FPS),
    ]
    return out


def _finisher() -> list[Clip]:
    return [
        Clip(
            f"A_Finisher_{role}",
            "Finisher",
            FINISHER_SECONDS,
            False,
            root_motion=True,
            markers=FINISHER_MARKERS,
            params={"role": role},
        )
        for role in ("Attacker", "Victim")
    ]


def _reactions() -> list[Clip]:
    out = [
        Clip(f"A_Death_{d}", "Reactions", 1.6, False, params={"from": d})
        for d in ("Front", "Back", "Left", "Right", "Head")
    ]
    out += [
        Clip(f"A_Hit_{z}", "Reactions", 0.5, False, params={"zone": z})
        for z in ("Head", "Torso_Front", "Torso_Back", "Arm_L", "Arm_R", "Leg_L", "Leg_R")
    ]
    out += [
        Clip("A_KillCam_Rifle_Fire", "Reactions", 1.0, True),
        Clip("A_KillCam_Rifle_Run", "Reactions", 0.6, True),
        Clip("A_KillCam_Pistol_Fire", "Reactions", 1.0, True),
    ]
    return out


#: Crew clips retargeted from the three.js crew set (`characters/anim.py`):
#: name -> (source clip, seconds, loop).
CREW_SOURCES = {
    "A_Crew_Stand": ("A_Idle", 6.0, True),
    "A_Crew_Walk": ("A_Walk", 1.0, True),
    "A_Crew_Sit_Idle": ("A_Sit_Idle", 6.0, True),
    "A_Crew_Sit_Type": ("A_Sit_Type", 4.0, True),
    "A_Crew_Stand_Type": ("A_Stand_Type", 4.0, True),
    "A_Crew_Talk": ("A_Talk", 6.0, True),
    "A_Crew_Listen": ("A_Listen", 6.0, True),
    "A_Crew_Sit_Down": ("A_Sit_Down", 1.2, False),
    "A_Crew_Stand_Up": ("A_Stand_Up", 1.2, False),
    "A_Crew_Bunk": ("A_Sleep", 6.0, True),
}


def _crew() -> list[Clip]:
    # Seconds are nominal; the authored length comes from the source clip.
    return [
        Clip(name, "Crew", seconds, loop, params={"source": src})
        for name, (src, seconds, loop) in CREW_SOURCES.items()
    ]


CLIPS: tuple[Clip, ...] = tuple(_locomotion() + _weapons() + _finisher() + _reactions() + _crew())
BY_NAME: dict[str, Clip] = {c.name: c for c in CLIPS}


def problems() -> list[str]:
    """Contract checks on the table itself (run by the unit tests)."""
    out = []
    names = [c.name for c in CLIPS]
    if len(set(names)) != len(names):
        out.append("duplicate clip names")
    for c in CLIPS:
        if len(c.name) > 64 or not c.name.startswith("A_"):
            out.append(f"{c.name}: breaks art-pipeline 3 naming")
        weapon = c.group.startswith("Weapons/")
        if weapon and c.fps != WEAPON_FPS:
            out.append(f"{c.name}: weapon clips sample at {WEAPON_FPS} fps")
        if not weapon and c.fps != BODY_FPS:
            out.append(f"{c.name}: body clips sample at {BODY_FPS} fps")
        for marker, time in c.markers:
            if not 0.0 <= time <= c.seconds + 1e-9:
                out.append(f"{c.name}: marker {marker} at {time} s outside the clip")
    for name in ("A_Finisher_Attacker", "A_Finisher_Victim"):
        c = BY_NAME[name]
        if c.markers != FINISHER_MARKERS or not c.root_motion:
            out.append(f"{name}: finisher markers or root motion")
    if skeleton.SKELETON != "SKEL_Verse_Human":
        out.append("skeleton name changed")
    return out
