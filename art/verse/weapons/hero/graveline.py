"""Graveline hero rifle with a holographic box sight, for the first-person view (bpy).

An original design (no real firearm copied): a slab-sided upper with a chamfered
spine, a long octagonal handguard with slot rows, a three-port brake, a
skeleton stock on a buffer tube and a box holographic sight with a hooded
window. Burnt-bronze coating on the aluminium, black anodised optic, black
polymer furniture, nitrided steel barrel.

Bones and sockets follow `specs.GRAVELINE` so the viewmodel and the rig keep
working: `Root` (grip point), `Magazine`, `Bolt`, `Trigger`.
"""

from __future__ import annotations

from .. import specs
from . import kit

#: Socket positions of this mesh (weapon space, metres), from `specs.GRAVELINE_HERO`.
SOCKETS = {s.name: s.location for s in specs.GRAVELINE_HERO.sockets}
SIGHT_Z = SOCKETS["SOCKET_Sight"][2]


def materials() -> dict:
    return {
        "bronze": kit.coated(
            "M_Weapon_Bronze",
            base=(0.235, 0.175, 0.105),
            worn=(0.62, 0.6, 0.57),
            rough=0.64,
            wear=0.42,
            dust_amount=0.35,
            scratches=0.45,
        ),
        "anodised": kit.coated(
            "M_Weapon_Anodised",
            base=(0.018, 0.018, 0.02),
            worn=(0.24, 0.24, 0.25),
            rough=0.62,
            metallic_base=0.0,
            wear=0.7,
            micro=0.15,
            scratches=0.25,
        ),
        "polymer": kit.polymer("M_Weapon_Polymer"),
        "steel": kit.steel("M_Weapon_Steel"),
        "glass": kit.glass("M_Weapon_Optic"),
        "reticle": kit.emissive("M_Weapon_Reticle", (1.0, 0.12, 0.04), 14.0),
    }


