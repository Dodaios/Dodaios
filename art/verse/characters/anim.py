"""Animation clips of the shared human skeleton, authored as pose functions.

Every clip is a function `clip(rig) -> list[pose]` (one pose per frame at 30 fps).
Looping clips use only harmonics of their own period, so the last frame equals
the first and the loop is seamless. Clips are in place: the root never travels;
A_Walk moves the planted foot backwards at exactly WALK_SPEED instead, so the
runtime moves the character at that speed and the feet do not slide.

Conventions (Blender axes: X = character's left, -Y = forward, Z = up):
- Standing clips: feet on the floor (Z = 0) around the origin.
- Sitting clips: buttocks on a seat surface at Z = SEAT_HEIGHT whose centre is
  0.06 m in front of the origin; feet flat on the floor ~0.45 m forward.
- A_Sleep: lying on the back on a mattress whose top surface is Z = 0 at the
  origin; head towards +Y (three.js -Z), feet towards -Y (three.js +Z).
"""

from __future__ import annotations

import math

from mathutils import Matrix, Vector

from characters import common as C

TAU = 2.0 * math.pi
FWD = Vector((0, -1, 0))
UP = Vector((0, 0, 1))


def harm(t: float, period: float, terms) -> float:
    """Sum of sines with integer harmonics of `period`: seamless over the period."""
    return sum(a * math.sin(TAU * k * t / period + ph) for k, a, ph in terms)


def ease(x: float) -> float:
    x = C.clamp(x, 0.0, 1.0)
    return x * x * x * (x * (6 * x - 15) + 10)


class Body:
    """Measurements of one rig used by the clips."""

    def __init__(self, rig):
        self.rig = rig
        self.hips = rig.head("Hips")
        self.hip_l = rig.head("UpperLeg_L")
        self.thigh = rig.length["UpperLeg_L"]
        self.shin = rig.length["LowerLeg_L"]
        self.leg = self.thigh + self.shin
        self.ankle = rig.head("Foot_L")
        self.ball = rig.head("Toe_L")
        self.arm = rig.length["UpperArm_L"] + rig.length["ForeArm_L"]
        self.shoulder = rig.head("UpperArm_L")
        self.head = rig.head("Head")
        self.scale = self.hips.z / 0.903  # 1.0 for the male skeleton
        # Foot geometry relative to the ankle, foot pointing straight ahead.
        fz = self.ankle.z - self.ball.z
        fl = math.hypot(self.ball.y - self.ankle.y, self.ball.x - self.ankle.x)
        self.foot_vec = Vector((0.0, -fl, -fz))  # ankle -> ball
        self.heel_vec = Vector((0.0, 0.068 * self.scale, -self.ankle.z))  # ankle -> heel


def foot_dir(vec: Vector, pitch_deg: float, out_deg: float, side: str) -> Vector:
    """Ankle->ball direction pitched (heel up > 0) and turned out."""
    v = Matrix.Rotation(math.radians(pitch_deg), 3, "X") @ vec
    sgn = 1.0 if side == "L" else -1.0
    v = Matrix.Rotation(math.radians(out_deg) * sgn, 3, "Z") @ v
    return v.normalized()


def planted_leg(b: Body, side: str, x: float, y: float, out_deg=6.0, pitch=0.0, toe=0.0, lift=0.0):
    """Leg spec for a foot standing on the floor; (x, y) is the ankle's floor position."""
    sgn = 1.0 if side == "L" else -1.0
    fv = foot_dir(b.foot_vec, pitch, out_deg, side)
    return {
        "target": (sgn * x, y, b.ankle.z + lift),
        "pole": (sgn * 0.12, -1.0, 0.1),
        "foot_dir": tuple(fv),
        "foot_up": (0, 0, 1),
        "toe": toe,
    }


