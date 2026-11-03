"""WP14 look development captures in a headless editor with a GPU (evidence of WP14).

`python scripts/unreal/import_art.py lookdev` runs this in a transient level
(never saved) and writes PNG frames plus `lookdev.json` into
`unreal/Verse/Saved/Harness/proof/WP14/lookdev/` (ignored):

* `chart_*`: the 24-patch chart as unlit emissive patches at exposure 1
  through `M_Verse_PostTonemap` (A14.4, compared with Blender AgX by
  `art/verse/weapons/look/evaluate.py`),
* `turn_<Weapon>_<view>`: weapon turnarounds under a hard work light,
* `fp_<Weapon>`: first-person framings,
* `ref_<view>`: reference views of a deck corner in Military-Industrial Noir,
* `vfx_<view>`: bolts in flight (own amber, foe red), muzzle flash, impact,
* `vfx_cost` in `lookdev.json`: A14.5, the frame cost of 64 and 1024 bolts in
  flight at 2560x1440 (see `measure_bolt_cost`).

Rendering needs frames, so the module returns `{"deferred": true}` and runs
a small state machine on the editor's tick; it writes the report and quits
the editor itself.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path

from . import PROJECT_DIR, REPO_ROOT

OUT = PROJECT_DIR / "Saved" / "Harness" / "proof" / "WP14" / "lookdev"
POST = "/Game/Verse/PostProcess/M_Verse_PostTonemap.M_Verse_PostTonemap"
M = "/Game/Verse/Materials/Master/"
PLANE = "/Engine/BasicShapes/Plane.Plane"
CUBE = "/Engine/BasicShapes/Cube.Cube"
WIDTH, HEIGHT = 1920, 1080
CHART_W, CHART_H = 1200, 800
WARMUP_S = 20.0
STABLE_MAX_S = 600.0
CAPTURES_PER_SHOT = 6
COST_W, COST_H = 2560, 1440
COST_ROUNDS = 24
COST_INNER = 4
COST_SETS = {"bolts_64": 64, "bolts_1024": 1024}

#: Look profile of the reference scenes (style-unreal.md "Look profile").
PROFILE = {
    "exposure_bias": -4.0,
    "bloom": 0.35,
    "work_light": {"kelvin": 5600, "candela": 2600.0, "cone_deg": 26.0, "source_radius_cm": 1.5},
    "fill_light": {"kelvin": 4300, "candela": 90.0},
    "fog": {"density": 0.035, "luminance": 0.004, "volumetric": True, "albedo": 0.9},
}

LIN = {
    "void": (0.0034, 0.0037, 0.0044),
    "black_steel": (0.0080, 0.0085, 0.0103),
    "graphite": (0.0232, 0.0262, 0.0307),
    "gunmetal": (0.0437, 0.0497, 0.0630),
    "concrete": (0.112, 0.125, 0.138),
    "raw_concrete": (0.141, 0.150, 0.147),
    "amber": (0.888, 0.366, 0.0423),
    "red": (0.768, 0.0176, 0.0242),
    "work_white": (0.888, 0.906, 0.913),
}


def _specs():
    path = str(REPO_ROOT / "art" / "verse")
    if path not in sys.path:
        sys.path.insert(0, path)
    from weapons import specs
    from weapons.look import agx

    return specs, agx


class Scene:
    def __init__(self, u):
        self.u = u
        self.eas = u.get_editor_subsystem(u.EditorActorSubsystem)
        self.world = u.get_editor_subsystem(u.UnrealEditorSubsystem).get_editor_world()
        self.groups: dict[str, list] = {}

    def spawn(self, cls, loc=(0, 0, 0), rot=(0, 0, 0), group="base"):
        u = self.u
        actor = self.eas.spawn_actor_from_class(cls, u.Vector(*loc), _rotator(u, rot))
        self.groups.setdefault(group, []).append(actor)
        return actor

    def forget(self, actor) -> None:
        """Destroy an actor and drop it from its group (a destroyed actor is invalid)."""
        for members in self.groups.values():
            if actor in members:
                members.remove(actor)
        actor.destroy_actor()

    def show(self, group: str, visible: bool) -> None:
        for actor in self.groups.get(group, []):
            actor.set_actor_hidden_in_game(not visible)
            actor.set_is_temporarily_hidden_in_editor(not visible)
            for comp in actor.get_components_by_class(self.u.SceneComponent):
                comp.set_visibility(visible, True)

    def mid(self, master: str, vectors=None, scalars=None):
        u = self.u
        parent = u.load_asset(M + master + "." + master)
        mid = u.MaterialLibrary.create_dynamic_material_instance(self.world, parent)
        for k, v in (vectors or {}).items():
            mid.set_vector_parameter_value(k, u.LinearColor(*v, 1.0))
        for k, v in (scalars or {}).items():
            mid.set_scalar_parameter_value(k, float(v))
        return mid

    def box(self, size_cm, loc, material, group="base", rot=(0, 0, 0)):
        u = self.u
        actor = self.spawn(u.StaticMeshActor, loc, rot, group)
        comp = actor.static_mesh_component
        comp.set_mobility(u.ComponentMobility.MOVABLE)
        comp.set_static_mesh(u.load_asset(CUBE))
        comp.set_material(0, material)
        actor.set_actor_scale3d(u.Vector(size_cm[0] / 100, size_cm[1] / 100, size_cm[2] / 100))
        return actor

    def plane(self, size_cm, loc, material, rot=(0, 0, 0), group="base"):
        u = self.u
        actor = self.spawn(u.StaticMeshActor, loc, rot, group)
        comp = actor.static_mesh_component
        comp.set_mobility(u.ComponentMobility.MOVABLE)
        comp.set_static_mesh(u.load_asset(PLANE))
        comp.set_material(0, material)
        actor.set_actor_scale3d(u.Vector(size_cm[0] / 100, size_cm[1] / 100, 1.0))
        return actor

    def mesh(self, path: str, loc, rot, group: str):
        u = self.u
        asset = u.load_asset(path)
        if isinstance(asset, u.SkeletalMesh):
            actor = self.spawn(u.SkeletalMeshActor, loc, rot, group)
            comp = actor.skeletal_mesh_component
            comp.set_skeletal_mesh_asset(asset)
        else:
            actor = self.spawn(u.StaticMeshActor, loc, rot, group)
            comp = actor.static_mesh_component
            comp.set_mobility(u.ComponentMobility.MOVABLE)
            comp.set_static_mesh(asset)
        return actor

    def spot(self, loc, target, kelvin, candela, cone, group="base", radius=1.5, shadows=True):
        u = self.u
        rot = _look_rot(loc, target)
        actor = self.spawn(u.SpotLight, loc, rot, group)
        c = actor.spot_light_component
        c.set_mobility(u.ComponentMobility.MOVABLE)
        c.set_editor_property("intensity_units", u.LightUnits.CANDELAS)
        c.set_intensity(candela)
        c.set_editor_property("use_temperature", True)
        c.set_editor_property("temperature", float(kelvin))
        c.set_editor_property("outer_cone_angle", cone)
        c.set_editor_property("inner_cone_angle", cone * 0.6)
        c.set_editor_property("attenuation_radius", 4000.0)
        c.set_editor_property("source_radius", radius)
        c.set_editor_property("cast_shadows", shadows)
        return actor

    def point(self, loc, colour, candela, group="base"):
        u = self.u
        actor = self.spawn(u.PointLight, loc, (0, 0, 0), group)
        c = actor.point_light_component
        c.set_mobility(u.ComponentMobility.MOVABLE)
        c.set_editor_property("intensity_units", u.LightUnits.CANDELAS)
        c.set_intensity(candela)
        c.set_light_color(u.LinearColor(*colour, 1.0))
        c.set_editor_property("attenuation_radius", 600.0)
        c.set_editor_property("source_radius", 2.0)
        return actor


def _rotator(u, rot):
    """`rot` is (pitch, yaw, roll) degrees; `unreal.Rotator` takes (roll, pitch, yaw)."""
    return u.Rotator(roll=rot[2], pitch=rot[0], yaw=rot[1])


def _look_rot(loc, target):
    dx, dy, dz = (t - s for s, t in zip(loc, target, strict=True))
    yaw = math.degrees(math.atan2(dy, dx))
    pitch = math.degrees(math.atan2(dz, math.hypot(dx, dy)))
    return (pitch, yaw, 0.0)


def _post_settings(u, *, bias: float, bloom: float, fog=True):
    s = u.PostProcessSettings()
    post = u.load_asset(POST)
    s.set_editor_property(
        "weighted_blendables", u.WeightedBlendables([u.WeightedBlendable(1.0, post)])
    )
    s.set_editor_property("override_auto_exposure_method", True)
    s.set_editor_property("auto_exposure_method", u.AutoExposureMethod.AEM_MANUAL)
    s.set_editor_property("override_auto_exposure_bias", True)
    s.set_editor_property("auto_exposure_bias", bias)
    s.set_editor_property("override_auto_exposure_apply_physical_camera_exposure", True)
    s.set_editor_property("auto_exposure_apply_physical_camera_exposure", False)
    s.set_editor_property("override_bloom_intensity", True)
    s.set_editor_property("bloom_intensity", bloom)
    s.set_editor_property("override_local_exposure_highlight_contrast_scale", True)
    s.set_editor_property("local_exposure_highlight_contrast_scale", 1.0)
    s.set_editor_property("override_local_exposure_shadow_contrast_scale", True)
    s.set_editor_property("local_exposure_shadow_contrast_scale", 1.0)
    return s


class Capture:
    def __init__(
        self, scene: Scene, width: int, height: int, srgb: bool = False, float16: bool = False
    ):
        u = scene.u
        fmt = u.TextureRenderTargetFormat
        target_format = fmt.RTF_RGBA8_SRGB if srgb else fmt.RTF_RGBA8
        if float16:
            target_format = fmt.RTF_RGBA16F
        self.u = u
        self.scene = scene
        self.rt = u.RenderingLibrary.create_render_target2d(
            scene.world,
            width,
            height,
            target_format,
            u.LinearColor(0, 0, 0, 1),
            False,
        )
        self.actor = scene.spawn(u.SceneCapture2D, (0, 0, 0), (0, 0, 0), "capture")
        c = self.actor.capture_component2d
        c.set_editor_property("texture_target", self.rt)
        c.set_editor_property("capture_source", u.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
        c.set_editor_property("capture_every_frame", False)
        c.set_editor_property("capture_on_movement", False)
        # Post-process materials (the grade) need a view state, which a capture
        # only keeps when it persists its rendering state (or captures every frame).
        c.set_editor_property("always_persist_rendering_state", True)
        c.set_editor_property("post_process_blend_weight", 1.0)
        self.comp = c

    def setup(self, loc, target, fov, settings, ortho_width: float | None = None):
        u = self.u
        self.actor.set_actor_location_and_rotation(
            u.Vector(*loc), _rotator(u, _look_rot(loc, target)), False, False
        )
        self.comp.set_editor_property("fov_angle", fov)
        self.comp.set_editor_property("post_process_settings", settings)
        if ortho_width:
            self.comp.set_editor_property("projection_type", u.CameraProjectionMode.ORTHOGRAPHIC)
            self.comp.set_editor_property("ortho_width", ortho_width)
        else:
            self.comp.set_editor_property("projection_type", u.CameraProjectionMode.PERSPECTIVE)

    def shoot(self, name: str) -> str:
        for _ in range(CAPTURES_PER_SHOT):
            self.comp.capture_scene()
        OUT.mkdir(parents=True, exist_ok=True)
        target = OUT / f"{name}.png"
        target.unlink(missing_ok=True)
        self.u.RenderingLibrary.export_render_target(
            self.scene.world, self.rt, str(OUT), f"{name}.png"
        )
        if not target.is_file():
            alt = OUT / name
            if alt.is_file():
                alt.replace(target)
        return target.name


# --------------------------------------------------------------------------
# Scenes
# --------------------------------------------------------------------------


def build_room(scene: Scene) -> None:
    u = scene.u
    floor = scene.mid("M_Verse_Floor")
    wall = scene.mid("M_Verse_Surface", {"BaseTint": LIN["graphite"]}, {"EdgeWear": 0.2})
    concrete = scene.mid(
        "M_Verse_Surface",
        {"BaseTint": LIN["concrete"]},
        {"RoughnessMin": 0.7, "RoughnessMax": 0.95},
    )
    steel = scene.mid(
        "M_Verse_Surface", {"BaseTint": LIN["black_steel"]}, {"Metallic": 1.0, "RoughnessMin": 0.3}
    )
    scene.plane((4000, 4000), (0, 0, 0), floor)
    scene.box((40, 4000, 1200), (900, 0, 600), wall)
    scene.box((4000, 40, 1200), (0, 900, 600), concrete)
    scene.box((4000, 40, 1200), (0, -900, 600), wall)
    scene.box((40, 4000, 1200), (-900, 0, 600), steel)
    scene.box((120, 120, 100), (0, 0, 50), steel)  # pedestal
    fog = scene.spawn(u.ExponentialHeightFog, (0, 0, 0), group="fog")
    comp = fog.get_component_by_class(u.ExponentialHeightFogComponent)
    f = PROFILE["fog"]
    comp.set_editor_property("fog_density", f["density"])
    comp.set_editor_property(
        "fog_inscattering_luminance",
        u.LinearColor(f["luminance"], f["luminance"], f["luminance"], 1),
    )
    comp.set_editor_property("enable_volumetric_fog", f["volumetric"])
    comp.set_editor_property("volumetric_fog_albedo", u.Color(230, 230, 230, 255))
    w = PROFILE["work_light"]
    scene.spot(
        (-250, 320, 520),
        (0, 0, 115),
        w["kelvin"],
        w["candela"],
        w["cone_deg"],
        radius=w["source_radius_cm"],
    )
    fl = PROFILE["fill_light"]
    scene.spot(
        (350, -300, 260), (0, 0, 110), fl["kelvin"], fl["candela"], 50.0, shadows=False, radius=20.0
    )
    scene.spot((420, 300, 400), (0, 0, 115), 6500, 900.0, 18.0, radius=1.0)  # rim


def build_reference(scene: Scene) -> None:
    """A deck corner: crates, a catwalk rail, amber and red practical lamps."""
    steel = scene.mid(
        "M_Verse_Surface", {"BaseTint": LIN["black_steel"]}, {"Metallic": 1.0, "EdgeWear": 0.8}
    )
    gunmetal = scene.mid("M_Verse_Surface", {"BaseTint": LIN["gunmetal"]}, {"Metallic": 0.6})
    concrete = scene.mid(
        "M_Verse_Surface", {"BaseTint": LIN["raw_concrete"]}, {"RoughnessMax": 0.95}
    )
    amber = scene.mid("M_Verse_Emissive", {"EmissiveColor": LIN["amber"]}, {"EmissiveNits": 25.0})
    red = scene.mid("M_Verse_Emissive", {"EmissiveColor": LIN["red"]}, {"EmissiveNits": 20.0})
    white = scene.mid(
        "M_Verse_Emissive", {"EmissiveColor": LIN["work_white"]}, {"EmissiveNits": 60.0}
    )
    g = "ref"
    for i, (x, y) in enumerate(((300, 250), (300, 380), (430, 300), (180, -320))):
        scene.box(
            (120, 120, 120 + 40 * (i % 2)),
            (x, y, 60 + 20 * (i % 2)),
            steel if i % 2 else gunmetal,
            g,
        )
    scene.box((900, 30, 30), (300, -600, 280), steel, g)
    for x in (-100, 200, 500, 800):
        scene.box((20, 20, 280), (x, -600, 140), steel, g)
    scene.box((300, 300, 40), (650, -500, 20), concrete, g)
    scene.box((10, 30, 12), (880, 0, 260), amber, g)
    scene.box((10, 30, 12), (880, -420, 200), red, g)
    scene.box((60, 20, 8), (400, 0, 1150), white, g)
    scene.point((860, 0, 260), LIN["amber"], 8.0, g)
    scene.point((860, -420, 200), LIN["red"], 6.0, g)
    w = PROFILE["work_light"]
    scene.spot(
        (400, 0, 1140),
        (400, 0, 0),
        w["kelvin"],
        w["candela"] * 3,
        40.0,
        g,
        radius=w["source_radius_cm"],
    )


def build_vfx(scene: Scene) -> None:
    specs, _ = _specs()
    vfx = {v.asset: v.object_path for v in specs.VFX}
    g = "vfx"
    foe = scene.u.load_asset(
        "/Game/Verse/Materials/Instances/Weapons/MI_Weapon_Vfx_BoltFoe.MI_Weapon_Vfx_BoltFoe"
    )
    for i in range(3):
        scene.mesh(vfx["SM_Vfx_Bolt"], (-200 + 160 * i, 120 - 40 * i, 140 + 10 * i), (0, 8, 0), g)
        bolt = scene.mesh(
            vfx["SM_Vfx_Bolt"], (300 - 150 * i, -150 + 50 * i, 120 + 15 * i), (0, 180 + 10, 0), g
        )
        if foe is not None:
            bolt.static_mesh_component.set_material(0, foe)
    scene.mesh(vfx["SM_Vfx_MuzzleFlash"], (20, 0, 140), (0, 0, 0), g)
    scene.mesh(vfx["SM_Vfx_ImpactSparks"], (860, 0, 160), (0, 180, 0), g)
    scorch = scene.u.load_asset(
        "/Game/Verse/Materials/Instances/Weapons/MI_Weapon_Vfx_Scorch.MI_Weapon_Vfx_Scorch"
    )
    if scorch is not None:
        decal = scene.spawn(scene.u.DecalActor, (870, 0, 160), (0, 0, 0), g)
        decal.set_decal_material(scorch)
        decal.decal.set_editor_property("decal_size", scene.u.Vector(20, 25, 25))
    rifle = specs.GRAVELINE
    scene.mesh(rifle.object_path, (-55, 0, 105), (0, 0, 0), g)


def build_bolt_swarm(scene: Scene) -> dict[str, str]:
    """Bolts in flight for A14.5, in front of the cost camera; returns set -> group.

    `bolts_64` is 64 bolts (half own, half foe); `bolts_1024` adds 960 more,
    so a timing difference large enough to measure divides back to 64.
    """
    specs, _ = _specs()
    path = {v.asset: v.object_path for v in specs.VFX}["SM_Vfx_Bolt"]
    foe = scene.u.load_asset(
        "/Game/Verse/Materials/Instances/Weapons/MI_Weapon_Vfx_BoltFoe.MI_Weapon_Vfx_BoltFoe"
    )
    groups = {"bolts_64": "cost_64", "bolts_1024": "cost_960"}
    for i in range(COST_SETS["bolts_1024"]):
        group = "cost_64" if i < COST_SETS["bolts_64"] else "cost_960"
        col, row, layer = i % 16, (i // 16) % 8, i // 128
        loc = (3600 + 120 * layer, -900 + 120 * col, 300 + 110 * row)
        bolt = scene.mesh(path, loc, (0, 180 if i % 2 else 0, 0), group)
        if foe is not None and i % 2:
            bolt.static_mesh_component.set_material(0, foe)
    return groups


def measure_bolt_cost(u, scene: Scene, cap: Capture, groups: dict[str, str]) -> dict:
    """A14.5: frame cost of bolts in flight at 2560x1440, an upper bound on GPU time.

    Each sample is `capture_scene()` followed by a one-pixel readback, which
    flushes the render thread and waits for the GPU, so its wall time holds
    the full render of the frame. The configurations (no bolts, 64, 1024)
    alternate inside every round, so drift and other machine load hit all of
    them alike; the medians are compared. The difference includes the
    render-thread cost of the extra draws as well, so it bounds the GPU cost
    of the bolts from above.
    """

    def show(n: int) -> None:
        scene.show("cost_64", n >= COST_SETS["bolts_64"])
        scene.show("cost_960", n >= COST_SETS["bolts_1024"])

    def sample() -> float:
        cap.comp.capture_scene()
        u.RenderingLibrary.read_render_target_pixel(scene.world, cap.rt, 1, 1)
        start = time.perf_counter()
        for _ in range(COST_INNER):
            cap.comp.capture_scene()
            u.RenderingLibrary.read_render_target_pixel(scene.world, cap.rt, 1, 1)
        return (time.perf_counter() - start) * 1000.0 / COST_INNER

    configs = {"none": 0, **COST_SETS}
    times: dict[str, list[float]] = {k: [] for k in configs}
    for _ in range(COST_ROUNDS):
        for name, n in configs.items():
            show(n)
            times[name].append(sample())
    show(0)

    def median(values: list[float]) -> float:
        ordered = sorted(values)
        mid = len(ordered) // 2
        return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2

    med = {k: median(v) for k, v in times.items()}
    delta_64 = med["bolts_64"] - med["none"]
    delta_1024 = med["bolts_1024"] - med["none"]
    per_64_from_1024 = delta_1024 * 64.0 / COST_SETS["bolts_1024"]
    return {
        "resolution": [COST_W, COST_H],
        "rounds": COST_ROUNDS,
        "captures_per_sample": COST_INNER,
        "median_ms": {k: round(v, 4) for k, v in med.items()},
        "samples_ms": {k: [round(x, 4) for x in v] for k, v in times.items()},
        "delta_64_ms": round(delta_64, 4),
        "delta_1024_ms": round(delta_1024, 4),
        "per_64_from_1024_ms": round(per_64_from_1024, 4),
        "bound_ms": round(max(delta_64, per_64_from_1024, 0.0), 4),
        "limit_ms": 0.1,
        "method": "wall time of capture + readback, medians, includes render-thread cost",
    }


def build_chart(scene: Scene, agx) -> list[dict]:
    """24 unlit patches facing -X at x = 2000; returns their pixel centres."""
    patches = []
    size = 100.0
    cols, rows = 6, 4
    for i, value in enumerate(agx.chart_linear()):
        col, row = i % cols, i // cols
        y = (col - (cols - 1) / 2) * size * 1.1
        z = 1000 + ((rows - 1) / 2 - row) * size * 1.1
        mid = scene.mid("M_Verse_Emissive", {"EmissiveColor": value}, {"EmissiveNits": 1.0})
        scene.plane((size, size), (2000, y, z), mid, rot=(90, 0, 0), group="chart")
        patches.append({"index": i, "y": y, "z": z})
    return patches


PROBE_FOLDER = "/Game/Verse/Test/WP14/Probe"

#: Debug bodies for the chart probe; each replaces the grade's custom node.
PROBE_CODE = {
    "identity": "return Scene.rgb;",
    "red_after": "return float3(1.0, 0.0, 0.0);",
    "exposure": "return float3(Exposure, Exposure, Exposure);",
    "coord": (
        "float3 c = (Scene.rgb + Bloom.rgb * BloomScale) * Exposure;"
        "return saturate((log2(max(c, 1e-10) / 0.18) - (EV_MIN)) / (EV_RANGE));"
    ),
}


def probe_materials(u) -> dict:
    """Transient post materials (never saved) that expose what the grade sees.

    `identity` returns the scene input, `exposure` the eye-adaptation value,
    `coord` the LUT coordinate; `grade` is the real `M_Verse_PostTonemap` and
    `none` no blendable (the engine tonemapper).
    """
    from . import masters

    _, agx = _specs()
    out = {"grade": u.load_asset(POST), "none": None}
    tools = u.AssetToolsHelpers.get_asset_tools()
    for name, code in PROBE_CODE.items():
        code = code.replace("EV_MIN", repr(agx.EV_MIN)).replace(
            "EV_RANGE", repr(agx.EV_MAX - agx.EV_MIN)
        )
        asset = f"M_WP14_Probe_{name}"
        path = f"{PROBE_FOLDER}/{asset}"
        if u.EditorAssetLibrary.does_asset_exist(path):
            mat = u.EditorAssetLibrary.load_asset(path)
            u.MaterialEditingLibrary.delete_all_material_expressions(mat)
        else:
            mat = tools.create_asset(asset, PROBE_FOLDER, u.Material, u.MaterialFactoryNew())
        g = masters.Graph(u, mat)
        for param in masters.POST_TONEMAP.params:
            g.param(param)
        mat.set_editor_property("material_domain", u.MaterialDomain.MD_POST_PROCESS)
        location = u.BlendableLocation.BL_REPLACING_TONEMAPPER
        if name.endswith("_after"):
            location = u.BlendableLocation.BL_SCENE_COLOR_AFTER_TONEMAPPING
        mat.set_editor_property("blendable_location", location)
        ids = u.SceneTextureId
        scene_tex = u.MaterialExpressionSceneTexture
        g.node(scene_tex, "Scene", scene_texture_id=ids.PPI_POST_PROCESS_INPUT0)
        g.node(scene_tex, "Bloom", scene_texture_id=ids.PPI_POST_PROCESS_INPUT2)
        g.node(u.MaterialExpressionEyeAdaptation, "Exposure")
        g.custom(
            "Probe",
            code,
            {
                "Scene": ("Scene", "Color"),
                "Bloom": ("Bloom", "Color"),
                "Exposure": ("Exposure", ""),
                "BloomScale": ("BloomScale", ""),
            },
        )
        g.out("Probe", "", "MP_EMISSIVE_COLOR")
        u.MaterialEditingLibrary.recompile_material(mat)
        out[name] = mat
    return out


def _blendables(cap: Capture) -> list[str]:
    held = cap.comp.get_editor_property("post_process_settings")
    array = held.get_editor_property("weighted_blendables").get_editor_property("array")
    return [f"{b.get_editor_property('weight')}:{b.get_editor_property('object')}" for b in array]


def probe_chart(u, scene: Scene, cap: Capture, setup, mats: dict) -> dict:
    """One 8-bit chart frame per probe material (`chart_probe_<name>.png`).

    `volume` shoots the real grade through an unbound PostProcessVolume
    instead of the capture's own settings.
    """
    result = {"blendables": {}}
    for name, mat in mats.items():
        settings = _post_settings(u, bias=0.0, bloom=0.0)
        blend = [u.WeightedBlendable(1.0, mat)] if mat is not None else []
        settings.set_editor_property("weighted_blendables", u.WeightedBlendables(blend))
        setup(cap, settings)
        result["blendables"][name] = _blendables(cap)
        result[name] = cap.shoot(f"chart_probe_{name}")
    volume = scene.spawn(u.PostProcessVolume, (1500, 0, 1000), group="chart")
    volume.set_editor_property("unbound", True)
    volume.set_editor_property("priority", 100.0)
    volume.set_editor_property("blend_weight", 1.0)
    volume.set_editor_property("settings", _post_settings(u, bias=0.0, bloom=0.0))
    bare = _post_settings(u, bias=0.0, bloom=0.0)
    bare.set_editor_property("weighted_blendables", u.WeightedBlendables([]))
    setup(cap, bare)
    result["volume"] = cap.shoot("chart_probe_volume")
    scene.forget(volume)
    return result


def chart_pixels(patches: list[dict], ortho_width: float) -> list[tuple[int, int]]:
    """Patch centres in the chart frame (camera on -X looking +X, +Y right). Pure."""
    scale = CHART_W / ortho_width
    out = []
    for p in patches:
        px = CHART_W / 2 + p["y"] * scale
        py = CHART_H / 2 - (p["z"] - 1000) * scale
        out.append((int(round(px)), int(round(py))))
    return out


# --------------------------------------------------------------------------
# State machine on the editor tick
# --------------------------------------------------------------------------


class Runner:
    def __init__(self, u, result_path: str):
        self.u = u
        self.result_path = result_path
        self.report: dict = {"frames": [], "errors": [], "out_dir": str(OUT)}
        self.started = time.monotonic()
        self.stage = "setup"
        self.handle = None
        self.shots: list = []
        self.last_probe = b""
        self.done = False
        self.busy = False

    def log(self, message: str) -> None:
        line = f"[verse_lookdev] {message}"
        print(line)
        try:
            OUT.mkdir(parents=True, exist_ok=True)
            with (OUT / "lookdev.log").open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            pass

    def start(self):
        (OUT / "lookdev.log").unlink(missing_ok=True)
        self.log("start")
        # `-ExecutePythonScript` quits the editor on the tick after the script
        # returns unless the script asks to stay alive (EditorPythonExecuter);
        # `finish` quits it itself.
        self.u.EditorPythonScripting.set_keep_python_script_alive(True)
        self.handle = self.u.register_slate_post_tick_callback(self.tick)

    def finish(self):
        u = self.u
        self.done = True
        self.report["ok"] = not self.report["errors"] and bool(self.report["frames"])
        self.report["seconds"] = round(time.monotonic() - self.started, 1)
        self.log(f"finish ok={self.report['ok']} frames={len(self.report['frames'])}")
        text = json.dumps(self.report, indent=2, default=str) + "\n"
        targets = [OUT / "lookdev.json"]
        if self.result_path:
            targets.append(Path(self.result_path))
        for target in targets:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
                self.log(f"wrote {target}")
            except Exception as error:  # never quit without saying why
                self.log(f"could not write {target}: {type(error).__name__}: {error}")
        if os.environ.get("VERSE_PIPELINE_QUIT") == "1":
            self.log("quit")
            u.SystemLibrary.quit_editor()

    def tick(self, _dt):
        # Asset creation inside a stage can pump Slate, which ticks again.
        if self.done or self.busy:
            return
        self.busy = True
        try:
            self._tick()
        except Exception as error:  # report, never hang the editor
            import traceback

            self.report["errors"].append(f"{type(error).__name__}: {error}")
            self.report["traceback"] = traceback.format_exc()
            self.log(f"error in stage {self.stage}: {type(error).__name__}: {error}")
            self.finish()
        finally:
            self.busy = False

    def _tick(self):
        if self.stage == "setup":
            self.log("setup")
            self._setup()
            self.stage = "warmup"
            self.log(f"setup done, {len(self.shots)} shots")
            return
        elapsed = time.monotonic() - self.started
        if self.stage == "warmup":
            if elapsed < WARMUP_S:
                return
            self.stage = "stabilise"
            return
        if self.stage == "stabilise":
            name = self.probe.shoot("probe")
            data = (OUT / name).read_bytes()
            stable = data == self.last_probe
            self.last_probe = data
            if stable or elapsed > STABLE_MAX_S:
                self.report["stable_after_s"] = round(elapsed, 1)
                self.report["stable"] = stable
                (OUT / name).unlink(missing_ok=True)
                self.stage = "shoot"
            return
        if self.stage == "shoot":
            if not self.shots:
                self.finish()
                return
            fn = self.shots.pop(0)
            self.log(f"shot {getattr(fn, '__name__', '?')}, {len(self.shots)} left")
            fn()

    def _setup(self):
        u = self.u
        specs, agx = _specs()
        world = u.EditorLoadingAndSavingUtils.new_blank_map(False)
        if world is None:
            raise RuntimeError("could not create the transient lookdev level")
        scene = Scene(u)
        self.scene = scene
        build_room(scene)
        build_reference(scene)
        build_vfx(scene)
        patches = build_chart(scene, agx)
        cost_groups = build_bolt_swarm(scene)
        try:  # built before the warm-up so their shaders compile in time
            probe_mats = probe_materials(u)
        except Exception as error:  # the probe is diagnostics only
            probe_mats = {}
            self.report["chart_probe_error"] = f"{type(error).__name__}: {error}"
        cap = Capture(scene, WIDTH, HEIGHT)
        cost_cap = Capture(scene, COST_W, COST_H)
        chart_cap = Capture(scene, CHART_W, CHART_H)
        chart_cap_srgb = Capture(scene, CHART_W, CHART_H, srgb=True)
        self.probe = cap
        look = _post_settings(u, bias=PROFILE["exposure_bias"], bloom=PROFILE["bloom"])
        chart_settings = _post_settings(u, bias=0.0, bloom=0.0)
        ortho = 6 * 110.0 + 120.0
        self.report["chart"] = {
            "pixels": chart_pixels(patches, ortho),
            "linear": agx.chart_linear(),
            "frame": "chart_agx.png",
        }
        self.report["profile"] = PROFILE
        weapons = [s for s in specs.ARSENAL]
        state = {"placed": None}

        def only(groups):
            for name in ("ref", "vfx", "chart", "turn"):
                scene.show(name, name in groups)
            scene.show("fog", "chart" not in groups)
            scene.show("cost_64", False)
            scene.show("cost_960", False)

        def chart():
            only({"chart"})
            chart_cap.setup(
                (1000, 0, 1000), (2000, 0, 1000), 30.0, chart_settings, ortho_width=ortho
            )
            self.report["frames"].append(chart_cap.shoot("chart_agx"))
            chart_cap_srgb.setup(
                (1000, 0, 1000), (2000, 0, 1000), 30.0, chart_settings, ortho_width=ortho
            )
            self.report["frames"].append(chart_cap_srgb.shoot("chart_agx_srgb_target"))

            def place(capture, settings):
                capture.setup((1000, 0, 1000), (2000, 0, 1000), 30.0, settings, ortho_width=ortho)

            self.log("chart probe")
            try:
                self.report["chart_probe"] = probe_chart(u, scene, chart_cap, place, probe_mats)
                self.log(f"chart probe done: {sorted(self.report['chart_probe'])}")
            except Exception as error:  # the probe is diagnostics only
                self.report["chart_probe_error"] = f"{type(error).__name__}: {error}"
                self.log(f"chart probe failed: {self.report['chart_probe_error']}")

        self.shots.append(chart)

        for spec in weapons:
            for view, (yaw, dist_scale, height) in {
                "right": (90.0, 1.0, 0.0),
                "left": (-90.0, 1.0, 0.0),
                "three_quarter": (35.0, 1.1, 25.0),
            }.items():

                def shot(spec=spec, view=view, yaw=yaw, dist_scale=dist_scale, height=height):
                    only({"turn"})
                    if state["placed"] is not None:
                        scene.forget(state["placed"])
                    actor = scene.mesh(spec.object_path, (0, 0, 115), (0, 0, 0), "turn")
                    state["placed"] = actor
                    size = _extent(actor)
                    dist = max(size * 1.6, 60.0) * dist_scale
                    rad = math.radians(yaw)
                    loc = (dist * math.sin(rad) * 0.0 + dist * math.cos(rad) * 0.0, 0, 0)
                    loc = (-dist * math.sin(rad) * 0.35, dist * math.sin(rad), 115 + height)
                    if view == "three_quarter":
                        loc = (dist * 0.8, dist * 0.6, 115 + height + size * 0.3)
                    cap.setup(loc, _centre(actor), 40.0, look)
                    self.report["frames"].append(cap.shoot(f"turn_{spec.asset}_{view}"))

                self.shots.append(shot)

        for spec in (specs.GRAVELINE, specs.TALLOW, specs.HOOKBILL, specs.SKITTER, specs.LONGSIGHT):

            def fp(spec=spec):
                only({"turn"})
                if state["placed"] is not None:
                    scene.forget(state["placed"])
                eye = (-120.0, 0.0, 160.0)
                actor = scene.mesh(
                    spec.object_path,
                    (eye[0] + 28, eye[1] + 11, eye[2] - 14),
                    (2.0, -4.0, 0.0),
                    "turn",
                )
                state["placed"] = actor
                cap.setup(eye, (eye[0] + 100, eye[1], eye[2] - 6), 75.0, look)
                self.report["frames"].append(cap.shoot(f"fp_{spec.asset}"))

            self.shots.append(fp)

        for view, (loc, target) in {
            "corner": ((-500, 400, 220), (500, -150, 120)),
            "lamps": ((-200, -100, 170), (880, -200, 220)),
            "catwalk": ((100, 300, 160), (500, -600, 220)),
        }.items():

            def ref(view=view, loc=loc, target=target):
                only({"ref"})
                if state["placed"] is not None:
                    scene.forget(state["placed"])
                    state["placed"] = None
                cap.setup(loc, target, 70.0, look)
                self.report["frames"].append(cap.shoot(f"ref_{view}"))

            self.shots.append(ref)

        for view, (loc, target) in {
            "bolts": ((-420, 260, 180), (300, -40, 130)),
            "impact": ((450, 120, 170), (870, 0, 160)),
        }.items():

            def vfx(view=view, loc=loc, target=target):
                only({"vfx"})
                cap.setup(loc, target, 60.0, look)
                self.report["frames"].append(cap.shoot(f"vfx_{view}"))

            self.shots.append(vfx)

        def vfx_cost():
            only({"ref"})
            if state["placed"] is not None:
                scene.forget(state["placed"])
                state["placed"] = None
            cost_cap.setup((2200, 0, 700), (3800, 0, 700), 70.0, look)
            self.report["vfx_cost"] = measure_bolt_cost(u, scene, cost_cap, cost_groups)
            scene.show("cost_64", True)
            scene.show("cost_960", True)
            self.report["frames"].append(cost_cap.shoot("vfx_cost_1024_bolts"))
            scene.show("cost_64", False)
            scene.show("cost_960", False)

        self.shots.append(vfx_cost)


def _extent(actor) -> float:
    origin, extent = actor.get_actor_bounds(False)
    return 2.0 * max(extent.x, extent.y, extent.z)


def _centre(actor):
    origin, _extent = actor.get_actor_bounds(False)
    return (origin.x, origin.y, origin.z)


def run(prelude: dict | None = None) -> dict:
    import unreal

    runner = Runner(unreal, os.environ.get("VERSE_PIPELINE_RESULT", ""))
    if prelude:
        runner.report["prelude"] = prelude
        runner.report["errors"] += prelude.get("errors", [])
    runner.start()
    return {"deferred": True}
