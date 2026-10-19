/**
 * The sky pad: a landing platform that stands out of the agents floor on its
 * east side. The main boulevard runs on across the window line as a bridge to
 * a round pad in the open air, where the courier stands ready to board. Pure
 * and tested; the drawing is SkyPadStructure.tsx, the ship and its flight
 * SkyCourier.tsx with courierFlight.ts.
 *
 * Everything here lies outside the slab (`layout.bounds`), inside the city's
 * empty plaza, at floor level: the pad's top is the floor's top (y = 0).
 */
import type { Point, Rect } from "./officeLayout";

export const SKY_PAD = {
  /** The bridge: as wide as the boulevard, this long between the slab's edge and the pad's rim. */
  bridgeWidth: 5,
  bridgeLength: 9,
  /** The pad's radius and the depth of its deck. */
  radius: 12,
  thickness: 0.9,
  /** How far inside a rail a walker's centre stays (as on the slab). */
  railClearance: 0.65,
} as const;

/** The courier's size on the pad (metres): its authored ship (a 30 m hull) scaled to the Verse's people. */
export const COURIER = {
  scale: 0.6,
  /** Nose tip and pod-spike tips from the hull's middle, the length between them, the span over the pods' fins. */
  nose: 15.6 * 0.6,
  tail: 20.8 * 0.6,
  length: 36.4 * 0.6,
  span: 13.9 * 0.6,
  clearance: 0.6,
  /** The hull's middle above the deck when it stands on its gear (authored 0.63 m to the gear roots + 2.3 m gear). */
  standHeight: (0.7 * 0.9 + 2.3) * 0.6,
} as const;

/** How far the hull's middle stands from the pad's middle towards the tail, so the whole ship sits centred on the deck. */
const SHIP_SHIFT = (COURIER.tail - COURIER.nose) / 2;

export interface SkyPad {
  side: "east";
  /** The walkable deck of the bridge (a walker's centre may stand anywhere in it). */
  bridge: Rect;
  /** The pad's centre and its full radius; walkers keep `railClearance` from the rim. */
  pad: Point & { r: number };
  /** Where the courier stands: the pad's centre, nose to the north (heading in radians, 0 = facing -z). */
  ship: Point & { heading: number };
  /** The courier's footprint on the deck, solid for walkers. */
  shipRect: Rect;
  /** The place beside the courier's hatch where the person boards (and steps out again). */
  board: Point & { facing: number };
  /** The opening the bridge cuts into the floor's east rail and window wall, as a z range. */
  gap: { minZ: number; maxZ: number };
}

/**
 * The pad for a slab whose boulevard runs along z = `boulevardZ`: a bridge out of the east edge on that line,
 * the pad beyond it.
 */
export function skyPadFor(bounds: Rect, floor: Rect, boulevardZ: number): SkyPad {
  const half = SKY_PAD.bridgeWidth / 2;
  const padX = bounds.maxX + SKY_PAD.bridgeLength + SKY_PAD.radius;
  const shipRect = {
    minX: padX - COURIER.span / 2 - COURIER.clearance, maxX: padX + COURIER.span / 2 + COURIER.clearance,
    minZ: boulevardZ - COURIER.length / 2 - COURIER.clearance, maxZ: boulevardZ + COURIER.length / 2 + COURIER.clearance,
  };
  return {
    side: "east",
    bridge: {
      // From inside the floor's walkable edge (so the two grids join) to a metre onto the pad.
      minX: floor.maxX - 0.4, maxX: bounds.maxX + SKY_PAD.bridgeLength + 1,
      minZ: boulevardZ - half + SKY_PAD.railClearance, maxZ: boulevardZ + half - SKY_PAD.railClearance,
    },
    pad: { x: padX, z: boulevardZ, r: SKY_PAD.radius },
    // Nose to the north (-z): the longer tail half reaches south, so the middle stands a little north of centre.
    ship: { x: padX, z: boulevardZ - SHIP_SHIFT, heading: 0 },
    shipRect,
    // Beside the hatch on the courier's west flank, facing it: the first thing the bridge leads to.
    board: { x: shipRect.minX - 0.9, z: boulevardZ + 1.2, facing: Math.PI / 2 },
    gap: { minZ: boulevardZ - half, maxZ: boulevardZ + half },
  };
}

/** Whether a walker's centre may stand at p on the pad or its bridge (the courier excluded). */
export function onSkyPad(pad: SkyPad, p: Point): boolean {
  const { bridge } = pad;
  if (p.x >= bridge.minX && p.x <= bridge.maxX && p.z >= bridge.minZ && p.z <= bridge.maxZ) return true;
  return Math.hypot(p.x - pad.pad.x, p.z - pad.pad.z) <= pad.pad.r - SKY_PAD.railClearance;
}

/** The rectangle round the bridge and the pad. */
export function skyPadExtent(pad: SkyPad): Rect {
  return {
    minX: Math.min(pad.bridge.minX, pad.pad.x - pad.pad.r), maxX: pad.pad.x + pad.pad.r,
    minZ: Math.min(pad.bridge.minZ, pad.pad.z - pad.pad.r), maxZ: Math.max(pad.bridge.maxZ, pad.pad.z + pad.pad.r),
  };
}

/** The slab and, where there is one, the sky pad: what the camera frames and the full map shows. */
export function boundsWithPad(bounds: Rect, pad?: SkyPad): Rect {
  if (!pad) return bounds;
  const e = skyPadExtent(pad);
  return { minX: Math.min(bounds.minX, e.minX), maxX: Math.max(bounds.maxX, e.maxX), minZ: Math.min(bounds.minZ, e.minZ), maxZ: Math.max(bounds.maxZ, e.maxZ) };
}