def hanging_arm(b: Body, side: str, swing=0.0, bend=10.0, out=0.05, fwd=0.02, curl=14.0):
    """Arm hanging from the shoulder. swing > 0 swings forwards (degrees)."""
    sgn = 1.0 if side == "L" else -1.0
    reach = b.arm * math.cos(math.radians(bend) * 0.5) * 0.985
    d = Matrix.Rotation(-math.radians(swing), 3, "X") @ Vector((0, 0, -1))
    rel = d * reach + Vector((sgn * out, -fwd, 0.0))
    hand_dir = (
        Matrix.Rotation(-math.radians(swing + bend * 0.6), 3, "X") @ Vector((sgn * 0.05, -0.05, -1))
    ).normalized()
    return {
        "rel": tuple(rel),
        "pole": (sgn * 0.25, 1.0, 0.0),
        "hand_dir": tuple(hand_dir),
        "dorsal": (sgn * 1.0, 0.1, 0.0),
        "fingers": curl,
        "thumb": 10.0,
    }


def frames(seconds: float) -> int:
    return int(round(seconds * C.FPS)) + 1  # inclusive last frame (= first for loops)


# ----------------------------------------------------------------------- standing


def stand_pose(b: Body, t: float, period: float, sway=0.012, breathe=1.0):
    """Relaxed standing base pose (weight shift, breathing) for time t."""
    w = harm(t, period, [(1, 1.0, 0.0)])  # -1..1 weight shift
    br = harm(t, period, [(2, 1.0, 0.3)]) * breathe
    hip_x = sway * w
    hz = b.hips.z - 0.012 * b.scale - 0.004 * abs(w)
    lean = -1.5 * w
    return {
        "hips": Vector((hip_x, 0.012, hz)),
        "hips_rot": (2.0, harm(t, period, [(1, 1.5, 1.2)]), lean),
        "spine": {
            "Spine": (1.0 + 0.6 * br, 0.0, -lean * 0.5),
            "Chest": (-1.5 - 0.9 * br, harm(t, period, [(1, -1.0, 1.2)]), -lean * 0.4),
            "Neck": (-2.0, 0.0, 0.0),
            "Head": (3.0, 0.0, 0.0),
        },
        "shoulder_L": (0.8 * br, 0.0),
        "shoulder_R": (0.8 * br, 0.0),
        "leg_L": planted_leg(b, "L", 0.105 * b.scale, 0.03, 8.0),
        "leg_R": planted_leg(b, "R", 0.105 * b.scale, 0.03, 8.0),
    }


def clip_idle(b: Body):
    T = 6.0
    out = []
    for f in range(frames(T)):
        t = f / C.FPS
        p = stand_pose(b, t, T)
        look = harm(t, T, [(1, 9.0, 0.4), (2, 4.0, 2.0)])
        nod = harm(t, T, [(3, 1.5, 0.0)])
        p["spine"]["Neck"] = (-2.0 + nod, look * 0.4, 0.0)
        p["spine"]["Head"] = (3.0 + nod, look * 0.6, harm(t, T, [(1, 2.0, 1.0)]))
        sw = harm(t, T, [(1, 3.0, 0.6), (3, 1.0, 1.0)])
        p["arm_L"] = hanging_arm(b, "L", swing=sw, bend=12)
        p["arm_R"] = hanging_arm(b, "R", swing=-sw * 0.7, bend=14)
        out.append(p)
    return out


def clip_listen(b: Body):
    """Parade rest: hands clasped behind the back, attentive head."""
    T = 6.0
    out = []
    for f in range(frames(T)):
        t = f / C.FPS
        p = stand_pose(b, t, T, sway=0.006)
        p["leg_L"] = planted_leg(b, "L", 0.14 * b.scale, 0.03, 10.0)
        p["leg_R"] = planted_leg(b, "R", 0.14 * b.scale, 0.03, 10.0)
        nod = harm(t, T, [(2, 2.5, 0.0), (3, 1.0, 0.5)])
        tilt = harm(t, T, [(1, 4.0, 0.8)])
        p["spine"]["Chest"] = (-3.0, 0.0, 0.0)
        p["spine"]["Neck"] = (-1.0 + nod * 0.4, 0.0, 0.0)
        p["spine"]["Head"] = (4.0 + nod, harm(t, T, [(1, 4.0, 0.2)]), tilt)
        p["shoulder_L"] = (0.0, -6.0)
        p["shoulder_R"] = (0.0, -6.0)
        for s, sg in (("L", 1.0), ("R", -1.0)):
            p[f"arm_{s}"] = {
                "target": (sg * 0.045 * b.scale, 0.135 * b.scale, b.hips.z + 0.10 * b.scale),
                "pole": (sg * 1.0, 0.6, -0.3),
                "hand_dir": (-sg * 0.9, 0.25, -0.35),
                "dorsal": (0.0, 1.0, 0.1),
                "fingers": 35.0,
                "thumb": 20.0,
            }
        out.append(p)
    return out


