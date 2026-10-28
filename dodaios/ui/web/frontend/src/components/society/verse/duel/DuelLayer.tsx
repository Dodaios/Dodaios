/**
 * The duel in the eye-level scene: runs the match once per rendered frame
 * (before the eye view renders), hands the shoulder camera to the renderer
 * (`runtime.cameraOverride`), and draws both duellists, their blasters and
 * shields, the bolts and every effect the frame's events call for
 * (`DuelFx`: muzzle flashes and light pops, impacts, hit flashes, shield
 * ripples, parry bursts, shield shards, steam and heat haze), and asks the
 * eye view for the duel's stronger bloom (`DUEL_BLOOM`).
 *
 * In first person the person's own body is not drawn (the viewmodel's arms
 * and blaster stand in for it, `viewmodel/`), and their muzzle flashes and
 * vent steam come from the viewmodel's blaster instead.
 *
 * Mounted inside the stage's Canvas while a duel is on; everything it adds
 * to the scene goes again when it unmounts.
 */
import { useEffect, useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { Color, Group } from "three";
import type { Deck } from "../content/deck";
import type { StageRuntime } from "../runtime";
import { COMMANDER_SKIN, disposeInstance, type CharacterLibrary } from "../actors/characters";
import { applyLook, type Look } from "../actors/look";
import { hash32 } from "../life/crew";
import { CAMERA_RIGS } from "../combat/camera";
import type { DuelController } from "./duelController";
import { DUEL_BLOOM, DuelFx, type FxFrame } from "./duelFx";
import { radialTexture } from "./effects";
import { DuelFigure, type FigureLook } from "./figure";
import { HIDE_BODY_FIRST_SHARE } from "../viewmodel/motion";

interface Props {
  runtime: StageRuntime;
  controller: DuelController;
  deck: Deck;
  library: CharacterLibrary | null;
  commanderId: string;
  commanderLook: Look;
}

/** The bot: the trooper body in gunmetal armour with red accents and a red visor. */
export const OPPONENT_LOOK: FigureLook = {
  tint: { M_Armor: "#3a3f46", M_Accent: "#a3221a", M_Undersuit: "#141619" },
  glow: { M_Visor: "#ff2a1a" },
  accent: new Color(1, 0.16, 0.08),
};

/** The person's blaster cells (amber). */
export const OWN_ACCENT = new Color(1, 0.6, 0.15);

export function DuelLayer({ runtime, controller, deck, library, commanderId, commanderLook }: Props) {
  const scene = useThree((s) => s.scene);
  const gl = useThree((s) => s.gl);
  const fx = useMemo(() => {
    const group = new Group();
    group.name = "Duel";
    const effects = new DuelFx(OWN_ACCENT, OPPONENT_LOOK.accent);
    group.add(effects.group);
    return { group, effects };
  }, []);
  const shadow = useMemo(() => radialTexture([[0, "rgba(255,255,255,0.9)"], [0.35, "rgba(255,255,255,0.55)"], [1, "rgba(255,255,255,0)"]]), []);

  useEffect(() => {
    scene.add(fx.group);
    return () => {
      scene.remove(fx.group);
      fx.effects.dispose();
      shadow.dispose();
      runtime.bloomOverride = null;
    };
  }, [scene, fx, shadow]);

  // Both bodies: the commander's own (their look) and the trooper.
  const figures = useRef<{ own: DuelFigure | null; foe: DuelFigure | null }>({ own: null, foe: null });
  useEffect(() => {
    if (!library) return;
    let alive = true;
    const own = library.model("officer", COMMANDER_SKIN, hash32(commanderId));
    const foe = library.model("trooper") ?? library.model("technician");
    const load = async () => {
      const [a, b] = await Promise.all([own ? library.instantiate(own) : null, foe ? library.instantiate(foe) : null]);
      if (!alive) { for (const i of [a, b]) if (i) disposeInstance(i); return; }
      if (a) {
        applyLook(a, library.contract, commanderLook);
        const f = new DuelFigure(a, { accent: OWN_ACCENT }, shadow);
        figures.current.own = f;
        fx.group.add(f.group);
      }
      if (b) {
        const f = new DuelFigure(b, OPPONENT_LOOK, shadow);
        figures.current.foe = f;
        fx.group.add(f.group);
      }
    };
    load().catch((error: unknown) => console.warn("Duel bodies failed to load", error));
    return () => {
      alive = false;
      for (const key of ["own", "foe"] as const) {
        const f = figures.current[key];
        if (f) { fx.group.remove(f.group); f.dispose(); }
        figures.current[key] = null;
      }
    };
  }, [library, commanderId, commanderLook, fx, shadow]);

  // Leaving the duel gives the camera back; the next match starts with a clean room.
  useEffect(() => controller.subscribe(() => {
    if (controller.phase === "off") { runtime.cameraOverride = null; runtime.bloomOverride = null; }
    if (controller.phase === "running" && !controller.view) fx.effects.clear();
  }), [controller, runtime, fx]);
  useEffect(() => () => { runtime.cameraOverride = null; }, [runtime]);

  const scratch = useMemo(() => ({ time: 0 }), []);
  const override = useMemo(() => ({ position: { x: 0, y: 0, z: 0 }, target: { x: 0, y: 0, z: 0 }, fovDeg: CAMERA_RIGS.hip.fovDeg }), []);
  const frameInfo = useMemo<FxFrame>(() => ({
    view: null as unknown as FxFrame["view"],
    floorY: 0,
    ownHidden: false,
    cam: { x: 0, y: 0, z: 0 },
    camDir: { x: 0, y: 0, z: 1 },
    muzzle: () => null,
  }), []);

  useFrame((_, dt) => {
    if (!controller.active) {
      fx.group.visible = false;
      return;
    }
    fx.group.visible = true;
    runtime.bloomOverride = DUEL_BLOOM;
    const floorY = controller.floorY;
    const eyeCamera = runtime.eye?.camera;
    if (eyeCamera) controller.camera.aspect = eyeCamera.aspect;
    controller.frame(Math.min(dt, 0.25) * 1000, runtime.eye?.test ?? null);
    const view = controller.view;
    if (!view) return;
    const pose = controller.pose;
    override.position.x = pose.position.x; override.position.y = pose.position.y; override.position.z = pose.position.z;
    override.target.x = pose.target.x; override.target.y = pose.target.y; override.target.z = pose.target.z;
    override.fovDeg = pose.fovDeg;
    runtime.cameraOverride = override;

    // Effects slow down with a knockout's slow motion.
    const step = controller.phase === "paused" ? 0 : Math.min(dt, 0.1) * controller.timeScale;
    scratch.time += step;
    const mySlot = view.slot;
    // Through the eyes the person's own body is hidden; the viewmodel draws their arms and blaster.
    const ownHidden = controller.camera.firstShare > HIDE_BODY_FIRST_SHARE;
    if (figures.current.own) figures.current.own.group.visible = !ownHidden;
    const bySlot = (slot: number) => (slot === mySlot ? figures.current.own : figures.current.foe);
    for (const p of view.players) bySlot(p.slot)?.update(step, p, floorY, deck, scratch.time);

    const f = frameInfo;
    f.view = view;
    f.floorY = floorY;
    f.ownHidden = ownHidden;
    f.cam = pose.position;
    f.camDir = pose.dir;
    f.muzzle = (slot, out) => bySlot(slot)?.muzzle(out) ?? null;
    fx.effects.setViewportHeight(gl.domElement.height || 1080);
    fx.effects.frame(step, f);
    const events = controller.visualEvents;
    for (const e of events) fx.effects.play(e, f);
    events.length = 0;
    fx.effects.settle(step, f);
  }, 0);

  return null;
}
