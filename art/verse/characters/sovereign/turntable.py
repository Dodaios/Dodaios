"""Editor step: render `SK_Sovereign` from four sides, framed like the three.js reference.

Runs inside the Unreal editor with the D3D12 RHI offscreen (``-ExecutePythonScript``),
started by ``art/verse/characters/sovereign/build.py --turntable`` under the machine lock.
The camera matches ``art/verse/characters/sovereign/turntable_three.html``: 30 degrees
field of view, 4.2 m away, eye 1.15 m, aimed at 0.93 m, yaw 0 = the Sovereign's front.
Lighting is a neutral grey dome (sky light), a warm key from front right above and a cool
rim from behind left, the same directions as the reference.

    VERSE_SOV_TURNTABLE_OUT    folder for the PNGs (unreal_yaw<deg>.png) and turntable.json
    VERSE_SOV_TURNTABLE_ANIM   optional AnimSequence path to pose the body (default: rest)
    VERSE_SOV_QUIT             "1": quit the editor when done
"""

from __future__ import annotations

import json
import math
import os
import time
import traceback
from pathlib import Path

import unreal

MESH = os.environ.get(
    "VERSE_SOV_TURNTABLE_MESH", "/Game/Verse/Characters/Sovereign/SK_Sovereign.SK_Sovereign"
)
EMISSIVE = "/Game/Verse/Materials/Master/M_Verse_Emissive.M_Verse_Emissive"
SURFACE = "/Game/Verse/Materials/Master/M_Verse_Surface.M_Verse_Surface"
CHARACTER = "/Game/Verse/Materials/Master/M_Verse_Character.M_Verse_Character"
SPHERE = "/Engine/BasicShapes/Sphere.Sphere"
CYLINDER = "/Engine/BasicShapes/Cylinder.Cylinder"
YAWS = (0, 45, 90, 180)
WIDTH, HEIGHT = 900, 1100
FOV = 30.0
DIST, EYE, AIM = 420.0, 115.0, 93.0
CAPTURES = 24
WARMUP_S = 8.0

OUT = Path(os.environ.get("VERSE_SOV_TURNTABLE_OUT", "."))
REPORT: dict = {"frames": [], "errors": []}


def rotator(pitch: float, yaw: float, roll: float = 0.0):
    return unreal.Rotator(roll=roll, pitch=pitch, yaw=yaw)


def look(loc, target):
    dx, dy, dz = (t - s for s, t in zip(loc, target, strict=True))
    return rotator(
        math.degrees(math.atan2(dz, math.hypot(dx, dy))), math.degrees(math.atan2(dy, dx))
    )