def clip_talk(b: Body):
    T = 4.0
    out = []
    for f in range(frames(T)):
        t = f / C.FPS
        p = stand_pose(b, t, T, sway=0.008)
        g1 = harm(t, T, [(1, 1.0, 0.0), (2, 0.5, 1.1)])
        g2 = harm(t, T, [(1, 1.0, 2.2), (3, 0.4, 0.3)])
        nod = harm(t, T, [(2, 3.0, 0.0), (5, 1.0, 0.7)])
        p["spine"]["Chest"] = (-1.0 + nod * 0.2, g1 * 3.0, 0.0)
        p["spine"]["Neck"] = (-2.0, g1 * 2.0, 0.0)
        p["spine"]["Head"] = (2.0 + nod, g1 * 4.0, harm(t, T, [(1, 3.0, 0.4)]))
        sh = b.shoulder
        for s, sg, g in (("L", 1.0, g2), ("R", -1.0, g1)):
            up = 0.5 + 0.5 * g
            p[f"arm_{s}"] = {
                "target": (
                    sg * (0.16 + 0.05 * g) * b.scale,
                    -0.24 * b.scale - 0.06 * up,
                    sh.z - 0.40 * b.scale + 0.10 * up,
                ),
                "pole": (sg * 0.6, 0.7, -0.5),
                "hand_dir": (sg * 0.25, -1.0, 0.15 * up),
                "dorsal": (-sg * 0.35 * up, 0.0, -1.0),
                "fingers": 10.0 + 12.0 * (1 - up),
                "thumb": 5.0,
            }
        out.append(p)
    return out


def clip_wave(b: Body):
    """Right hand raised high, waving: 'waiting for you'."""
    T = 2.0
    out = []
    for f in range(frames(T)):
        t = f / C.FPS
        p = stand_pose(b, t, T, sway=0.004, breathe=0.5)
        w = math.sin(TAU * 2 * t / T)
        p["hips_rot"] = (1.0, 0.0, 1.5)
        p["spine"]["Chest"] = (-3.0, 0.0, 2.0)
        p["spine"]["Head"] = (-4.0, 0.0, -2.0 + 2.0 * w * 0.3)
        p["shoulder_R"] = (14.0, 2.0)
        sh = b.shoulder
        p["arm_R"] = {
            "target": (-(sh.x + 0.16 * b.scale + 0.07 * w), -0.10, sh.z + 0.42 * b.scale),
            "pole": (-1.0, 0.4, -1.0),
            "hand_dir": (-0.25 * w - 0.1, -0.05, 1.0),
            "dorsal": (0.0, 1.0, 0.0),
            "fingers": 2.0,
            "thumb": 0.0,
        }
        p["arm_L"] = hanging_arm(b, "L", swing=2.0, bend=12)
        out.append(p)
    return out


