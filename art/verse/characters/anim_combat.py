"""Duel clips of the shared human skeleton: a rifle stance, directional locomotion,
turn-in-place, the dodge roll, hit reactions, the knockout fall and the get-up.

Same conventions as `anim.py` (Blender axes: X = character's left, -Y = forward,
Z = up; 30 fps; in place). Every clip holds the blaster right-handed in a bladed
stance (pelvis and chest turned right, head forward), so the left hand reaches the
shroud. The runtime (`duel/figure.ts`) re-solves the arms onto the blaster every
frame by two-bone IK and calibrates the hands against `A_Combat_Idle` frame 0, where
the blaster points straight ahead, level, its grip `GRIP_FROM_WRIST` ahead of the
right wrist.

Locomotion clips share one phase convention: phase 0 is the left foot's contact,
0.5 the right foot's, so the runtime blends any of them on one normalised phase. A
clip moves its planted foot backwards at exactly its `LOCOMOTION` speed along its
heading; the runtime advances the phase at (ground speed / blended stride), so the
feet do not slide in any direction or blend.

Hit and stagger clips are additive: frame 0 is the idle's frame 0 and only the
spine, head and shoulders move.
"""

from __future__ import annotations

import math

from mathutils import Matrix, Vector

from characters import common as C
from characters.anim import TAU, Body, _lerp_spec, ease, frames, harm

# Stance: pelvis and chest turned to the right (twist < 0), the head back to the front.
BLADE = {"hips": -14.0, "Spine": -9.0, "Chest": -9.0, "Neck": 14.0, "Head": 18.0}

# Gun geometry (metres along the barrel, Blender axes, scaled with the body).
STOCK = 0.29  # stock butt behind the grip
LEFT_HOLD = 0.22  # the left palm's hold ahead of the grip
WRIST_BACK, WRIST_UP = 0.06, 0.03  # right wrist from the grip (behind, above)

# heading in degrees: 0 = forward, 90 = to the character's left, 180 = back, -90 = right
HEADINGS = {"F": 0.0, "L": 90.0, "B": 180.0, "R": -90.0}
BACK_SPEED = 0.78  # straight back runs at 78% (combat tuning)

GAITS = {
    # frames per cycle (two steps), m/s forward, stance share, swing height, hip drop, forward lean
    "Walk": {
        "n": 20,
        "speed": 2.4,
        "duty": 0.52,
        "lift": 0.075,
        "drop": 0.075,
        "lean": 5.0,
        "bob": 0.014,
    },
    "Run": {
        "n": 18,
        "speed": 4.8,
        "duty": 0.30,
        "lift": 0.14,
        "drop": 0.095,
        "lean": 9.0,
        "bob": 0.03,
    },
}
SPRINT = {
    "n": 16,
    "speed": 7.0,
    "duty": 0.24,
    "lift": 0.18,
    "drop": 0.10,
    "lean": 15.0,
    "bob": 0.035,
}

TURN_SECONDS = 0.6
TURN_DEG = 90.0

# Filled in by `combat_clips()`: per clip {"speed": m/s, "heading": deg} for the manifest.
LOCOMOTION: dict[str, dict] = {}


def _rz(deg: float) -> Matrix:
    return Matrix.Rotation(math.radians(deg), 3, "Z")


def _rx(deg: float) -> Matrix:
    return Matrix.Rotation(math.radians(deg), 3, "X")


def _dir(heading: float) -> Vector:
    h = math.radians(heading)
    return Vector((math.sin(h), -math.cos(h), 0.0))


def smootherstep(x: float) -> float:
    return ease(x)


def _foot_rot(pitch: float, yaw: float) -> Matrix:
    """Foot rotation: pitched (heel up > 0) about its own axis, then turned (left > 0)."""
    return _rz(yaw) @ _rx(pitch)


def _leg(b: Body, side: str, ankle: Vector, pitch: float, yaw: float, toe: float = 0.0, pole=None):
    sg = 1.0 if side == "L" else -1.0
    fv = _foot_rot(pitch, yaw) @ b.foot_vec
    return {
        "target": tuple(ankle),
        "pole": pole if pole is not None else (sg * 0.12, -1.0, 0.1),
        "foot_dir": tuple(fv.normalized()),
        "foot_up": (0.0, 0.0, 1.0),
        "toe": toe,
    }


def _planted(
    b: Body, side: str, x: float, y: float, yaw: float, pitch: float = 0.0, lift: float = 0.0
):
    """Ankle over a floor point (x, y) for a flat foot, turned by `yaw` (left > 0)."""
    return _leg(b, side, Vector((x, y, b.ankle.z + lift)), pitch, yaw)


