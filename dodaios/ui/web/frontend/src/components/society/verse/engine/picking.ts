/**
 * What is under the pointer, decided on the plate rather than by ray-casting
 * skinned meshes: a body is a slim upright box from its feet to the top of its
 * head as the camera sees it, a station is a small area round its spot and its
 * member sockets. Pure.
 */
import type { Deck, Station } from "../content/deck";
import type { ActorPose } from "../runtime";
import { worldToPlate, type PlateCamera, type PlatePoint } from "./plateMath";

/** Half-width of a body on the plate, metres. */
const BODY_HALF_W = 0.3;
/** Station hotspot half-size on the plate, metres. */
const STATION_HALF = 0.85;

/** The body under plate point p, nearest the camera first; null when none. */
export function pickBody(cam: PlateCamera, poses: Iterable<ActorPose>, p: PlatePoint, accept: (id: string) => boolean): string | null {
  let best: string | null = null;
  let bestDepth = -Infinity;
  const cos = Math.cos((cam.pitchDeg * Math.PI) / 180);
  for (const pose of poses) {
    if (!accept(pose.id)) continue;
    const feet = worldToPlate(cam, pose.x, pose.y, pose.z);
    const top = feet.v + pose.height * cos;
    if (Math.abs(p.u - feet.u) > BODY_HALF_W || p.v < feet.v - 0.12 || p.v > top + 0.08) continue;
    // Bodies further toward +z (and higher) are nearer the camera and drawn in front.
    const depth = pose.z + pose.y * Math.tan((cam.pitchDeg * Math.PI) / 180);
    if (depth > bestDepth) { bestDepth = depth; best = pose.id; }
  }
  return best;
}

/** Plate points that stand for a station: its spot and its member sockets (the console, the table). */
export function stationPoints(deck: Deck, station: Station): PlatePoint[] {
  const pts = [worldToPlate(deck.camera, station.x, station.y + 0.5, station.z)];
  for (const [kind, ids] of Object.entries(station.sockets)) {
    for (const id of ids ?? []) {
      const s = deck.sockets.find((x) => x.kind === kind && x.id === id);
      if (s) pts.push(worldToPlate(deck.camera, s.x, s.y + (kind === "screen" || kind === "holo" ? 0 : 0.5), s.z));
    }
  }
  return pts;
}

export function pickStation(deck: Deck, p: PlatePoint): Station | null {
  let best: Station | null = null;
  let bestD = Infinity;
  for (const station of deck.stations) {
    for (const q of stationPoints(deck, station)) {
      const du = Math.abs(q.u - p.u);
      const dv = Math.abs(q.v - p.v);
      if (du > STATION_HALF || dv > STATION_HALF) continue;
      const d = Math.hypot(du, dv);
      if (d < bestD) { bestD = d; best = station; }
    }
  }
  return best;
}