def clip_salute(b: Body):
    """One-shot: come to attention, salute, hold, return (2.4 s)."""
    T = 2.4
    out = []
    n = frames(T)
    for f in range(n):
        t = f / C.FPS
        raise_ = ease((t - 0.25) / 0.45) * (1.0 - ease((t - 1.75) / 0.5))
        att = ease(t / 0.3) * (1.0 - ease((t - 2.0) / 0.4))
        p = stand_pose(b, 0.0, T, sway=0.0, breathe=0.0)
        p["spine"]["Chest"] = (-1.5 - 2.5 * att, 0.0, 0.0)
        p["spine"]["Head"] = (3.0 - 3.0 * att, 0.0, 0.0)
        p["hips"] = Vector((0.0, 0.012, b.hips.z - 0.008 * b.scale))
        x = 0.105 - 0.035 * att
        p["leg_L"] = planted_leg(b, "L", x * b.scale, 0.03, 8.0 + 6.0 * att)
        p["leg_R"] = planted_leg(b, "R", x * b.scale, 0.03, 8.0 + 6.0 * att)
        rest_r = hanging_arm(b, "R", swing=0.0, bend=8, out=0.03, curl=8.0 + 6 * att)
        hd = b.head
        sal = {
            "target": (-0.135 * b.scale, hd.y - 0.075 * b.scale, hd.z + 0.045 * b.scale),
            "pole": (-1.0, -0.25, -0.15),
            "hand_dir": (0.75, -0.25, 0.55),
            "dorsal": (-0.35, -0.75, 0.55),
            "fingers": 0.0,
            "thumb": 0.0,
        }
        if raise_ <= 0.0:
            p["arm_R"] = rest_r
        else:
            # Blend in shoulder-relative space so the hand travels on a clean arc.
            sh = Vector(b.shoulder)
            sh.x = -sh.x
            r0 = Vector(rest_r["rel"]) + sh
            r1 = Vector(sal["target"])
            mid = r0.lerp(r1, raise_) + Vector((-0.10, -0.12, 0.0)) * math.sin(math.pi * raise_)
            p["arm_R"] = {
                "target": tuple(mid),
                "pole": tuple(Vector(rest_r["pole"]).lerp(Vector(sal["pole"]), raise_)),
                "hand_dir": tuple(
                    Vector(rest_r["hand_dir"]).lerp(Vector(sal["hand_dir"]), raise_).normalized()
                ),
                "dorsal": tuple(
                    Vector(rest_r["dorsal"]).lerp(Vector(sal["dorsal"]), raise_).normalized()
                ),
                "fingers": C.lerp(rest_r["fingers"], 0.0, raise_),
                "thumb": C.lerp(10.0, 0.0, raise_),
            }
        p["arm_L"] = hanging_arm(b, "L", swing=0.0, bend=8, out=0.03, curl=8.0 + 6 * att)
        out.append(p)
    return out


def clip_stand_type(b: Body):
    """Standing at a console, typing on a surface at STAND_DESK_HEIGHT."""
    T = 4.0
    out = []
    for f in range(frames(T)):
        t = f / C.FPS
        p = stand_pose(b, t, T, sway=0.006, breathe=0.6)
        p["hips"] = Vector((p["hips"].x, 0.03, p["hips"].z))
        p["hips_rot"] = (6.0, 0.0, p["hips_rot"][2])
        p["spine"]["Spine"] = (5.0, 0.0, 0.0)
        p["spine"]["Chest"] = (4.0, 0.0, 0.0)
        p["spine"]["Neck"] = (4.0, harm(t, T, [(1, 3.0, 0.5)]), 0.0)
        p["spine"]["Head"] = (10.0, harm(t, T, [(1, 4.0, 0.5), (2, 2.0, 1.0)]), 0.0)
        _typing_hands(b, p, t, T, C.STAND_DESK_HEIGHT, -0.36 * b.scale)
        out.append(p)
    return out


def _typing_hands(b: Body, p: dict, t: float, T: float, desk_z: float, desk_y: float):
    for s, sg, ph in (("L", 1.0, 0.0), ("R", -1.0, 1.7)):
        tap = harm(t, T, [(13, 1.0, ph), (17, 0.6, ph * 2), (7, 0.4, ph * 3)])
        shift = harm(t, T, [(1, 0.025, ph), (2, 0.012, ph + 1)])
        p[f"arm_{s}"] = {
            "target": (
                sg * (0.135 * b.scale + shift * 0.5),
                desk_y + shift,
                desk_z + 0.045 + 0.006 * max(0.0, tap),
            ),
            "pole": (sg * 0.8, 0.6, -0.9),
            "hand_dir": (-sg * 0.22, -1.0, -0.22),
            "dorsal": (sg * 0.15, 0.0, 1.0),
            "fingers": 28.0 + 14.0 * max(0.0, tap),
            "thumb": 12.0,
        }


# ------------------------------------------------------------------------ sitting


