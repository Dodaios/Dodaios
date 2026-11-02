"""Every clip of `catalogue.CLIPS`, authored as poses for `fps/solver.py`.

Runs inside Blender. Poses use the crew pose dict (`characters/posing.py`)
and the crew clip helpers (`characters/anim.py`, `anim_combat.py`), so the
locomotion, hit and crew clips keep the foot contacts and timing the three.js
crew already proved; weapon, finisher, mantle, slide and prone clips are new.

Blender axes: X = the character's left, -Y = forward, Z = up, metres, root
space (the root bone is the origin unless a pose sets ``root``).

Weapons: a weapon's frame W is "root-like": its bone Y axis is the weapon's
up, its Z axis the barrel (or blade). A weapon built like a character (its
`Root` bone up, the barrel towards the character's forward) therefore sits
correctly on `Weapon_R` / `Weapon_L` with an identity attachment. The right
hand's frame relative to W is fixed (`Fps.grip`), so every pose places the
weapon and the hand follows.
"""

from __future__ import annotations

import math

from mathutils import Matrix, Vector

from characters import anim as A
from characters import anim_combat as AC
from characters import common as C
from characters.anim import Body, ease, harm
from characters.anim_combat import _keyed, _lerp_spec, _lying, _norm, _planted, _spine
from characters.fps import catalogue as K

V = Vector
STOCK = 0.29
#: Right-hand finger curls on a pistol grip with the index on the trigger (degrees).
TRIGGER_GRIP = {"Index": 38.0, "Middle": 112.0, "Ring": 118.0, "Pinky": 118.0, "Thumb": 46.0}
SUPPORT_GRIP = {"Index": 70.0, "Middle": 86.0, "Ring": 92.0, "Pinky": 96.0, "Thumb": 30.0}
KNIFE_GRIP = {"Index": 104.0, "Middle": 112.0, "Ring": 116.0, "Pinky": 118.0, "Thumb": 52.0}
OPEN_HAND = {"Index": 14.0, "Middle": 16.0, "Ring": 18.0, "Pinky": 20.0, "Thumb": 10.0}
FIST_LOOSE = {"Index": 60.0, "Middle": 66.0, "Ring": 70.0, "Pinky": 72.0, "Thumb": 24.0}


def _rz(deg: float) -> Matrix:
    return Matrix.Rotation(math.radians(deg), 3, "Z")


def _rx(deg: float) -> Matrix:
    return Matrix.Rotation(math.radians(deg), 3, "X")


def axes(pitch: float = 0.0, yaw: float = 0.0, roll: float = 0.0):
    """(fwd, right, up) of an aim direction; pitch > 0 up, yaw > 0 to the left."""
    fwd = _rz(yaw) @ (_rx(-pitch) @ V((0.0, -1.0, 0.0)))
    right = _rz(yaw) @ V((-1.0, 0.0, 0.0))
    up = right.cross(fwd).normalized()
    if roll:
        r = Matrix.Rotation(math.radians(roll), 3, fwd)
        right, up = r @ right, r @ up
    return fwd.normalized(), right.normalized(), up.normalized()


def weapon_matrix(pos: Vector, fwd: Vector, up: Vector) -> Matrix:
    return C.frame_matrix(pos, up, fwd)


def _spec(m: Matrix, pole: Vector, fingers: float = 40.0, thumb: float = 20.0) -> dict:
    return {
        "target": tuple(m.translation),
        "pole": tuple(pole.normalized()),
        "hand_dir": tuple(m.col[1].xyz.normalized()),
        "dorsal": tuple(m.col[2].xyz.normalized()),
        "fingers": fingers,
        "thumb": thumb,
    }


def free_hand(target, hand_dir, dorsal, pole, fingers=14.0, thumb=10.0) -> dict:
    return {
        "target": tuple(target),
        "pole": tuple(V(pole).normalized()),
        "hand_dir": tuple(V(hand_dir).normalized()),
        "dorsal": tuple(V(dorsal).normalized()),
        "fingers": fingers,
        "thumb": thumb,
    }