def _stance_feet(b: Body):
    """Bladed stance: left foot ahead, right foot back and turned out (floor x, y, yaw per side)."""
    s = b.scale
    return {"L": (0.115 * s, -0.11 * s, -12.0), "R": (-0.155 * s, 0.13 * s, -38.0)}


# ------------------------------------------------------------------------ the blaster


def _shoulder_r(b: Body, p: dict) -> Vector:
    M = b.rig.solve(p)
    return M["UpperArm_R"].translation.copy(), M


def hold_arms(b: Body, p: dict, pitch: float = 0.0, yaw: float = 0.0, tuck: float = 0.0):
    """Both arms on the blaster: stock at the right shoulder pocket, barrel along (yaw, pitch)."""
    sh, _M = _shoulder_r(b, p)
    s = b.scale
    fwd = _rz(yaw) @ (_rx(-pitch) @ Vector((0.0, -1.0, 0.0)))
    right = _rz(yaw) @ Vector((-1.0, 0.0, 0.0))
    up = right.cross(fwd).normalized()
    pocket = sh + Vector((0.03, -0.07, -0.05)) * s
    grip = pocket + fwd * (STOCK * s) - fwd * (tuck * 0.12) - up * (tuck * 0.10)
    wrist_r = grip - fwd * (WRIST_BACK * s) + up * (WRIST_UP * s)
    palm_l = grip + fwd * (LEFT_HOLD * s) - up * (0.03 * s)
    wrist_l = palm_l - fwd * (0.05 * s) - up * (0.04 * s) - right * (0.03 * s)
    return {
        "arm_R": {
            "target": tuple(wrist_r),
            "pole": tuple((right * 1.0 - up * 1.0 + fwd * 0.3).normalized()),
            "hand_dir": tuple((fwd * 0.7 - up * 0.7).normalized()),
            "dorsal": tuple(right),
            "fingers": 48.0,
            "thumb": 26.0,
        },
        "arm_L": {
            "target": tuple(wrist_l),
            "pole": tuple((-right * 0.6 - up * 1.0).normalized()),
            "hand_dir": tuple((fwd * 0.85 + right * 0.45 + up * 0.2).normalized()),
            "dorsal": tuple((-up * 0.9 - right * 0.4).normalized()),
            "fingers": 40.0,
            "thumb": 20.0,
        },
    }


def _with_hold(b: Body, p: dict, **kw) -> dict:
    p.update(hold_arms(b, p, **kw))
    return p


def _spine(bend=0.0, twist=0.0, lean=0.0, extra=None):
    sp = {
        "Spine": (bend * 0.45, BLADE["Spine"] + twist * 0.5, lean * 0.5),
        "Chest": (bend * 0.55, BLADE["Chest"] + twist * 0.5, lean * 0.5),
        "Neck": (-bend * 0.3, BLADE["Neck"], -lean * 0.3),
        "Head": (-bend * 0.4, BLADE["Head"], -lean * 0.4),
    }
    for k, v in (extra or {}).items():
        a = sp[k]
        sp[k] = (a[0] + v[0], a[1] + v[1], a[2] + v[2])
    return sp


# ------------------------------------------------------------------------- standing


def combat_stand(
    b: Body, t: float = 0.0, period: float = 2.0, crouch: float = 0.0, breathe: float = 1.0
):
    """The ready stance (no arms): knees soft, pelvis bladed, chest leaning in."""
    w = harm(t, period, [(1, 1.0, 0.0)]) * breathe
    br = harm(t, period, [(2, 1.0, 0.4)]) * breathe
    s = b.scale
    feet = _stance_feet(b)
    hz = b.hips.z - (0.055 + 0.25 * crouch) * s - 0.004 * abs(w)
    p = {
        "hips": Vector((0.012 * w * s - 0.01 * s, 0.01 * s + 0.03 * crouch, hz)),
        "hips_rot": (6.0 + 14.0 * crouch, BLADE["hips"], -1.2 * w),
        "spine": _spine(bend=6.0 + 10.0 * crouch + 0.8 * br, lean=0.6 * w),
        "shoulder_L": (0.6 * br, 4.0),
        "shoulder_R": (0.6 * br, 0.0),
    }
    if crouch > 0:
        wide = 1.0 + 0.25 * crouch
        p["leg_L"] = _planted(
            b, "L", feet["L"][0] * wide, feet["L"][1] * (1 + crouch), feet["L"][2]
        )
        p["leg_R"] = _planted(
            b, "R", feet["R"][0] * wide, feet["R"][1] * (1 + crouch * 0.6), feet["R"][2]
        )
    else:
        p["leg_L"] = _planted(b, "L", feet["L"][0], feet["L"][1], feet["L"][2])
        p["leg_R"] = _planted(b, "R", feet["R"][0], feet["R"][1], feet["R"][2])
    return p