def sit_base(b: Body, t: float, T: float, lean=0.0):
    seat_hips_z = C.SEAT_HEIGHT + 0.094 * b.scale
    br = harm(t, T, [(2, 1.0, 0.3)])
    p = {
        "hips": Vector((0.0, 0.06, seat_hips_z)),
        "hips_rot": (-6.0 + lean * 0.5, 0.0, 0.0),
        "spine": {
            "Spine": (4.0 + lean * 0.5 + 0.5 * br, 0.0, 0.0),
            "Chest": (1.0 + lean * 0.3 - 0.8 * br, 0.0, 0.0),
            "Neck": (-1.0, 0.0, 0.0),
            "Head": (4.0, 0.0, 0.0),
        },
        "shoulder_L": (0.6 * br, 0.0),
        "shoulder_R": (0.6 * br, 0.0),
    }
    knee_fwd = b.thigh * 0.98
    for s in ("L", "R"):
        x = 0.125 * b.scale
        y = 0.06 - knee_fwd - 0.03
        p[f"leg_{s}"] = planted_leg(b, s, x, y, 8.0)
    return p


def clip_sit_idle(b: Body):
    T = 6.0
    out = []
    for f in range(frames(T)):
        t = f / C.FPS
        p = sit_base(b, t, T, lean=-6.0)
        look = harm(t, T, [(1, 10.0, 0.2), (2, 4.0, 1.4)])
        p["spine"]["Neck"] = (-1.0, look * 0.4, 0.0)
        p["spine"]["Head"] = (
            4.0 + harm(t, T, [(3, 1.5, 0.0)]),
            look * 0.6,
            harm(t, T, [(1, 2.0, 1.0)]),
        )
        for s, sg in (("L", 1.0), ("R", -1.0)):
            p[f"arm_{s}"] = {
                "target": (
                    sg * 0.15 * b.scale,
                    0.06 - b.thigh * 0.55,
                    C.SEAT_HEIGHT + 0.17 * b.scale,
                ),
                "pole": (sg * 0.5, 1.0, -0.4),
                "hand_dir": (-sg * 0.25, -1.0, -0.35),
                "dorsal": (sg * 0.3, 0.0, 1.0),
                "fingers": 22.0,
                "thumb": 10.0,
            }
        out.append(p)
    return out


def clip_sit_type(b: Body):
    T = 4.0
    out = []
    for f in range(frames(T)):
        t = f / C.FPS
        p = sit_base(b, t, T, lean=8.0)
        p["spine"]["Neck"] = (2.0, harm(t, T, [(1, 3.0, 0.5)]), 0.0)
        p["spine"]["Head"] = (
            6.0 + harm(t, T, [(2, 1.5, 0.3)]),
            harm(t, T, [(1, 5.0, 0.5), (3, 2.0, 1.0)]),
            0.0,
        )
        _typing_hands(b, p, t, T, C.DESK_HEIGHT, 0.06 - 0.40 * b.scale)
        out.append(p)
    return out


# -------------------------------------------------------------------------- sleep


def clip_sleep(b: Body):
    T = 6.0
    out = []
    for f in range(frames(T)):
        t = f / C.FPS
        br = harm(t, T, [(1, 1.0, 0.0)])  # slow sleeping breath: 6 s
        hz = 0.105 * b.scale
        p = {
            "hips": Vector((0.0, 0.0, hz)),
            "hips_rot": (-90.0, 0.0, 0.0),
            "spine": {
                "Spine": (-2.0 - 0.8 * br, 0.0, 0.0),
                "Chest": (2.0 + 0.8 * br, 0.0, 0.0),
                "Neck": (10.0, 8.0, 0.0),
                "Head": (8.0, 14.0, 0.0),
            },
            "shoulder_L": (1.0 * br, 0.0),
            "shoulder_R": (1.0 * br, 0.0),
        }
        # Legs extended along -Y, feet relaxed (toes up and out).
        for s, sg in (("L", 1.0), ("R", -1.0)):
            ank_y = -(b.leg * 0.985)
            p[f"leg_{s}"] = {
                "target": (sg * 0.13 * b.scale, ank_y, b.ankle.z * 0.6 + 0.02),
                "pole": (sg * 0.35, 0.0, 1.0),
                "foot_dir": tuple(Vector((sg * 0.35, -0.6, 0.75)).normalized()),
                "foot_up": (0.0, 1.0, 0.0),
                "toe": 0.0,
            }
        # Left hand resting on the belly, right arm alongside the body.
        p["arm_L"] = {
            "target": (0.04 * b.scale, 0.30 * b.scale, 0.21 * b.scale + 0.006 * br),
            "pole": (1.0, 0.0, -0.4),
            "hand_dir": (-1.0, -0.25, 0.0),
            "dorsal": (0.0, 0.0, 1.0),
            "fingers": 25.0,
            "thumb": 10.0,
        }
        p["arm_R"] = {
            "target": (-0.25 * b.scale, 0.06 * b.scale, 0.07 * b.scale),
            "pole": (-0.3, 0.0, -1.0),
            "hand_dir": (-0.15, -1.0, 0.0),
            "dorsal": (-1.0, 0.0, 0.3),
            "fingers": 30.0,
            "thumb": 15.0,
        }
        out.append(p)
    return out