def build() -> dict:
    m = materials()
    B, A, P, S = m["bronze"], m["anodised"], m["polymer"], m["steel"]

    # ---- Upper receiver: slab with a chamfered spine and an ejection port.
    upper = kit.box("Upper", (-0.075, -0.0235, 0.032), (0.215, 0.0235, 0.084), B, bevel=0.0025)
    spine_l = kit.box(
        "SpineCutL",
        (-0.08, 0.012, 0.074),
        (0.22, 0.04, 0.10),
        None,
        rot=(45, 0, 0),
        pivot=(0, 0.0235, 0.084),
    )
    spine_r = kit.box(
        "SpineCutR",
        (-0.08, -0.04, 0.074),
        (0.22, -0.012, 0.10),
        None,
        rot=(-45, 0, 0),
        pivot=(0, -0.0235, 0.084),
    )
    port = kit.box("PortCut", (0.075, -0.03, 0.046), (0.15, -0.018, 0.071), None)
    for c in (spine_l, spine_r, port):
        c.modifiers.clear()
        kit.cut(upper, c)
    # Dust cover hinge rod and the bolt carrier face seen through the port.
    kit.cylinder("PortHinge", 0.073, 0.152, 0.0022, S, y=-0.0238, z=0.044)
    kit.box("BoltFace", (0.078, -0.019, 0.049), (0.147, -0.012, 0.068), S, bone="Bolt", bevel=0.001)
    # Side relief panels (machining pockets) on the left.
    for i, (x0, x1) in enumerate(((-0.065, -0.005), (0.16, 0.205))):
        pocket = kit.box(f"PocketCut{i}", (x0, 0.019, 0.042), (x1, 0.03, 0.07), None)
        pocket.modifiers.clear()
        kit.cut(upper, pocket)
    # Forward assist style plunger on the right, charging handle at the rear.
    kit.cylinder_axis("Plunger", (0.0, -0.028, 0.068), 0.0065, 0.012, "Y", A)
    kit.box("ChargeBar", (-0.105, -0.004, 0.072), (-0.07, 0.004, 0.082), A, bevel=0.001)
    kit.box("ChargeLatch", (-0.112, -0.022, 0.071), (-0.098, 0.022, 0.083), A, bevel=0.0018)

    # Engraved markings on the left of the upper and the lower.
    kit.engrave(upper, "GRAVELINE", (0.02, 0.0236, 0.056), 0.0085)
    kit.engrave(upper, "DODAIOS ARMS  CAL 6.8", (0.02, 0.0236, 0.044), 0.0042)
    for k, x in enumerate((-0.05, 0.19)):
        kit.cylinder_axis(f"UpperPin{k}", (x, 0.0, 0.074), 0.0024, 0.0485, "Y", S, sides=16)
    # ---- Top rail along upper and handguard: 41 lugs.
    kit.box("RailBase", (-0.07, -0.0105, 0.084), (0.46, 0.0105, 0.090), A, bevel=0.0008)
    x = -0.066
    i = 0
    while x < 0.455:
        kit.box(
            f"RailLug{i:02d}", (x, -0.0105, 0.090), (x + 0.0052, 0.0105, 0.0955), A, bevel=0.0006
        )
        x += 0.01
        i += 1

    # ---- Lower receiver, magazine well, trigger guard.
    lower = kit.box("Lower", (-0.06, -0.022, -0.012), (0.155, 0.022, 0.033), B, bevel=0.0022)
    kit.box(
        "MagWell", (0.068, -0.0245, -0.04), (0.128, 0.0245, 0.005), B, bevel=0.003, rot=(0, -8, 0)
    )
    kit.box("GuardBottom", (0.0, -0.007, -0.042), (0.075, 0.007, -0.036), P, bevel=0.002)
    kit.box("GuardFront", (0.066, -0.007, -0.042), (0.074, 0.007, -0.01), P, bevel=0.002)
    kit.box(
        "Trigger", (0.028, -0.003, -0.032), (0.034, 0.003, -0.008), S, bone="Trigger", bevel=0.0012
    )
    kit.cylinder_axis("PinTrigger", (0.031, 0.0, 0.0), 0.0022, 0.047, "Y", S)
    kit.cylinder_axis("PinHammer", (0.054, 0.0, 0.004), 0.0022, 0.047, "Y", S)
    kit.cylinder_axis("PinTakedown", (-0.045, 0.0, 0.022), 0.0026, 0.047, "Y", S)
    kit.cylinder_axis("Selector", (0.012, 0.026, 0.02), 0.0055, 0.004, "Y", A)
    kit.box(
        "SelectorLever", (0.004, 0.027, 0.018), (0.03, 0.03, 0.024), A, bevel=0.001, rot=(0, -20, 0)
    )
    kit.box("MagRelease", (0.071, -0.027, 0.002), (0.082, -0.022, 0.014), A, bevel=0.0012)
    del lower

    # ---- Pistol grip: raked, finger ridges.
    kit.box(
        "Grip",
        (-0.017, -0.0155, -0.118),
        (0.019, 0.0155, -0.004),
        P,
        bevel=0.004,
        segments=3,
        rot=(0, 18, 0),
        pivot=(0, 0, -0.004),
    )
    kit.box(
        "GripBeavertail",
        (-0.03, -0.016, -0.018),
        (0.005, 0.016, -0.004),
        P,
        bevel=0.004,
        rot=(0, 18, 0),
        pivot=(0, 0, -0.004),
    )
    kit.box(
        "GripCap",
        (-0.02, -0.017, -0.128),
        (0.024, 0.017, -0.118),
        P,
        bevel=0.003,
        rot=(0, 18, 0),
        pivot=(0, 0, -0.004),
    )

    # ---- Magazine: one curved body with a ribbed spine and a base plate.
    kit.curved_box(
        "Mag", (0.074, -0.0195, -0.215), (0.122, 0.0195, -0.02), P, bone="Magazine", bend=1.05
    )
    kit.curved_box(
        "MagSpine",
        (0.118, -0.0215, -0.2),
        (0.126, 0.0215, -0.03),
        P,
        bone="Magazine",
        bend=1.05,
        bevel=0.0015,
    )
    kit.box(
        "MagPlate",
        (0.112, -0.022, -0.232),
        (0.172, 0.022, -0.218),
        P,
        bone="Magazine",
        bevel=0.003,
        rot=(0, -24, 0),
        pivot=(0.142, 0, -0.225),
    )
    for k in range(5):
        d = 0.05 + k * 0.032
        x = 0.072 + 1.05 * d * d
        kit.box(
            f"MagRibL{k}",
            (x + 0.006, 0.0192, 0.0 - d - 0.004),
            (x + 0.044, 0.0212, 0.0 - d),
            P,
            bone="Magazine",
            bevel=0.0008,
            rot=(0, -2 * 1.05 * d * 57.3, 0),
        )

    # ---- Handguard: octagonal tube with slot rows and a hand stop.
    hg = kit.prism("Handguard", 0.205, 0.475, 0.031, 8, B, z=0.052, rot_deg=22.5, bevel=0.002)
    for side, y in (("L", 0.026), ("R", -0.026)):
        for k in range(6):
            x0 = 0.23 + k * 0.039
            slot = kit.box(
                f"Slot{side}{k}", (x0, y - 0.012, 0.046), (x0 + 0.024, y + 0.012, 0.058), None
            )
            slot.modifiers.clear()
            kit.cut(hg, slot)
    for k in range(5):
        x0 = 0.25 + k * 0.042
        slot = kit.box(f"SlotB{k}", (x0, -0.006, 0.0), (x0 + 0.026, 0.006, 0.03), None)
        slot.modifiers.clear()
        kit.cut(hg, slot)
    kit.box("HandStop", (0.36, -0.006, 0.006), (0.40, 0.006, 0.022), P, bevel=0.003)
    kit.box("HandguardNut", (0.198, -0.026, 0.024), (0.212, 0.026, 0.08), A, bevel=0.002)

    # ---- Barrel, gas block, brake.
    kit.cylinder("Barrel", 0.2, 0.67, 0.0092, S, z=0.045, sides=36)
    kit.cylinder("BrakeCollar", 0.664, 0.676, 0.0128, S, z=0.045, sides=6)
    brake = kit.cylinder("Brake", 0.676, 0.742, 0.0142, S, z=0.045, sides=36)
    for k in range(3):
        x0 = 0.684 + k * 0.018
        for y0, y1 in ((0.004, 0.03), (-0.03, -0.004)):
            c = kit.box(f"BrakePort{k}{y0 > 0}", (x0, y0, 0.036), (x0 + 0.009, y1, 0.054), None)
            c.modifiers.clear()
            kit.cut(brake, c)
    bore = kit.cylinder("BoreCut", 0.735, 0.75, 0.006, None, z=0.045, sides=24)
    bore.modifiers.clear()
    kit.cut(brake, bore)

    # ---- Stock: buffer tube, skeleton stock, butt pad, cheek riser.
    kit.cylinder("BufferTube", -0.27, -0.06, 0.0152, A, z=0.058, sides=32)
    kit.cylinder("CastleNut", -0.072, -0.06, 0.018, A, z=0.058, sides=8)
    kit.box("StockTop", (-0.27, -0.016, 0.064), (-0.13, 0.016, 0.088), P, bevel=0.004)
    kit.box(
        "StockStrut",
        (-0.25, -0.012, -0.03),
        (-0.2, 0.012, 0.06),
        P,
        bevel=0.004,
        rot=(0, 25, 0),
        pivot=(-0.225, 0, 0.015),
    )
    kit.box("StockBottom", (-0.285, -0.014, -0.045), (-0.17, 0.014, -0.025), P, bevel=0.004)
    kit.box("ButtPad", (-0.3, -0.019, -0.05), (-0.283, 0.019, 0.092), P, bevel=0.005, segments=3)

    # ---- Holographic sight on the rail (x 0.02 .. 0.135).
    kit.box("OpticMount", (0.025, -0.017, 0.0955), (0.11, 0.017, 0.104), A, bevel=0.0015)
    kit.box("OpticClamp", (0.04, -0.025, 0.086), (0.07, -0.017, 0.104), A, bevel=0.0015)
    kit.cylinder_axis("OpticKnob", (0.055, -0.03, 0.095), 0.0085, 0.009, "Y", A, sides=16)
    body = kit.box("OpticBody", (0.02, -0.0215, 0.104), (0.135, 0.0215, 0.118), A, bevel=0.003)
    del body
    # Hood: a hollow box tube with the window through X.
    hood = kit.box(
        "OpticHood", (0.032, -0.0255, 0.112), (0.128, 0.0255, 0.162), A, bevel=0.0035, segments=3
    )
    win = kit.box("OpticWindowCut", (0.0, -0.019, 0.118), (0.2, 0.019, 0.155), None)
    win.modifiers.clear()
    kit.cut(hood, win)
    slant = kit.box(
        "OpticSlantCut",
        (0.1, -0.05, 0.16),
        (0.2, 0.05, 0.2),
        None,
        rot=(0, 28, 0),
        pivot=(0.105, 0, 0.162),
    )
    slant.modifiers.clear()
    kit.cut(hood, slant)
    for side, y in (("L", 0.0262), ("R", -0.0262)):
        for k, (sx, sz) in enumerate(((0.045, 0.12), (0.045, 0.154), (0.118, 0.12))):
            kit.cylinder_axis(
                f"OpticScrew{side}{k}", (sx, y, sz), 0.0019, 0.0012, "Y", m["steel"], sides=12
            )
    # Front and rear frame lips, the rear battery cap and the button panel.
    kit.box("OpticLipRear", (0.03, -0.0262, 0.111), (0.036, 0.0262, 0.163), A, bevel=0.0015)
    lip_win = kit.box("OpticLipWin", (0.0, -0.0175, 0.1195), (0.2, 0.0175, 0.1535), None)
    lip_win.modifiers.clear()
    kit.cut(bpy_obj("OpticLipRear"), lip_win)
    kit.box("OpticButtonPanel", (0.008, -0.016, 0.104), (0.03, 0.016, 0.116), A, bevel=0.002)
    for k, y in enumerate((-0.007, 0.007)):
        kit.box(
            f"OpticButton{k}",
            (0.0035, y - 0.004, 0.106),
            (0.009, y + 0.004, 0.114),
            m["polymer"],
            bevel=0.0012,
        )
    kit.cylinder_axis("OpticBattery", (0.09, 0.027, 0.111), 0.0075, 0.008, "Y", A, sides=24)
    # Glass: the angled front pane and the rear pane.
    kit.box(
        "OpticGlassFront",
        (0.121, -0.0192, 0.1182),
        (0.1225, 0.0192, 0.1548),
        m["glass"],
        bevel=0.0,
        rot=(0, -12, 0),
    )
    kit.box(
        "OpticGlassRear", (0.0405, -0.0192, 0.1182), (0.0415, 0.0192, 0.1548), m["glass"], bevel=0.0
    )
    # Reticle: 65 MOA style ring and a centre dot, drawn on the front pane.
    kit.torus("ReticleRing", (0.1195, 0.0, SIGHT_Z), 0.0062, 0.00024, m["reticle"])
    kit.cylinder_axis(
        "ReticleDot", (0.1195, 0.0, SIGHT_Z), 0.0004, 0.0003, "X", m["reticle"], sides=16, bevel=0.0
    )
    for k, (dy, dz) in enumerate(((0, 1), (0, -1), (1, 0), (-1, 0))):
        c = (0.1195, dy * 0.0071, SIGHT_Z + dz * 0.0071)
        lo = (
            c[0] - 0.00015,
            c[1] - (0.0005 if dy else 0.00022),
            c[2] - (0.0005 if dz else 0.00022),
        )
        hi = (
            c[0] + 0.00015,
            c[1] + (0.0005 if dy else 0.00022),
            c[2] + (0.0005 if dz else 0.00022),
        )
        kit.box(f"ReticleTick{k}", lo, hi, m["reticle"], bevel=0.0)
    return {"materials": m, "sockets": SOCKETS}


def bpy_obj(name):
    import bpy

    return bpy.data.objects[name]