def clip_combat_idle(b: Body):
    T = 2.0
    out = []
    for f in range(frames(T)):
        t = f / C.FPS
        p = combat_stand(b, t, T)
        sway = harm(t, T, [(1, 1.2, 0.8)])
        out.append(_with_hold(b, p, pitch=0.6 * sway if f else 0.0, yaw=0.0))
    # Frame 0 is the calibration frame: the barrel level and straight ahead.
    out[0] = _with_hold(b, combat_stand(b, 0.0, T), pitch=0.0, yaw=0.0)
    out[-1] = out[0]
    return out


def clip_combat_cover(b: Body):
    """Low behind cover: deep crouch, barrel down, head up and scanning."""
    T = 2.0
    out = []
    for f in range(frames(T)):
        t = f / C.FPS
        p = combat_stand(b, t, T, crouch=1.0, breathe=1.3)
        look = harm(t, T, [(1, 6.0, 0.3)])
        sp = p["spine"]
        sp["Head"] = (sp["Head"][0] - 6.0, sp["Head"][1] + look, sp["Head"][2])
        out.append(_with_hold(b, p, pitch=-32.0, yaw=8.0, tuck=0.3))
    return out


# ---------------------------------------------------------------------- locomotion


def _gait_foot(b: Body, ph: float, g: dict, heading: float, side: str):
    """Ankle (in place), foot pitch and toe for one foot at phase `ph` (0 = its contact)."""
    s = b.scale
    n, d = g["n"], g["duty"]
    speed = g["speed"] * (BACK_SPEED if abs(heading) > 135 else 1.0)
    S = speed * n / C.FPS * (b.leg / 0.8426)
    u = _dir(heading)
    fwdness = math.cos(math.radians(heading))
    lateral = abs(math.sin(math.radians(heading)))
    sg = 1.0 if side == "L" else -1.0
    width = (0.095 + 0.05 * lateral) * s
    base = Vector((sg * width, 0.03 * s * max(0.0, fwdness), 0.0))
    yaw = -6.0 * sg + 18.0 * math.sin(math.radians(heading)) * lateral
    run = d < 0.4
    strike = (0.0 if run else -14.0) if fwdness > 0.3 else (14.0 if fwdness < -0.3 else 0.0)
    push = 34.0 if fwdness > -0.3 else 12.0
    half = S * d * 0.5
    if ph < d:
        k = ph / d
        along = half - S * ph
        if k < 0.25:
            pitch = C.lerp(strike, 0.0, ease(k / 0.25))
        elif k > 0.55:
            pitch = push * ((k - 0.55) / 0.45) ** 1.6
        else:
            pitch = 0.0
        lift = 0.0
        cross = 0.0
        toe = pitch * 0.85 if pitch > 0 else 0.0
    else:
        k = (ph - d) / (1.0 - d)
        m = -S * (1.0 - d)
        h00 = 2 * k**3 - 3 * k**2 + 1
        h10 = k**3 - 2 * k**2 + k
        h01 = -2 * k**3 + 3 * k**2
        h11 = k**3 - k**2
        along = h00 * (-half) + h10 * m + h01 * half + h11 * m
        lift = g["lift"] * s * math.sin(math.pi * k) ** 0.75
        if k < 0.5:
            pitch = C.lerp(push, -6.0, ease(k / 0.5))
        else:
            pitch = C.lerp(-6.0, strike, ease((k - 0.5) / 0.5))
        toe = C.lerp(push * 0.85, 4.0, ease(min(1.0, k / 0.4)))
        # Side steps cross over: the trailing foot passes in front, the leading one behind.
        trailing = (sg > 0) != (u.x > 0)
        cross = (-0.11 if trailing else 0.09) * s * lateral * math.sin(math.pi * k)
    flat = base + u * along + Vector((0.0, cross, 0.0))
    flat.z = b.ankle.z
    R = _foot_rot(pitch, yaw)
    if pitch > 0:  # heel up: the ball stays where the flat foot's ball is
        ankle = flat + _rz(yaw) @ b.foot_vec - R @ b.foot_vec
    elif pitch < 0:  # heel down: the heel stays
        ankle = flat + _rz(yaw) @ b.heel_vec - R @ b.heel_vec
    else:
        ankle = flat.copy()
    ankle.z += lift
    return ankle, pitch, yaw, toe