# --------------------------------------------------------------------------- walk


WALK_FRAMES = 30  # one full cycle (two steps): 120 steps per minute
LEG_M = 0.8426  # hip-to-ankle length of the male skeleton (walks at WALK_SPEED)


def walk_stride(b: Body) -> float:
    """Ground distance per cycle; the male skeleton walks at WALK_SPEED."""
    return C.WALK_SPEED * (WALK_FRAMES / C.FPS) * (b.leg / LEG_M)


def _foot_track(b: Body, phase: float, stride: float, side: str):
    """Ankle position (in-place frame), foot pitch and toe angle at a cycle phase."""
    v = stride  # ground displacement per unit phase (+Y = backwards)
    hs_pitch, to_pitch = -18.0, 38.0
    load_end, rise_start, toe_off = 0.08, 0.42, 0.62
    x = 0.098 * b.scale
    heel_hs_y = 0.025 + b.heel_vec.y - v * 0.31

    def heel_pivot(heel_y, pitch):
        r = Matrix.Rotation(math.radians(pitch), 3, "X")
        heel = Vector((0.0, heel_y, 0.0))
        return heel - r @ b.heel_vec

    def ball_pivot(ball_y, pitch):
        r = Matrix.Rotation(math.radians(pitch), 3, "X")
        ball = Vector((0.0, ball_y, b.ball.z))
        return ball - r @ b.foot_vec

    def stance(ph):
        if ph < load_end:
            k = ease(ph / load_end)
            pitch = C.lerp(hs_pitch, 0.0, k)
            a = heel_pivot(heel_hs_y + v * ph, pitch)
            return a, pitch, 0.0
        a_flat = heel_pivot(heel_hs_y + v * load_end, 0.0)
        if ph < rise_start:
            return a_flat + Vector((0, v * (ph - load_end), 0)), 0.0, 0.0
        ball0 = (a_flat + b.foot_vec).y + v * (rise_start - load_end)
        k = (ph - rise_start) / (toe_off - rise_start)
        pitch = to_pitch * (k**1.6)
        a = ball_pivot(ball0 + v * (ph - rise_start), pitch)
        return a, pitch, pitch * 0.9

    if phase < toe_off:
        a, pitch, toe = stance(phase)
    else:
        s = (phase - toe_off) / (1.0 - toe_off)
        a0, p0, _ = stance(toe_off)
        a1, p1, _ = stance(0.0)
        a1 = a1.copy()
        # Hermite in y with the ground speed at both ends, lifted in z.
        m = v * (1.0 - toe_off)
        h00 = 2 * s**3 - 3 * s**2 + 1
        h10 = s**3 - 2 * s**2 + s
        h01 = -2 * s**3 + 3 * s**2
        h11 = s**3 - s**2
        y = h00 * a0.y + h10 * m + h01 * a1.y + h11 * m
        lift = math.sin(math.pi * min(1.0, s * 1.15)) ** 1.5
        z = C.lerp(a0.z, a1.z, ease(s)) + 0.055 * b.scale * lift
        a = Vector((0.0, y, z))
        if s < 0.5:
            pitch = C.lerp(p0, -4.0, ease(s / 0.5))
        else:
            pitch = C.lerp(-4.0, hs_pitch, ease((s - 0.5) / 0.5))
        if s < 0.35:
            toe = C.lerp(p0 * 0.9, 6.0, ease(s / 0.35))
        else:
            toe = C.lerp(6.0, 0.0, ease((s - 0.35) / 0.65))
    a.x = x if side == "L" else -x
    return a, pitch, toe