class Fps:
    """Measurements and calibrated grips of one body variant."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.b = Body(ctx.rig)
        self.s = self.b.scale
        head = ctx.rig.rest["Head"]
        eye_r = min((V(e) for e in ctx.eyes), key=lambda e: e.x)
        self.eye_local = head.inverted() @ eye_r
        self.weapon: dict[str, Matrix] = {}
        self._calibrate()

    # ------------------------------------------------------------ calibration

    def solve(self, p: dict):
        return self.b.rig.solve(p)

    def eye(self, M) -> Vector:
        return M["Head"] @ self.eye_local

    def _calibrate(self) -> None:
        """Fix the right hand's grip frame and the support hands from the rifle hold
        of the crew duel clips (`anim_combat.hold_arms`), the pistol and the knife."""
        b, s = self.b, self.s
        p = AC.combat_stand(b, 0.0, 2.0, breathe=0.0)
        p.update(AC.hold_arms(b, p))
        M = self.solve(p)
        fwd, right, up = axes()
        sh = M["UpperArm_R"].translation
        grip = sh + V((0.03, -0.07, -0.05)) * s + fwd * (STOCK * s)
        W = weapon_matrix(grip, fwd, up)
        self.grip = M["Hand_R"].inverted() @ W  # hand -> weapon
        self.grip_inv = self.grip.inverted()
        self.support = {"Rifle": W.inverted() @ M["Hand_L"]}
        self.weapon["Rifle"] = W
        # Pistol: a two-hand grip, the left hand wrapped round the right.
        p = AC.combat_stand(b, 0.0, 2.0, breathe=0.0)
        Wp = self.weapon_frame(p, "Pistol", ads=1.0)
        hr = Wp @ self.grip_inv
        pos = hr.translation - right * (0.045 * s) + fwd * (0.012 * s) - up * (0.03 * s)
        hl = C.frame_matrix(pos, (fwd * 0.55 - right * 0.45 - up * 0.65), -right)
        self.support["Pistol"] = Wp.inverted() @ hl
        self.weapon["Pistol"] = Wp
        # Knife in the left hand (Weapon_L), blade forward, held low.
        p = AC.combat_stand(b, 0.0, 2.0, breathe=0.0)
        spec = self.knife_hand(p)
        M = self.solve({**p, "arm_L": spec, "arm_R": self.guard_hand(p)})
        hand = M["Hand_L"]
        K_ = weapon_matrix(hand @ V((0.0, 0.055 * s, 0.0)), fwd, up)
        self.knife_grip = hand.inverted() @ K_  # hand -> knife
        self.weapon["Knife"] = K_

    # ---------------------------------------------------------------- weapons

    def weapon_frame(
        self,
        p: dict,
        cls: str,
        ads: float = 0.0,
        pitch: float = 0.0,
        yaw: float = 0.0,
        roll: float = 0.0,
        kick: float = 0.0,
        offset: Vector | None = None,
    ) -> Matrix:
        s = self.s
        M = self.solve(p)
        fwd, right, up = axes(pitch + 2.5 * kick, yaw, roll)
        sh = M["UpperArm_R"].translation
        eye = self.eye(M)
        if cls == "Rifle":
            hip = sh + V((0.03, -0.07, -0.05)) * s + fwd * (STOCK * s)
            aim = eye + fwd * (0.14 * s) - up * (0.085 * s)
        else:
            hip = sh + V((0.15, -0.30, -0.16)) * s + fwd * (0.08 * s)
            aim = eye + fwd * (0.34 * s) - up * (0.07 * s) + V((0.03, 0.0, 0.0)) * s
        pos = hip.lerp(aim, ads) - fwd * (0.028 * kick * s)
        if offset is not None:
            pos = pos + offset * s
        return weapon_matrix(pos, fwd, up)

    def hold(
        self, p: dict, cls: str = "Rifle", support: float = 1.0, left: dict | None = None, **aim
    ) -> dict:
        """Put the weapon of `cls` in the right hand (and the left on its support)."""
        W = self.weapon_frame(p, cls, **aim)
        fwd = W.col[2].xyz
        up = W.col[1].xyz
        right = up.cross(fwd).normalized() * -1.0
        hr = W @ self.grip_inv
        p["arm_R"] = _spec(hr, right - up + fwd * 0.3, 48.0, 26.0)
        p["fingers_R"] = dict(TRIGGER_GRIP)
        hl = W @ self.support[cls]
        on = _spec(hl, -right * 0.6 - up, 40.0, 20.0)
        if left is not None and support < 1.0:
            on = _lerp_spec(_tuple_spec(left), on, support)
        p["arm_L"] = on
        p["fingers_L"] = _lerp_spec(OPEN_HAND, SUPPORT_GRIP, support)
        p["_weapon"] = W
        return p

    def at_weapon(self, W: Matrix, local) -> Vector:
        """A point given in the weapon frame (metres, scaled) in root space."""
        return (W @ V((*[x * self.s for x in local], 1.0))).xyz

    # ------------------------------------------------------------------ knife

    def knife_hand(self, p: dict, reach: float = 0.0, lift: float = 0.0, cut: float = 0.0) -> dict:
        s = self.s
        M = self.solve(p)
        sh = M["UpperArm_L"].translation
        target = sh + V((0.02, -0.30 - 0.32 * reach, -0.30 + 0.20 * lift + 0.08 * reach)) * s
        target = target + V((-0.12 * cut, 0.0, 0.0)) * s
        return free_hand(
            target,
            (0.15 - 0.4 * cut, -1.0, 0.25 + 0.2 * lift),
            (0.9, 0.0, 0.3),
            (0.6, 0.4, -1.0),
            50.0,
            26.0,
        )

    def guard_hand(self, p: dict, up: float = 0.0) -> dict:
        s = self.s
        M = self.solve(p)
        sh = M["UpperArm_R"].translation
        target = sh + V((0.10, -0.26, -0.22 + 0.12 * up)) * s
        return free_hand(
            target, (0.35, -0.6, 0.7), (-0.9, -0.1, 0.2), (-0.6, 0.4, -1.0), 30.0, 16.0
        )

    def knife(self, p: dict, **kw) -> dict:
        p["arm_L"] = self.knife_hand(p, **kw)
        p["arm_R"] = self.guard_hand(p)
        p["fingers_L"] = dict(KNIFE_GRIP)
        p["fingers_R"] = dict(FIST_LOOSE)
        return p


def _tuple_spec(spec: dict) -> dict:
    return {k: (tuple(v) if isinstance(v, (Vector, list)) else v) for k, v in spec.items()}


def _clean(p: dict) -> dict:
    q = dict(p)
    q.pop("_weapon", None)
    return q


def lerp_pose(a: dict, b: dict, k: float) -> dict:
    return _lerp_spec(_norm(_clean(a)), _norm(_clean(b)), k)


def keyed(keys, t):
    return _keyed([(kt, _norm(_clean(kp))) for kt, kp in keys], t)


def with_root(p: dict, x: float = 0.0, y: float = 0.0, z: float = 0.0, yaw: float = 0.0) -> dict:
    p["root"] = Matrix.Translation(V((x, y, z))) @ Matrix.Rotation(math.radians(yaw), 4, "Z")
    return p


# =================================================================== stances


def stand(F: Fps, t: float = 0.0, period: float = 4.0, crouch: float = 0.0, breathe=1.0) -> dict:
    return AC.combat_stand(F.b, t, period, crouch=crouch, breathe=breathe)


def crouch_pose(F: Fps, t: float = 0.0, period: float = 4.0) -> dict:
    p = stand(F, t, period, crouch=1.0)
    s = F.s
    p["hips"] = V(p["hips"]) + V((0.0, 0.03 * s, -0.20 * s))
    p["hips_rot"] = (p["hips_rot"][0] + 6.0, p["hips_rot"][1], p["hips_rot"][2])
    p["spine"] = _spine(bend=20.0, extra={"Neck": (-6.0, 0, 0), "Head": (-8.0, 0, 0)})
    feet = AC._stance_feet(F.b)
    p["leg_L"] = _planted(F.b, "L", feet["L"][0] * 1.3, feet["L"][1] * 1.9, feet["L"][2])
    p["leg_R"] = _planted(
        F.b, "R", feet["R"][0] * 1.3, feet["R"][1] * 1.4, feet["R"][2], pitch=20.0
    )
    return p


def prone_pose(
    F: Fps, t: float = 0.0, phase: float | None = None, heading: float = 0.0, breathe: float = 1.0
) -> dict:
    """Face down, the body along +Y from the chest, legs straight back (crawl when phased)."""
    s = F.s
    br = harm(t, 4.0, [(2, 1.0, 0.3)]) * breathe
    draw_l = draw_r = 0.0
    sway = 0.0
    if phase is not None:
        c = math.cos(2 * math.pi * phase)
        draw_l, draw_r = 0.5 * (1 + c), 0.5 * (1 - c)
        sway = math.sin(2 * math.pi * phase)
    side = math.sin(math.radians(heading))
    p = {
        "hips": V((0.03 * sway * s, 0.42 * s, 0.17 * s + 0.003 * br)),
        "hips_rot": (86.0, 4.0 * sway + 10.0 * side, 3.0 * sway),
        "spine": {
            "Spine": (2.0 + 0.6 * br, -3.0 * sway, -2.0 * sway),
            "Chest": (-6.0, -3.0 * sway, -2.0 * sway),
            "Neck": (-34.0, 0.0, 0.0),
            "Head": (-30.0, -10.0 * side, 0.0),
        },
        "shoulder_L": (8.0, 14.0),
        "shoulder_R": (8.0, 14.0),
    }
    for sd, draw in (("L", draw_l), ("R", draw_r)):
        sg = 1.0 if sd == "L" else -1.0
        straight = V((sg * 0.16 * s, 0.42 * s + F.b.leg * 0.98, 0.07 * s))
        drawn = V((sg * 0.34 * s, 0.42 * s + F.b.leg * 0.62, 0.11 * s))
        tgt = straight.lerp(drawn, draw) + V((-0.06 * side * s, 0.0, 0.0))
        p[f"leg_{sd}"] = {
            "target": tuple(tgt),
            "pole": tuple(V((sg * (0.2 + 0.8 * draw), 0.0, -1.0)).normalized()),
            "foot_dir": tuple(V((sg * 0.1, 0.35, -1.0)).normalized()),
            "foot_up": (0.0, 1.0, 0.0),
            "toe": 25.0,
        }
    return p


def rifle(F: Fps, p: dict, **aim) -> dict:
    return F.hold(p, "Rifle", **aim)


def lean_pose(F: Fps, stance: str, side: str) -> dict:
    sign = 1.0 if side == "L" else -1.0
    p = stand(F, breathe=0.0) if stance == "Stand" else crouch_pose(F)
    s = F.s
    p["hips"] = V(p["hips"]) + V((sign * 0.06 * s, 0.0, 0.0))
    extra = {
        "Spine": (0.0, 0.0, 9.0 * sign),
        "Chest": (0.0, 0.0, 9.0 * sign),
        "Neck": (0.0, 0.0, -4.0 * sign),
        "Head": (0.0, 0.0, -5.0 * sign),
    }
    base = p["spine"]
    p["spine"] = {k: tuple(a + b for a, b in zip(base[k], extra[k], strict=True)) for k in base}
    return rifle(F, p, roll=-6.0 * sign)


# ================================================================ locomotion


GAIT = {
    "Stand": {
        "n": 18,
        "speed": 4.5,
        "duty": 0.32,
        "lift": 0.13,
        "drop": 0.09,
        "lean": 7.0,
        "bob": 0.026,
    },
    "Crouch": {
        "n": 24,
        "speed": 2.2,
        "duty": 0.56,
        "lift": 0.07,
        "drop": 0.30,
        "lean": 14.0,
        "bob": 0.010,
    },
    "Sprint": {
        "n": 16,
        "speed": 6.5,
        "duty": 0.25,
        "lift": 0.17,
        "drop": 0.10,
        "lean": 14.0,
        "bob": 0.034,
    },
}


def gait(F: Fps, stance: str, heading: float) -> list[dict]:
    poses = AC.gait_clip(F.b, GAIT[stance], heading)
    out = []
    for p in poses:
        if stance == "Crouch":
            p["spine"] = _spine(
                bend=18.0, twist=0.0, lean=0.0, extra={"Neck": (-6.0, 0, 0), "Head": (-8.0, 0, 0)}
            )
        if stance == "Sprint":
            sp = p["spine"]
            sp["Chest"] = (sp["Chest"][0] + 4.0, sp["Chest"][1] + 6.0, sp["Chest"][2])
            out.append(rifle(F, p, pitch=-38.0, yaw=38.0, offset=V((0.10, 0.10, -0.10))))
        else:
            out.append(rifle(F, p))
    return out


def prone_move(F: Fps, clip: K.Clip) -> list[dict]:
    out = []
    for f in range(clip.frames):
        ph = f / (clip.frames - 1)
        p = prone_pose(F, ph * clip.seconds, ph, clip.params["heading"])
        crawl = math.sin(2 * math.pi * ph)
        out.append(rifle(F, p, pitch=4.0, offset=V((0.0, -0.05 * crawl, 0.0))))
    return out


def idle(F: Fps, clip: K.Clip, stance: str) -> list[dict]:
    out = []
    for f in range(clip.frames):
        t = f / clip.fps
        if stance == "Stand":
            p = stand(F, t, clip.seconds)
        elif stance == "Crouch":
            p = crouch_pose(F, t, clip.seconds)
        else:
            p = prone_pose(F, t)
        sway = harm(t, clip.seconds, [(1, 0.8, 0.6)])
        out.append(rifle(F, p, pitch=0.5 * sway, yaw=0.3 * sway))
    out[-1] = out[0]
    return out


def jump_start(F: Fps, clip: K.Clip) -> list[dict]:
    s = F.s
    k0 = rifle(F, stand(F, breathe=0.0))
    k1 = stand(F, breathe=0.0, crouch=0.5)
    k1["hips"] = V(k1["hips"]) + V((0.0, 0.02 * s, -0.08 * s))
    k1 = rifle(F, k1, pitch=-4.0)
    k2 = fall_pose(F, 0.0)
    keys = [(0.0, k0), (0.12, k1), (clip.seconds, k2)]
    return [keyed(keys, f / clip.fps) for f in range(clip.frames)]


def fall_pose(F: Fps, t: float) -> dict:
    s = F.s
    w = math.sin(2 * math.pi * t)
    p = stand(F, breathe=0.0)
    p["hips"] = V((0.0, 0.02 * s, F.b.hips.z - 0.02 * s))
    p["hips_rot"] = (8.0, AC.BLADE["hips"], 1.5 * w)
    p["spine"] = _spine(bend=6.0 + 1.5 * w)
    for sd, fwd in (("L", -0.10), ("R", 0.08)):
        sg = 1.0 if sd == "L" else -1.0
        p[f"leg_{sd}"] = {
            "target": (sg * 0.13 * s, (fwd + 0.02 * w * sg) * s, F.b.ankle.z + 0.16 * s),
            "pole": (sg * 0.15, -1.0, 0.2),
            "foot_dir": tuple(V((0.0, -0.55, -0.83)).normalized()),
            "foot_up": (0.0, 0.0, 1.0),
            "toe": 10.0,
        }
    return rifle(F, p, pitch=2.0 * w)


def fall_loop(F: Fps, clip: K.Clip) -> list[dict]:
    out = [fall_pose(F, f / clip.fps) for f in range(clip.frames)]
    out[-1] = out[0]
    return out


def land(F: Fps, clip: K.Clip) -> list[dict]:
    s = F.s
    k0 = fall_pose(F, 0.0)
    k0["leg_L"] = _planted(F.b, "L", 0.13 * s, -0.10 * s, -8.0)
    k0["leg_R"] = _planted(F.b, "R", 0.13 * s, 0.10 * s, -30.0)
    k1 = stand(F, breathe=0.0, crouch=0.8)
    k1["hips"] = V(k1["hips"]) + V((0.0, 0.03 * s, -0.12 * s))
    k1["spine"] = _spine(bend=22.0)
    k1 = rifle(F, k1, pitch=-8.0)
    k2 = rifle(F, stand(F, breathe=0.0))
    keys = [(0.0, k0), (0.09, k1), (clip.seconds, k2)]
    return [keyed(keys, f / clip.fps) for f in range(clip.frames)]


def slide_pose(F: Fps, t: float) -> dict:
    s = F.s
    shake = 0.4 * math.sin(t * 37.0)
    p = {
        "hips": V((0.0, 0.10 * s, 0.36 * s)),
        "hips_rot": (-16.0, -12.0, 4.0 + shake),
        "spine": {
            "Spine": (12.0, -4.0, 0.0),
            "Chest": (14.0, -4.0, 0.0),
            "Neck": (-4.0, 8.0, 0.0),
            "Head": (-6.0, 10.0, 0.0),
        },
        "shoulder_L": (0.0, 4.0),
        "shoulder_R": (0.0, 0.0),
        "leg_L": {
            "target": (0.11 * s, -0.56 * s, 0.10 * s),
            "pole": (0.1, -0.3, 1.0),
            "foot_dir": tuple(V((0.05, -0.55, 0.83)).normalized()),
            "foot_up": tuple(V((0.0, 0.83, 0.55)).normalized()),
            "toe": 0.0,
        },
        "leg_R": {
            "target": (-0.22 * s, 0.32 * s, 0.11 * s),
            "pole": (-0.5, -0.7, -0.5),
            "foot_dir": tuple(V((-0.15, 0.9, -0.4)).normalized()),
            "foot_up": (0.0, 0.0, 1.0),
            "toe": 20.0,
        },
    }
    return rifle(F, p, pitch=1.0, yaw=4.0)


def slide(F: Fps, clip: K.Clip) -> list[dict]:
    k0 = gait(F, "Sprint", 0.0)[0]
    k3 = rifle(F, crouch_pose(F))
    out = []
    for f in range(clip.frames):
        t = f / clip.fps
        sp = slide_pose(F, t)
        if t < 0.15:
            out.append(lerp_pose(k0, sp, ease(t / 0.15)))
        elif t < 0.80:
            out.append(sp)
        else:
            out.append(lerp_pose(sp, k3, ease((t - 0.80) / (clip.seconds - 0.80))))
    return out


def kneel_pose(F: Fps) -> dict:
    s = F.s
    p = stand(F, breathe=0.0)
    p["hips"] = V((0.0, 0.30 * s, 0.52 * s))
    p["hips_rot"] = (14.0, -10.0, 0.0)
    p["spine"] = _spine(bend=12.0)
    p["leg_L"] = _planted(F.b, "L", 0.14 * s, -0.02 * s, -8.0)
    p["leg_R"] = {
        "target": (-0.13 * s, 0.66 * s, 0.13 * s),
        "pole": (-0.05, -1.0, -0.6),
        "foot_dir": tuple(V((0.0, 0.35, -0.94)).normalized()),
        "foot_up": (0.0, 1.0, 0.0),
        "toe": 30.0,
    }
    return p


def prone_transition(F: Fps, clip: K.Clip, enter: bool) -> list[dict]:
    s = F.s
    a = rifle(F, stand(F, breathe=0.0))
    k = rifle(F, kneel_pose(F), pitch=-20.0)
    hands = prone_pose(F, breathe=0.0)
    hands["hips"] = V((0.0, 0.42 * s, 0.36 * s))
    hands["hips_rot"] = (60.0, 0.0, 0.0)
    hands = rifle(F, hands, pitch=-10.0)
    z = rifle(F, prone_pose(F, breathe=0.0))
    T = clip.seconds
    keys = [(0.0, a), (0.36 * T, k), (0.68 * T, hands), (T, z)]
    if not enter:
        keys = [(T - kt, kp) for kt, kp in reversed(keys)]
    return [keyed(keys, f / clip.fps) for f in range(clip.frames)]


def mantle(F: Fps, clip: K.Clip) -> list[dict]:
    """Root motion over a ledge: the left hand plants on the edge, the knees tuck."""
    s = F.s
    T = clip.seconds
    height, travel = clip.params["height"], clip.params["travel"]
    edge = V((0.16 * s, -0.34 * s, height))
    k0 = rifle(F, stand(F, breathe=0.0))
    tuck = stand(F, breathe=0.0, crouch=0.8)
    tuck["hips"] = V((0.0, 0.10 * s, 0.58 * s))
    tuck["hips_rot"] = (26.0, -10.0, 0.0)
    tuck["spine"] = _spine(bend=26.0)
    for sd in ("L", "R"):
        sg = 1.0 if sd == "L" else -1.0
        tuck[f"leg_{sd}"] = {
            "target": (sg * 0.13 * s, 0.18 * s, 0.24 * s),
            "pole": (sg * 0.2, -1.0, 0.3),
            "foot_dir": tuple(V((0.0, -0.6, -0.8)).normalized()),
            "foot_up": (0.0, 0.0, 1.0),
            "toe": 10.0,
        }
    tuck = rifle(F, tuck, pitch=-30.0, yaw=25.0, offset=V((0.10, 0.10, -0.08)))
    k2 = rifle(F, crouch_pose(F))
    k3 = rifle(F, stand(F, breathe=0.0))
    out = []
    for f in range(clip.frames):
        t = f / clip.fps
        u = t / T
        z = height * ease(min(1.0, u / 0.62))
        y = -travel * ease(max(0.0, (u - 0.22) / 0.78))
        if u < 0.45:
            p = lerp_pose(k0, tuck, ease(u / 0.45))
        elif u < 0.8:
            p = lerp_pose(tuck, k2, ease((u - 0.45) / 0.35))
        else:
            p = lerp_pose(k2, k3, ease((u - 0.8) / 0.2))
        p = _norm(p)
        # The rifle rides one-handed; the left hand plants on the edge until 75 %.
        p = rifle(
            F,
            p,
            pitch=-30.0 * math.sin(math.pi * min(1.0, u * 1.2)),
            yaw=20.0,
            support=0.0 if 0.08 < u < 0.75 else 1.0,
            left=free_hand(
                edge - V((0.0, y, z)) + V((0.0, 0.03 * s, 0.04 * s)),
                (0.0, -1.0, -0.25),
                (0.0, 0.1, 1.0),
                (0.8, 0.5, -0.3),
                18.0,
                12.0,
            ),
        )
        out.append(with_root(p, 0.0, y, z))
    return out


# =================================================================== weapons


def _gun_clip(F: Fps, clip: K.Clip, cls: str, fn) -> list[dict]:
    """Frames of a weapon clip: `fn(t, base pose) -> pose` on the standing base."""
    out = []
    for f in range(clip.frames):
        t = f / clip.fps
        out.append(fn(t, stand(F, t, 4.0, breathe=0.6)))
    return out


def weapon_idle(F: Fps, clip: K.Clip, cls: str, ads: float) -> list[dict]:
    def fn(t, p):
        sway = harm(t, clip.seconds, [(1, 1.0, 0.0), (2, 0.3, 1.1)]) * (0.35 if ads else 0.8)
        return F.hold(p, cls, ads=ads, pitch=0.6 * sway, yaw=0.4 * sway)

    out = _gun_clip(F, clip, cls, fn)
    out[-1] = out[0]
    return out


def weapon_fire(F: Fps, clip: K.Clip, cls: str) -> list[dict]:
    period = 60.0 / K.WEAPON_CLASSES[cls]["rpm"]

    def fn(t, p):
        x = t % period
        k = (x / 0.012) if x < 0.012 else math.exp(-(x - 0.012) / 0.035)
        return F.hold(p, cls, kick=k * (1.0 if cls == "Rifle" else 1.6))

    return _gun_clip(F, clip, cls, fn)


def reload(F: Fps, clip: K.Clip, cls: str, empty: bool) -> tuple[list[dict], list]:
    """Tactical or empty reload; returns (poses, OffHandIK curve keys)."""
    s = F.s
    T = clip.seconds
    if cls == "Rifle":
        mag = (0.0, -0.13, 0.10)  # weapon frame: x, up (bone Y), barrel (bone Z)
        bolt = (-0.05, 0.05, -0.04)
    else:
        mag = (0.0, -0.11, -0.01)
        bolt = (0.0, 0.04, 0.03)
    pouch = V((0.20 * s, -0.04 * s, F.b.hips.z + 0.02 * s))
    if empty:
        beats = [
            (0.0, "on"),
            (0.10, "tilt"),
            (0.18, "mag"),
            (0.30, "out"),
            (0.42, "pouch"),
            (0.54, "under"),
            (0.62, "in"),
            (0.72, "bolt"),
            (0.80, "bolt_back"),
            (0.90, "on"),
            (1.0, "on"),
        ]
    else:
        beats = [
            (0.0, "on"),
            (0.12, "tilt"),
            (0.22, "mag"),
            (0.38, "out"),
            (0.52, "pouch"),
            (0.66, "under"),
            (0.76, "in"),
            (0.90, "on"),
            (1.0, "on"),
        ]
    tilt_of = {
        "on": 0.0,
        "tilt": 1.0,
        "mag": 1.0,
        "out": 1.0,
        "pouch": 0.8,
        "under": 1.0,
        "in": 1.0,
        "bolt": 0.6,
        "bolt_back": 0.6,
    }

    def left_target(name: str, W: Matrix) -> dict:
        fwd = W.col[2].xyz
        up = W.col[1].xyz
        left = fwd.cross(up).normalized()
        if name in ("mag", "under", "in"):
            push = {"mag": 0.0, "under": -0.07, "in": 0.0}[name]
            tgt = F.at_weapon(W, (mag[0], mag[1] - 0.06 + push, mag[2] - 0.02)) + left * 0.03 * s
            return free_hand(tgt, up * 0.85 + fwd * 0.3, left, (0.6, 0.2, -1.0), 70.0, 30.0)
        if name == "out":
            tgt = F.at_weapon(W, (mag[0], mag[1] - 0.20, mag[2] - 0.06)) + left * 0.05 * s
            return free_hand(tgt, up * 0.6 + fwd * 0.3, left, (0.6, 0.2, -1.0), 70.0, 30.0)
        if name == "pouch":
            return free_hand(
                pouch, (0.1, -0.2, -1.0), (1.0, 0.0, 0.0), (0.6, 0.6, -0.2), 60.0, 24.0
            )
        if name in ("bolt", "bolt_back"):
            back = 0.07 if name == "bolt_back" else 0.0
            tgt = F.at_weapon(W, (bolt[0], bolt[1] + 0.04, bolt[2] - back))
            return free_hand(tgt, fwd * 0.4 - up * 0.6, up, (0.6, 0.4, -1.0), 60.0, 30.0)
        raise KeyError(name)

    out, curve = [], []
    for f in range(clip.frames):
        t = f / clip.fps
        u = t / T
        i = max(j for j, (b0, _) in enumerate(beats) if b0 <= u + 1e-9)
        i = min(i, len(beats) - 2)
        (u0, n0), (u1, n1) = beats[i], beats[i + 1]
        k = ease((u - u0) / max(1e-6, u1 - u0))
        tilt = C.lerp(tilt_of[n0], tilt_of[n1], k)
        base = stand(F, t, 4.0, breathe=0.6)
        aim = {
            "pitch": 8.0 * tilt,
            "yaw": 10.0 * tilt,
            "roll": 22.0 * tilt,
            "offset": V((0.06, 0.04, -0.03)) * tilt,
        }
        W = F.weapon_frame(base, cls, **aim)
        specs = [None if n in ("on", "tilt") else _tuple_spec(left_target(n, W)) for n in (n0, n1)]
        if specs[0] is None and specs[1] is None:
            p = F.hold(base, cls, **aim)
            ik = 1.0
        elif specs[0] is None:
            p = F.hold(base, cls, support=1.0 - k, left=specs[1], **aim)
            ik = 1.0 - k
        elif specs[1] is None:
            p = F.hold(base, cls, support=k, left=specs[0], **aim)
            ik = k
        else:
            p = F.hold(base, cls, support=0.0, left=_lerp_spec(specs[0], specs[1], k), **aim)
            ik = 0.0
        if n0 in ("mag", "out", "under", "in") or n1 in ("mag", "out", "under", "in"):
            p["fingers_L"] = dict(SUPPORT_GRIP)
        out.append(p)
        curve.append((round(t, 5), round(ik, 4)))
    return out, curve


def equip(F: Fps, clip: K.Clip, cls: str, holster: bool) -> list[dict]:
    T = clip.seconds
    out = []
    for f in range(clip.frames):
        t = f / clip.fps
        u = t / T
        k = ease(1.0 - u) if holster else ease(u)
        base = stand(F, t, 4.0, breathe=0.6)
        if cls == "Rifle":
            aim = {
                "pitch": -58.0 * (1 - k),
                "yaw": 42.0 * (1 - k),
                "offset": V((0.12, 0.12, -0.14)) * (1 - k),
            }
        else:
            aim = {
                "pitch": -80.0 * (1 - k),
                "yaw": 0.0,
                "offset": V((-0.10, 0.18, -0.30)) * (1 - k),
            }
        out.append(F.hold(base, cls, support=k, left=_tuple_spec(_hang(F, base)), **aim))
    return out


def _hang(F: Fps, p: dict) -> dict:
    s = F.s
    M = F.solve(p)
    sh = M["UpperArm_L"].translation
    return free_hand(
        sh + V((0.06, -0.06, -0.52)) * s,
        (0.05, -0.05, -1.0),
        (1.0, 0.1, 0.0),
        (0.25, 1.0, 0.0),
        14.0,
        10.0,
    )


def knife_idle(F: Fps, clip: K.Clip) -> list[dict]:
    out = []
    for f in range(clip.frames):
        t = f / clip.fps
        p = stand(F, t, clip.seconds, breathe=0.8)
        sway = harm(t, clip.seconds, [(1, 1.0, 0.0)])
        out.append(F.knife(p, lift=0.05 * sway))
    out[-1] = out[0]
    return out


def knife_strike(F: Fps, clip: K.Clip) -> list[dict]:
    hit = K.KNIFE["hit"]
    out = []
    for f in range(clip.frames):
        t = f / clip.fps
        p = stand(F, t, 4.0, breathe=0.0)
        if t < 0.06:
            reach, lift, cut = -0.25 * ease(t / 0.06), 0.15 * ease(t / 0.06), -0.3 * ease(t / 0.06)
        elif t < hit:
            k = ease((t - 0.06) / (hit - 0.06))
            reach, lift, cut = C.lerp(-0.25, 1.0, k), C.lerp(0.15, 0.35, k), C.lerp(-0.3, 1.0, k)
        elif t < 0.25:
            reach, lift, cut = 1.0, 0.35, 1.0
        else:
            k = ease((t - 0.25) / (clip.seconds - 0.25))
            reach, lift, cut = C.lerp(1.0, 0.0, k), C.lerp(0.35, 0.0, k), C.lerp(1.0, 0.0, k)
        twist = 14.0 * max(0.0, min(1.0, reach))
        p["spine"] = _spine(bend=6.0 + 6.0 * max(0.0, reach), twist=twist)
        out.append(F.knife(p, reach=reach, lift=lift, cut=cut))
    return out


def knife_equip(F: Fps, clip: K.Clip, holster: bool) -> list[dict]:
    s = F.s
    out = []
    for f in range(clip.frames):
        t = f / clip.fps
        k = ease(1.0 - t / clip.seconds) if holster else ease(t / clip.seconds)
        p = stand(F, t, 4.0, breathe=0.0)
        hold = F.knife(dict(p))
        sheath = free_hand(
            V((0.17 * s, 0.02 * s, F.b.hips.z - 0.02 * s)),
            (0.0, 0.1, -1.0),
            (1.0, 0.0, 0.0),
            (0.5, 0.8, 0.0),
            90.0,
            40.0,
        )
        p["arm_L"] = _lerp_spec(_tuple_spec(sheath), _tuple_spec(hold["arm_L"]), k)
        p["arm_R"] = _lerp_spec(_tuple_spec(_hang_r(F, p)), _tuple_spec(hold["arm_R"]), k)
        p["fingers_L"] = dict(KNIFE_GRIP)
        p["fingers_R"] = _lerp_spec(OPEN_HAND, FIST_LOOSE, k)
        out.append(p)
    return out


def _hang_r(F: Fps, p: dict) -> dict:
    s = F.s
    M = F.solve(p)
    sh = M["UpperArm_R"].translation
    return free_hand(
        sh + V((-0.06, -0.06, -0.52)) * s,
        (-0.05, -0.05, -1.0),
        (-1.0, 0.1, 0.0),
        (-0.25, 1.0, 0.0),
        14.0,
        10.0,
    )


# ================================================================== finisher


def finisher(F: Fps, clip: K.Clip) -> list[dict]:
    """Paired 2.5 s finisher (combat-state 7.4). Both clips start with the victim
    `FINISHER_VICTIM_OFFSET_CM` ahead of the attacker, facing the same way; the
    victim is thrown on its back and the attacker kneels at its head."""
    s = F.s
    off = V((0.0, -K.FINISHER_VICTIM_OFFSET_CM[0] / 100.0, 0.0))  # victim root, attacker space
    lying = _norm(_lying(F.b))
    lying["fingers_L"] = dict(OPEN_HAND)
    lying["fingers_R"] = dict(OPEN_HAND)
    M = F.solve(lying)
    throat_a = M["Neck"].translation + off
    chest_a = M["Chest"].translation + off
    if clip.params["role"] == "Victim":
        return _victim(F, clip, lying)
    kneel_y = throat_a.y + 0.50 * s
    T = {name: t for name, t in K.FINISHER_MARKERS}
    start = F.knife(stand(F, breathe=0.0))
    start["fingers_R"] = dict(OPEN_HAND)
    lock = stand(F, breathe=0.0)
    lock["hips"] = V(lock["hips"]) + V((0.0, -0.06 * s, -0.04 * s))
    lock["spine"] = _spine(bend=10.0)
    head_v = V((0.0, off.y + 0.02, 1.55 * s))
    lock = F.knife(lock, reach=0.2)
    lock["arm_R"] = free_hand(
        head_v + V((-0.03, 0.08, -0.06)) * s,
        (0.3, -0.6, 0.2),
        (0.0, 0.1, 1.0),
        (-0.8, 0.3, -0.4),
        60.0,
        30.0,
    )
    lock["fingers_R"] = dict(FIST_LOOSE)
    kneel = kneel_pose(F)
    kneel["hips_rot"] = (30.0, 0.0, 0.0)
    kneel["spine"] = {
        "Spine": (18.0, 0, 0),
        "Chest": (16.0, 0, 0),
        "Neck": (-8.0, 0, 0),
        "Head": (-6.0, 0, 0),
    }

    def kneel_at(knife_t: Vector, pin: Vector) -> dict:
        p = dict(kneel)
        root_shift = V((0.0, kneel_y, 0.0))
        p["arm_L"] = free_hand(
            knife_t - root_shift, (0.1, -0.2, -1.0), (1.0, 0.0, 0.0), (0.8, 0.3, -0.6), 52.0, 26.0
        )
        p["arm_R"] = free_hand(
            pin - root_shift, (0.0, -0.4, -0.9), (-0.2, 0.0, 1.0), (-0.8, 0.3, -0.6), 30.0, 16.0
        )
        p["fingers_L"] = dict(KNIFE_GRIP)
        p["fingers_R"] = dict(OPEN_HAND)
        return p

    raised = kneel_at(throat_a + V((0.10, 0.10, 0.55)) * s, chest_a + V((0.0, 0.0, 0.10)) * s)
    struggle = kneel_at(throat_a + V((0.10, 0.12, 0.42)) * s, chest_a + V((0.0, 0.0, 0.10)) * s)
    strike = kneel_at(throat_a + V((0.0, 0.0, 0.06)) * s, chest_a + V((0.0, 0.0, 0.10)) * s)
    rise = F.knife(stand(F, breathe=0.0))
    keys = [
        (0.0, (0.0, start)),
        (T["Takedown"], (-0.04, lock)),
        (T["Struggle"], (kneel_y, raised)),
        (T["Kill"], (kneel_y, struggle)),
        (T["Kill"] + 0.2, (kneel_y, strike)),
        (T["Recover"], (kneel_y, strike)),
        (T["Release"], (kneel_y, rise)),
    ]
    out = []
    for f in range(clip.frames):
        t = f / clip.fps
        y = _keyed([(kt, {"y": v[0]}) for kt, v in keys], t)["y"]
        p = keyed([(kt, v[1]) for kt, v in keys], t)
        if T["Struggle"] < t < T["Kill"]:
            shake = math.sin(t * 23.0) * 0.012 * s
            p["arm_R"] = dict(p["arm_R"], target=tuple(V(p["arm_R"]["target"]) + V((shake, 0, 0))))
        out.append(with_root(p, 0.0, y, 0.0))
    return out


def _victim(F: Fps, clip: K.Clip, lying: dict) -> list[dict]:
    s = F.s
    T = {name: t for name, t in K.FINISHER_MARKERS}
    start = stand(F, breathe=0.0)
    start["arm_L"] = _hang(F, start)
    start["arm_R"] = _hang_r(F, start)
    start["fingers_L"] = dict(OPEN_HAND)
    start["fingers_R"] = dict(OPEN_HAND)
    caught = dict(start)
    caught["hips"] = V(start["hips"]) + V((0.0, 0.06 * s, -0.03 * s))
    caught["spine"] = _spine(bend=-10.0, extra={"Neck": (-10.0, 0, 0), "Head": (-14.0, 0, 0)})
    M = F.solve(caught)
    face = M["Head"].translation + V((0.0, -0.08, 0.0)) * s
    caught["arm_L"] = free_hand(
        face + V((0.10, 0.02, -0.08)) * s,
        (-0.4, 0.2, 0.9),
        (0.8, -0.4, 0.0),
        (0.8, -0.2, -0.6),
        50.0,
        20.0,
    )
    caught["arm_R"] = free_hand(
        face + V((-0.10, 0.02, -0.08)) * s,
        (0.4, 0.2, 0.9),
        (-0.8, -0.4, 0.0),
        (-0.8, -0.2, -0.6),
        50.0,
        20.0,
    )
    falling = stand(F, breathe=0.0, crouch=0.6)
    falling["hips"] = V((0.0, 0.30 * s, 0.55 * s))
    falling["hips_rot"] = (-35.0, -6.0, 0.0)
    falling["spine"] = _spine(bend=-12.0)
    falling["arm_L"] = caught["arm_L"]
    falling["arm_R"] = caught["arm_R"]
    fight = dict(lying)
    M = F.solve(lying)
    neck = M["Neck"].translation
    fight["arm_L"] = free_hand(
        neck + V((0.08, 0.05, 0.22)) * s,
        (0.0, 0.3, 1.0),
        (1.0, 0.0, 0.0),
        (0.8, 0.0, -0.5),
        60.0,
        24.0,
    )
    fight["arm_R"] = free_hand(
        neck + V((-0.08, 0.05, 0.24)) * s,
        (0.0, 0.3, 1.0),
        (-1.0, 0.0, 0.0),
        (-0.8, 0.0, -0.5),
        60.0,
        24.0,
    )
    keys = [
        (0.0, start),
        (T["Takedown"], caught),
        (0.55, falling),
        (T["Struggle"], fight),
        (T["Kill"], fight),
        (T["Recover"], lying),
        (T["Release"], lying),
    ]
    out = []
    for f in range(clip.frames):
        t = f / clip.fps
        p = keyed(keys, t)
        if T["Struggle"] < t < T["Recover"]:
            w = math.sin(t * 19.0) * 0.02 * s
            for sd in ("arm_L", "arm_R"):
                p[sd] = dict(p[sd], target=tuple(V(p[sd]["target"]) + V((w, 0.0, w))))
        out.append(with_root(p))
    return out


# ================================================================= reactions


def death(F: Fps, clip: K.Clip) -> list[dict]:
    s = F.s
    d = clip.params["from"]
    k0 = rifle(F, stand(F, breathe=0.0))
    jolt = stand(F, breathe=0.0)
    back = {"Front": 1.0, "Back": -1.0, "Left": 0.0, "Right": 0.0, "Head": 0.4}[d]
    side = {"Left": -1.0, "Right": 1.0}.get(d, 0.0)
    jolt["hips"] = V(jolt["hips"]) + V((0.05 * side, 0.05 * back, -0.02)) * s
    jolt["spine"] = _spine(
        bend=-14.0 * back,
        lean=10.0 * side,
        extra={"Head": (-18.0 * back - (25.0 if d == "Head" else 0.0), 0, 0)},
    )
    jolt = rifle(F, jolt, pitch=-20.0)
    buckle = stand(F, breathe=0.0, crouch=0.8)
    buckle["hips"] = V((0.0, 0.10 * back * s, 0.55 * s))
    buckle["spine"] = _spine(
        bend=-8.0 * back + (20.0 if d in ("Back", "Head") else 0.0), lean=14.0 * side
    )
    buckle["arm_L"] = _hang(F, buckle)
    buckle["arm_R"] = _hang_r(F, buckle)
    buckle["fingers_L"] = dict(OPEN_HAND)
    buckle["fingers_R"] = dict(OPEN_HAND)
    if d in ("Front", "Left", "Right"):
        down = _norm(_lying(F.b))
        if side:
            down["hips_rot"] = (-90.0, -10.0 + 60.0 * side, 4.0)
    else:
        down = prone_pose(F, breathe=0.0)
        down["arm_L"] = free_hand(
            V((0.38 * s, -0.10 * s, 0.06 * s)),
            (0.3, -0.7, -0.1),
            (0.0, 0.0, 1.0),
            (0.3, 0.2, -1.0),
            30.0,
            15.0,
        )
        down["arm_R"] = free_hand(
            V((-0.40 * s, 0.15 * s, 0.06 * s)),
            (-0.3, 0.6, -0.1),
            (0.0, 0.0, 1.0),
            (-0.3, 0.2, -1.0),
            30.0,
            15.0,
        )
    down["fingers_L"] = dict(OPEN_HAND)
    down["fingers_R"] = dict(OPEN_HAND)
    keys = [(0.0, k0), (0.10, jolt), (0.45, buckle), (0.95, down), (clip.seconds, down)]
    return [keyed(keys, f / clip.fps) for f in range(clip.frames)]


def hit(F: Fps, clip: K.Clip) -> list[dict]:
    zone = clip.params["zone"]
    side = {
        "Head": "F",
        "Torso_Front": "F",
        "Torso_Back": "B",
        "Arm_L": "L",
        "Arm_R": "R",
        "Leg_L": "L",
        "Leg_R": "R",
    }[zone]
    src = AC.hit_clip(F.b, side)
    out = []
    for f in range(clip.frames):
        t = f / clip.fps
        p = dict(src[min(f, len(src) - 1)])
        p["spine"] = dict(p["spine"])
        env = AC._flinch_env(t)
        if zone == "Head":
            h = p["spine"]["Head"]
            p["spine"]["Head"] = (h[0] - 14.0 * env, h[1] + 6.0 * env, h[2])
        if zone.startswith("Leg"):
            sd = zone[-1]
            p["hips"] = V(p["hips"]) + V((0.0, 0.0, -0.05 * F.s * max(0.0, env)))
            leg = dict(p[f"leg_{sd}"])
            leg["target"] = tuple(V(leg["target"]) + V((0.0, -0.03, 0.0)) * max(0.0, env))
            p[f"leg_{sd}"] = leg
        kick = max(0.0, env) * (0.6 if zone.startswith("Arm") else 0.3)
        out.append(rifle(F, p, pitch=-6.0 * kick, yaw=8.0 * kick * (1 if side == "L" else -1)))
    return out


def killcam(F: Fps, clip: K.Clip) -> list[dict]:
    if clip.name == "A_KillCam_Rifle_Run":
        return gait(F, "Stand", 0.0)
    cls = "Rifle" if "Rifle" in clip.name else "Pistol"
    period = 60.0 / K.WEAPON_CLASSES[cls]["rpm"] if cls == "Rifle" else 0.5
    out = []
    for f in range(clip.frames):
        t = f / clip.fps
        x = t % period
        k = (x / 0.012) if x < 0.012 else math.exp(-(x - 0.012) / 0.035)
        out.append(F.hold(stand(F, t, clip.seconds, breathe=0.4), cls, ads=0.4, kick=k))
    out[-1] = out[0]
    return out


# ====================================================================== crew


def crew(F: Fps, clip: K.Clip) -> list[dict]:
    fn, _loop = A.CLIPS[clip.params["source"]]
    return fn(F.b)


# ================================================================== registry


def author(F: Fps, clip: K.Clip) -> tuple[list[dict], dict]:
    """(poses, float curves {name: [(t, v)]}) of one catalogue clip."""
    n = clip.name
    g = clip.group
    curves: dict[str, list] = {}
    if n == "A_Stand_Idle":
        poses = idle(F, clip, "Stand")
    elif n == "A_Crouch_Idle":
        poses = idle(F, clip, "Crouch")
    elif n == "A_Prone_Idle":
        poses = idle(F, clip, "Prone")
    elif "_Move_" in n or n == "A_Sprint_F":
        stance = clip.params["stance"]
        if stance == "Prone":
            poses = prone_move(F, clip)
        else:
            poses = gait(F, stance, clip.params["heading"])
    elif n == "A_Jump_Start":
        poses = jump_start(F, clip)
    elif n == "A_Fall_Loop":
        poses = fall_loop(F, clip)
    elif n == "A_Land":
        poses = land(F, clip)
    elif n == "A_Slide":
        poses = slide(F, clip)
    elif n in ("A_Prone_Enter", "A_Prone_Exit"):
        poses = prone_transition(F, clip, n.endswith("Enter"))
    elif n.startswith("A_Mantle_"):
        poses = mantle(F, clip)
    elif "_Lean_" in n:
        poses = [lean_pose(F, clip.params["stance"], clip.params["side"])] * clip.frames
    elif g in ("Weapons/Rifle", "Weapons/Pistol"):
        cls = g.split("/")[1]
        what = n.split(f"A_{cls}_", 1)[1]
        if what in ("Idle", "ADS"):
            poses = weapon_idle(F, clip, cls, 1.0 if what == "ADS" else 0.0)
        elif what == "Fire":
            poses = weapon_fire(F, clip, cls)
        elif what.startswith("Reload_"):
            poses, curve = reload(F, clip, cls, what.endswith("Empty"))
            curves["OffHandIK"] = curve
        elif what in ("Equip", "Holster"):
            poses = equip(F, clip, cls, what == "Holster")
        else:
            raise KeyError(n)
    elif n == "A_Knife_Idle":
        poses = knife_idle(F, clip)
    elif n == "A_Knife_Strike":
        poses = knife_strike(F, clip)
    elif n in ("A_Knife_Equip", "A_Knife_Holster"):
        poses = knife_equip(F, clip, n.endswith("Holster"))
    elif g == "Finisher":
        poses = finisher(F, clip)
    elif n.startswith("A_Death_"):
        poses = death(F, clip)
    elif n.startswith("A_Hit_"):
        poses = hit(F, clip)
    elif n.startswith("A_KillCam_"):
        poses = killcam(F, clip)
    elif g == "Crew":
        poses = crew(F, clip)
    else:
        raise KeyError(f"no author for {n}")
    return [_clean(p) for p in poses], curves