def _keep_reach(b: Body, legs: dict, hz: float, hx: float) -> float:
    """Lower the hips just enough that both ankles stay inside the legs' reach."""
    for s, (a, *_r) in legs.items():
        hip = b.hip_l.copy()
        hip.x = abs(hip.x) * (1 if s == "L" else -1) + hx
        dx = a.x - hip.x
        dy = a.y
        reach = b.leg * 0.99
        zmax = a.z + math.sqrt(max(0.0, reach**2 - dx * dx - dy * dy)) + (b.hips.z - b.hip_l.z)
        if hz > zmax - 0.004:
            hz = zmax - 0.004 - 0.004 * math.tanh((hz - zmax) / 0.004)
    return hz


def gait_clip(b: Body, g: dict, heading: float):
    n = g["n"]
    d = g["duty"]
    s = b.scale
    fwdness = math.cos(math.radians(heading))
    side = math.sin(math.radians(heading))
    run = d < 0.4
    out = []
    for f in range(n + 1):
        ph = (f % n) / n
        legs = {}
        for sd, off in (("L", 0.0), ("R", 0.5)):
            legs[sd] = _gait_foot(b, (ph + off) % 1.0, g, heading, sd)
        bob_phase = math.cos(2 * TAU * (ph - d * 0.5))
        bob = (-1.0 if run else 1.0) * g["bob"] * s * bob_phase
        sway = math.cos(TAU * (ph - d * 0.5))
        hx = 0.016 * s * sway * (0.5 if run else 1.0)
        hz = b.hips.z - g["drop"] * s + bob
        hz = _keep_reach(b, legs, hz, hx)
        osc = math.cos(TAU * ph)
        twist = -7.0 * osc * fwdness
        lean = g["lean"] * (fwdness if fwdness > 0 else 0.35 * fwdness)
        p = {
            "hips": Vector((hx, 0.0, hz)),
            "hips_rot": (lean, BLADE["hips"] * 0.6 + twist, 5.0 * side - 2.0 * sway),
            "spine": _spine(
                bend=4.0 + 0.4 * lean, twist=-twist * 0.8 + BLADE["hips"] * 0.4, lean=-3.0 * side
            ),
            "shoulder_L": (1.5 * bob_phase if run else 0.0, 4.0),
            "shoulder_R": (1.5 * bob_phase if run else 0.0, 0.0),
        }
        for sd, (a, pitch, yaw, toe) in legs.items():
            p[f"leg_{sd}"] = _leg(b, sd, a, pitch, yaw, toe)
        out.append(_with_hold(b, p, pitch=0.0, yaw=0.0))
    return out


def sprint_clip(b: Body):
    """Forward sprint, the blaster carried low across the chest."""
    g = SPRINT
    out = []
    for p in gait_clip(b, g, 0.0):
        p["spine"]["Chest"] = (
            p["spine"]["Chest"][0] + 4.0,
            p["spine"]["Chest"][1] + 6.0,
            p["spine"]["Chest"][2],
        )
        out.append(_with_hold(b, p, pitch=-35.0, yaw=35.0, tuck=0.6))
    return out


# ---------------------------------------------------------------------- turn in place


def turn_clip(b: Body, sign: float):
    """Two steps turning the body by TURN_DEG (sign +1 = left). The runtime turns the
    root by sign * TURN_DEG * smootherstep(t / TURN_SECONDS); the feet are posed in the
    world and counter-rotated into the turning root, so they stay planted."""
    T = TURN_SECONDS
    feet = _stance_feet(b)
    first, second = ("L", "R") if sign > 0 else ("R", "L")
    windows = {first: (0.03, 0.33), second: (0.26, 0.57)}
    out = []
    for f in range(frames(T)):
        t = f / C.FPS
        r = sign * TURN_DEG * smootherstep(t / T)
        p = combat_stand(b, 0.0, 2.0, breathe=0.0)
        dip = math.sin(math.pi * C.clamp(t / T, 0.0, 1.0))
        p["hips"] = p["hips"] + Vector((0.0, 0.0, -0.02 * b.scale * dip))
        hr = p["hips_rot"]
        p["hips_rot"] = (hr[0], hr[1] + sign * 8.0 * dip, hr[2])
        for sd in ("L", "R"):
            x, y, yaw0 = feet[sd]
            w0, w1 = windows[sd]
            k = ease(C.clamp((t - w0) / (w1 - w0), 0.0, 1.0))
            start = Vector((x, y, 0.0))
            end = _rz(sign * TURN_DEG) @ start
            world = start.lerp(end, k)
            yaw_world = yaw0 + sign * TURN_DEG * k
            lift = 0.06 * b.scale * math.sin(math.pi * k)
            local = _rz(-r) @ world
            p[f"leg_{sd}"] = _planted(
                b,
                sd,
                local.x,
                local.y,
                yaw_world - r,
                pitch=-4.0 * math.sin(math.pi * k),
                lift=lift,
            )
        out.append(_with_hold(b, p))
    return out


# --------------------------------------------------------------------------- the roll


