/**
 * One orbit camera that follows the captain: drag to turn round, right-drag
 * (or Shift-drag) to pan, the wheel to zoom down to the captain's shoulder
 * or out to the whole deck. Following resumes as soon as the captain walks.
 * The overview frames the whole deck; a focus request glides to a point.
 */
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useRef } from "react";
import { PerspectiveCamera, Vector3 } from "three";
import type { DeckPlan, Vec2 } from "../plan/types";
import { captain, useShip } from "../shipStore";
import { CUTAWAY } from "./kit/cutaway";

export const CAMERA_FOV = 38;
export const MIN_PITCH = 0.42;
export const MAX_PITCH = 1.38;
export const MIN_DIST = 3.2;

export interface Orbit { yaw: number; pitch: number; dist: number; target: Vec2; targetY: number }

/** Distance that frames a deck of `w` x `d` metres at `pitch` with the given aspect. */
export function overviewDistance(w: number, d: number, aspect: number, pitch: number, fovDeg = CAMERA_FOV): number {
  const vfov = (fovDeg * Math.PI) / 180;
  const hfov = 2 * Math.atan(Math.tan(vfov / 2) * aspect);
  // Seen at an angle, the deck's depth shrinks by sin(pitch).
  const byDepth = (d * Math.sin(pitch) * 0.5) / Math.tan(vfov / 2);
  const byWidth = (w * 0.5) / Math.tan(hfov / 2);
  return Math.max(byDepth, byWidth) * 1.12;
}

export function maxDistance(plan: DeckPlan): number {
  const w = plan.bounds.x1 - plan.bounds.x0, d = plan.bounds.z1 - plan.bounds.z0;
  return Math.max(40, Math.hypot(w, d) * 1.7);
}

export function cameraPosition(o: Orbit, out = new Vector3()): Vector3 {
  const h = Math.cos(o.pitch) * o.dist;
  return out.set(o.target.x + Math.sin(o.yaw) * h, o.targetY + Math.sin(o.pitch) * o.dist, o.target.z + Math.cos(o.yaw) * h);
}

/** Shared with the HUD (the minimap draws the view cone) and the controls. */
export const orbit: Orbit = { yaw: 0.55, pitch: 0.95, dist: 16, target: { x: 0, z: 0 }, targetY: 1.1 };

const tmp = new Vector3();

