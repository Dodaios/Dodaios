/**
 * Where the duel arena shows itself on the deck: a small "Duel · E" marker
 * over the nearest reactor-ring console once the commander is close to the
 * ring, and a small icon over the shaft in the bird's-eye view. Pure, so the
 * rule is tested without a renderer.
 */
import type { ArenaDef } from "../combat/arena";
import type { ControlMode } from "../life/control";

/** How close to the control ring (metres past its outer edge) the marker appears. */
export const DUEL_BEACON_RANGE_M = 12;
/** Height of the marker above the console's floor, metres. */
export const DUEL_BEACON_HEIGHT_M = 1.6;

export interface DuelBeacon {
  kind: "label" | "icon";
  x: number;
  y: number;
  z: number;
}

/** The control ring's outer radius around the shaft axis (the annulus bridge), else the consoles' distance. */
export function ringRadius(arena: ArenaDef): number {
  const ring = arena.bridges.find((b) => b.kind === "annulus");
  if (ring && ring.kind === "annulus") return ring.r1;
  const c = arena.centre;
  return Math.max(0, ...arena.terminals.map((t) => Math.hypot(t.x - c.x, t.z - c.z)));
}

/**
 * The marker for this frame, or null. `floorY`: the arena room's floor;
 * `commander`: where the commander stands (null: not on this deck).
 */
export function duelBeacon(
  arena: ArenaDef, floorY: number, mode: ControlMode, commander: { x: number; z: number } | null,
): DuelBeacon | null {
  const c = arena.centre;
  if (mode === "overview") return { kind: "icon", x: c.x, y: floorY, z: c.z };
  if (!commander) return null;
  const toRing = Math.hypot(commander.x - c.x, commander.z - c.z) - ringRadius(arena);
  if (toRing > DUEL_BEACON_RANGE_M) return null;
  let best: { x: number; z: number } | null = null;
  let bestD = Infinity;
  for (const t of arena.terminals) {
    const d = Math.hypot(t.x - commander.x, t.z - commander.z);
    if (d < bestD) { bestD = d; best = t; }
  }
  const at = best ?? c;
  return { kind: "label", x: at.x, y: floorY + DUEL_BEACON_HEIGHT_M, z: at.z };
}