def clip_walk(b: Body):
    n = WALK_FRAMES
    stride = walk_stride(b)
    out = []
    for f in range(n + 1):
        ph = (f % n) / n
        legs = {}
        for s, off in (("L", 0.0), ("R", 0.5)):
            a, pitch, toe = _foot_track(b, (ph + off) % 1.0, stride, s)
            legs[s] = (a, pitch, toe)
        c1 = math.cos(TAU * ph)
        s1 = math.sin(TAU * ph)
        bob = -math.cos(2 * TAU * ph)
        hz = b.hips.z - 0.040 * b.scale + 0.016 * b.scale * (bob * 0.5 - 0.5)
        # Keep both legs within reach (soft): lower the hips where needed.
        for s in ("L", "R"):
            a = legs[s][0]
            hip = b.hip_l.copy()
            hip.x = abs(hip.x) * (1 if s == "L" else -1)
            dx = a.x - hip.x
            dy = a.y - 0.0
            reach = b.leg * 0.992
            zmax = a.z + math.sqrt(max(0.0, reach**2 - dx * dx - dy * dy)) + (b.hips.z - b.hip_l.z)
            if hz > zmax - 0.004:
                hz = zmax - 0.004 - 0.004 * math.tanh((hz - zmax) / 0.004)
        p = {
            "hips": Vector((0.016 * b.scale * s1, 0.0, hz)),
            "hips_rot": (4.0, -5.0 * c1, -3.0 * s1),
            "spine": {
                "Spine": (1.0, 4.0 * c1, 2.0 * s1),
                "Chest": (-2.0, 4.5 * c1, 1.0 * s1),
                "Neck": (-1.0, -2.0 * c1, 0.0),
                "Head": (2.0, -1.5 * c1, 0.0),
            },
            "shoulder_L": (0.0, -2.0 * c1),
            "shoulder_R": (0.0, 2.0 * c1),
        }
        for s in ("L", "R"):
            a, pitch, toe = legs[s]
            fv = foot_dir(b.foot_vec, pitch, 5.0, s)
            sg = 1.0 if s == "L" else -1.0
            p[f"leg_{s}"] = {
                "target": tuple(a),
                "pole": (sg * 0.1, -1.0, 0.0),
                "foot_dir": tuple(fv),
                "foot_up": (0, 0, 1),
                "toe": toe,
            }
        swing_l = -18.0 * c1
        p["arm_L"] = hanging_arm(b, "L", swing=swing_l, bend=14 + 10 * max(0.0, -c1), out=0.045)
        p["arm_R"] = hanging_arm(b, "R", swing=-swing_l, bend=14 + 10 * max(0.0, c1), out=0.045)
        out.append(p)
    return out


def clip_attention(b: Body):
    """Standing at attention: heels together, arms straight, chest up (loop)."""
    T = 4.0
    out = []
    for f in range(frames(T)):
        t = f / C.FPS
        p = stand_pose(b, t, T, sway=0.0, breathe=0.6)
        p["hips"] = Vector((0.0, 0.01, b.hips.z - 0.004 * b.scale))
        p["hips_rot"] = (0.0, 0.0, 0.0)
        p["spine"]["Spine"] = (-1.0, 0.0, 0.0)
        p["spine"]["Chest"] = (-4.0 - 0.6 * harm(t, T, [(2, 1.0, 0.3)]), 0.0, 0.0)
        p["spine"]["Neck"] = (-1.0, 0.0, 0.0)
        p["spine"]["Head"] = (-1.0 + 0.4 * harm(t, T, [(1, 1.0, 0.0)]), 0.0, 0.0)
        p["shoulder_L"] = (-1.0, -4.0)
        p["shoulder_R"] = (-1.0, -4.0)
        p["leg_L"] = planted_leg(b, "L", 0.07 * b.scale, 0.03, 18.0)
        p["leg_R"] = planted_leg(b, "R", 0.07 * b.scale, 0.03, 18.0)
        p["arm_L"] = hanging_arm(b, "L", swing=0.0, bend=5, out=0.015, fwd=0.0, curl=30.0)
        p["arm_R"] = hanging_arm(b, "R", swing=0.0, bend=5, out=0.015, fwd=0.0, curl=30.0)
        out.append(p)
    return out


