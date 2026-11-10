"""The WP14 arsenal as data (pure Python, no bpy).

Weapon space (Blender, metres): +X towards the muzzle, +Z up, +Y to the
weapon's left; the origin is the grip point, which becomes bone `Root` and
attaches to `Weapon_R` of `SKEL_Verse_Human` (art-pipeline 12.2). In Unreal
space that is +X forward, +Z up, +Y right (`lib/ue_space.py`).

Ids follow combat-state 2.2 (`graveline`, `tallow`, `hookbill`, `bulwark`,
`breach_charge`, `skitter`, `longsight`). WP02 owns the weapon data assets;
these ids are the G0 test ids until WP02.1 lands.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CONTENT_ROOT = "/Game/Verse/Weapons"
VFX_ROOT = "/Game/Verse/VFX/Weapons"
OWNER = "WP14"

#: Budgets of A14.1 / art-pipeline 6.2 and 10.4.
MAX_WEAPON_BONES = 24
MAX_FIRST_PERSON_TRIANGLES = 60_000
MAX_WORLD_WEAPON_TRIANGLES = 150_000
MAX_VFX_TRIANGLES = 2_000

#: Sockets every firearm carries (art-pipeline 12.2).
FIREARM_SOCKETS = ("SOCKET_Muzzle", "SOCKET_Sight", "SOCKET_Support", "SOCKET_Eject")
KNIFE_SOCKETS = ("SOCKET_Tip",)
#: Static bone that carries the socket empties in the FBX. The Interchange
#: skeletal importer keys the sockets found directly under the root joint by
#: the joint's uid instead of its bone name and then drops them (UE 5.7), so
#: the empties sit on this child of `Root` with Root's exact head and tail;
#: `weapons.editor.rig` re-binds each socket to its spec bone after the
#: import, which keeps its local transform because both bones coincide.
SOCKET_BASE = "SocketBase"

#: Material slots (Blender names); `lib/unreal_materials.py` maps them to
#: `/Game/Verse/Materials/Instances/Weapons/MI_Weapon_*`.
SLOT_STEEL = "M_Weapon_Steel"
SLOT_POLYMER = "M_Weapon_Polymer"
SLOT_GRIP = "M_Weapon_Grip"
SLOT_OPTIC = "M_Weapon_Optic"
SLOT_RETICLE = "M_Weapon_Reticle"
SLOT_FIELD = "M_Weapon_Field"
SLOT_INDICATOR = "M_Weapon_Indicator"
WEAPON_SLOTS = (SLOT_STEEL, SLOT_POLYMER, SLOT_GRIP, SLOT_OPTIC, SLOT_RETICLE)


@dataclass(frozen=True)
class Bone:
    name: str
    parent: str | None
    head: tuple[float, float, float]
    tail: tuple[float, float, float]


@dataclass(frozen=True)
class Socket:
    name: str
    bone: str
    location: tuple[float, float, float]  # weapon space, metres (Blender)


@dataclass(frozen=True)
class WeaponSpec:
    weapon_id: str
    display_name: str
    role: str
    asset: str  # SK_Weapon_* or SM_Weapon_*
    kind: str  # "skeletal" or "static"
    bones: tuple[Bone, ...] = ()
    sockets: tuple[Socket, ...] = ()
    triangle_cap: int = MAX_FIRST_PERSON_TRIANGLES
    design: tuple[str, ...] = field(default_factory=tuple)

    @property
    def folder(self) -> str:
        return f"{CONTENT_ROOT}/{self.display_name}"

    @property
    def object_path(self) -> str:
        return f"{self.folder}/{self.asset}.{self.asset}"

    @property
    def skeleton(self) -> str | None:
        if self.kind != "skeletal":
            return None
        return f"SKEL_Weapon_{self.display_name}"

    @property
    def skeleton_path(self) -> str | None:
        skel = self.skeleton
        return f"{self.folder}/{skel}.{skel}" if skel else None

    def socket_names(self) -> tuple[str, ...]:
        return tuple(s.name for s in self.sockets)


def _b(name, parent, head, tail) -> Bone:
    return Bone(name, parent, tuple(head), tuple(tail))


def export_bones(spec: WeaponSpec) -> tuple[Bone, ...]:
    """The bones written to the FBX: the spec bones plus `SOCKET_BASE` on Root."""
    if spec.kind != "skeletal" or not spec.sockets:
        return spec.bones
    root = next(b for b in spec.bones if b.parent is None)
    return (*spec.bones, Bone(SOCKET_BASE, root.name, root.head, root.tail))


def _firearm_bones(*, mag, bolt, trigger, bolt_name="Bolt") -> tuple[Bone, ...]:
    """Root at the grip, pointing forward; parts as children of Root."""
    return (
        _b("Root", None, (0.0, 0.0, 0.0), (0.06, 0.0, 0.0)),
        _b("Magazine", "Root", mag, (mag[0], mag[1], mag[2] - 0.05)),
        _b(bolt_name, "Root", bolt, (bolt[0] - 0.05, bolt[1], bolt[2])),
        _b("Trigger", "Root", trigger, (trigger[0], trigger[1], trigger[2] - 0.02)),
    )


def _sockets(muzzle, sight, support, eject) -> tuple[Socket, ...]:
    return (
        Socket("SOCKET_Muzzle", "Root", muzzle),
        Socket("SOCKET_Sight", "Root", sight),
        Socket("SOCKET_Support", "Root", support),
        Socket("SOCKET_Eject", "Root", eject),
    )


GRAVELINE = WeaponSpec(
    weapon_id="graveline",
    display_name="Graveline",
    role="assault rifle",
    asset="SK_Weapon_Graveline",
    kind="skeletal",
    bones=_firearm_bones(
        mag=(0.085, 0.0, -0.02), bolt=(0.14, -0.03, 0.055), trigger=(0.035, 0.0, -0.005)
    ),
    sockets=_sockets(
        muzzle=(0.735, 0.0, 0.035),
        sight=(0.1255, 0.0, 0.1475),  # the reflex dot (`build.GRAVELINE_DOT`)
        support=(0.40, 0.0, -0.005),
        eject=(0.15, -0.032, 0.045),
    ),
    design=(
        "Split upper receiver with a panel break, raised side panels and a framed ejection port",
        "Handguard of bands and ribs around a dark core: two rows of open vents per side",
        "Low open reflex sight on a short riser: slim posts, wide glass, small amber dot",
        "Top rail of cross lugs from the end plate to the handguard's front",
        "Slotted muzzle device of three rings on a faceted core",
        "Skeleton stock on a tube: cheek riser, angled lower strut, butt block with rubber pad",
        "Magazine in two segments that curve forward, with side ribs and a steel base plate",
    ),
)

TALLOW = WeaponSpec(
    weapon_id="tallow",
    display_name="Tallow",
    role="pistol",
    asset="SK_Weapon_Tallow",
    kind="skeletal",
    bones=_firearm_bones(
        mag=(-0.012, 0.0, -0.03),
        bolt=(0.03, 0.0, 0.055),
        trigger=(0.03, 0.0, 0.0),
        bolt_name="Slide",
    ),
    sockets=_sockets(
        muzzle=(0.155, 0.0, 0.05),
        sight=(-0.02, 0.0, 0.085),
        support=(-0.005, 0.022, -0.045),
        eject=(0.06, -0.016, 0.065),
    ),
    design=(
        "Wedge slide whose front third steps down by a 45 degree chamfer",
        "Rear serration as three deep horizontal grooves, not vertical cuts",
        "Grip with a hard brutalist backstrap step and a flat base plate",
        "Square trigger guard with a chamfered front corner",
    ),
)

HOOKBILL = WeaponSpec(
    weapon_id="hookbill",
    display_name="Hookbill",
    role="knife",
    asset="SK_Weapon_Hookbill",
    kind="skeletal",
    bones=(_b("Root", None, (0.0, 0.0, 0.0), (0.06, 0.0, 0.0)),),
    sockets=(Socket("SOCKET_Tip", "Root", (0.25, 0.0, 0.004)),),
    design=(
        "Straight single-edged blade whose spine bends down into a short hook at the tip",
        "Faceted blade grind: two flat planes, no hollow grind",
        "Square guard plate and a handle of stacked chamfered rubber blocks",
        "Pommel as a flat hexagonal cap",
    ),
)

SKITTER = WeaponSpec(
    weapon_id="skitter",
    display_name="Skitter",
    role="submachine gun",
    asset="SK_Weapon_Skitter",
    kind="skeletal",
    bones=_firearm_bones(
        mag=(0.11, 0.0, -0.02), bolt=(0.09, 0.03, 0.05), trigger=(0.035, 0.0, -0.005)
    ),
    sockets=_sockets(
        muzzle=(0.40, 0.0, 0.03),
        sight=(0.06, 0.0, 0.103),
        support=(0.11, 0.0, -0.09),
        eject=(0.12, -0.03, 0.04),
    ),
    design=(
        "Short box receiver with a forward magazine that doubles as the support grip",
        "Charging slot on the left side",
        "Stubby collapsed stock of a single flat bar",
        "Low open sight blades instead of an optic",
    ),
)

LONGSIGHT = WeaponSpec(
    weapon_id="longsight",
    display_name="Longsight",
    role="designated marksman rifle",
    asset="SK_Weapon_Longsight",
    kind="skeletal",
    bones=_firearm_bones(
        mag=(0.10, 0.0, -0.02), bolt=(0.16, -0.032, 0.06), trigger=(0.035, 0.0, -0.005)
    ),
    sockets=_sockets(
        muzzle=(0.925, 0.0, 0.04),
        sight=(0.11, 0.0, 0.15),
        support=(0.44, 0.0, -0.01),
        eject=(0.17, -0.034, 0.05),
    ),
    design=(
        "Long faceted octagonal barrel shroud ending in a squared muzzle block",
        "Tube sight on two flat stand-offs with deep sun hoods",
        "Solid stock with a stepped cheek riser",
        "Short box magazine",
    ),
)

BULWARK = WeaponSpec(
    weapon_id="bulwark",
    display_name="Bulwark",
    role="deployable energy barricade",
    asset="SM_Weapon_Bulwark",
    kind="static",
    triangle_cap=MAX_WORLD_WEAPON_TRIANGLES,
    design=(
        "Low steel sled with two fold-out feet and an emitter rail along its top",
        "Energy field panel as a separate mesh SM_Weapon_BulwarkField (thin, translucent)",
        "One black glass status lens at the rear (unlit)",
    ),
)

BULWARK_FIELD = WeaponSpec(
    weapon_id="bulwark",
    display_name="Bulwark",
    role="energy field of the Bulwark",
    asset="SM_Weapon_BulwarkField",
    kind="static",
    triangle_cap=MAX_WORLD_WEAPON_TRIANGLES,
)

BREACH_CHARGE = WeaponSpec(
    weapon_id="breach_charge",
    display_name="BreachCharge",
    role="breach charge",
    asset="SM_Weapon_BreachCharge",
    kind="static",
    triangle_cap=MAX_WORLD_WEAPON_TRIANGLES,
    design=(
        "Flat rectangular slab in a chamfered frame with four corner pads",
        "Detonator block in the middle with one black glass arming lens (unlit)",
    ),
)

ARSENAL: tuple[WeaponSpec, ...] = (
    GRAVELINE,
    TALLOW,
    HOOKBILL,
    BULWARK,
    BULWARK_FIELD,
    BREACH_CHARGE,
    SKITTER,
    LONGSIGHT,
)


@dataclass(frozen=True)
class VfxSpec:
    asset: str
    use: str
    material: str  # MI name
    triangle_cap: int = MAX_VFX_TRIANGLES

    @property
    def object_path(self) -> str:
        return f"{VFX_ROOT}/{self.asset}.{self.asset}"


VFX: tuple[VfxSpec, ...] = (
    VfxSpec(
        "SM_Vfx_Bolt",
        "laser bolt core and glow sleeve, 60 cm long, +X along flight",
        "MI_Weapon_Vfx_BoltOwn",
    ),
    VfxSpec("SM_Vfx_MuzzleFlash", "crossed flash cards on +X", "MI_Weapon_Vfx_MuzzleOwn"),
    VfxSpec(
        "SM_Vfx_ImpactSparks",
        "spark streak burst along +X (surface normal)",
        "MI_Weapon_Vfx_Sparks",
    ),
)


#: Weapon VFX material instances: (MI, master, use). The scorch is a decal (no mesh).
VFX_MATERIALS: tuple[tuple[str, str, str], ...] = (
    ("MI_Weapon_Vfx_BoltOwn", "M_Verse_Emissive", "own bolt, amber"),
    ("MI_Weapon_Vfx_BoltFoe", "M_Verse_Emissive", "opponent bolt, red"),
    ("MI_Weapon_Vfx_MuzzleOwn", "M_Verse_Emissive", "own muzzle flash, amber"),
    ("MI_Weapon_Vfx_MuzzleFoe", "M_Verse_Emissive", "opponent muzzle flash, red"),
    ("MI_Weapon_Vfx_Sparks", "M_Verse_Emissive", "impact sparks, amber-white"),
    ("MI_Weapon_Vfx_Scorch", "M_Verse_Decal", "impact scorch decal, oil black"),
)


def by_id(weapon_id: str) -> WeaponSpec:
    for spec in ARSENAL:
        if spec.weapon_id == weapon_id and not spec.asset.endswith("Field"):
            return spec
    raise KeyError(weapon_id)


def by_asset(asset: str) -> WeaponSpec:
    for spec in ARSENAL:
        if spec.asset == asset:
            return spec
    raise KeyError(asset)


def required_sockets(spec: WeaponSpec) -> tuple[str, ...]:
    if spec.kind != "skeletal":
        return ()
    return KNIFE_SOCKETS if spec.role == "knife" else FIREARM_SOCKETS


def required_bones(spec: WeaponSpec) -> tuple[str, ...]:
    if spec.kind != "skeletal":
        return ()
    if spec.role == "knife":
        return ("Root",)
    slide = "Slide" if spec.role == "pistol" else "Bolt"
    return ("Root", "Magazine", slide, "Trigger")


def socket_to_ue_cm(location_m: tuple[float, float, float]) -> tuple[float, float, float]:
    """Blender metres -> Unreal centimetres (art-pipeline 4.1)."""
    x, y, z = location_m
    return (round(100.0 * x, 4), round(-100.0 * y, 4), round(100.0 * z, 4))
