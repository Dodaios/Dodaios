/**
 * What the pointer is on in the eye-level view: a crew member (an upright
 * cylinder around each body), a station (the deck point hit lies near it,
 * on its console or its floor), or a floor point to walk to. Bodies hidden
 * behind the deck's geometry are not picked. Pure apart from the BVH query.
 */
import { DoubleSide, type Ray } from "three";
import type { MeshBVH } from "three-mesh-bvh";
import type { Station } from "../../content/deck";

export type EyeHit =
  | { kind: "crew"; id: string }
  | { kind: "station"; id: string }
  | { kind: "floor"; x: number; y: number; z: number }
  | null;

export interface BodyPose { id: string; x: number; y: number; z: number; height: number }

/** Bodies are picked within this radius of their axis, metres. */
export const BODY_PICK_RADIUS = 0.34;
/** A deck point this close (horizontally) to a station's anchor picks the station, metres. */
export const STATION_PICK_RADIUS = 1.5;

/** Distance along the ray to where it enters an upright cylinder (x, z, radius, y0..y1), or null. Pure. */
export function rayCylinder(
  origin: { x: number; y: number; z: number },
  dir: { x: number; y: number; z: number },
  x: number, z: number, radius: number, y0: number, y1: number,
): number | null {
  const ox = origin.x - x;
  const oz = origin.z - z;
  const a = dir.x * dir.x + dir.z * dir.z;
  let t0: number;
  let t1: number;
  if (a < 1e-9) {
    if (ox * ox + oz * oz > radius * radius) return null;
    t0 = -Infinity;
    t1 = Infinity;
  } else {
    const b = 2 * (ox * dir.x + oz * dir.z);
    const c = ox * ox + oz * oz - radius * radius;
    const disc = b * b - 4 * a * c;
    if (disc < 0) return null;
    const s = Math.sqrt(disc);
    t0 = (-b - s) / (2 * a);
    t1 = (-b + s) / (2 * a);
  }
  // The span of t where the ray is between the heights.
  let h0 = -Infinity;
  let h1 = Infinity;
  if (Math.abs(dir.y) < 1e-9) {
    if (origin.y < y0 || origin.y > y1) return null;
  } else {
    const ta = (y0 - origin.y) / dir.y;
    const tb = (y1 - origin.y) / dir.y;
    h0 = Math.min(ta, tb);
    h1 = Math.max(ta, tb);
  }
  const enter = Math.max(t0, h0, 0);
  const leave = Math.min(t1, h1);
  return enter <= leave ? enter : null;
}

export function eyePick(
  ray: Ray,
  stations: readonly Station[],
  bodies: Iterable<BodyPose>,
  pickable: (id: string) => boolean,
  collider: MeshBVH | null,
): EyeHit {
  const hit = collider ? collider.raycastFirst(ray, DoubleSide) : null;
  const wall = hit ? hit.distance : Infinity;
  let best: { id: string; t: number } | null = null;
  for (const body of bodies) {
    if (!pickable(body.id)) continue;
    const t = rayCylinder(ray.origin, ray.direction, body.x, body.z, BODY_PICK_RADIUS, body.y, body.y + body.height + 0.1);
    if (t !== null && t < wall && (!best || t < best.t)) best = { id: body.id, t };
  }
  if (best) return { kind: "crew", id: best.id };
  if (!hit) return null;
  const p = hit.point;
  let station: Station | null = null;
  let near = STATION_PICK_RADIUS;
  for (const s of stations) {
    const d = Math.hypot(s.x - p.x, s.z - p.z);
    if (d <= near && Math.abs(p.y - s.y) < 2.2) { near = d; station = s; }
  }
  if (station) return { kind: "station", id: station.id };
  const up = hit.face ? hit.face.normal.y : 0;
  return up > 0.6 ? { kind: "floor", x: p.x, y: p.y, z: p.z } : null;
}