class Turntable:
    def __init__(self):
        self.eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        self.started = time.monotonic()
        self.stage = "setup"
        self.index = 0
        self.busy = False
        self.done = False
        self.handle = None

    # ------------------------------------------------------------------ scene
    def spawn(self, cls, loc=(0, 0, 0), rot=(0, 0, 0)):
        return self.eas.spawn_actor_from_class(cls, unreal.Vector(*loc), rotator(*rot))

    def mid(self, master, vectors=None, scalars=None):
        parent = unreal.load_asset(master)
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        m = unreal.MaterialLibrary.create_dynamic_material_instance(world, parent)
        for k, v in (vectors or {}).items():
            m.set_vector_parameter_value(k, unreal.LinearColor(*v, 1.0))
        for k, v in (scalars or {}).items():
            m.set_scalar_parameter_value(k, float(v))
        return m

    def shape(self, mesh, loc, scale, material, shadows=True):
        actor = self.spawn(unreal.StaticMeshActor, loc)
        comp = actor.static_mesh_component
        comp.set_mobility(unreal.ComponentMobility.MOVABLE)
        comp.set_static_mesh(unreal.load_asset(mesh))
        comp.set_material(0, material)
        comp.set_cast_shadow(shadows)
        # backdrop only: a closed dome in the distance fields would occlude the sky light
        comp.set_editor_property("affect_distance_field_lighting", False)
        actor.set_actor_scale3d(unreal.Vector(*scale))
        return actor

    def setup(self):
        unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).new_level(
            "/Temp/SovereignTurntable"
        )
        self.world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        # full-resolution atlases: a fresh editor streams textures in over many frames, and
        # a few captures would show their low mips as blocks
        unreal.SystemLibrary.execute_console_command(self.world, "r.TextureStreaming 0")
        for cvar in ("r.DynamicGlobalIlluminationMethod 0", "r.ReflectionMethod 0"):
            unreal.SystemLibrary.execute_console_command(self.world, cvar)
        asset = unreal.load_asset(MESH)
        if isinstance(asset, unreal.StaticMesh):
            # control renders of the same FBX without skinning
            body = self.spawn(unreal.StaticMeshActor)
            comp = body.static_mesh_component
            comp.set_mobility(unreal.ComponentMobility.MOVABLE)
            comp.set_static_mesh(asset)
        else:
            body = self.spawn(unreal.SkeletalMeshActor)
            comp = body.skeletal_mesh_component
            comp.set_skeletal_mesh_asset(asset)
        if os.environ.get("VERSE_SOV_TURNTABLE_PLAIN") == "1":
            # control render: one plain grey material on every slot (no atlas, no normal map)
            plain = self.mid(CHARACTER, {"BaseTint": (0.5, 0.5, 0.5)}, {"Roughness": 0.6})
            flat = unreal.load_asset("/Engine/EngineMaterials/FlatNormal.FlatNormal")
            white = unreal.load_asset(
                "/Engine/EngineResources/WhiteSquareTexture.WhiteSquareTexture"
            )
            plain.set_texture_parameter_value("NormalMap", flat)
            plain.set_texture_parameter_value("BaseColorMap", white)
            plain.set_texture_parameter_value("ORMMap", white)
            for index in range(comp.get_num_materials()):
                comp.set_material(index, plain)
        anim = os.environ.get("VERSE_SOV_TURNTABLE_ANIM", "")
        if anim and not isinstance(asset, unreal.StaticMesh):
            comp.set_animation_mode(unreal.AnimationMode.ANIMATION_SINGLE_NODE)
            comp.set_animation(unreal.load_asset(anim))
        # the room: a neutral grey dome lights the scene through the sky light
        dome = self.mid(EMISSIVE, {"EmissiveColor": (0.35, 0.35, 0.35)}, {"EmissiveNits": 1.0})
        self.shape(SPHERE, (0, 0, 0), (-60.0, -60.0, -60.0), dome, shadows=False)
        floor = self.mid(
            SURFACE,
            {"BaseTint": (0.045, 0.045, 0.045)},
            {"RoughnessMin": 0.85, "RoughnessMax": 0.95},
        )
        self.shape(CYLINDER, (0, 0, -1.0), (2.8, 2.8, 0.02), floor)
        # ambient and reflections from a fixed studio-like cubemap (the reference's
        # RoomEnvironment); a captured scene lit nothing in a headless editor
        sky = self.spawn(unreal.SkyLight, (0, 0, 300))
        sc = sky.light_component
        sc.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)
        sc.set_editor_property("real_time_capture", False)
        sc.set_editor_property("source_type", unreal.SkyLightSourceType.SLS_SPECIFIED_CUBEMAP)
        sc.set_editor_property(
            "cubemap", unreal.load_asset("/Engine/MapTemplates/Sky/DaylightAmbientCubemap")
        )
        sc.set_intensity(1.0)
        self.sky = sc
        # key and rim from the reference's directions (three.js -> Unreal: +X the figure's left
        # = +X, +Y up = +Z, +Z toward the front camera = +Y; the mesh faces +Y)
        key = self.spawn(unreal.DirectionalLight, (0, 0, 300), self.direction((2.0, 3.0, 3.5)))
        key.light_component.set_mobility(unreal.ComponentMobility.MOVABLE)
        key.light_component.set_intensity(4.0)
        # like the reference (three.js lights cast no shadows), and a scene capture rasters
        # directional shadows coarsely (stair-stepped blocks)
        key.light_component.set_cast_shadows(False)
        key.light_component.set_light_color(unreal.LinearColor(1.0, 0.92, 0.82, 1.0))
        rim = self.spawn(unreal.DirectionalLight, (0, 0, 300), self.direction((-2.5, -3.0, 2.5)))
        rim.light_component.set_mobility(unreal.ComponentMobility.MOVABLE)
        rim.light_component.set_intensity(2.5)
        rim.light_component.set_cast_shadows(False)
        # studio fill from four sides and below, shadowless: the soft ambient of the reference's
        # RoomEnvironment (sky light ambient does not reach a headless capture)
        fill = float(os.environ.get("VERSE_SOV_TURNTABLE_FILL", "0.9"))
        for towards in (
            (4.0, 0.0, 1.0),
            (-4.0, 0.0, 1.0),
            (0.0, 4.0, 1.0),
            (0.0, -4.0, 1.0),
            (0.0, 0.0, -1.0),
        ):
            light = self.spawn(unreal.DirectionalLight, (0, 0, 300), self.direction(towards))
            lc = light.light_component
            lc.set_mobility(unreal.ComponentMobility.MOVABLE)
            lc.set_intensity(fill)
            lc.set_cast_shadows(False)
            lc.set_editor_property("forward_shading_priority", 0)
        rim.light_component.set_light_color(unreal.LinearColor(0.85, 0.9, 1.0, 1.0))
        rim.light_component.set_editor_property("forward_shading_priority", 0)
        self.rt = unreal.RenderingLibrary.create_render_target2d(
            self.world,
            WIDTH,
            HEIGHT,
            unreal.TextureRenderTargetFormat.RTF_RGBA8_SRGB,
            unreal.LinearColor(0, 0, 0, 1),
            False,
        )
        cap = self.spawn(unreal.SceneCapture2D)
        c = cap.capture_component2d
        c.set_editor_property("texture_target", self.rt)
        # VERSE_SOV_TURNTABLE_SOURCE=basecolor shows the albedo alone (material checks)
        source = os.environ.get("VERSE_SOV_TURNTABLE_SOURCE", "")
        c.set_editor_property(
            "capture_source",
            {
                "basecolor": unreal.SceneCaptureSource.SCS_BASE_COLOR,
                "normal": unreal.SceneCaptureSource.SCS_NORMAL,
            }.get(source, unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR),
        )
        c.set_editor_property("capture_every_frame", False)
        c.set_editor_property("capture_on_movement", False)
        c.set_editor_property("always_persist_rendering_state", True)
        c.set_editor_property("fov_angle", FOV)
        near = float(os.environ.get("VERSE_SOV_TURNTABLE_NEAR", "0"))
        if near > 0:
            c.set_editor_property("override_custom_near_clipping_plane", True)
            c.set_editor_property("custom_near_clipping_plane", near)
        if os.environ.get("VERSE_SOV_TURNTABLE_WIRE") == "1":
            flags = [unreal.EngineShowFlagsSetting(show_flag_name="Wireframe", enabled=True)]
            c.set_editor_property("show_flag_settings", flags)
        post = unreal.PostProcessSettings()
        post.set_editor_property("override_auto_exposure_method", True)
        post.set_editor_property("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL)
        post.set_editor_property("override_auto_exposure_bias", True)
        post.set_editor_property(
            "auto_exposure_bias", float(os.environ.get("VERSE_SOV_TURNTABLE_EV", "1.0"))
        )
        post.set_editor_property("override_auto_exposure_apply_physical_camera_exposure", True)
        post.set_editor_property("auto_exposure_apply_physical_camera_exposure", False)
        # no Lumen in the capture: a few captures do not converge its screen probes (blocky
        # light, missing reflections); the sky light gives ambient and reflections instead
        post.set_editor_property("override_dynamic_global_illumination_method", True)
        post.set_editor_property(
            "dynamic_global_illumination_method", unreal.DynamicGlobalIlluminationMethod.NONE
        )
        post.set_editor_property("override_reflection_method", True)
        post.set_editor_property("reflection_method", unreal.ReflectionMethod.NONE)
        # screen-space effects at reduced resolution do not settle over a few captures
        post.set_editor_property("override_ambient_occlusion_intensity", True)
        post.set_editor_property("ambient_occlusion_intensity", 0.0)
        # the ambient: a post-process ambient cubemap (the sky light lights nothing in a
        # headless capture), the studio fill of the reference's RoomEnvironment
        post.set_editor_property("override_ambient_cubemap_intensity", True)
        post.set_editor_property(
            "ambient_cubemap_intensity", float(os.environ.get("VERSE_SOV_TURNTABLE_AMBIENT", "1.0"))
        )
        post.set_editor_property(
            "ambient_cubemap", unreal.load_asset("/Engine/MapTemplates/Sky/DaylightAmbientCubemap")
        )
        post.set_editor_property("override_bloom_intensity", True)
        post.set_editor_property("bloom_intensity", 0.3)
        c.set_editor_property("post_process_settings", post)
        c.set_editor_property("post_process_blend_weight", 1.0)
        self.cap, self.comp = cap, c
        REPORT["mesh_found"] = unreal.load_asset(MESH) is not None

    @staticmethod
    def direction(towards_light):
        """(pitch, yaw) of a directional light shining from `towards_light` to the origin."""
        x, y, z = towards_light
        return (-math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(-y, -x)))

    def place(self, yaw_deg):
        a = math.radians(yaw_deg)
        # yaw 0 = in front of the Sovereign: the mesh faces +Y (coordinates.md 3.3); positive
        # yaw walks round to its left like the three.js camera
        loc = (DIST * math.sin(a), DIST * math.cos(a), EYE)
        self.cap.set_actor_location_and_rotation(
            unreal.Vector(*loc), look(loc, (0.0, 0.0, AIM)), False, False
        )

    def shoot(self, yaw_deg):
        for _ in range(CAPTURES):
            self.comp.capture_scene()
        OUT.mkdir(parents=True, exist_ok=True)
        name = f"unreal_yaw{yaw_deg}.png"
        (OUT / name).unlink(missing_ok=True)
        unreal.RenderingLibrary.export_render_target(self.world, self.rt, str(OUT), name)
        REPORT["frames"].append(name)

    # ------------------------------------------------------------------ ticking
    def start(self):
        unreal.EditorPythonScripting.set_keep_python_script_alive(True)
        self.handle = unreal.register_slate_post_tick_callback(self.tick)

    def tick(self, _dt):
        if self.done or self.busy:
            return
        self.busy = True
        try:
            if self.stage == "setup":
                self.setup()
                self.stage = "warmup"
            elif self.stage == "warmup":
                if not getattr(self, "recaptured", False) and time.monotonic() - self.started > 2.0:
                    self.sky.recapture_sky()
                    self.recaptured = True
                if time.monotonic() - self.started > WARMUP_S:
                    self.stage = "shoot"
                    self.place(YAWS[0])
            elif self.stage == "shoot":
                self.shoot(YAWS[self.index])
                self.index += 1
                if self.index >= len(YAWS):
                    self.finish()
                else:
                    self.place(YAWS[self.index])
        except Exception as error:  # report, never hang the editor
            REPORT["errors"].append(f"{type(error).__name__}: {error}")
            REPORT["traceback"] = traceback.format_exc()
            self.finish()
        finally:
            self.busy = False

    def finish(self):
        self.done = True
        if self.handle is not None:
            unreal.unregister_slate_post_tick_callback(self.handle)
        REPORT["ok"] = not REPORT["errors"] and len(REPORT["frames"]) == len(YAWS)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "turntable.json").write_text(json.dumps(REPORT, indent=2) + "\n", encoding="utf-8")
        if os.environ.get("VERSE_SOV_QUIT") == "1":
            unreal.SystemLibrary.quit_editor()


Turntable().start()