def roll_clip(b: Body):
    """Dodge roll in place (the runtime carries the root along the roll and faces it the
    roll's way): dive, tucked shoulder roll through 360 degrees, crouched landing, up."""
    T = 0.6
    s = b.scale
    out = []
    stand = combat_stand(b, 0.0, 2.0, breathe=0.0)
    feet = _stance_feet(b)
    for f in range(frames(T)):
        t = f / C.FPS
        a = 360.0 * smootherstep((t - 0.05) / 0.33)
        tuck = smootherstep((t - 0.03) / 0.08) * (1.0 - smootherstep((t - 0.33) / 0.09))
        crouch = smootherstep(t / 0.07) * (1.0 - smootherstep((t - 0.40) / 0.2))
        Ra = _rx(a)
        centre = Vector((0.0, 0.0, 0.43 * s))
        stand_hips = Vector(stand["hips"]) + Vector((0.0, -0.05 * crouch, -0.30 * s * crouch))
        tucked_hips = centre + Ra @ Vector((0.0, 0.06 * s, -0.04 * s))
        hips = stand_hips.lerp(tucked_hips, tuck)
        # Past half way the untucked pelvis angle counts from a full turn, so it never spins back.
        base = stand["hips_rot"][0] + 22.0 * crouch + (360.0 if a > 180.0 else 0.0)
        p = {
            "hips": hips,
            "hips_rot": (C.lerp(base, a, tuck), -4.0 * tuck, 14.0 * tuck),
            "spine": _spine(
                bend=10.0 * crouch + 70.0 * tuck,
                extra={"Neck": (48.0 * tuck, 0, 0), "Head": (50.0 * tuck, 0, 0)},
            ),
            "shoulder_L": (6.0 * tuck, 10.0 * tuck),
            "shoulder_R": (6.0 * tuck, 10.0 * tuck),
        }
        for sd in ("L", "R"):
            sg = 1.0 if sd == "L" else -1.0
            x, y, yaw = feet[sd]
            floor = _planted(b, sd, x * (1 + 0.3 * crouch), y * (1 - 0.6 * crouch), yaw)
            fl = Vector(floor["target"])
            tl = hips + Ra @ Vector((sg * 0.13 * s, -0.02 * s, -0.30 * s))
            target = fl.lerp(tl, tuck)
            pole = Vector((sg * 0.12, -1.0, 0.1)).lerp(Ra @ Vector((sg * 0.1, -1.0, 0.4)), tuck)
            fdir = (
                Vector(floor["foot_dir"]).lerp(Ra @ Vector((0.0, -0.3, -0.95)), tuck).normalized()
            )
            fup = Vector((0, 0, 1)).lerp(Ra @ Vector((0.0, -1.0, 0.2)), tuck).normalized()
            p[f"leg_{sd}"] = {
                "target": tuple(target),
                "pole": tuple(pole),
                "foot_dir": tuple(fdir),
                "foot_up": tuple(fup),
                "toe": 10.0 * tuck,
            }
        out.append(_chest_hold(b, p, tuck=0.6 * tuck + 0.3 * crouch))
    return out


_HOLD_CACHE: dict[int, tuple] = {}


def _chest_local_hold(b: Body):
    """The idle's frame-0 hands in the chest's own frame (so the blaster can follow a
    rolling or falling chest)."""
    key = id(b)
    if key not in _HOLD_CACHE:
        p = clip_combat_idle(b)[0]
        M = b.rig.solve(p)
        inv = M["Chest"].inverted()
        rot = inv.to_3x3()
        arms = {}
        for sd in ("L", "R"):
            spec = dict(p[f"arm_{sd}"])
            spec["target"] = tuple((inv @ Vector((*spec["target"], 1.0))).xyz)
            for k in ("pole", "hand_dir", "dorsal"):
                spec[k] = tuple(rot @ Vector(spec[k]))
            arms[sd] = spec
        _HOLD_CACHE[key] = arms
    return _HOLD_CACHE[key]


def _chest_hold(b: Body, p: dict, tuck: float = 0.0) -> dict:
    """Arms holding the blaster where the idle holds it, relative to the chest."""
    M = b.rig.solve(p)
    ch = M["Chest"]
    rot = ch.to_3x3()
    local = _chest_local_hold(b)
    for sd in ("L", "R"):
        spec = dict(local[sd])
        tgt = Vector(spec["target"])
        # Tucked: the hands come in towards the sternum and down.
        tgt = tgt.lerp(Vector((tgt.x * 0.6, tgt.y - 0.08, tgt.z * 0.55)), tuck)
        spec["target"] = tuple((ch @ Vector((*tgt, 1.0))).xyz)
        for k in ("pole", "hand_dir", "dorsal"):
            spec[k] = tuple(rot @ Vector(spec[k]))
        p[f"arm_{sd}"] = spec
    return p