def _lerp_spec(a, b, k):
    if isinstance(a, dict):
        return {key: _lerp_spec(a[key], b[key], k) for key in a if key in b}
    if isinstance(a, Vector):
        return a.lerp(b, k)
    if isinstance(a, (tuple, list)):
        return tuple(C.lerp(x, y, k) for x, y in zip(a, b, strict=True))
    return C.lerp(a, b, k)


def _abs_arms(b: Body, p: dict) -> dict:
    """Copy of a pose whose arm targets are absolute (for blending)."""
    q = dict(p)
    M = b.rig.solve(p)
    for s in ("L", "R"):
        spec = dict(p[f"arm_{s}"])
        if "rel" in spec:
            sh = (M[f"Shoulder_{s}"] @ Vector((0, b.rig.length[f"Shoulder_{s}"], 0, 1))).xyz
            spec["target"] = tuple(sh + Vector(spec.pop("rel")))
        q[f"arm_{s}"] = spec
    return q


def clip_sit_down(b: Body):
    """One-shot: standing in front of the seat (feet where the seated feet go) -> seated."""
    T = 1.5
    sit = _abs_arms(b, clip_sit_idle(b)[0])
    stand = stand_pose(b, 0.0, 6.0, sway=0.0, breathe=0.0)
    feet_y = sit["leg_L"]["target"][1]
    stand["hips"] = Vector((0.0, feet_y + 0.03, b.hips.z - 0.012 * b.scale))
    for s in ("L", "R"):
        stand[f"leg_{s}"] = dict(sit[f"leg_{s}"])
        stand[f"arm_{s}"] = hanging_arm(b, s, swing=0.0, bend=12)
    stand = _abs_arms(b, stand)
    out = []
    for f in range(frames(T)):
        t = f / C.FPS
        k = ease((t - 0.1) / 1.15)
        p = _lerp_spec(stand, sit, k)
        lean = math.sin(math.pi * k) ** 1.2
        p["hips"] = p["hips"] + Vector((0.0, 0.04 * lean, -0.03 * lean))
        p["hips_rot"] = (p["hips_rot"][0] + 30.0 * lean, 0.0, 0.0)
        sp = dict(p["spine"])
        sp["Spine"] = (sp["Spine"][0] + 6.0 * lean, 0.0, 0.0)
        sp["Head"] = (sp["Head"][0] - 14.0 * lean, 0.0, 0.0)
        p["spine"] = sp
        for s in ("L", "R"):
            arm = dict(p[f"arm_{s}"])
            arm["target"] = tuple(Vector(arm["target"]) + Vector((0.0, -0.10 * lean, 0.05 * lean)))
            p[f"arm_{s}"] = arm
        out.append(p)
    return out


def clip_stand_up(b: Body):
    """One-shot: seated -> standing (the reverse of A_Sit_Down, a little quicker)."""
    down = clip_sit_down(b)
    rev = list(reversed(down))
    n = len(rev)
    m = int(round(n * 0.85))
    return [rev[min(n - 1, int(round(i * (n - 1) / (m - 1))))] for i in range(m)]


CLIPS = {
    "A_Idle": (clip_idle, True),
    "A_Walk": (clip_walk, True),
    "A_Sit_Idle": (clip_sit_idle, True),
    "A_Sit_Type": (clip_sit_type, True),
    "A_Stand_Type": (clip_stand_type, True),
    "A_Talk": (clip_talk, True),
    "A_Listen": (clip_listen, True),
    "A_Salute": (clip_salute, False),
    "A_Wave": (clip_wave, True),
    "A_Attention": (clip_attention, True),
    "A_Sit_Down": (clip_sit_down, False),
    "A_Stand_Up": (clip_stand_up, False),
    "A_Sleep": (clip_sleep, True),
}