export function CameraRig({ plan, compact }: { plan: DeckPlan; compact: boolean }) {
  const { camera, gl, size } = useThree();
  const follow = useShip((s) => s.follow);
  const overviewSeq = useShip((s) => s.overviewSeq);
  const focus = useShip((s) => s.focus);
  const goal = useRef<Orbit | null>(null);
  const userDist = useRef(compact ? 20 : 16);

  // Arriving on a deck: start behind the captain.
  const arrivals = useShip((s) => s.arrivals);
  useEffect(() => {
    orbit.target = { x: captain.x, z: captain.z };
    orbit.yaw = captain.yaw + Math.PI;
    orbit.pitch = 0.95;
    orbit.dist = userDist.current;
    goal.current = null;
  }, [arrivals, plan.deck]);

  useEffect(() => {
    if (overviewSeq === 0) return;
    const w = plan.bounds.x1 - plan.bounds.x0, d = plan.bounds.z1 - plan.bounds.z0;
    const pitch = 1.08;
    goal.current = {
      yaw: 0.0, pitch, dist: overviewDistance(w, d, size.width / Math.max(1, size.height), pitch),
      target: { x: (plan.bounds.x0 + plan.bounds.x1) / 2, z: (plan.bounds.z0 + plan.bounds.z1) / 2 + d * 0.04 }, targetY: 0,
    };
  }, [overviewSeq, plan, size.width, size.height]);

  useEffect(() => {
    if (!focus) return;
    goal.current = { ...orbit, target: focus.at, dist: Math.min(orbit.dist, 18), targetY: 1 };
  }, [focus]);

  // Pointer controls on the canvas.
  useEffect(() => {
    const el = gl.domElement;
    let drag: { x: number; y: number; button: number; moved: boolean; pan: boolean } | null = null;
    const down = (e: PointerEvent) => {
      if (e.button !== 0 && e.button !== 2) return;
      drag = { x: e.clientX, y: e.clientY, button: e.button, moved: false, pan: e.button === 2 || e.shiftKey };
    };
    const move = (e: PointerEvent) => {
      if (!drag) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (!drag.moved && Math.hypot(dx, dy) < 5) return;
      if (!drag.moved) { drag.moved = true; el.setPointerCapture?.(e.pointerId); }
      drag.x = e.clientX; drag.y = e.clientY;
      goal.current = null;
      if (drag.pan) {
        useShip.getState().setFollow(false);
        const k = orbit.dist * 0.0016;
        const cos = Math.cos(orbit.yaw), sin = Math.sin(orbit.yaw);
        // Screen right is (cos, -sin) on the floor, screen up (further away) is (-sin, -cos).
        orbit.target = { x: orbit.target.x - (dx * cos + dy * sin * 1.2) * k, z: orbit.target.z + (dx * sin - dy * cos * 1.2) * k };
      } else {
        orbit.yaw -= dx * 0.006;
        orbit.pitch = Math.min(MAX_PITCH, Math.max(MIN_PITCH, orbit.pitch + dy * 0.004));
      }
    };
    const up = (e: PointerEvent) => {
      if (drag?.moved) {
        // Swallow the click that ends a drag.
        const stop = (ev: MouseEvent) => { ev.stopPropagation(); el.removeEventListener("click", stop, true); };
        el.addEventListener("click", stop, true);
        setTimeout(() => el.removeEventListener("click", stop, true), 0);
      }
      drag = null;
      el.releasePointerCapture?.(e.pointerId);
    };
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      goal.current = null;
      const far = maxDistance(plan);
      const step = orbit.dist < 20 ? 0.12 : 0.22;
      orbit.dist = Math.min(far, Math.max(MIN_DIST, orbit.dist * (e.deltaY > 0 ? 1 + step : 1 / (1 + step))));
      userDist.current = Math.min(orbit.dist, 30);
    };
    const menu = (e: Event) => e.preventDefault();
    el.addEventListener("pointerdown", down);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    el.addEventListener("wheel", wheel, { passive: false });
    el.addEventListener("contextmenu", menu);
    return () => {
      el.removeEventListener("pointerdown", down);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      el.removeEventListener("wheel", wheel);
      el.removeEventListener("contextmenu", menu);
    };
  }, [gl, plan]);

  useFrame((_, dt) => {
    const k = 1 - Math.exp(-dt * 6);
    if (captain.moving && !useShip.getState().follow) useShip.getState().setFollow(true);
    if (goal.current) {
      const g = goal.current;
      orbit.target.x += (g.target.x - orbit.target.x) * k;
      orbit.target.z += (g.target.z - orbit.target.z) * k;
      orbit.targetY += (g.targetY - orbit.targetY) * k;
      orbit.dist += (g.dist - orbit.dist) * k;
      orbit.pitch += (g.pitch - orbit.pitch) * k;
      let dy = g.yaw - orbit.yaw;
      dy = Math.atan2(Math.sin(dy), Math.cos(dy));
      orbit.yaw += dy * k;
      if (Math.abs(g.dist - orbit.dist) < 0.05 && Math.hypot(g.target.x - orbit.target.x, g.target.z - orbit.target.z) < 0.05) goal.current = null;
    } else if (follow) {
      orbit.target.x += (captain.x - orbit.target.x) * k;
      orbit.target.z += (captain.z - orbit.target.z) * k;
      orbit.targetY += (1.1 - orbit.targetY) * k;
      if (orbit.dist > 40) orbit.dist += (userDist.current - orbit.dist) * k * 0.5;
    }
    cameraPosition(orbit, tmp);
    camera.position.copy(tmp);
    // The cut-away looks from the camera at the captain (or, while panning, at what the camera looks at).
    const cam = CUTAWAY.uCutCam.value, focus = CUTAWAY.uCutFocus.value;
    cam[0] = tmp.x; cam[1] = tmp.z;
    const following = useShip.getState().follow;
    focus[0] = following ? captain.x : orbit.target.x; focus[1] = following ? captain.z : orbit.target.z;
    CUTAWAY.uCutInner.value = orbit.dist < 34 ? 1 : 0;
    camera.lookAt(orbit.target.x, orbit.targetY, orbit.target.z);
    const persp = camera as PerspectiveCamera;
    // The near plane follows the distance, against depth fighting at the overview.
    const near = Math.min(2, Math.max(0.08, orbit.dist * 0.02));
    if (Math.abs(persp.near - near) > 0.01) { persp.near = near; persp.updateProjectionMatrix(); }
  });
  return null;
}