# -------------------------------------------------------------------- additive hits


def _additive(b: Body, T: float, deltas):
    """Clip whose every frame is the idle's frame 0 plus spine/shoulder deltas(t)."""
    base = clip_combat_idle(b)[0]
    out = []
    for f in range(frames(T)):
        t = f / C.FPS
        p = dict(base)
        sp = dict(base["spine"])
        d = deltas(t)
        for k, v in d.get("spine", {}).items():
            a = sp[k]
            sp[k] = (a[0] + v[0], a[1] + v[1], a[2] + v[2])
        p["spine"] = sp
        for k in ("shoulder_L", "shoulder_R"):
            if k in d:
                a = base[k]
                p[k] = (a[0] + d[k][0], a[1] + d[k][1])
        out.append(p)
    out[0] = base
    return out


def _flinch_env(t: float) -> float:
    if t < 0.05:
        return ease(t / 0.05)
    x = t - 0.05
    return math.exp(-x / 0.1) * math.cos(x * 9.0) * (1.0 - ease((t - 0.36) / 0.12))


def hit_clip(b: Body, side: str):
    """Additive flinch from a bolt arriving from `side` (F, B, L, R)."""

    def deltas(t):
        e = _flinch_env(t)
        if side == "F":
            sp = {
                "Spine": (-6 * e, 0, 0),
                "Chest": (-9 * e, 0, 0),
                "Neck": (-4 * e, 0, 0),
                "Head": (-12 * e, 0, 0),
            }
            sh = (5 * e, -4 * e)
        elif side == "B":
            sp = {
                "Spine": (7 * e, 0, 0),
                "Chest": (9 * e, 0, 0),
                "Neck": (5 * e, 0, 0),
                "Head": (10 * e, 0, 0),
            }
            sh = (3 * e, 4 * e)
        else:
            sg = 1.0 if side == "L" else -1.0
            sp = {
                "Spine": (-2 * e, 5 * sg * e, -5 * sg * e),
                "Chest": (-3 * e, 8 * sg * e, -7 * sg * e),
                "Head": (-4 * e, 6 * sg * e, -10 * sg * e),
            }
            sh = (4 * e, -3 * e)
        return {"spine": sp, "shoulder_L": sh, "shoulder_R": sh}

    return _additive(b, 0.5, deltas)


def stagger_clip(b: Body):
    """Additive reel after eating one's own reflected bolt: thrown back, wobbling, recovering."""

    def deltas(t):
        hit = ease(t / 0.1) * (1.0 - ease((t - 0.25) / 0.6))
        wob = math.sin(t * 15.0) * math.exp(-t / 0.35) * (1.0 - ease((t - 0.7) / 0.3))
        sp = {
            "Spine": (-10 * hit, 4 * wob, 3 * wob),
            "Chest": (-16 * hit, 7 * wob, 5 * wob),
            "Neck": (-6 * hit, 0, 0),
            "Head": (-18 * hit + 8 * wob * 0.5, -6 * wob, -8 * wob),
        }
        return {
            "spine": sp,
            "shoulder_L": (12 * hit, -10 * hit),
            "shoulder_R": (12 * hit, -6 * hit),
        }

    return _additive(b, 1.0, deltas)


# ---------------------------------------------------------------- knockout and get-up


def _lying(b: Body):
    """On the back on the floor, root at the feet's end: the body lies towards +Y."""
    s = b.scale
    p = {
        "hips": Vector((0.02 * s, 0.62 * s, 0.11 * s)),
        "hips_rot": (-90.0, -10.0, 4.0),
        "spine": {
            "Spine": (-2.0, 3.0, 0.0),
            "Chest": (2.0, 4.0, 0.0),
            "Neck": (8.0, 10.0, 0.0),
            "Head": (6.0, 26.0, 0.0),
        },
        "shoulder_L": (0.0, 0.0),
        "shoulder_R": (0.0, 0.0),
        "leg_L": {
            "target": (0.17 * s, 0.62 * s - b.leg * 0.97, b.ankle.z * 0.6 + 0.02),
            "pole": (0.35, 0.0, 1.0),
            "foot_dir": tuple(Vector((0.35, -0.6, 0.75)).normalized()),
            "foot_up": (0.0, 1.0, 0.0),
            "toe": 0.0,
        },
        "leg_R": {
            "target": (-0.10 * s, 0.62 * s - 0.48 * s, b.ankle.z),
            "pole": (-0.25, -0.35, 1.0),
            "foot_dir": tuple(Vector((-0.1, -0.85, -0.45)).normalized()),
            "foot_up": (0.0, 0.0, 1.0),
            "toe": 0.0,
        },
        "arm_R": {
            "target": (-0.46 * s, 0.78 * s, 0.07 * s),
            "pole": (-0.3, 0.2, -1.0),
            "hand_dir": (-0.5, -0.8, -0.1),
            "dorsal": (0.0, 0.0, 1.0),
            "fingers": 30.0,
            "thumb": 15.0,
        },
        "arm_L": {
            "target": (0.40 * s, 0.86 * s, 0.06 * s),
            "pole": (0.3, 0.2, -1.0),
            "hand_dir": (0.6, 0.7, -0.1),
            "dorsal": (0.0, 0.0, 1.0),
            "fingers": 20.0,
            "thumb": 10.0,
        },
    }
    return p


