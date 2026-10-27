/**
 * The duel in the eye-level scene: runs the match once per rendered frame
 * (before the eye view renders), hands the shoulder camera to the renderer
 * (`runtime.cameraOverride`), and draws both duellists, their blasters and
 * shields, the bolts and every effect the frame's events call for (muzzle
 * flashes, impact sparks and scorches, hit sparks, block ripples, parry
 * bursts, overheat steam).
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
import { Color, Group, Vector3 } from "three";
import type { Deck } from "../content/deck";
import type { StageRuntime } from "../runtime";
import { COMMANDER_SKIN, disposeInstance, type CharacterLibrary } from "../actors/characters";
import { applyLook, type Look } from "../actors/look";
import { hash32 } from "../life/crew";
import { CAMERA_RIGS } from "../combat/camera";
import type { CombatEvent } from "../combat/types";
import { BOLT_COLOURS } from "./blaster";
import type { DuelController } from "./duelController";
import { BoltPool, Flashes, radialTexture, Scorches, Sparks, Steam } from "./effects";
import { DuelFigure, type FigureLook } from "./figure";
import { ShieldMesh } from "./shield";
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
const WHITE = new Color(1, 1, 1);
const SPARK_HOT = new Color(1, 0.62, 0.25);
const SHIELD_SPARK = new Color(0.45, 0.8, 1);
const HIT_SPARK = new Color(1, 0.35, 0.15);

export function DuelLayer({ runtime, controller, deck, library, commanderId, commanderLook }: Props) {
  const scene = useThree((s) => s.scene);
  const fx = useMemo(() => {
    const group = new Group();
    group.name = "Duel";
    const bolts = new BoltPool();
    const sparks = new Sparks();
    const flashes = new Flashes();
    const scorches = new Scorches();
    const steam = new Steam();
    const shields = [new ShieldMesh(OWN_ACCENT), new ShieldMesh(OPPONENT_LOOK.accent)];
    group.add(bolts.group, sparks.points, flashes.group, scorches.group, steam.points, ...shields.map((s) => s.mesh));
    return { group, bolts, sparks, flashes, scorches, steam, shields };
  }, []);
  const shadow = useMemo(() => radialTexture([[0, "rgba(255,255,255,0.9)"], [0.35, "rgba(255,255,255,0.55)"], [1, "rgba(255,255,255,0)"]]), []);

  useEffect(() => {
    scene.add(fx.group);
    return () => {
      scene.remove(fx.group);
      fx.bolts.dispose();
      fx.sparks.dispose();
      fx.flashes.dispose();
      fx.scorches.dispose();
      fx.steam.dispose();
      for (const s of fx.shields) s.dispose();
      shadow.dispose();
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
    if (controller.phase === "off") runtime.cameraOverride = null;
    if (controller.phase === "running" && !controller.view) {
      fx.bolts.clear(); fx.sparks.clear(); fx.flashes.clear(); fx.scorches.clear(); fx.steam.clear();
    }
  }), [controller, runtime, fx]);
  useEffect(() => () => { runtime.cameraOverride = null; }, [runtime]);

  const scratch = useMemo(() => ({ v: new Vector3(), time: 0, steamAcc: [0, 0] }), []);
  const override = useMemo(() => ({ position: { x: 0, y: 0, z: 0 }, target: { x: 0, y: 0, z: 0 }, fovDeg: CAMERA_RIGS.hip.fovDeg }), []);

  useFrame((_, dt) => {
    if (!controller.active) {
      fx.group.visible = false;
      return;
    }
    fx.group.visible = true;
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

    const step = controller.phase === "paused" ? 0 : Math.min(dt, 0.1);
    scratch.time += step;
    const mySlot = view.slot;
    // Through the eyes the person's own body is hidden; the viewmodel draws their arms and blaster.
    const ownHidden = controller.camera.firstShare > HIDE_BODY_FIRST_SHARE;
    if (figures.current.own) figures.current.own.group.visible = !ownHidden;
    const bySlot = (slot: number) => (slot === mySlot ? figures.current.own : figures.current.foe);
    for (const p of view.players) {
      const f = bySlot(p.slot);
      f?.update(step, p, floorY, deck, scratch.time);
      fx.shields[p.slot === mySlot ? 0 : 1].update(step, p, floorY);
      // A venting blaster steams.
      const k = p.slot === mySlot ? 0 : 1;
      if (f && p.alive && (p.venting || p.heat > 0.85) && !(k === 0 && ownHidden)) {
        scratch.steamAcc[k] += step * (p.overheated ? 40 : p.venting ? 26 : 8);
        const n = Math.floor(scratch.steamAcc[k]);
        if (n > 0) { scratch.steamAcc[k] -= n; f.muzzle(scratch.v); fx.steam.emit(scratch.v.x, scratch.v.y - 0.02, scratch.v.z, n); }
      }
    }
    fx.bolts.update(view.bolts, mySlot, floorY);

    const events = controller.visualEvents;
    for (const e of events) play(e);
    events.length = 0;

    fx.sparks.update(step, floorY);
    fx.flashes.update(step);
    fx.scorches.update(step);
    fx.steam.update(step);

    function play(e: CombatEvent): void {
      const y = (v: number) => v + floorY;
      switch (e.type) {
        case "shot": {
          const own = e.player === mySlot;
          if (own && ownHidden) break;
          const colour = own ? BOLT_COLOURS.own : BOLT_COLOURS.foe;
          const f = bySlot(e.player);
          const at = f ? f.muzzle(scratch.v) : scratch.v.set(e.x, y(e.y), e.z);
          fx.flashes.spawn(at.x, at.y, at.z, colour, 9, 0.12, 0.42, 0.07, true);
          fx.flashes.spawn(at.x, at.y, at.z, WHITE, 6, 0.05, 0.14, 0.05);
          break;
        }
        case "impact": {
          const ix = e.x, iy = y(e.y), iz = e.z;
          fx.sparks.burst(ix, iy, iz, e.nx, e.ny, e.nz, 14, SPARK_HOT, 4.5, 0.8, 7);
          fx.flashes.spawn(ix + e.nx * 0.05, iy + e.ny * 0.05, iz + e.nz * 0.05, SPARK_HOT, 7, 0.2, 0.6, 0.12);
          fx.scorches.add(ix, iy, iz, e.nx, e.ny, e.nz);
          break;
        }
        case "hit": {
          const hx = e.x, hy = y(e.y), hz = e.z;
          const dx = hx - e.fromX, dz = hz - e.fromZ;
          const l = Math.hypot(dx, dz) || 1;
          fx.sparks.burst(hx, hy, hz, -dx / l, 0.2, -dz / l, e.headshot ? 26 : 18, HIT_SPARK, 3.5, 1.0, 8);
          fx.flashes.spawn(hx, hy, hz, e.headshot ? WHITE : HIT_SPARK, e.headshot ? 9 : 6, 0.2, 0.55, 0.12);
          break;
        }
        case "block": case "deflect": {
          const s = fx.shields[e.player === mySlot ? 0 : 1];
          s.block(e.x, y(e.y), e.z);
          fx.sparks.burst(e.x, y(e.y), e.z, 0, 0.3, 0, e.type === "deflect" ? 18 : 10, SHIELD_SPARK, 3.2, 1.2, 6);
          fx.flashes.spawn(e.x, y(e.y), e.z, SHIELD_SPARK, 6, 0.18, 0.5, 0.1);
          break;
        }
        case "parry": {
          const s = fx.shields[e.player === mySlot ? 0 : 1];
          s.parry(e.x, y(e.y), e.z);
          fx.flashes.spawn(e.x, y(e.y), e.z, BOLT_COLOURS.parry, 14, 0.3, 1.4, 0.22, true);
          fx.flashes.spawn(e.x, y(e.y), e.z, WHITE, 8, 0.1, 0.4, 0.08);
          fx.sparks.burst(e.x, y(e.y), e.z, 0, 0.4, 0, 30, BOLT_COLOURS.parry, 5, 1.3, 9);
          break;
        }
        case "shield_break":
          fx.shields[e.player === mySlot ? 0 : 1].shatter();
          break;
        case "overheat": {
          if (e.player === mySlot && ownHidden) break;
          const f = bySlot(e.player);
          if (f) { f.muzzle(scratch.v); fx.steam.emit(scratch.v.x, scratch.v.y, scratch.v.z, 30); fx.flashes.spawn(scratch.v.x, scratch.v.y, scratch.v.z, HIT_SPARK, 5, 0.1, 0.35, 0.2); }
          break;
        }
        default:
          break;
      }
    }
  }, 0);

  return null;
}
