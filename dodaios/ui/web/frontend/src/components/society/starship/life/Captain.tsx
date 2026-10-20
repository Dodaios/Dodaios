/**
 * The captain: the person's own figure. WASD or the arrows walk relative to
 * the camera (Shift runs), a click on the floor walks there along a route
 * drawn as a line of lights, E uses the station the captain stands at.
 * The captain never comes to rest inside anything solid.
 */
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import { BufferGeometry, Color, Float32BufferAttribute, Points, PointsMaterial } from "three";
import { CrewFigure } from "../crew/figure";
import { findPath, isFree, nearestFree, type NavGrid } from "../nav/shipNav";
import type { DeckPlan, Vec2 } from "../plan/types";
import { orbit } from "../render/CameraRig";
import { captain, useShip, type CaptainLook } from "../shipStore";
import { stepAlong, turnTowards, wrapAngle } from "./motion";

export const WALK = 2.0;
export const RUN = 4.2;

/** Text fields keep their keys. */
export function typesText(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && (target.isContentEditable || target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT");
}

const KEYS = new Set(["KeyW", "KeyA", "KeyS", "KeyD", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "ShiftLeft", "ShiftRight"]);


export function CaptainFigure(props: {
  plan: DeckPlan;
  grid: NavGrid;
  /** Colours from the quartermaster, the cut from the level system. */
  look: CaptainLook & { cut: string | null };
  pips: number;
  awake: boolean;
  reduced: boolean;
  /** Host element that owns the walking keys (focus inside it). */
  keyHost: React.RefObject<HTMLElement | null>;
}) {
  const { plan, grid, look, pips, awake } = props;
  const figure = useMemo(() => new CrewFigure({ kind: "captain", captain: { ...look, pips } }), [look, pips]);
  useEffect(() => () => figure.dispose(), [figure]);
  const keys = useRef(new Set<string>());
  const t = useRef(0);
  const body = useRef({ x: captain.x, z: captain.z, yaw: captain.yaw, path: [] as Vec2[], speed: 0, phase: 0 });
  const arrivals = useShip((s) => s.arrivals);
  const walkTo = useShip((s) => s.walkTo);

  // Arriving on a deck: out of the turbolift.
  useEffect(() => {
    const at = nearestFree(grid, plan.lift) ?? plan.lift;
    Object.assign(body.current, { x: at.x, z: at.z, yaw: plan.lift.yaw, path: [], speed: 0 });
    Object.assign(captain, { x: at.x, z: at.z, yaw: plan.lift.yaw, path: [], moving: false, seated: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [arrivals, plan.deck]);
  // A rebuilt plan may have put something where the captain stands.
  useEffect(() => {
    if (!isFree(grid, body.current)) {
      const at = nearestFree(grid, body.current) ?? plan.lift;
      body.current.x = at.x; body.current.z = at.z;
    }
  }, [grid, plan]);

  const placeAt = useShip((s) => s.placeAt);
  const usedPlace = useRef(0);
  useEffect(() => {
    if (!placeAt || placeAt.seq === usedPlace.current) return;
    usedPlace.current = placeAt.seq;
    const at = nearestFree(grid, placeAt.at) ?? placeAt.at;
    Object.assign(body.current, { x: at.x, z: at.z, path: [], speed: 0 });
    captain.seated = null;
  }, [placeAt, grid]);

  const usedWalk = useRef(0);
  useEffect(() => {
    if (!walkTo || walkTo.seq === usedWalk.current) return;
    usedWalk.current = walkTo.seq;
    const route = findPath(grid, body.current, walkTo.at);
    if (route) { body.current.path = route; captain.seated = null; }
  }, [walkTo, grid]);

  useEffect(() => {
    if (!awake) return;
    const owns = (e: KeyboardEvent) => {
      if (typesText(e.target)) return false;
      const host = props.keyHost.current;
      const active = document.activeElement;
      return !active || active === document.body || (host?.contains(active) ?? false);
    };
    const down = (e: KeyboardEvent) => {
      if (!KEYS.has(e.code) || !owns(e)) return;
      keys.current.add(e.code);
      if (e.code.startsWith("Arrow")) e.preventDefault();
    };
    const up = (e: KeyboardEvent) => keys.current.delete(e.code);
    const blur = () => keys.current.clear();
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", blur);
    return () => { window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); window.removeEventListener("blur", blur); keys.current.clear(); };
  }, [awake, props.keyHost]);

  // The route marker: a dotted line of lights to the destination.
  const marker = useMemo(() => {
    const g = new BufferGeometry();
    g.setAttribute("position", new Float32BufferAttribute(new Float32Array(3 * 200), 3));
    const m = new PointsMaterial({ color: new Color(1.6, 1.25, 0.5), size: 0.16, sizeAttenuation: true, toneMapped: false, transparent: true, opacity: 0.9, depthWrite: false });
    const p = new Points(g, m);
    p.frustumCulled = false;
    return p;
  }, []);
  useEffect(() => () => { marker.geometry.dispose(); (marker.material as PointsMaterial).dispose(); }, [marker]);

  const { camera } = useThree();
  void camera;
  useFrame((_, rawDt) => {
    const dt = Math.min(0.1, rawDt);
    t.current += dt;
    const b = body.current;
    const k = keys.current;
    const fwd = (k.has("KeyW") || k.has("ArrowUp") ? 1 : 0) - (k.has("KeyS") || k.has("ArrowDown") ? 1 : 0);
    const side = (k.has("KeyD") || k.has("ArrowRight") ? 1 : 0) - (k.has("KeyA") || k.has("ArrowLeft") ? 1 : 0);
    const run = k.has("ShiftLeft") || k.has("ShiftRight");
    let moving = false;
    if (fwd !== 0 || side !== 0) {
      b.path = [];
      captain.seated = null;
      // Camera-relative: forward is away from the camera on the floor.
      const cy = orbit.yaw;
      const dx = -Math.sin(cy) * fwd + Math.cos(cy) * side;
      const dz = -Math.cos(cy) * fwd - Math.sin(cy) * side;
      const len = Math.hypot(dx, dz) || 1;
      const pace = run ? RUN : WALK;
      b.speed += (pace - b.speed) * Math.min(1, dt * 8);
      const step = b.speed * dt;
      const nx = b.x + (dx / len) * step, nz = b.z + (dz / len) * step;
      if (isFree(grid, { x: nx, z: nz })) { b.x = nx; b.z = nz; }
      else if (isFree(grid, { x: nx, z: b.z })) b.x = nx;
      else if (isFree(grid, { x: b.x, z: nz })) b.z = nz;
      b.yaw = turnTowards(b.yaw, Math.atan2(dx, dz), dt, 10);
      b.phase += step / 1.3;
      moving = true;
    } else if (b.path.length > 0) {
      const left = b.path.reduce((s, p, i) => s + Math.hypot(p.x - (i ? b.path[i - 1].x : b.x), p.z - (i ? b.path[i - 1].z : b.z)), 0);
      const pace = left > 14 ? RUN : WALK;
      const before = { x: b.x, z: b.z };
      stepAlong(b, dt, pace);
      moving = Math.hypot(b.x - before.x, b.z - before.z) > 1e-4 || b.path.length > 0;
    } else {
      b.speed = 0;
    }
    if (captain.seated) {
      b.x = captain.seated.x; b.z = captain.seated.z;
      b.yaw = turnTowards(b.yaw, captain.seated.yaw, dt, 6);
    }
    Object.assign(captain, { x: b.x, z: b.z, yaw: wrapAngle(b.yaw), path: b.path, moving, speed: b.speed });
    figure.apply({
      activity: captain.seated ? "sit" : moving ? "walk" : "stand", t: props.reduced ? 0 : t.current, phase: b.phase, speed: b.speed,
      seatY: captain.seated?.seatY, seed: 0.42,
    }, dt);
    figure.group.position.set(b.x, 0, b.z);
    figure.group.rotation.y = b.yaw;
    // Route marker.
    const pos = marker.geometry.attributes.position as Float32BufferAttribute;
    let n = 0, prev: Vec2 = { x: b.x, z: b.z };
    for (const p of b.path) {
      const len = Math.hypot(p.x - prev.x, p.z - prev.z);
      for (let d = 0.45; d < len && n < 199; d += 0.45) {
        const tt = d / len;
        pos.setXYZ(n++, prev.x + (p.x - prev.x) * tt, 0.05, prev.z + (p.z - prev.z) * tt);
      }
      prev = p;
    }
    marker.geometry.setDrawRange(0, n);
    pos.needsUpdate = true;
  });

  return (
    <>
      <primitive object={figure.group} />
      <primitive object={marker} />
    </>
  );
}

/** Walk the captain to a clicked floor point (anything solid resolves to free floor beside it). */
export function walkCaptainTo(grid: NavGrid, at: Vec2): void {
  const target = nearestFree(grid, at, 4);
  if (!target) return;
  useShip.getState().requestWalk(target);
}