def _abs_hold(b: Body, p: dict, tuck: float = 0.0) -> dict:
    return _chest_hold(b, p, tuck=tuck)


def _keyed(keys, t: float):
    """Pose at time t between timed key poses (eased per segment)."""
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, p0), (t1, p1) in zip(keys, keys[1:], strict=False):
        if t <= t1:
            return _lerp_spec(p0, p1, ease((t - t0) / (t1 - t0)))
    return keys[-1][1]


def _norm(p: dict) -> dict:
    """Arm and leg vectors as tuples, hips as a Vector (so key poses blend)."""
    q = dict(p)
    q["hips"] = Vector(p["hips"])
    for k in ("arm_L", "arm_R", "leg_L", "leg_R"):
        q[k] = {
            kk: (tuple(v) if isinstance(v, (Vector, tuple, list)) else v) for kk, v in p[k].items()
        }
    q["spine"] = {k: tuple(v) for k, v in p["spine"].items()}
    return q


def death_clip(b: Body):
    """Knocked out: jolted back, knees buckle, falls on the back, a small bounce, still."""
    s = b.scale
    k0 = _norm(clip_combat_idle(b)[0])
    jolt = combat_stand(b, 0.0, 2.0, breathe=0.0)
    jolt["hips"] = Vector(jolt["hips"]) + Vector((0.0, 0.05 * s, -0.02 * s))
    jolt["hips_rot"] = (-6.0, BLADE["hips"] - 6.0, 3.0)
    jolt["spine"] = _spine(bend=-14.0, extra={"Head": (-18.0, 0, 0)})
    jolt = _norm(_abs_hold(b, jolt))
    jolt["arm_L"] = dict(
        jolt["arm_L"],
        target=tuple(Vector(jolt["arm_L"]["target"]) + Vector((0.16, 0.10, 0.12)) * s),
    )
    buckle = combat_stand(b, 0.0, 2.0, breathe=0.0)
    buckle["hips"] = Vector((0.0, 0.16 * s, 0.60 * s))
    buckle["hips_rot"] = (-18.0, BLADE["hips"] - 14.0, 6.0)
    buckle["spine"] = _spine(bend=-8.0, extra={"Head": (16.0, 8.0, 0.0)})
    buckle = _norm(_abs_hold(b, buckle, tuck=0.4))
    buckle["arm_L"] = dict(
        buckle["arm_L"],
        target=tuple(Vector(buckle["arm_L"]["target"]) + Vector((0.25, 0.05, -0.10)) * s),
    )
    rest = _norm(_lying(b))
    land = _norm(_lying(b))
    land["hips"] = Vector((0.0, 0.44 * s, 0.22 * s))
    land["hips_rot"] = (-66.0, -14.0, 5.0)
    land["spine"] = {
        "Spine": (12.0, 0, 0),
        "Chest": (8.0, 2.0, 0.0),
        "Neck": (12.0, 4.0, 0.0),
        "Head": (18.0, 10.0, 0.0),
    }
    land["leg_L"] = dict(rest["leg_L"], target=(0.16 * s, 0.05 * s, b.ankle.z + 0.06 * s))
    land["leg_R"] = dict(rest["leg_R"], target=(-0.12 * s, 0.10 * s, b.ankle.z + 0.03 * s))
    impact = _norm(_lying(b))
    impact["hips"] = Vector((0.01 * s, 0.58 * s, 0.10 * s))
    impact["spine"] = dict(impact["spine"], Head=(-6.0, 14.0, 0.0), Neck=(-4.0, 6.0, 0.0))
    bounce = _norm(_lying(b))
    bounce["hips"] = Vector((0.02 * s, 0.61 * s, 0.13 * s))
    bounce["spine"] = dict(bounce["spine"], Chest=(6.0, 4.0, 0.0), Head=(12.0, 22.0, 0.0))
    keys = [
        (0.0, k0),
        (0.1, jolt),
        (0.42, buckle),
        (0.68, land),
        (0.82, impact),
        (0.96, bounce),
        (1.3, rest),
    ]
    return [_keyed(keys, f / C.FPS) for f in range(frames(1.4))]


def getup_clip(b: Body):
    """From the knockout pose back to the ready stance (round reset): sit up, a knee, up."""
    s = b.scale
    rest = _norm(_lying(b))
    sit = _norm(_lying(b))
    sit["hips"] = Vector((0.0, 0.56 * s, 0.12 * s))
    sit["hips_rot"] = (-28.0, -6.0, 0.0)
    sit["spine"] = {
        "Spine": (18.0, 0, 0),
        "Chest": (10.0, 0.0, 0.0),
        "Neck": (0.0, 0.0, 0.0),
        "Head": (4.0, 0.0, 0.0),
    }
    sit["leg_L"] = dict(
        rest["leg_L"],
        target=(0.16 * s, 0.12 * s, b.ankle.z),
        foot_dir=tuple(Vector((0.1, -0.85, -0.45)).normalized()),
        foot_up=(0, 0, 1),
        pole=(0.3, -0.3, 1.0),
    )
    sit["leg_R"] = dict(
        rest["leg_R"],
        target=(-0.13 * s, 0.22 * s, b.ankle.z),
        foot_dir=tuple(Vector((-0.1, -0.85, -0.45)).normalized()),
        foot_up=(0, 0, 1),
        pole=(-0.3, -0.3, 1.0),
    )
    sit["arm_R"] = dict(rest["arm_R"], target=(-0.26 * s, 0.82 * s, 0.10 * s))
    sit["arm_L"] = dict(rest["arm_L"], target=(0.26 * s, 0.82 * s, 0.10 * s))
    kneel = combat_stand(b, 0.0, 2.0, breathe=0.0)
    kneel["hips"] = Vector((0.0, 0.30 * s, 0.52 * s))
    kneel["hips_rot"] = (14.0, -10.0, 0.0)
    kneel["spine"] = _spine(bend=12.0)
    kneel["leg_L"] = _planted(b, "L", 0.14 * s, -0.02 * s, -8.0)
    kneel["leg_R"] = {
        "target": (-0.13 * s, 0.66 * s, 0.13 * s),
        "pole": (-0.05, -1.0, -0.6),
        "foot_dir": tuple(Vector((0.0, 0.35, -0.94)).normalized()),
        "foot_up": (0.0, 1.0, 0.0),
        "toe": 30.0,
    }
    kneel = _norm(_abs_hold(b, kneel, tuck=0.3))
    rise = combat_stand(b, 0.0, 2.0, crouch=0.6, breathe=0.0)
    rise["hips"] = Vector((0.0, 0.12 * s, 0.74 * s))
    rise = _norm(_abs_hold(b, rise, tuck=0.15))
    end = _norm(clip_combat_idle(b)[0])
    sit = _norm(sit)
    keys = [(0.0, rest), (0.32, sit), (0.72, kneel), (1.08, rise), (1.45, end)]
    return [_keyed(keys, f / C.FPS) for f in range(frames(1.5))]


# ------------------------------------------------------------------------- registry


def combat_clips():
    """{name: (fn, loop)} of every duel clip; fills LOCOMOTION."""
    clips = {
        "A_Combat_Idle": (clip_combat_idle, True),
        "A_Combat_Cover": (clip_combat_cover, True),
    }
    LOCOMOTION.clear()
    for gname, g in GAITS.items():
        for dname, heading in HEADINGS.items():
            name = f"A_Combat_{gname}_{dname}"
            clips[name] = ((lambda b, g=g, h=heading: gait_clip(b, g, h)), True)
            speed = round(g["speed"] * (BACK_SPEED if dname == "B" else 1.0), 4)
            LOCOMOTION[name] = {"speed": speed, "heading": heading}
    clips["A_Combat_Sprint"] = (sprint_clip, True)
    LOCOMOTION["A_Combat_Sprint"] = {"speed": SPRINT["speed"], "heading": 0.0}
    clips["A_Combat_Turn_L"] = ((lambda b: turn_clip(b, 1.0)), False)
    clips["A_Combat_Turn_R"] = ((lambda b: turn_clip(b, -1.0)), False)
    clips["A_Combat_Roll"] = (roll_clip, False)
    for sd in ("F", "B", "L", "R"):
        clips[f"A_Combat_Hit_{sd}"] = ((lambda b, sd=sd: hit_clip(b, sd)), False)
    clips["A_Combat_Stagger"] = (stagger_clip, False)
    clips["A_Combat_Death"] = (death_clip, False)
    clips["A_Combat_GetUp"] = (getup_clip, False)
    return clips
